"""FastAPI application entry point for Team SDE 7 (W5)."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import logger
from app.core.middleware import RequestCorrelationMiddleware
from app.models.errors import ErrorDetail, ErrorEnvelope
from app.routers import health, sessions


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown events."""
    settings = get_settings()
    logger.info(
        f"Starting {settings.app_name} [Team: {settings.team}] "
        f"[Workstream: {settings.workstream}] [Mode: {'MOCK' if settings.mock_mode else 'PROD'}]"
    )
    yield
    logger.info(f"Shutting down {settings.app_name}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Academiaai AI Voicebot Backend - Team SDE 7\n"
            "Workstream W5: Backend, Sessions and Observability (Week 1)"
        ),
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 1. Register Request and Correlation ID Middleware
    app.add_middleware(RequestCorrelationMiddleware)

    # 2. Register Global Exception Handlers for Typed Error Envelope

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """Handle custom application domain exceptions."""
        request_id = getattr(request.state, "request_id", None)
        envelope = ErrorEnvelope(
            success=False,
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                request_id=request_id,
                details=exc.details,
            ),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle Pydantic request validation errors (HTTP 422)."""
        request_id = getattr(request.state, "request_id", None)
        # Format field error details safely
        error_details = []
        for err in exc.errors():
            loc = " -> ".join(str(item) for item in err.get("loc", []))
            error_details.append({
                "field": loc,
                "issue": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            })

        envelope = ErrorEnvelope(
            success=False,
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request payload validation failed.",
                request_id=request_id,
                details=error_details,
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle standard HTTPExceptions including Starlette 404s."""
        request_id = getattr(request.state, "request_id", None)
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            500: "INTERNAL_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }
        code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
        envelope = ErrorEnvelope(
            success=False,
            error=ErrorDetail(
                code=code,
                message=str(exc.detail),
                request_id=request_id,
                details=None,
            ),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all handler for unhandled exceptions to prevent leaking stack traces."""
        request_id = getattr(request.state, "request_id", None)
        logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")

        envelope = ErrorEnvelope(
            success=False,
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An internal server error occurred. Please contact support with the request ID.",
                request_id=request_id,
                details=None,
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(mode="json"),
        )

    # 3. Mount Routers
    # Health checks available at root and versioned prefix
    app.include_router(health.router)
    app.include_router(health.router, prefix=settings.api_v1_prefix)

    # Session routes under versioned prefix /api/v1/sessions and unversioned /sessions
    app.include_router(sessions.router, prefix=settings.api_v1_prefix)
    app.include_router(sessions.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
