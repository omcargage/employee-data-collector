"""Comprehensive tests for device enrollment, authentication, and metric ingestion per Prompt 16.

Test cases:
- duplicate batch: idempotent handling without duplicate records
- bad payload: schema validation failures return 422
- wrong credential: missing/invalid API keys return 401
- payload claiming another employee: device claiming mismatched device_id returns 403
- enrollment lifecycle: one-time tokens, single-use enforcement, device binding
- device profile (/devices/me) and heartbeats (/devices/heartbeat)
"""
from datetime import date, datetime, timedelta, timezone
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from edc_schemas import MetricBatch, Rollup15Min, RollupDaily, WindowBlocks
from edc_server.core.security import generate_enrollment_token, hash_secret
from edc_server.db.models import Device, DeviceEnrollment, Employee, MetricBatchRecord, MetricRollupRecord


@pytest.fixture
def test_employee(db_session: Session) -> Employee:
    """Create a test employee in the database."""
    emp = Employee(
        employee_code="EMP-TEST-001",
        name="Jane Developer",
        department="Platform Engineering",
        is_active=True,
    )
    db_session.add(emp)
    db_session.commit()
    db_session.refresh(emp)
    return emp


@pytest.fixture
def enrolled_device(db_session: Session, test_employee: Employee) -> dict:
    """Create an enrolled device with known credentials."""
    raw_api_key = "edc_key_valid_test_secret_credential_123456"
    device_id = "test-device-win-001"

    dev = Device(
        id=device_id,
        employee_id=test_employee.id,
        platform="windows",
        os_version="Windows 11 23H2",
        agent_version="0.1.0",
        is_active=True,
    )
    db_session.add(dev)
    db_session.flush()

    enrollment = DeviceEnrollment(
        employee_id=test_employee.id,
        device_id=device_id,
        token_hash=hash_secret("used_enroll_token"),
        credential_hash=hash_secret(raw_api_key),
        status="enrolled",
    )
    db_session.add(enrollment)
    db_session.commit()

    return {
        "device": dev,
        "employee": test_employee,
        "api_key": raw_api_key,
        "headers": {"Authorization": f"Bearer {raw_api_key}"},
    }


