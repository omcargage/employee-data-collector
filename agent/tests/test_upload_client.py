"""Comprehensive unit and mock-server test suite for EDC Upload Client.

Validates:
- Device identity persistence.
- Keyring credential storage and isolation.
- Token enrollment exchange with backend.
- MetricBatch assembly from SQLite queue.
- Upload over HTTPS with Server Ack guarantee (200/201).
- Mock-server tests for:
    1. Server Outage (503 Service Unavailable / 500 error - zero data loss).
    2. Mid-upload Timeout (httpx.ReadTimeout - no loss, retried).
    3. Duplicate Ack (200 OK duplicate - marked done without duplicates).
- Exponential backoff with random jitter.
- Retention policy (prune delivered queue items > 14 days; pending/failed never pruned).
- AgentLifecycle integration with upload queue.
"""
from datetime import date, datetime, timedelta, timezone
from typing import List
from uuid import UUID, uuid4
import httpx
import pytest

from edc_agent.client.batch_builder import build_batch_from_queue
from edc_agent.client.device_identity import get_or_create_device_id
from edc_agent.client.enrollment import enroll_agent
from edc_agent.client.keyring_store import (
    delete_credential,
    enable_memory_keyring,
    get_credential,
    store_credential,
)
from edc_agent.client.uploader import UploadClient, compute_backoff_delay
from edc_agent.lifecycle import AgentLifecycle
from edc_agent.storage.database import Database
from edc_agent.storage.queue import UploadQueue
from edc_schemas import MetricBatch, Rollup15Min, RollupDaily, WindowBlocks


@pytest.fixture(autouse=True)
def isolated_memory_keyring():
    """Ensure in-memory mock keyring is enabled and clean for all tests."""
    enable_memory_keyring(True)
    delete_credential()
    yield
    delete_credential()
    enable_memory_keyring(False)


@pytest.fixture
def mem_db():
    """Fresh in-memory SQLite database."""
    return Database(":memory:")


@pytest.fixture
def queue(mem_db):
    """UploadQueue bound to in-memory DB."""
    return UploadQueue(mem_db)


def _create_sample_15min_rollup(db: Database) -> int:
    """Helper to insert a sample 15-minute rollup."""
    now = datetime.now(timezone.utc)
    blocks = WindowBlocks(n_char=60, n_backspace=3, flight_time_n=57, covered_s=900.0)
    rollup = Rollup15Min(
        window_start=now - timedelta(minutes=15),
        window_end=now,
        coverage_ratio=0.98,
        low_coverage=False,
        total_keystrokes=63,
        char_keystrokes=60,
        backspace_count=3,
        blocks=blocks,
    )
    return db.insert_rollup_15min(rollup)


def _create_sample_daily_rollup(db: Database, log_day: date = date(2026, 11, 15)) -> int:
    """Helper to insert a sample daily rollup."""
    rollup = RollupDaily(
        logical_day=log_day,
        coverage_ratio=0.95,
        low_coverage=False,
        avg_session_duration_mins=45.0,
        max_session_duration_mins=90.0,
        total_breaks_count=5,
    )
    return db.insert_rollup_daily(rollup)


# ==============================================================================
# 1. Device Identity & Keyring Store Tests
# ==============================================================================

def test_device_identity_persistence(mem_db):
    """Device ID is generated once and persistently returned from agent_state."""
    dev_id1 = get_or_create_device_id(mem_db)
    assert dev_id1.startswith("dev-")

    dev_id2 = get_or_create_device_id(mem_db)
    assert dev_id1 == dev_id2
    assert mem_db.get_agent_state("device_id") == dev_id1


def test_keyring_store_lifecycle():
    """Store, retrieve, and delete API credentials securely."""
    assert get_credential() is None

    store_credential("secret-api-key-xyz")
    assert get_credential() == "secret-api-key-xyz"

    assert delete_credential() is True
    assert get_credential() is None


# ==============================================================================
# 2. Agent Enrollment Tests
# ==============================================================================

def test_enroll_agent_success(mem_db):
    """Successful enrollment exchanges one-time token for API key and saves in keyring."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/devices/enroll"
        return httpx.Response(
            status_code=200,
            json={
                "status": "enrolled",
                "device_id": "dev-sample-1234",
                "employee_id": "emp-uuid-1",
                "employee_code": "E1001",
                "api_key": "edc_dev_key_test_token_abc",
                "enrolled_at": "2026-11-16T12:00:00Z",
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    res = enroll_agent(
        server_url="https://edc.example.com",
        enrollment_token="one-time-token-999",
        db=mem_db,
        device_id="dev-sample-1234",
        http_client=mock_client,
    )

    assert res["status"] == "enrolled"
    assert get_credential() == "edc_dev_key_test_token_abc"
    assert mem_db.get_agent_state("server_url") == "https://edc.example.com"
    assert mem_db.get_agent_state("employee_code") == "E1001"


def test_enroll_agent_rejection(mem_db):
    """Server rejection (e.g., token expired/used) raises ValueError without storing credential."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=400,
            json={"detail": "Enrollment token has expired or is invalid"},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    with pytest.raises(ValueError, match="Enrollment token has expired or is invalid"):
        enroll_agent(
            server_url="https://edc.example.com",
            enrollment_token="expired-token",
            db=mem_db,
            http_client=mock_client,
        )

    assert get_credential() is None


