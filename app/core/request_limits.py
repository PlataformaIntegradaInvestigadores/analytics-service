"""Bound actual ASGI body bytes before JSON decoding, including streamed bodies."""

from starlette.responses import JSONResponse

from app.core.json_io import decode_json
from app.domain.common import AnalyticsError


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        lengths = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]
        try:
            if len(lengths) > 1 or lengths and (not lengths[0].isdigit()):
                raise ValueError
            declared = int(lengths[0]) if lengths else None
        except ValueError:
            response = JSONResponse(
                {
                    "detail": {
                        "code": "invalid_content_length",
                        "message": "Invalid body length header",
                    }
                },
                status_code=400,
            )
            return await response(scope, receive, send)

        async def too_large():
            response = JSONResponse(
                {
                    "detail": {
                        "code": "payload_too_large",
                        "message": "Request body exceeds configured byte limit",
                    }
                },
                status_code=413,
            )
            await response(scope, receive, send)

        if declared is not None and declared > self.max_bytes:
            return await too_large()
        body, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                return await too_large()
            body.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False
        if declared is not None and declared != total:
            response = JSONResponse(
                {
                    "detail": {
                        "code": "invalid_content_length",
                        "message": "Declared and received body sizes disagree",
                    }
                },
                status_code=400,
            )
            return await response(scope, receive, send)
        payload = b"".join(body)
        content_types = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-type"
        ]
        if (
            payload
            and content_types
            and (
                b"application/json" in content_types[0].lower()
                or b"+json" in content_types[0].lower()
            )
        ):
            try:
                decode_json(payload)
            except AnalyticsError as exc:
                response = JSONResponse(
                    {"detail": {"code": exc.code, "message": str(exc)}}, status_code=400
                )
                return await response(scope, receive, send)

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        return await self.app(scope, bounded_receive, send)
