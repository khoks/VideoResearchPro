"""BYOK credentials router — E-5.6.

Per-user provider API keys, gated on the ``byok_llm_keys`` feature
(Studio tier). The router never returns the decrypted secret — only
metadata (provider, label, timestamps). To rotate a key, the user
sets a new value with PUT (which overwrites). To remove a key, DELETE.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import byok_service
from app.services.byok_service import (
    SUPPORTED_PROVIDERS,
    UnsupportedProviderError,
)
from app.services.tier_service import require_feature

router = APIRouter(prefix="/auth/credentials", tags=["auth"])


class CredentialMetadata(BaseModel):
    provider: str
    label: str | None
    created_at: datetime
    updated_at: datetime
    has_secret: bool = True

    model_config = {"from_attributes": True}


class CredentialUpsertPayload(BaseModel):
    secret: str = Field(min_length=1, max_length=2048)
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
    plaintext."""
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
    """Return the set of providers BYOK is supported for. Useful for
    populating the credentials-management UI without hard-coding
    provider names client-side."""
    return sorted(SUPPORTED_PROVIDERS)
