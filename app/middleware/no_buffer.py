"""Disable proxy response buffering for JSON API routes."""
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_NO_BUFFER = (
    (b"cache-control", b"no-store, no-cache, must-revalidate"),
    (b"x-accel-buffering", b"no"),
    (b"pragma", b"no-cache"),
)


class NoBufferMiddleware:
    """Set headers so nginx/reverse proxies flush JSON responses immediately."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = list(message.get("headers") or [])
                names = {k.lower() for k, _ in existing}
                for key, val in _NO_BUFFER:
                    if key not in names:
                        existing.append((key, val))
                message = {**message, "headers": existing}
            await send(message)

        await self.app(scope, receive, send_wrapper)
