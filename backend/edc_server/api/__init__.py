"""API endpoints and routing for EDC FastAPI server."""
from edc_server.api.health import router as health_router

__all__ = ["health_router"]
