"""Main FastAPI application entry point for the EDC backend server."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from edc_server.api.health import router as health_router
from edc_server.config import settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="EDC Telemetry Ingestion and Management API",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routers
    app.include_router(health_router)

    return app


app = create_app()
