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


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


# E-5.4 password-reset flow
class PasswordResetRequestPayload(BaseModel):
    email: EmailStr


class PasswordResetConfirmPayload(BaseModel):
    token: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class PasswordResetRequestResponse(BaseModel):
    """Always 200 + a generic message — never leaks whether the
    email exists. The actual reset secret is delivered to the user
    via email (when SMTP configured) or via operator log."""

    message: str = "If that email is registered, a reset link has been sent."
    # When SMTP is unconfigured, the secret is included in this field
    # so a self-host operator running the request manually can pass it
    # straight to the user. Always None on a SaaS-style deployment.
    debug_secret: str | None = None


class PasswordResetConfirmResponse(BaseModel):
    message: str = "Password updated. You may now log in."


# E-5.4 audit log
class AuditLogEntry(BaseModel):
    id: str
    event: str
    ip_address: str | None
    user_agent: str | None
    metadata_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
