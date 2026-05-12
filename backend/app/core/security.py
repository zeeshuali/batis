from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings


API_KEY_HEADER_NAME = "X-API-Key"


def get_expected_api_key() -> Optional[str]:
    return get_settings().backend_api_key


def api_key_auth(request: Request) -> None:
    """
    Simple API key auth using a shared secret in the BACKEND_API_KEY env var.
    If BACKEND_API_KEY is not set, auth is effectively disabled (for local dev).
    """
    expected = get_expected_api_key()
    if not expected:
        return

    header_val = request.headers.get(API_KEY_HEADER_NAME)
    if not header_val or header_val != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def api_key_dependency(_: None = Depends(api_key_auth)) -> None:  # pragma: no cover
    return None

