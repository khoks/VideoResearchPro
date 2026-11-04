"""BYOK credentials router — E-5.6.

Per-user provider API keys, gated on the ``byok_llm_keys`` feature
(Studio tier). The router never returns the decrypted secret — only
metadata (provider, label, timestamps). To rotate a key, the user
sets a new value with PUT (which overwrites). To remove a key, DELETE.

PUT takes a key only for ``byok_service.RESOLVED_PROVIDERS``, the
providers an LLM call reads a stored key for; ``GET /providers`` lists the
same set. DELETE takes every ``SUPPORTED_PROVIDERS`` name, so a row stored
before that rule (a ``local`` key, which no call reads) can still go.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import byok_service
from app.services.byok_service import (
    RESOLVED_PROVIDERS,
    SUPPORTED_PROVIDERS,
    EncryptionConfigurationError,
    UnsupportedProviderError,
)
from app.services.tier_service import require_feature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/credentials", tags=["auth"])


class CredentialMetadata(BaseModel):
    provider: str
    label: str | None
    created_at: datetime
    updated_at: datetime
    has_secret: bool = True

    model_config = {"from_attributes": True}


# Longest key accepted. Checked in the handler, not as a pydantic
# constraint: FastAPI's 422 body carries the rejected value as ``input``,
# so a constraint on ``secret`` would send an over-long key straight back
# in the response.
SECRET_MAX_CHARS = 2048


class CredentialUpsertPayload(BaseModel):
    # No length constraint here (see SECRET_MAX_CHARS). A non-string value
    # still fails type validation, and is not a key.
    secret: str
    label: str | None = Field(default=None, max_length=128)


class CredentialDeletedResponse(BaseModel):
    deleted: bool


@router.get("", response_model=list[CredentialMetadata])
def list_credentials(
    current_user: User = Depends(require_feature("byok_llm_keys")),
    db: Session = Depends(get_db),
) -> list[CredentialMetadata]:
    rows = byok_service.list_for_user(db, current_user.id)
    return [CredentialMetadata.model_validate(r) for r in rows]


@router.put("/{provider}", response_model=CredentialMetadata)
def set_credential(
    provider: str,
    payload: CredentialUpsertPayload,
    current_user: User = Depends(require_feature("byok_llm_keys")),
    db: Session = Depends(get_db),
) -> CredentialMetadata:
    """Upsert the credential for the given provider. The secret is
    encrypted at rest; the response carries metadata only — never the
    plaintext. Refusals never quote the submitted key."""
    if len(payload.secret) > SECRET_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Key is too long (at most {SECRET_MAX_CHARS} characters).",
        )
    if provider in SUPPORTED_PROVIDERS and provider not in RESOLVED_PROVIDERS:
        # Storable, but no call would ever read it (``local`` is the
        # install's own endpoint, keyed by LLM_LOCAL_API_KEY): refuse
        # rather than store a key that is silently ignored.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No call uses a stored key for '{provider}'. Keys are taken for: "
                f"{', '.join(sorted(RESOLVED_PROVIDERS))}."
            ),
        )
    try:
        row = byok_service.set_credential(
            db,
            user_id=current_user.id,
            provider=provider,
            secret=payload.secret,
            label=payload.label,
        )
    except UnsupportedProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except EncryptionConfigurationError:
        # BYOK_ENCRYPTION_KEY is set but malformed, so nothing can be
        # encrypted. The user cannot fix that; say so, and leave the
        # operator a log line. Neither carries the configured key or the
        # submitted one.
        logger.error(
            "BYOK key save refused: BYOK_ENCRYPTION_KEY is set but is not a "
            "valid Fernet key (32 url-safe base64-encoded bytes)"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Keys cannot be saved: this install's BYOK_ENCRYPTION_KEY is set "
                "but is not a valid key. Ask the operator to fix it."
            ),
        )
    return CredentialMetadata.model_validate(row)


@router.delete("/{provider}", response_model=CredentialDeletedResponse)
def delete_credential(
    provider: str,
    current_user: User = Depends(require_feature("byok_llm_keys")),
    db: Session = Depends(get_db),
) -> CredentialDeletedResponse:
    try:
        deleted = byok_service.delete_credential(
            db, user_id=current_user.id, provider=provider
        )
    except UnsupportedProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    return CredentialDeletedResponse(deleted=deleted)


@router.get("/providers", response_model=list[str])
def list_providers(
    _: User = Depends(require_feature("byok_llm_keys")),
) -> list[str]:
    """Return the providers a key can be set for: the ones an LLM call
    reads a stored key for (``RESOLVED_PROVIDERS``, the same list as
    ``GET /settings/llm`` ``byok.providers``). Useful for populating a
    credentials-management UI without hard-coding provider names."""
    return sorted(RESOLVED_PROVIDERS)
