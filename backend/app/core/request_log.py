"""Request logging that is safe for a clinical app.

One line per request: id, method, path, status and duration. Never the query string, the
headers, the body, or the user's identity: all of those can contain patient information or
secrets. The request id is returned in `X-Request-ID` so a doctor can quote it in a bug report.
"""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("similia.request")
_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_UUID_IN_PATH = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def configure_logging(level: str = "INFO") -> None:
    """Plain, single-line log format. Idempotent."""
    root = logging.getLogger()
    if not any(getattr(h, "_similia", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler._similia = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
    root.setLevel(level.upper() if level.upper() in logging._nameToLevel else "INFO")
    # Upstream request URLs can contain PostgREST filters and private object keys.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_path(path: str) -> str:
    """Record ids are replaced so the log cannot be used to follow one patient around."""
    return _UUID_IN_PATH.sub("{id}", path)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _SAFE_ID.match(supplied) else uuid.uuid4().hex
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.info(
                "%s %s %s %s %dms",
                request_id,
                request.method,
                log_path(request.url.path),
                status,
                elapsed,
            )
        response.headers["X-Request-ID"] = request_id
        return response
