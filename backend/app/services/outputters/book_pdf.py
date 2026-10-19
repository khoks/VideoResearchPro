"""Book PDF rendering (S-6.1.5): an optional converter, chosen at runtime.

Engines, in the plan's order (docs/plans/l2-author-studio.md):

1. **WeasyPrint** (BSD-3-Clause). Prints HTML with CSS Paged Media:
   running chapter titles, page numbers, page numbers in the table of
   contents. Needs the Pango libraries: on Windows MSYS2's
   ``mingw-w64-ucrt-x86_64-pango`` with ``WEASYPRINT_DLL_DIRECTORIES``
   pointing at its ``bin``; on Debian/Ubuntu ``libpango-1.0-0
   libpangoft2-1.0-0``. Without Pango its import raises ``OSError``.
2. **Chromium through Playwright** (Apache-2.0), already the optional
   SPA-extraction dependency (E-1.6). Page size, margins, breaks, page
   numbers (CSS margin boxes, Chromium 131 and later), a PDF outline and a
   tagged PDF; no running chapter titles (`string-set`) and no page numbers
   in the table of contents (`target-counter`).

Neither is in ``requirements.txt``: both live in ``requirements-author.txt``
(the Playwright precedent). ``AUTHOR_PDF_ENGINE`` picks one (``auto``,
``weasyprint``, ``chromium``) or turns PDF off (``off``). When nothing is
usable, a request for a PDF is refused with :func:`unavailable_message`,
which says what to install; the EPUB and Markdown need neither.

Availability is probed once per process (Chromium's probe starts the
Playwright driver, about a second); restart the API and the worker after
installing a converter.

Both engines are sandboxed from the network: WeasyPrint's URL fetcher
refuses everything but ``data:`` URLs and Chromium aborts every request
and runs with JavaScript off. The HTML comes from `book_html`, which has
already dropped images and raw HTML, so this is a second wall.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.config import settings
from app.services.output_service import OutputError, OutputUnavailable

logger = logging.getLogger(__name__)

ENGINES = ("weasyprint", "chromium")

INSTALL_HINT = (
    "PDF export needs a converter on the server. Install one, then restart the API and the worker: "
    "WeasyPrint (`pip install -r backend/requirements-author.txt` plus the Pango libraries: "
    "on Windows `pacman -S mingw-w64-ucrt-x86_64-pango` in MSYS2 and WEASYPRINT_DLL_DIRECTORIES "
    "set to its bin folder; on Debian or Ubuntu `apt install libpango-1.0-0 libpangoft2-1.0-0`), "
    "or Chromium (`pip install -r backend/requirements-author.txt`, then `playwright install chromium`). "
    "EPUB and Markdown downloads need neither."
)

class PdfError(OutputError):
    """Rendering was attempted and failed."""


@lru_cache(maxsize=1)
def _weasyprint_problem() -> str | None:
    """None when WeasyPrint imports, otherwise why not."""
    try:
        import weasyprint  # noqa: F401
    except ImportError:
        return "WeasyPrint is not installed"
    except Exception as e:  # noqa: BLE001 — OSError when Pango is missing
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        return f"WeasyPrint is installed but cannot load its libraries ({first})"
    return None


@lru_cache(maxsize=1)
def _chromium_problem() -> str | None:
    """None when Playwright and its Chromium build are present."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright is not installed"
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception as e:  # noqa: BLE001 — driver failed to start
        return f"Playwright could not start ({type(e).__name__}: {e})"
    if not path or not os.path.exists(path):
        return "Playwright is installed but Chromium is not (run `playwright install chromium`)"
    return None


_PROBES = {"weasyprint": _weasyprint_problem, "chromium": _chromium_problem}


def reset_probes() -> None:
    """Forget the cached probe results (tests; a long-lived shell)."""
    _weasyprint_problem.cache_clear()
    _chromium_problem.cache_clear()


def _candidates() -> tuple[str, ...]:
    choice = (settings.AUTHOR_PDF_ENGINE or "auto").strip().lower()
    if choice == "off":
        return ()
    if choice in ENGINES:
        return (choice,)
    if choice != "auto":
        logger.warning("AUTHOR_PDF_ENGINE=%r is not one of auto/weasyprint/chromium/off; using auto", choice)
    return ENGINES


def pdf_engine() -> str | None:
    """The engine that will print a book's PDF, or None."""
    for engine in _candidates():
        if _PROBES[engine]() is None:
            return engine
    return None


def unavailable_message() -> str:
    """Why there is no PDF engine, with what to install."""
    candidates = _candidates()
    if not candidates:
        return "PDF export is turned off on this server (AUTHOR_PDF_ENGINE=off). EPUB and Markdown are available."
    reasons = "; ".join(f"{e}: {_PROBES[e]()}" for e in candidates)
    return f"{INSTALL_HINT} Found: {reasons}."


def require_engine() -> str:
    engine = pdf_engine()
    if engine is None:
        raise OutputUnavailable(unavailable_message())
    return engine


def render_pdf(document_html: str, *, engine: str | None = None) -> bytes:
    """Print a standalone HTML document (`book_html.html_document`) to PDF."""
    engine = engine or require_engine()
    try:
        if engine == "weasyprint":
            return _render_weasyprint(document_html)
        if engine == "chromium":
            return _render_chromium(document_html)
    except OutputError:
        raise
    except Exception as e:  # noqa: BLE001 — surface as a clear failure
        logger.exception("book_pdf: %s failed", engine)
        raise PdfError(f"PDF rendering failed in {engine}: {type(e).__name__}: {e}") from e
    raise PdfError(f"unknown PDF engine {engine!r}")


def _refuse_fetch(url: str, *args, **kwargs):
    """WeasyPrint URL fetcher: ``data:`` URLs only."""
    import weasyprint

    if url.startswith("data:"):
        fetch = getattr(weasyprint, "default_url_fetcher")
        return fetch(url, *args, **kwargs)
    raise ValueError(f"book PDF does not fetch external resources: {url[:80]}")


def _render_weasyprint(document_html: str) -> bytes:
    import weasyprint

    return weasyprint.HTML(string=document_html, url_fetcher=_refuse_fetch).write_pdf()


def _render_chromium(document_html: str) -> bytes:
    from playwright.sync_api import sync_playwright

    timeout_ms = max(1, int(settings.AUTHOR_PDF_TIMEOUT_SEC)) * 1000
    with sync_playwright() as p:
        browser = p.chromium.launch(timeout=timeout_ms)
        try:
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(document_html, wait_until="load", timeout=timeout_ms)
            return page.pdf(
                prefer_css_page_size=True,
                print_background=True,
                # Page numbers come from the stylesheet's margin boxes;
                # Chromium's own footer would print them twice.
                display_header_footer=False,
                outline=True,
                tagged=True,
            )
        finally:
            browser.close()
