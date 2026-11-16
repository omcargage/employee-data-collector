"""Health check endpoint validating service and database connectivity."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from edc_server.config import settings
from edc_server.db.session import check_db_health, get_db

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Service and database health check")
def health_check(db: Session = Depends(get_db)) -> JSONResponse:
    """Validate server health and active database connectivity."""
    db_ok = check_db_health(db)
    timestamp = datetime.now(timezone.utc).isoformat()

    if db_ok:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ok",
                "service": settings.app_name,
                "version": settings.app_version,
                "database": "healthy",
                "timestamp": timestamp,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "degraded",
            "service": settings.app_name,
            "version": settings.app_version,
            "database": "unhealthy",
            "timestamp": timestamp,
        },
    )
