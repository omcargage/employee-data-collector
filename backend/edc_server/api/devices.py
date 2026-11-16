"""Device enrollment, authenticated heartbeat, and device profile endpoints."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from edc_server.core.auth import get_authenticated_device
from edc_server.core.security import generate_api_key, generate_enrollment_token, hash_secret
from edc_server.db.models import AgentHeartbeat, Device, DeviceEnrollment, Employee, utcnow
from edc_server.db.session import get_db

router = APIRouter(prefix="/devices", tags=["Devices"])


class CreateEnrollmentTokenRequest(BaseModel):
    employee_code: str
    expires_in_days: int = Field(default=7, ge=1, le=90)


class CreateEnrollmentTokenResponse(BaseModel):
    enrollment_token: str
    employee_code: str
    expires_at: str


class EnrollDeviceRequest(BaseModel):
    enrollment_token: str
    device_id: str
    platform: str  # "windows", "macos", "linux"
    os_version: Optional[str] = None
    agent_version: Optional[str] = None


class EnrollDeviceResponse(BaseModel):
    status: str
    device_id: str
    employee_id: str
    employee_code: str
    api_key: str
    token_type: str = "Bearer"


class HeartbeatRequest(BaseModel):
    ts_utc: Optional[datetime] = None
    agent_version: str = "0.1.0"
    status: str = "collecting"


class HeartbeatResponse(BaseModel):
    status: str
    device_id: str
    recorded_at: str


class DeviceProfileResponse(BaseModel):
    device_id: str
    platform: str
    os_version: Optional[str] = None
    agent_version: Optional[str] = None
    employee_id: str
    employee_code: str
    employee_name: str
    is_active: bool
    created_at: str
    last_seen_at: Optional[str] = None


@router.post("/tokens", response_model=CreateEnrollmentTokenResponse, status_code=status.HTTP_201_CREATED)
def create_enrollment_token(
    payload: CreateEnrollmentTokenRequest,
    db: Session = Depends(get_db),
) -> CreateEnrollmentTokenResponse:
    """Issue a secure, one-time enrollment token bound to an employee."""
    emp = db.scalar(select(Employee).where(Employee.employee_code == payload.employee_code))
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee '{payload.employee_code}' not found",
        )

    raw_token = generate_enrollment_token()
    token_hash = hash_secret(raw_token)
    expires_at = utcnow() + timedelta(days=payload.expires_in_days)

    enrollment = DeviceEnrollment(
        employee_id=emp.id,
        device_id=None,
        token_hash=token_hash,
        credential_hash=None,
        status="pending",
        expires_at=expires_at,
    )
    db.add(enrollment)
    db.commit()

    return CreateEnrollmentTokenResponse(
        enrollment_token=raw_token,
        employee_code=emp.employee_code,
        expires_at=expires_at.isoformat(),
    )


@router.post("/enroll", response_model=EnrollDeviceResponse, status_code=status.HTTP_200_OK)
def enroll_device(
    payload: EnrollDeviceRequest,
    db: Session = Depends(get_db),
) -> EnrollDeviceResponse:
    """Exchange a valid one-time enrollment token for a permanent hashed per-device credential."""
    token_hash = hash_secret(payload.enrollment_token)

    stmt = select(DeviceEnrollment).where(
        DeviceEnrollment.token_hash == token_hash,
        DeviceEnrollment.status == "pending",
    )
    enrollment = db.scalar(stmt)
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or already used enrollment token",
        )

    now = utcnow()
    if enrollment.expires_at:
        exp = enrollment.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Enrollment token has expired",
            )

    # Check if device ID already exists
    device = db.scalar(select(Device).where(Device.id == payload.device_id))
    if device is not None:
        if device.employee_id != enrollment.employee_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device is already registered to another employee",
            )
        # Update device properties
        device.platform = payload.platform
        device.os_version = payload.os_version
        device.agent_version = payload.agent_version
        device.last_seen_at = now
    else:
        # Create new device
        device = Device(
            id=payload.device_id,
            employee_id=enrollment.employee_id,
            platform=payload.platform,
            os_version=payload.os_version,
            agent_version=payload.agent_version,
            is_active=True,
            last_seen_at=now,
        )
        db.add(device)
        db.flush()

    # Generate permanent per-device credential and store its hash
    raw_api_key = generate_api_key()
    cred_hash = hash_secret(raw_api_key)

    enrollment.device_id = device.id
    enrollment.credential_hash = cred_hash
    enrollment.status = "enrolled"
    enrollment.enrolled_at = now

    db.commit()
    db.refresh(device)

    employee = device.employee
    return EnrollDeviceResponse(
        status="enrolled",
        device_id=device.id,
        employee_id=str(device.employee_id),
        employee_code=employee.employee_code,
        api_key=raw_api_key,
        token_type="Bearer",
    )


@router.get("/me", response_model=DeviceProfileResponse)
def get_current_device_profile(
    device: Device = Depends(get_authenticated_device),
) -> DeviceProfileResponse:
    """Return authenticated device details derived strictly from validated credentials."""
    emp = device.employee
    return DeviceProfileResponse(
        device_id=device.id,
        platform=device.platform,
        os_version=device.os_version,
        agent_version=device.agent_version,
        employee_id=str(device.employee_id),
        employee_code=emp.employee_code,
        employee_name=emp.name,
        is_active=device.is_active,
        created_at=device.created_at.isoformat(),
        last_seen_at=device.last_seen_at.isoformat() if device.last_seen_at else None,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
def record_device_heartbeat(
    payload: HeartbeatRequest,
    device: Device = Depends(get_authenticated_device),
    db: Session = Depends(get_db),
) -> HeartbeatResponse:
    """Record an authenticated agent alive heartbeat ping."""
    now = utcnow()
    device.last_seen_at = now

    heartbeat = AgentHeartbeat(
        device_id=device.id,
        ts_utc=payload.ts_utc or now,
        agent_version=payload.agent_version,
        status=payload.status,
        recorded_at=now,
    )
    db.add(heartbeat)
    db.commit()

    return HeartbeatResponse(
        status="recorded",
        device_id=device.id,
        recorded_at=now.isoformat(),
    )
