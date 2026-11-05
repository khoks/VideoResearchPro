"""``Content-Security-Policy`` on every response the API sends (T-4.11.2.1).

The API serves data, so the default policy allows nothing. A route earns
anything looser by being named here, so a new route that serves something odd
starts out locked, and shows up as unstyled rather than as an opening.

What each kind of response gets, and why (read from what the routes serve):

- **JSON:** ``API_POLICY``.
- **The stored report,** ``GET /jobs/{id}/report``: ``REPORT_POLICY``. The
  document is a ``<style>`` block and markup (``utils/html_builder.py``). The
  model writes the body, so a report is untrusted: no script runs, inline or by
  handler, and with ``sandbox`` the page has no origin of its own to reach for.
  It loads nothing: the template links no image, font or stylesheet, and an
  ``<img>`` the model wrote stays blocked, because it could report that the
  page was opened. Its source links are ``target="_blank"``, hence
  ``allow-popups``. The same flags as ``REPORT_FRAME_SANDBOX`` on the job page.
- **Every other non-JSON response:** ``FILE_POLICY``, the default plus
  ``sandbox``. That covers ``report.md``, Author Studio's ``content`` and
  ``download`` (Markdown, HTML, PDF, EPUB, PPTX, zip), a share's file (whatever
  was uploaded), the Echo export, the library's PDFs, a frame's JPEG, the
  dataset and notes exports, and the Q&A event stream. All but the first two
  and the frame are attachments, and the app fetches every one of them with the
  bearer header and shows the bytes from a blob: URL, whose policy is the app's
  own. So nothing here renders on the API's origin. If one ever did (an
  uploaded SVG opened by hand), it could run nothing.
- **The API docs,** ``/docs`` and ``/redoc``: FastAPI's pages, which load from
  public CDNs, so each policy names those files. Swagger's page has one inline
  script, allowed by its hash; the hash is taken from the page as served, so a
  FastAPI upgrade that changes that script cannot blank the page.
  ``/docs/oauth2-redirect`` keeps ``FILE_POLICY``: only a redirect flow lands
  there, and the one flow the API declares is the password flow.

A pure ASGI middleware rather than ``BaseHTTPMiddleware``, so a stream keeps
streaming and a WebSocket passes straight through. Only the two docs pages are
held in memory, to hash them, and they are a few kilobytes.

It is the outermost middleware, so a 429 and a CORS preflight carry the header.
Starlette's own last-resort 500 is sent from outside it and does not; that body
is a fixed line of plain text.
"""
from __future__ import annotations

import base64
import hashlib
import re

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_POLICY = "default-src 'none'; frame-ancestors 'none'"
FILE_POLICY = f"{API_POLICY}; sandbox"
_DOCUMENT_LOCKS = "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
REPORT_POLICY = (
    f"default-src 'none'; style-src 'unsafe-inline'; {_DOCUMENT_LOCKS}; "
    "sandbox allow-popups allow-popups-to-escape-sandbox"
)

_SWAGGER_CDN = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/"
_REDOC_CDN = "https://cdn.jsdelivr.net/npm/redoc@2/"
_DOCS_FAVICON = "https://fastapi.tiangolo.com"
_REDOC_LOGO = "https://cdn.redoc.ly/redoc/logo-mini.svg"
# `{inline_scripts}` becomes the hash of each inline script on the page as sent.
# Styles stay 'unsafe-inline': both pages set them from script at runtime, and
# neither shows anything a caller wrote.
_DOCS_PAGES = {
    "/docs": (
        f"default-src 'none'; script-src {_SWAGGER_CDN} {{inline_scripts}}; "
        f"style-src {_SWAGGER_CDN} 'unsafe-inline'; img-src data: {_DOCS_FAVICON}; "
        f"connect-src 'self'; {_DOCUMENT_LOCKS}"
    ),
    "/redoc": (
        f"default-src 'none'; script-src {_REDOC_CDN} {{inline_scripts}}; "
        "style-src https://fonts.googleapis.com 'unsafe-inline'; "
        f"font-src https://fonts.gstatic.com; img-src data: {_DOCS_FAVICON} {_REDOC_LOGO}; "
        f"connect-src 'self'; worker-src blob:; {_DOCUMENT_LOCKS}"
    ),
}

_REPORT_PATH = re.compile(r"/api/v1/jobs/[^/]+/report")
_INLINE_SCRIPT = re.compile(rb"<script>(.*?)</script>", re.S)


def _policy_for(path: str, content_type: str) -> str:
    if content_type.startswith("application/json"):
        return API_POLICY
    if _REPORT_PATH.fullmatch(path):
        return REPORT_POLICY
    return FILE_POLICY


def _inline_script_hashes(page: bytes) -> str:
    return " ".join(
        f"'sha256-{base64.b64encode(hashlib.sha256(script).digest()).decode()}'"
        for script in _INLINE_SCRIPT.findall(page)
    )


class ContentSecurityPolicyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        template = _DOCS_PAGES.get(scope["path"])
        if template is not None:
            await self.app(scope, receive, _send_docs_page(send, template))
            return

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = _policy_for(
                    scope["path"], headers.get("content-type", "")
                )
            await send(message)

        await self.app(scope, receive, send_with_policy)


def _send_docs_page(send: Send, template: str) -> Send:
    """Hold the response until its body is whole, since the header goes first
    and carries the hash of what follows."""
    start: Message = {}
    body = bytearray()

    async def send_docs_page(message: Message) -> None:
        if message["type"] == "http.response.start":
            start.update(message)
            return
        body.extend(message.get("body", b""))
        if message.get("more_body"):
            return
        page = bytes(body)
        MutableHeaders(scope=start)["Content-Security-Policy"] = template.format(
            inline_scripts=_inline_script_hashes(page)
        )
        await send(start)
        await send({"type": "http.response.body", "body": page})

    return send_docs_page
