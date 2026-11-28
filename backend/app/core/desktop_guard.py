"""Reject direct access to the local API when the desktop app is running.

Both services bind to loopback, but other local processes can still reach them.
The desktop launcher generates a per-launch secret and passes it to the Next.js
server, which adds it to every server-side proxy request. Comparison is
constant-time so the header cannot be guessed by timing.
"""

import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = "x-similia-desktop-token"


class DesktopTokenMiddleware:
    """Require the launcher's token on every request, including GraphQL WebSockets."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            supplied = Headers(scope=scope).get(HEADER, "").encode("utf-8")
            if not hmac.compare_digest(supplied, self._token):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await JSONResponse({"detail": "Desktop authentication required"}, 401)(
                        scope, receive, send
                    )
                return
        await self._app(scope, receive, send)
