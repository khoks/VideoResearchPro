"""CORS on the app's one list of origins (T-4.11.3.3).

Starlette's middleware with one change: an ``Origin`` is allowed when
``app_origins.allows`` says so, the check OAuth start makes on a
``redirect_uri``. A page the API answers is a page sign-in can return to,
and the other way round.

``allow_origins`` stays empty, so Starlette never takes its ``*`` branch, which
with credentials echoes back any origin. Everything else is as before:
credentials allowed, every method and header, ``Vary: Origin`` on what it
answers.
"""
from __future__ import annotations

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from app.utils import app_origins


class AppOriginsCORSMiddleware(CORSMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(
            app,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def is_allowed_origin(self, origin: str) -> bool:
        return app_origins.allows(origin)
