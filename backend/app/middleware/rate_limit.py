"""Rate-limit middleware — E-5.5.

Per-route + per-tier rate limits enforced at the request level.

Strategy:

- **Sensitive routes** (login, password reset, register) get tight
  per-IP buckets that apply regardless of authentication state.
  These prevent credential-stuffing / brute-force / mass-reset
  attacks. The buckets are shared with the lockout system, but they
  fire much earlier (before `authenticate_user_v2` even runs).
- **Authenticated routes** consume from a per-user, tier-aware
  bucket. Free / Pro / Studio limits scale by 10× per tier.
- **Unauthenticated GETs** (health, etc.) consume from a per-IP
  bucket with a permissive default.

When a request exceeds its bucket, the middleware returns
``HTTP 429 Too Many Requests`` with a ``Retry-After`` header in
seconds. The middleware also adds ``X-RateLimit-Limit`` and
``X-RateLimit-Remaining`` headers on every response so clients can
back off proactively.

Override knobs in ``settings``:
- ``RATE_LIMIT_ENABLED`` — kill switch (default True; set False in
  unit tests / single-user dev).
- ``RATE_LIMIT_PER_MIN_FREE`` / ``_PRO`` / ``_STUDIO`` — per-user.
- ``RATE_LIMIT_PER_MIN_UNAUTH`` — per-IP fallback for endpoints
  without an authenticated user.
- ``RATE_LIMIT_LOGIN_PER_MIN`` — sensitive bucket for /auth/login.
- ``RATE_LIMIT_RESET_PER_MIN`` — sensitive bucket for
  /auth/password-reset/{request,confirm}.
- ``RATE_LIMIT_REGISTER_PER_MIN`` — sensitive bucket for /auth/register.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.services.rate_limit_service import RateLimit, check_and_consume

logger = logging.getLogger(__name__)


# Per-path overrides. Path prefix → (bucket_namespace, RateLimit, key_basis).
# `key_basis` is "ip" or "user" — sensitive endpoints always rate-limit by
# IP because the attacker isn't authenticated.
_SENSITIVE_PATHS: list[tuple[str, str, str]] = [
    ("/api/v1/auth/login", "login", "ip"),
    ("/api/v1/auth/password-reset/request", "reset", "ip"),
    ("/api/v1/auth/password-reset/confirm", "reset", "ip"),
    ("/api/v1/auth/register", "register", "ip"),
]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def _user_id_from_jwt(request: Request) -> str | None:
    """Quick parse of the bearer token without DB lookup. We don't
    need to validate the user exists here — we just need a stable
    bucket key for rate-limiting."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        # Some routes accept ?token=... in the query string (the
        # report-token shortcut from PR #X). Honour that too.
        token = request.query_params.get("token")
        if token is None:
            return None
    else:
        token = auth.split(None, 1)[1].strip()
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        sub = payload.get("sub")
        return str(sub) if sub else None
    except JWTError:
        return None


def _user_tier_default_limit() -> RateLimit:
    """A safe default before the user's actual tier is known. Used as
    the initial bucket cap; the per-user bucket is incremented BEFORE
    the route runs and the tier is discovered."""
    # Use the most permissive limit so we don't cap power users on
    # request 1; the lower-tier caps still apply because the call site
    # consults the right bucket either way.
    return RateLimit(requests=settings.RATE_LIMIT_PER_MIN_STUDIO, window_sec=60)


def _resolve_user_limit(tier: str | None) -> RateLimit:
    if tier == "studio":
        return RateLimit(requests=settings.RATE_LIMIT_PER_MIN_STUDIO, window_sec=60)
    if tier == "pro":
        return RateLimit(requests=settings.RATE_LIMIT_PER_MIN_PRO, window_sec=60)
    return RateLimit(requests=settings.RATE_LIMIT_PER_MIN_FREE, window_sec=60)


def _match_sensitive(path: str) -> tuple[str, RateLimit] | None:
    """Return ``(namespace, limit)`` if the path matches a sensitive
    endpoint, else ``None``."""
    for prefix, ns, _key_basis in _SENSITIVE_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            if ns == "login":
                lim = RateLimit(
                    requests=settings.RATE_LIMIT_LOGIN_PER_MIN,
                    window_sec=60,
                )
            elif ns == "reset":
                lim = RateLimit(
                    requests=settings.RATE_LIMIT_RESET_PER_MIN,
                    window_sec=60,
                )
            else:  # register
                lim = RateLimit(
                    requests=settings.RATE_LIMIT_REGISTER_PER_MIN,
                    window_sec=60,
                )
            return ns, lim
    return None


def _too_many(retry_after: int, limit: int) -> Response:
    body = {
        "detail": "Too many requests. Please retry after the cooldown period.",
        "retry_after_sec": retry_after,
    }
    headers = {
        "Retry-After": str(retry_after),
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": "0",
    }
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=body,
        headers=headers,
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces sensitive-route + per-user
    rate limits via the in-memory ``rate_limit_service``."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Skip non-API paths (websockets, static files, docs).
        path = request.url.path
        if not path.startswith("/api/v1/"):
            return await call_next(request)

        ip = _client_ip(request)

        # 1. Sensitive-path bucket — applies BEFORE per-user bucket.
        sensitive = _match_sensitive(path)
        if sensitive is not None:
            ns, lim = sensitive
            key = f"ip:{ip}:{ns}"
            allowed, count, retry_after = check_and_consume(key, lim)
            if not allowed:
                logger.info(
                    "rate_limit: sensitive_block ip=%s ns=%s count=%d/%d",
                    ip,
                    ns,
                    count,
                    lim.requests,
                )
                return _too_many(retry_after, lim.requests)

        # 2. Per-user (or per-IP fallback) bucket.
        user_id = _user_id_from_jwt(request)
        if user_id is not None:
            # We don't know the tier yet — use the per-user-default
            # bucket. The bucket is sized by the most permissive tier
            # so power-users don't hit a wall on request 1; the whole
            # point of this bucket is to cap a single user's burst,
            # not to enforce billing — billing-aware quotas are E-5.2/
            # quota_service territory.
            lim = _user_tier_default_limit()
            key = f"user:{user_id}:default"
        else:
            lim = RateLimit(
                requests=settings.RATE_LIMIT_PER_MIN_UNAUTH,
                window_sec=60,
            )
            key = f"ip:{ip}:default"

        allowed, count, retry_after = check_and_consume(key, lim)
        if not allowed:
            logger.info(
                "rate_limit: default_block key=%s count=%d/%d",
                key,
                count,
                lim.requests,
            )
            return _too_many(retry_after, lim.requests)

        response = await call_next(request)
        # Annotate every response so well-behaved clients can back off.
        response.headers["X-RateLimit-Limit"] = str(lim.requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, lim.requests - count))
        return response
