"""Local authentication and authorization guardrails."""

import hmac
from typing import Optional
from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError

# Endpoints accessible without authentication
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/health",
    "/api/v1/ready",
)


def is_public_path(path: str) -> bool:
    """Check if the requested path is a designated public endpoint."""
    return any(path == p or path.startswith(f"{p}/") for p in PUBLIC_PATH_PREFIXES)


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract bearer token or API key from request headers."""
    # 1. Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        elif len(parts) == 1:
            return parts[0]

    # 2. Check X-API-Key header
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        return api_key_header.strip()

    return None


def constant_time_token_check(provided: Optional[str], expected: Optional[str]) -> bool:
    """Compare two tokens in constant time to prevent timing side-channel attacks."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def verify_authorization(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> bool:
    """FastAPI dependency enforcing local authorization on protected endpoints."""
    # Mock mode / Local development: bypass if auth_enabled is False
    if not settings.auth_enabled:
        return True

    # Public endpoints bypass authentication
    if is_public_path(request.url.path):
        return True

    # Extract token
    token = extract_token_from_request(request)
    if not token:
        raise UnauthorizedError(
            message="Authentication required. Provide 'Authorization: Bearer <token>' or 'X-API-Key'."
        )

    # Constant-time comparison to prevent timing side-channel attacks
    expected = settings.auth_token or ""
    if not constant_time_token_check(token, expected):
        raise ForbiddenError(message="Invalid authentication credentials.")

    return True


    return True
