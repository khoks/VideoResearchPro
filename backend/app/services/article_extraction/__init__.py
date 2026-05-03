"""Article extraction primitives — connector-agnostic clean-text from URLs.

Per [E-1.6 T-1.6.1](../../../docs/initiatives.md) and
[D-024](../../../docs/decisions.md#d-024--flip-e-16-to--with-primitives-only-scope-split-2026-04-28),
this is the **primitives** layer of the article connector — a single
public function ``extract_text(url) -> ExtractionResult`` that turns
a URL into a clean text + metadata bundle. The primitives ship now in
service of [S-1.5.8](../../../docs/initiatives.md#s-158--manual-paste-mode-mode-b-for-fbiglix-without-paid)
(Mode B paste-mode for FB / IG / LI / X-without-paid-API) and are
reusable by the future full article-connector UX (RSS feed, search-
engine integration, approval card variant) when E-1.6 unblocks.

**Strategy.**

- **Primary: trafilatura.** High-quality boilerplate removal for
  static HTML; handles most article / blog / longform-content pages.
  Returns title, body, author, publish date, language.
- **Fallback: Playwright.** For SPAs that render the article body
  client-side after JS execution, trafilatura's static-fetch sees
  only the shell. The full article connector ships with a Playwright
  fallback that loads the page in a headless browser, waits for
  hydration, then re-feeds the rendered DOM through trafilatura.
  **Today the fallback is structurally present but not implemented**
  — it returns ``None`` and emits a warning. The Playwright
  dependency (~150MB of Chromium binaries) is gated behind an
  opt-in install in a follow-up PR so the default backend install
  stays lean.
- **Hybrid orchestration.** ``extract_text(url)`` runs trafilatura
  first; if the result is ``None`` or shorter than
  ``MIN_WORD_COUNT`` (default 200 words — distinguishes "article"
  from "navigation page"), it falls through to the Playwright path.
  Today the fallback is a stub, so SPA-heavy articles return ``None``
  rather than fabricating text — caller treats that as
  "extraction failed, document unavailable".

**Public surface.**

- :class:`ExtractionResult` — typed dataclass returned by
  ``extract_text``.
- :func:`extract_text` — the single entry point. Caller passes a URL,
  receives ``ExtractionResult | None``.
- :data:`MIN_WORD_COUNT` — the threshold below which trafilatura
  output is treated as a failure (likely a navigation page, error
  page, or paywalled stub).

Future text-based connectors (article connector full UX, paste-mode
in S-1.5.8, future Substack / Medium connectors) import
``extract_text`` from this package — never from a per-connector
local module — so the trafilatura/Playwright tuning is shared.

**What this module does NOT do.**

- ❌ HTTP fetching with auth headers / cookies / login state. Pure
  read-only public-page extraction.
- ❌ Paywall bypass. If a page is paywalled, trafilatura sees the
  paywall HTML, returns the truncated stub, and ``extract_text``
  rejects it via the ``MIN_WORD_COUNT`` threshold.
- ❌ Rate limiting. Caller is responsible for spacing requests
  (each connector has its own rate-limit knob).
- ❌ Concurrency / threading. ``extract_text`` is synchronous; wrap
  in ``asyncio.to_thread`` if calling from async code.
"""
from app.services.article_extraction.extractor import (
    MIN_WORD_COUNT,
    ExtractionResult,
    extract_text,
)

__all__ = ["ExtractionResult", "extract_text", "MIN_WORD_COUNT"]
