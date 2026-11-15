"""Unit and integration tests for privacy notices, consent enforcement, self-report check-ins,

registry-compliant exports, and complete data deletion per Prompt 13.

Validates:
1. No collection before consent (lifecycle start fails without explicit consent).
2. End-of-day check-in ratings (1-5 Likert scale, stored with logical day, skippable).
3. Export CSV contains NO unexpected columns (strictly registry columns + joined labels).
4. Delete deletes (wipe local data clears all tables upon confirmation).
5. End-to-end: run a day, answer check-in, and export CSV with metrics and joined labels.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
import csv
from pathlib import Path
import zoneinfo
import pytest

from edc_schemas import ActivityEvent, EventKind, Rollup15Min, RollupDaily, WindowBlocks
from edc_agent.config import EDCConfig
from edc_agent.lifecycle import AgentLifecycle
from edc_agent.platforms.fake import FakeInputProvider
from edc_agent.privacy.consent import (
    CONSENT_NOTICE_VERSION,
    has_consent,
    prompt_for_consent,
    record_consent,
    revoke_consent,
)
from edc_agent.privacy.delete import delete_all_data
from edc_agent.privacy.export import export_data_to_csv, load_registry_columns
from edc_agent.privacy.self_report import (
    get_checkin_for_day,
    prompt_checkin,
    record_checkin,
    validate_rating,
)
from edc_agent.storage.database import Database


def test_no_collection_before_consent():
    """Verify that agent refuses to start and raises PermissionError if consent is not acknowledged."""
    db = Database(":memory:")
    config = EDCConfig(timezone="Asia/Kolkata")
    provider = FakeInputProvider(callback=lambda ev: None)

    # 1. Initially no consent exists
    assert has_consent(db) is False

    lifecycle = AgentLifecycle(
        config=config,
        db=db,
        provider=provider,
        require_consent=True,
    )

    with pytest.raises(PermissionError) as exc_info:
        lifecycle.start()
    assert "consent acknowledgement" in str(exc_info.value).lower()
    assert lifecycle.status == "stopped"

    # 2. Grant explicit consent
    record_consent(db, version=CONSENT_NOTICE_VERSION)
    assert has_consent(db) is True

    # 3. Collection now starts successfully
    lifecycle.start()
    assert lifecycle.status == "collecting"
    lifecycle.stop()

    # 4. Revoking consent halts further collection
    revoke_consent(db)
    assert has_consent(db) is False

    lifecycle2 = AgentLifecycle(config=config, db=db, provider=provider, require_consent=True)
    with pytest.raises(PermissionError):
        lifecycle2.start()


def test_self_report_ratings_and_skippable_checkin():
    """Verify 1-5 rating validation, storage in self_reports with logical day, and skippable check-ins."""
    db = Database(":memory:")
    day = date(2026, 11, 16)

    # 1. Rating validation (1-5 only)
    assert validate_rating("stress", 1) == 1
    assert validate_rating("energy", 5) == 5
    with pytest.raises(ValueError):
        validate_rating("stress", 0)
    with pytest.raises(ValueError):
        validate_rating("workload", 6)

    # 2. Record check-in
    record_checkin(db, logical_day=day, stress=4, energy=2, workload=5)
    retrieved = get_checkin_for_day(db, logical_day=day)
    assert retrieved is not None
    assert retrieved["stress"] == 4
    assert retrieved["energy"] == 2
    assert retrieved["workload"] == 5

    # Check non-existent day returns None
    assert get_checkin_for_day(db, logical_day=date(2026, 11, 17)) is None

    # 3. Skippable check-in returns False and does not store invalid ratings
    day2 = date(2026, 11, 17)
    res = prompt_checkin(db, logical_day=day2, skip=True)
    assert res is False
    assert get_checkin_for_day(db, logical_day=day2) is None


def test_export_contains_no_unexpected_columns(tmp_path: Path):
    """Verify that exported 15-minute and daily CSVs contain ONLY columns declared in the registry

    plus the joined labels (stress, energy, workload). No internal IDs or raw blobs.
    """
    db = Database(":memory:")
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    work_date = date(2026, 11, 16)

    # Record consent & a check-in label
    record_consent(db)
    record_checkin(db, logical_day=work_date, stress=3, energy=4, workload=4)

    # Insert a synthetic 15-min rollup
    w_start = datetime(2026, 11, 16, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    w_end = datetime(2026, 11, 16, 9, 15, tzinfo=tz).astimezone(dt_timezone.utc)
    r15 = Rollup15Min(
        schema_version="1.0.0",
        agent_version="0.1.0",
        window_start=w_start,
        window_end=w_end,
        coverage_ratio=1.0,
        low_coverage=False,
        day_of_week=0,
        is_weekend=False,
        hour_of_day=9,
        decimal_hour=9.0,
        blocks=WindowBlocks(covered_s=900.0, active_minutes=12, n_char=120),
        total_keystrokes=120,
    )
    db.insert_rollup_15min(r15)

    # Insert a synthetic daily rollup
    rd = RollupDaily(
        schema_version="1.0.0",
        agent_version="0.1.0",
        logical_day=work_date,
        day=work_date.isoformat(),
        coverage_ratio=0.95,
        low_coverage=False,
        day_of_week=0,
        is_weekend=False,
        avg_session_duration_mins=45.0,
        shift_start="09:00",
        shift_end="18:00",
    )
    db.insert_rollup_daily(rd)

    # Export CSVs
    f_15min, f_daily = export_data_to_csv(db, output_dir=tmp_path, prefix="test_export")

    # Load canonical columns from registry
    cols_15min, cols_daily = load_registry_columns()
    expected_15min_headers = set(cols_15min + ["stress", "energy", "workload"])
    expected_daily_headers = set(cols_daily + ["stress", "energy", "workload"])

    # 1. Check 15-minute CSV headers
    with open(f_15min, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers_15min = next(reader)
        row1 = next(reader)

    unexpected_15min = set(headers_15min) - expected_15min_headers
    assert unexpected_15min == set(), f"Unexpected columns found in 15-min export: {unexpected_15min}"
    # Verify no raw payload or internal id leaked
    assert "payload" not in headers_15min
    assert "blocks" not in headers_15min
    assert "id" not in headers_15min

    # Check joined label values in row
    stress_idx = headers_15min.index("stress")
    energy_idx = headers_15min.index("energy")
    workload_idx = headers_15min.index("workload")
    assert row1[stress_idx] == "3"
    assert row1[energy_idx] == "4"
    assert row1[workload_idx] == "4"

    # 2. Check Daily CSV headers
    with open(f_daily, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers_daily = next(reader)
        d_row1 = next(reader)

    unexpected_daily = set(headers_daily) - expected_daily_headers
    assert unexpected_daily == set(), f"Unexpected columns found in daily export: {unexpected_daily}"
    assert "payload" not in headers_daily
    assert "id" not in headers_daily

    d_stress_idx = headers_daily.index("stress")
    assert d_row1[d_stress_idx] == "3"


def test_delete_all_data_clears_all_tables():
    """Verify that edc delete-all-data permanently wipes all local records upon confirmation."""
    db = Database(":memory:")
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    work_date = date(2026, 11, 16)

    # Populate all tables
    record_consent(db)
    record_checkin(db, logical_day=work_date, stress=4, energy=3, workload=4)
    db.set_agent_state("status", "collecting")

    w_start = datetime(2026, 11, 16, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    w_end = datetime(2026, 11, 16, 9, 15, tzinfo=tz).astimezone(dt_timezone.utc)
    r15 = Rollup15Min(
        window_start=w_start,
        window_end=w_end,
        coverage_ratio=1.0,
        low_coverage=False,
        blocks=WindowBlocks(covered_s=900.0),
    )
    db.insert_rollup_15min(r15)

    rd = RollupDaily(
        logical_day=work_date,
        coverage_ratio=0.9,
    )
    db.insert_rollup_daily(rd)

    # Verify tables have data
    assert db.get_rollups_15min_count() == 1
    assert db.get_rollups_daily_count() == 1
    assert len(db.get_self_reports()) > 0
    assert db.get_latest_consent_record() is not None

    # Unconfirmed delete -> cancels without changes
    res_cancelled = delete_all_data(db, confirmed=False)
    assert res_cancelled is False
    assert db.get_rollups_15min_count() == 1

    # Confirmed delete -> wipes everything
    res_deleted = delete_all_data(db, confirmed=True)
    assert res_deleted is True

    # Assert complete erasure
    assert db.get_rollups_15min_count() == 0
    assert db.get_rollups_daily_count() == 0
    assert len(db.get_self_reports()) == 0
    assert db.get_latest_consent_record() is None
    assert db.get_agent_state("status") is None


def test_end_to_end_day_run_checkin_and_export(tmp_path: Path):
    """End-to-end integration test: acknowledge consent, run a day's collection,

    submit end-of-day check-in, and export CSV joined with metrics and labels.
    """
    db = Database(":memory:")
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    work_date = date(2026, 11, 16)

    # 1. Acknowledge consent
    assert has_consent(db) is False
    record_consent(db, version="1.0.0")
    assert has_consent(db) is True

    config = EDCConfig(
        timezone="Asia/Kolkata",
        shift_start="09:00",
        shift_end="18:00",
        lunch_window="12:30-13:15",
        logical_day_start="05:00",
    )

    t_start = datetime(2026, 11, 16, 9, 0, tzinfo=tz).astimezone(dt_timezone.utc)
    test_events = [
        ActivityEvent(ts_utc=t_start + timedelta(minutes=m), kind=EventKind.KEY_CHAR)
        for m in range(0, 180, 2)
    ]
    provider = FakeInputProvider(callback=lambda ev: None, events=test_events)

    lifecycle = AgentLifecycle(
        config=config,
        db=db,
        provider=provider,
        window_minutes=15,
        require_consent=True,
    )
    provider.callback = lifecycle.on_event

    lifecycle.start(start_time_utc=t_start)

    # Advance through morning windows up to 12:00
    cur_time = t_start
    for _ in range(12):
        for ev in test_events:
            if cur_time <= ev.ts_utc < cur_time + timedelta(minutes=15):
                lifecycle.on_event(ev)
        cur_time += timedelta(minutes=15)
        lifecycle.tick(cur_time)

    # Advance to next day boundary to close the day
    next_day_utc = datetime(2026, 11, 17, 5, 5, tzinfo=tz).astimezone(dt_timezone.utc)
    lifecycle.tick(next_day_utc)
    lifecycle.stop()

    # 2. Verify rollups created
    assert db.get_rollups_15min_count() >= 12
    assert db.get_rollups_daily_count() >= 1

    # 3. Answer end-of-day check-in
    prompt_checkin(db, logical_day=work_date, ratings=(4, 5, 3))
    checkin = get_checkin_for_day(db, work_date)
    assert checkin == {"stress": 4, "energy": 5, "workload": 3}

    # 4. Export CSV with joined labels
    f_15min, f_daily = export_data_to_csv(db, output_dir=tmp_path, prefix="e2e")
    assert f_15min.exists()
    assert f_daily.exists()

    with open(f_15min, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) >= 12
        assert rows[0]["stress"] == "4"
        assert rows[0]["energy"] == "5"
        assert rows[0]["workload"] == "3"

    with open(f_daily, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        d_rows = list(reader)
        assert len(d_rows) >= 1
        assert d_rows[0]["stress"] == "4"
        assert d_rows[0]["energy"] == "5"
        assert d_rows[0]["workload"] == "3"
        assert d_rows[0]["day"] == "2026-11-16"
