import logging
from fastapi import FastAPI
from app.core.settings import get_settings
from app.db.init_db import init_db
from app.middleware.request_context import RequestContextMiddleware
from app.routers import photos, health

# OpenTelemetry (opcional)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(title="FotosCDO API")
app.add_middleware(RequestContextMiddleware)

# Init DB + PostGIS
init_db()

# Instrumentación OTEL si está habilitada
if settings.ENABLE_OTEL:
    resource = Resource(attributes={"service.name": settings.OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OpenTelemetry habilitado -> %s", settings.OTEL_EXPORTER_OTLP_ENDPOINT)
else:
    logger.info("OpenTelemetry deshabilitado")

# Routers
app.include_router(photos.router)
app.include_router(health.router)

# Incluir trace-id en todas las respuestas (si OTEL está activo)
from opentelemetry.trace import get_current_span
from starlette.responses import Response
from starlette.requests import Request

@app.middleware("http")
async def add_trace_headers(request: Request, call_next):
    response: Response = await call_next(request)
    span = get_current_span()
    if span and span.get_span_context().trace_id:
        trace_id = format(span.get_span_context().trace_id, '032x')
        response.headers["x-trace-id"] = trace_id
    return response