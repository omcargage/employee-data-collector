"""API endpoints and routing for EDC FastAPI server."""
from edc_server.api.devices import router as devices_router
from edc_server.api.health import router as health_router
from edc_server.api.metrics import router as metrics_router

__all__ = ["health_router", "devices_router", "metrics_router"]
