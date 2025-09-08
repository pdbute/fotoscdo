import logging
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        operation_id = request.headers.get("x-operation-id") or str(uuid.uuid4())
        request.state.operation_id = operation_id
        response: Response = await call_next(request)
        response.headers["x-operation-id"] = operation_id
        return response