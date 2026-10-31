"""Typed error envelope models."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Structured details of an application error."""

    code: str = Field(..., description="Machine-readable error code (e.g. NOT_FOUND)")
    message: str = Field(..., description="Safe, client-facing error description")
    request_id: Optional[str] = Field(None, description="Associated request ID")
    details: Optional[Any] = Field(None, description="Optional metadata or validation error list")


class ErrorEnvelope(BaseModel):
    """Standardized top-level error response envelope."""

    success: bool = Field(False, description="Always False for error responses")
    error: ErrorDetail = Field(..., description="Detailed error payload")