def test_device_enrollment_lifecycle(client: TestClient, db_session: Session, test_employee: Employee):
    """Verify one-time token creation, successful device enrollment, and token single-use enforcement."""
    # 1. Admin/System issues one-time enrollment token
    create_resp = client.post(
        "/devices/tokens",
        json={"employee_code": test_employee.employee_code, "expires_in_days": 3},
    )
    assert create_resp.status_code == 201
    token_data = create_resp.json()
    enroll_token = token_data["enrollment_token"]

    # 2. Client enrolls using valid one-time token
    device_id = "new-laptop-hardware-id-999"
    enroll_resp = client.post(
        "/devices/enroll",
        json={
            "enrollment_token": enroll_token,
            "device_id": device_id,
            "platform": "windows",
            "os_version": "Windows 11 Pro",
            "agent_version": "0.1.0",
        },
    )
    assert enroll_resp.status_code == 200
    enroll_result = enroll_resp.json()
    assert enroll_result["status"] == "enrolled"
    assert enroll_result["device_id"] == device_id
    assert enroll_result["employee_code"] == test_employee.employee_code
    assert "api_key" in enroll_result
    new_api_key = enroll_result["api_key"]

    # 3. Attempting to reuse the one-time token MUST fail
    reuse_resp = client.post(
        "/devices/enroll",
        json={
            "enrollment_token": enroll_token,
            "device_id": "another-device-attempt",
            "platform": "windows",
        },
    )
    assert reuse_resp.status_code == 401
    assert "Invalid or already used" in reuse_resp.json()["detail"]

    # 4. Authenticate with newly received per-device API key
    headers = {"Authorization": f"Bearer {new_api_key}"}
    me_resp = client.get("/devices/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["device_id"] == device_id
    assert me_data["employee_code"] == test_employee.employee_code


def test_device_enrollment_with_invalid_or_expired_token(client: TestClient, db_session: Session, test_employee: Employee):
    """Verify enrollment fails with non-existent or expired tokens."""
    # Invalid token
    resp_invalid = client.post(
        "/devices/enroll",
        json={"enrollment_token": "non_existent_fake_token", "device_id": "dev-1", "platform": "windows"},
    )
    assert resp_invalid.status_code == 401

    # Expired token
    expired_token = "edc_enroll_expired_token_123"
    expired_enrollment = DeviceEnrollment(
        employee_id=test_employee.id,
        token_hash=hash_secret(expired_token),
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(expired_enrollment)
    db_session.commit()

    resp_expired = client.post(
        "/devices/enroll",
        json={"enrollment_token": expired_token, "device_id": "dev-2", "platform": "windows"},
    )
    assert resp_expired.status_code == 401
    assert "expired" in resp_expired.json()["detail"].lower()


def test_auth_wrong_credential(client: TestClient):
    """Verify that requests with missing, malformed, or wrong credentials return 401 Unauthorized."""
    # Missing header
    assert client.get("/devices/me").status_code == 401
    assert client.post("/devices/heartbeat", json={}).status_code == 401
    assert client.post("/metrics/batch", json={}).status_code == 401

    # Wrong credentials
    bad_headers = {"Authorization": "Bearer completely_fake_invalid_key_xyz"}
    assert client.get("/devices/me", headers=bad_headers).status_code == 401
    assert client.post("/devices/heartbeat", json={}, headers=bad_headers).status_code == 401
    assert client.post("/metrics/batch", json={}, headers=bad_headers).status_code == 401


def test_device_profile_and_heartbeat(client: TestClient, enrolled_device: dict):
    """Verify /devices/me returns authenticated metadata and /devices/heartbeat logs telemetry."""
    headers = enrolled_device["headers"]
    device_id = enrolled_device["device"].id

    # 1. /devices/me
    resp_me = client.get("/devices/me", headers=headers)
    assert resp_me.status_code == 200
    data_me = resp_me.json()
    assert data_me["device_id"] == device_id
    assert data_me["employee_code"] == enrolled_device["employee"].employee_code
    assert data_me["platform"] == "windows"

    # 2. /devices/heartbeat
    now_utc = datetime.now(timezone.utc).isoformat()
    resp_hb = client.post(
        "/devices/heartbeat",
        headers=headers,
        json={"ts_utc": now_utc, "agent_version": "0.1.0", "status": "collecting"},
    )
    assert resp_hb.status_code == 200
    data_hb = resp_hb.json()
    assert data_hb["status"] == "recorded"
    assert data_hb["device_id"] == device_id


def test_metrics_batch_ingestion_and_idempotency(client: TestClient, db_session: Session, enrolled_device: dict):
    """Verify valid batch ingestion and assert idempotency: submitting the same batch_id returns 200 without duplicates."""
    headers = enrolled_device["headers"]
    device_id = enrolled_device["device"].id

    batch_id = uuid.uuid4()
    w_start = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)
    w_end = w_start + timedelta(minutes=15)

    r15 = Rollup15Min(
        schema_version="1.0.0",
        agent_version="0.1.0",
        window_start=w_start,
        window_end=w_end,
        coverage_ratio=1.0,
        low_coverage=False,
        gross_wpm=68.5,
        net_wpm=65.0,
        blocks=WindowBlocks(covered_s=900.0, n_char=280),
    )

    r_daily = RollupDaily(
        schema_version="1.0.0",
        agent_version="0.1.0",
        logical_day=date(2026, 11, 16),
        coverage_ratio=0.95,
        low_coverage=False,
        after_hours_active_minutes=20.0,
        late_night_flag=False,
    )

    batch_payload = {
        "batch_id": str(batch_id),
        "device_id": device_id,
        "schema_version": "1.0.0",
        "rollups": [
            r15.model_dump(mode="json"),
            r_daily.model_dump(mode="json"),
        ],
    }

    # 1. First submission -> 201 Created
    resp_first = client.post("/metrics/batch", headers=headers, json=batch_payload)
    assert resp_first.status_code == 201
    data_first = resp_first.json()
    assert data_first["status"] == "accepted"
    assert data_first["batch_id"] == str(batch_id)
    assert data_first["rollups_count"] == 2

    # Check database records
    rollups_count_initial = db_session.query(MetricRollupRecord).filter_by(batch_id=batch_id).count()
    assert rollups_count_initial == 2

    # 2. Duplicate submission with exact same batch_id -> 200 OK (idempotent, no duplicate inserts)
    resp_duplicate = client.post("/metrics/batch", headers=headers, json=batch_payload)
    assert resp_duplicate.status_code == 200
    data_dup = resp_duplicate.json()
    assert data_dup["status"] == "duplicate"
    assert data_dup["batch_id"] == str(batch_id)

    # Rollups count MUST remain strictly 2
    rollups_count_after = db_session.query(MetricRollupRecord).filter_by(batch_id=batch_id).count()
    assert rollups_count_after == 2


def test_metrics_batch_bad_payload(client: TestClient, enrolled_device: dict):
    """Verify that malformed batches failing schema validation return 422 Unprocessable Entity."""
    headers = enrolled_device["headers"]
    device_id = enrolled_device["device"].id

    # 1. Missing batch_id
    bad_batch_1 = {
        "device_id": device_id,
        "rollups": [],
    }
    assert client.post("/metrics/batch", headers=headers, json=bad_batch_1).status_code == 422

    # 2. Invalid UUID format
    bad_batch_2 = {
        "batch_id": "not-a-valid-uuid",
        "device_id": device_id,
        "rollups": [],
    }
    assert client.post("/metrics/batch", headers=headers, json=bad_batch_2).status_code == 422

    # 3. Invalid rollup payload violating Pydantic schema
    bad_batch_3 = {
        "batch_id": str(uuid.uuid4()),
        "device_id": device_id,
        "rollups": [{"schema_version": "1.0.0", "coverage_ratio": "not-a-float"}],
    }
    assert client.post("/metrics/batch", headers=headers, json=bad_batch_3).status_code == 422


def test_metrics_batch_claiming_another_employee_or_device(
    client: TestClient, db_session: Session, enrolled_device: dict, test_employee: Employee
):
    """Verify security boundary: Device A cannot submit data claiming Device B or another employee."""
    headers_device_a = enrolled_device["headers"]

    # Create a second distinct employee and device (Device B)
    emp_b = Employee(employee_code="EMP-TEST-002", name="Bob Target")
    db_session.add(emp_b)
    db_session.flush()

    dev_b = Device(id="device-b-victim", employee_id=emp_b.id, platform="windows")
    db_session.add(dev_b)
    db_session.commit()

    # Device A sends a batch falsely claiming device_id = "device-b-victim"
    spoofed_batch = {
        "batch_id": str(uuid.uuid4()),
        "device_id": "device-b-victim",  # Spoofed device!
        "schema_version": "1.0.0",
        "rollups": [],
    }

    response = client.post("/metrics/batch", headers=headers_device_a, json=spoofed_batch)
    assert response.status_code == 403
    assert "does not match authenticated device" in response.json()["detail"]
