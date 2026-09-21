"""Request-origin checks for a local single-user app (not a login system)."""
import ipaddress
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _is_loopback_origin(value: str) -> bool:
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or parts.username or parts.password:
            return False
        if parts.hostname == "localhost":
            return True
        return ipaddress.ip_address(parts.hostname or "").is_loopback
    except (ValueError, TypeError):
        return False


class LocalWriteGuard(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            if (origin and not _is_loopback_origin(origin)) or site == "cross-site":
                return JSONResponse(status_code=403, content={"error": {"code": "CROSS_SITE_WRITE", "message": "仅允许本机页面发起修改请求"}})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
