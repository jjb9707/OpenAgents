"""Request ID middleware for the OpenAgents API.

Generates a UUID per request and sets X-Request-ID response header.
Accepts client-provided X-Request-ID header for distributed tracing.
"""

import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a unique request ID to every request.

    If the client provides an X-Request-ID header, that value is used
    (enabling distributed trace correlation). Otherwise a new UUID is
    generated. The chosen ID is set on the response via X-Request-ID.
    """

    async def dispatch(self, request: Request, call_next):
        # Accept client-provided request ID for distributed tracing,
        # or generate a new UUID if none is supplied
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        # Make the request ID available to downstream handlers via
        # request.state — useful for logging correlation
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
