"""Security middleware for localhost boundary defense, client header verification, and payload caps."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.backend.logging import format_logfmt, get_logger

logger = get_logger("security")

# Standard CORS allowed origins for extension and local reader
ALLOWED_CORS_ORIGINS: list[str] = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

ALLOWED_CLIENT_HEADERS: set[str] = {"extension", "reader"}
MAX_PAYLOAD_BYTES: int = 20_000_000  # 20 MB cap
EXEMPT_PATHS: set[str] = {
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def validate_image_magic_bytes(raw_bytes: bytes) -> bool:
    """Validate that raw bytes begin with canonical magic bytes for JPEG, PNG, or WebP.

    Returns False if format is invalid or bytes are too short.
    """
    if len(raw_bytes) < 4:
        return False

    # JPEG: \xff\xd8\xff
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return True

    # PNG: \x89PNG\r\n\x1a\n
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return True

    # WebP: RIFF....WEBP
    return bool(
        raw_bytes.startswith(b"RIFF")
        and len(raw_bytes) >= 12
        and raw_bytes[8:12] == b"WEBP"
    )



class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces request payload caps and validates X-InkShift-Client on protected routes."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 1. Payload size guard (HTTP 413)
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
                if content_length > MAX_PAYLOAD_BYTES:
                    client_host = request.client.host if request.client else "unknown"
                    logger.warning(
                        format_logfmt(
                            "PayloadSizeExceeded",
                            client_ip=client_host,
                            content_length=content_length,
                            max_allowed=MAX_PAYLOAD_BYTES,
                        )
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "success": False,
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": f"Payload size {content_length} bytes exceeds 20MB maximum limit.",
                            },
                        },
                    )
            except ValueError:
                pass

        # 2. Client header verification for protected /api/v1/* routes (HTTP 403)
        path = request.url.path
        if path.startswith("/api/v1/") and path not in EXEMPT_PATHS:
            client_header = request.headers.get("X-InkShift-Client")
            if client_header is None or client_header.lower() not in ALLOWED_CLIENT_HEADERS:
                client_host = request.client.host if request.client else "unknown"
                logger.warning(
                    format_logfmt(
                        "ForbiddenClientHeader",
                        client_ip=client_host,
                        path=path,
                        client_header=client_header or "none",
                    )
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "error": {
                            "code": "FORBIDDEN_CLIENT",
                            "message": "Access denied. Protected endpoints require valid 'X-InkShift-Client' header ('extension' or 'reader').",
                        },
                    },
                )

        return await call_next(request)