def test_enroll_agent_connection_error(mem_db):
    """Network connection failure during enrollment raises ConnectionError."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    with pytest.raises(ConnectionError, match="Could not connect to server"):
        enroll_agent(
            server_url="https://nonexistent.invalid",
            enrollment_token="tok-1",
            db=mem_db,
            http_client=mock_client,
        )


# ==============================================================================
# 3. Batch Builder Tests
# ==============================================================================

def test_batch_builder_from_queue(mem_db, queue):
    """Build a valid MetricBatch combining 15-minute and daily rollups from queue."""
    r15_id = _create_sample_15min_rollup(mem_db)
    rdaily_id = _create_sample_daily_rollup(mem_db)

    q1 = queue.enqueue("15min", r15_id)
    q2 = queue.enqueue("daily", rdaily_id)

    bundle = build_batch_from_queue(mem_db, queue, batch_size=10)
    assert bundle is not None
    batch, queue_ids = bundle

    assert isinstance(batch, MetricBatch)
    assert queue_ids == [q1, q2]
    assert len(batch.rollups) == 2
    assert batch.schema_version == "1.0.0"
    assert batch.device_id.startswith("dev-")


def test_batch_builder_empty_queue(mem_db, queue):
    """Empty queue yields None."""
    bundle = build_batch_from_queue(mem_db, queue)
    assert bundle is None


def test_batch_builder_skips_missing_rollups(mem_db, queue):
    """Queue items pointing to non-existent rollup IDs are skipped cleanly."""
    queue.enqueue("15min", 999999)  # Non-existent
    bundle = build_batch_from_queue(mem_db, queue)
    assert bundle is None


# ==============================================================================
# 4. Mock-Server Tests: Outage, Timeout, Duplicate Ack, and Server Ack
# ==============================================================================

def test_upload_success_on_server_ack_201(mem_db, queue):
    """Server responds 201 Created -> queue items marked 'done' ONLY upon server ack."""
    r15_id = _create_sample_15min_rollup(mem_db)
    q_id = queue.enqueue("15min", r15_id)
    store_credential("valid-api-key")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/metrics/batch"
        assert request.headers["authorization"] == "Bearer valid-api-key"
        return httpx.Response(
            status_code=201,
            json={
                "status": "processed",
                "batch_id": "test-batch",
                "rollups_count": 1,
                "message": "Batch ingested successfully",
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    client = UploadClient(
        db=mem_db,
        queue=queue,
        server_url="https://edc.example.com",
        http_client=mock_client,
    )

    res = client.sync_once()
    assert res["status"] == "success"
    assert res["status_code"] == 201
    assert res["count"] == 1

    # Verify queue status transitioned to 'done'
    item = queue.fetch_pending(include_failed=True)
    assert len(item) == 0  # No pending or failed items left!
    status_counts = queue.count_by_status()
    assert status_counts.get("done") == 1


def test_mock_server_outage_preserves_data(mem_db, queue):
    """Mock-Server Outage: HTTP 503 Service Unavailable marks items 'failed', zero data loss."""
    r15_id = _create_sample_15min_rollup(mem_db)
    q_id = queue.enqueue("15min", r15_id)
    store_credential("valid-api-key")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=503, text="Service Unavailable: Database failover")

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    client = UploadClient(
        db=mem_db,
        queue=queue,
        server_url="https://edc.example.com",
        http_client=mock_client,
    )

    res = client.sync_once()
    assert res["status"] == "server_rejected"
    assert res["status_code"] == 503

    # ZERO DATA LOSS: Item must NOT be marked done, remains in queue with status 'failed'
    pending_items = queue.fetch_pending(include_failed=True)
    assert len(pending_items) == 1
    assert pending_items[0].id == q_id
    assert pending_items[0].status == "failed"
    assert pending_items[0].attempts == 1


def test_mock_server_mid_upload_timeout_no_loss(mem_db, queue):
    """Mid-upload Timeout: httpx.ReadTimeout marks items 'failed', retried without loss."""
    r15_id = _create_sample_15min_rollup(mem_db)
    q_id = queue.enqueue("15min", r15_id)
    store_credential("valid-api-key")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Server timed out processing payload")

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    client = UploadClient(
        db=mem_db,
        queue=queue,
        server_url="https://edc.example.com",
        http_client=mock_client,
    )

    res = client.sync_once()
    assert res["status"] == "network_error"

    # ZERO DATA LOSS: Queue item must still be present and marked failed
    pending_items = queue.fetch_pending(include_failed=True)
    assert len(pending_items) == 1
    assert pending_items[0].status == "failed"
    assert pending_items[0].attempts == 1


def test_mock_server_duplicate_ack_after_timeout(mem_db, queue):
    """Mid-upload Timeout Recovery: Server received batch before timeout; retry returns duplicate ack 200.

    Guarantees:
    - Zero duplicates on server.
    - Zero data loss on client.
    - Queue item marked 'done' upon receiving duplicate ack.
    """
    r15_id = _create_sample_15min_rollup(mem_db)
    q_id = queue.enqueue("15min", r15_id)
    store_credential("valid-api-key")

    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt: Server actually processed batch, but connection timed out on return
            raise httpx.ReadTimeout("Connection dropped mid-flight")
        else:
            # Second attempt: Server recognizes duplicate batch_id and responds with HTTP 200 duplicate ack
            return httpx.Response(
                status_code=200,
                json={
                    "status": "duplicate",
                    "batch_id": "test-batch",
                    "rollups_count": 1,
                    "message": "Batch has already been received and processed (idempotent response)",
                },
            )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    client = UploadClient(
        db=mem_db,
        queue=queue,
        server_url="https://edc.example.com",
        http_client=mock_client,
    )

    # First attempt fails due to timeout
    first_res = client.sync_once()
    assert first_res["status"] == "network_error"
    items_after_timeout = queue.fetch_pending(include_failed=True)
    assert len(items_after_timeout) == 1
    assert items_after_timeout[0].status == "failed"

    # Second attempt retries: server responds with duplicate ack (HTTP 200)
    second_res = client.sync_once()
    assert second_res["status"] == "success"
    assert second_res["status_code"] == 200
    assert second_res["server_status"] == "duplicate"

    # Queue item is now marked 'done'!
    items_final = queue.fetch_pending(include_failed=True)
    assert len(items_final) == 0
    status_counts = queue.count_by_status()
    assert status_counts.get("done") == 1


# ==============================================================================
# 5. Exponential Backoff with Jitter Tests
# ==============================================================================

def test_exponential_backoff_with_jitter():
    """Verify exponential growth, max capping, and positive jitter."""
    delays_attempt_0 = [compute_backoff_delay(0, base_delay=1.0, max_delay=60.0) for _ in range(50)]
    delays_attempt_1 = [compute_backoff_delay(1, base_delay=1.0, max_delay=60.0) for _ in range(50)]
    delays_attempt_2 = [compute_backoff_delay(2, base_delay=1.0, max_delay=60.0) for _ in range(50)]
    delays_attempt_3 = [compute_backoff_delay(3, base_delay=1.0, max_delay=60.0) for _ in range(50)]

    # Attempt 0: 1.0 <= delay <= 1.25
    assert all(1.0 <= d <= 1.25 for d in delays_attempt_0)
    # Attempt 1: 2.0 <= delay <= 2.50
    assert all(2.0 <= d <= 2.50 for d in delays_attempt_1)
    # Attempt 2: 4.0 <= delay <= 5.00
    assert all(4.0 <= d <= 5.00 for d in delays_attempt_2)
    # Attempt 3: 8.0 <= delay <= 10.00
    assert all(8.0 <= d <= 10.00 for d in delays_attempt_3)

    # Check non-deterministic jitter variation
    assert len(set(delays_attempt_0)) > 1

    # Check capping at max_delay (e.g. attempt 20 should cap at max_delay + jitter)
    capped_delays = [compute_backoff_delay(20, base_delay=1.0, max_delay=30.0) for _ in range(20)]
    assert all(30.0 <= d <= 37.5 for d in capped_delays)


# ==============================================================================
# 6. Retention Policy Tests
# ==============================================================================

def test_retention_policy_prunes_only_old_delivered_items(mem_db, queue):
    """Retention policy prunes delivered ('done') items > 14 days; pending/failed NEVER pruned."""
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=20)).isoformat()
    recent_date = (now - timedelta(days=5)).isoformat()

    conn = mem_db.get_connection()
    # 1. Old 'done' item (should be pruned)
    conn.execute(
        "INSERT INTO upload_queue (batch_id, rollup_type, rollup_id, status, created_at) VALUES (?, '15min', 1, 'done', ?);",
        (str(uuid4()), old_date),
    )
    # 2. Recent 'done' item (should be kept)
    conn.execute(
        "INSERT INTO upload_queue (batch_id, rollup_type, rollup_id, status, created_at) VALUES (?, '15min', 2, 'done', ?);",
        (str(uuid4()), recent_date),
    )
    # 3. Old 'pending' item (must NOT be pruned: zero data loss guarantee!)
    conn.execute(
        "INSERT INTO upload_queue (batch_id, rollup_type, rollup_id, status, created_at) VALUES (?, '15min', 3, 'pending', ?);",
        (str(uuid4()), old_date),
    )
    # 4. Old 'failed' item (must NOT be pruned: zero data loss guarantee!)
    conn.execute(
        "INSERT INTO upload_queue (batch_id, rollup_type, rollup_id, status, created_at) VALUES (?, '15min', 4, 'failed', ?);",
        (str(uuid4()), old_date),
    )
    conn.commit()

    pruned = queue.prune_accepted(retention_days=14)
    assert pruned == 1  # Only the old 'done' item

    rows = conn.execute("SELECT rollup_id, status FROM upload_queue ORDER BY rollup_id ASC;").fetchall()
    remaining_rollup_ids = [r["rollup_id"] for r in rows]

    # Rollup 1 (old done) pruned; Rollups 2 (recent done), 3 (old pending), 4 (old failed) remain!
    assert remaining_rollup_ids == [2, 3, 4]


# ==============================================================================
# 7. Agent Lifecycle Queue Integration
# ==============================================================================

def test_agent_lifecycle_enqueues_rollups_to_upload_queue(mem_db):
    """AgentLifecycle automatically enqueues generated 15-minute and daily rollups."""
    lifecycle = AgentLifecycle(
        db=mem_db,
        require_consent=False,
    )

    assert lifecycle.upload_queue is not None
    # Simulate closing a 15-min window
    w_start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
    w_end = datetime(2026, 11, 16, 9, 15, tzinfo=timezone.utc)
    lifecycle.current_window = (w_start, w_end)
    rollup = lifecycle._close_window((w_start, w_end))

    # Verify rollup is in queue
    pending = lifecycle.upload_queue.fetch_pending()
    assert len(pending) == 1
    assert pending[0].rollup_type == "15min"
    assert pending[0].status == "pending"

    # Simulate closing a logical day
    daily_rollup = lifecycle._close_logical_day(date(2026, 11, 15))
    assert daily_rollup is not None

    pending_all = lifecycle.upload_queue.fetch_pending()
    assert len(pending_all) == 2
    types = [p.rollup_type for p in pending_all]
    assert "15min" in types
    assert "daily" in types


# ==============================================================================
# 8. CLI Command Integration
# ==============================================================================

def test_cli_enroll_and_upload(tmp_path, monkeypatch):
    """Test CLI commands cmd_enroll and cmd_upload."""
    from edc_agent.main import cmd_enroll, cmd_upload

    db_path = tmp_path / "cli_agent.db"
    file_db = Database(db_path)

    # Mock enroll handler
    def mock_enroll_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "status": "enrolled",
                "device_id": "dev-cli-123",
                "employee_id": "emp-uuid-1",
                "employee_code": "E1001",
                "api_key": "edc_cli_key",
                "enrolled_at": "2026-11-16T12:00:00Z",
            },
        )

    # Mock upload handler
    def mock_upload_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=201,
            json={"status": "processed", "batch_id": "cli-b", "rollups_count": 1, "message": "OK"},
        )

    mock_enroll_client = httpx.Client(transport=httpx.MockTransport(mock_enroll_handler))
    mock_upload_client = httpx.Client(transport=httpx.MockTransport(mock_upload_handler))

    # Test cmd_enroll with injected http_client via enroll_agent monkeypatch
    import edc_agent.main as edc_main
    original_enroll = edc_main.enroll_agent

    def patched_enroll(*args, **kwargs):
        kwargs["http_client"] = mock_enroll_client
        return original_enroll(*args, **kwargs)

    monkeypatch.setattr(edc_main, "enroll_agent", patched_enroll)

    # Enroll
    rc_enroll = cmd_enroll(token="cli-tok-123", server_url="https://edc.example.com", db_path=str(db_path))
    assert rc_enroll == 0
    assert get_credential() == "edc_cli_key"

    # Add item to queue
    r15_id = _create_sample_15min_rollup(file_db)
    queue = UploadQueue(file_db)
    queue.enqueue("15min", r15_id)

    # Patch UploadClient in main to use mock transport
    original_upload_client_init = UploadClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["http_client"] = mock_upload_client
        original_upload_client_init(self, *args, **kwargs)

    monkeypatch.setattr(UploadClient, "__init__", patched_init)

    rc_upload = cmd_upload(server_url="https://edc.example.com", db_path=str(db_path))
    assert rc_upload == 0

    # Ensure queue item is done
    assert len(queue.fetch_pending(include_failed=True)) == 0
