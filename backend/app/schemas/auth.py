from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class MfaRequiredResponse(BaseModel):
    """Returned by /auth/login when the user has MFA enabled. The
    caller must POST {mfa_token, code} to /auth/login/mfa to receive
    the real access token."""
    requires_mfa: bool = True
    mfa_token: str
    expires_in: int = 300  # seconds (matches MFA_TOKEN_TTL_MIN=5)


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime
    tier: str = "free"
    # S-8.10.1: set when the first-run wizard is finished. The wizard's
    # state lives at GET /auth/me/onboarding.
    onboarded_at: datetime | None = None

    model_config = {"from_attributes": True}


class MeResponse(UserResponse):
    """``GET /auth/me``: the caller, plus whether they operate this install
    (T-5.2.8 / D-111), so the Subscription page can say why the tier switch
    is unavailable instead of failing on submit."""

    is_operator: bool = False


# E-5.2.X self-service tier flip with mock payment (D-050)
class ChangeTierRequest(BaseModel):
    """Body for ``PUT /auth/me/tier``.

    ``mock_payment`` is accepted for forward-compat shape but ignored at
    the backend today — the entire flow exists for self-host evaluation
    of paid features before E-5.3 (Stripe) ships. When Stripe lands the
    same endpoint shape stays; the implementation flips from "trust the
    request" to "verify the Stripe webhook payload".
    """

    tier: str = Field(pattern=r"^(free|pro|studio)$")
    mock_payment: dict | None = None


class ChangeTierResponse(BaseModel):
    tier: str
    message: str = (
        "Tier updated. New capabilities are active immediately — "
        "your next request will reflect the new tier."
    )
    # Mock-payment dev-mode flag, surfaced so the frontend can render
    # the "Demo mode — no real payment processed" banner consistently.
    mock_payment_mode: bool = True


# E-5.4 password-reset flow
class PasswordResetRequestPayload(BaseModel):
    email: EmailStr


class PasswordResetConfirmPayload(BaseModel):
    token: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class PasswordResetRequestResponse(BaseModel):
    """Always 200 + a generic message — never leaks whether the
    email exists. The actual reset secret is delivered to the user
    via email (when SMTP configured) or via operator log, never in this
    response: the route is unauthenticated, so a secret here is an account
    takeover for anyone who knows the address (the ``debug_secret`` field
    that did this when SMTP was unset was removed on 2026-11-03)."""

    message: str = "If that email is registered, a reset code has been sent."


class PasswordResetConfirmResponse(BaseModel):
    message: str = "Password updated. You may now log in."


# T-5.4.14 change the password while signed in
class PasswordChangePayload(BaseModel):
    # No length constraints here: ``routers/auth.change_password`` checks the
    # new one against PASSWORD_MIN_CHARS..PASSWORD_MAX_CHARS, the rule a reset
    # uses, so a bad one gets a 400 with a sentence the page can show (the
    # ``detail`` of a 422 is a list). A 422 quotes nothing either way: the
    # handler in ``app/main.py`` drops ``input``.
    current_password: str
    new_password: str


# The new-password rule shared by register and reset (their Field bounds).
PASSWORD_MIN_CHARS = 6
PASSWORD_MAX_CHARS = 128


class PasswordChangeResponse(BaseModel):
    message: str = "Password changed. Your other sessions have been signed out."
    # How many other sessions were signed out; this one stays signed in.
    sessions_revoked: int = 0


# E-5.4 audit log
class AuditLogEntry(BaseModel):
    id: str
    event: str
    ip_address: str | None
    user_agent: str | None
    metadata_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
