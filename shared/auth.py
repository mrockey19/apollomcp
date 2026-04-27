import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class McpAuthMiddleware(BaseHTTPMiddleware):
    """Validates X-MCP-Auth header using constant-time comparison."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        expected = os.environ.get("MCP_SHARED_SECRET", "")
        provided = request.headers.get("X-MCP-Auth", "")

        if not expected or not hmac.compare_digest(expected, provided):
            return JSONResponse(
                {"error": "Unauthorized"}, status_code=401
            )

        return await call_next(request)
