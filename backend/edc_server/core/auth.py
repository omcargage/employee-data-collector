"""FastAPI dependency for device authentication using hashed per-device credentials."""
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from edc_server.core.security import hash_secret
from edc_server.db.models import Device, DeviceEnrollment
from edc_server.db.session import get_db


def get_authenticated_device(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    db: Session = Depends(get_db),
) -> Device:
    """Extract and validate per-device credential, returning the authenticated Device.

    Strict security boundary: Identity is derived solely from the authenticated credential,
    preventing any device from claiming another employee's identity.
    """
    token = None
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]
    elif x_device_token:
        token = x_device_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing device authentication credential (Authorization header required)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    cred_hash = hash_secret(token)

    stmt = (
        select(DeviceEnrollment)
        .where(
            DeviceEnrollment.credential_hash == cred_hash,
            DeviceEnrollment.status == "enrolled",
        )
    )
    enrollment = db.scalar(stmt)
    if not enrollment or not enrollment.device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked device credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check expiration
    now_utc = datetime.now(timezone.utc)
    if enrollment.expires_at:
        exp = enrollment.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now_utc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Device credentials have expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Check device active status
    device = enrollment.device
    if not device.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is marked inactive or decommissioned",
        )

    return device
