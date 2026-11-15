"""Tests for shared Pydantic schemas.

Validates that:
1. Valid payloads parse correctly.
2. Unknown / extra fields are strictly rejected.
3. No model can carry typed text, character identity, or clipboard data.
4. Merging two WindowBlocks yields the exact same totals as computing on the concatenated data.
"""
from datetime import date, datetime, timezone
from uuid import uuid4
import pytest
from pydantic import ValidationError

from edc_schemas import (
    ActivityEvent,
    EventKind,
    MetricBatch,
    Rollup15Min,
    RollupDaily,
    WindowBlocks,
)


def test_valid_payloads_parse():
    """Verify that all core schema models parse valid payloads cleanly."""
    now = datetime.now(timezone.utc)

    # 1. ActivityEvent: Keyboard
    key_event = ActivityEvent(
        ts_utc=now,
        kind=EventKind.KEY_CHAR,
    )
    assert key_event.kind == EventKind.KEY_CHAR
    assert key_event.x is None

    # 2. ActivityEvent: Mouse
    mouse_event = ActivityEvent(
        ts_utc=now,
        kind=EventKind.MOUSE_MOVE,
        x=1920.0,
        y=1080.0,
        button=1,
        scroll_ticks=0,
    )
    assert mouse_event.x == 1920.0
    assert mouse_event.button == 1

    # 3. WindowBlocks
    blocks = WindowBlocks(
        n_char=100,
        n_backspace=5,
        flight_time_n=95,
        flight_time_sum_ms=19000.0,
        flight_time_sum_sq_ms=4200000.0,
        covered_s=900.0,
    )
    assert blocks.n_char == 100
    assert blocks.flight_time_n == 95

    # 4. Rollup15Min
    rollup_15m = Rollup15Min(
        window_start=now,
        window_end=now,
        coverage_ratio=0.98,
        low_coverage=False,
        total_keystrokes=105,
        char_keystrokes=100,
        backspace_count=5,
        mean_flight_time_ms=200.0,
        blocks=blocks,
    )
    assert rollup_15m.coverage_ratio == 0.98
    assert rollup_15m.total_keystrokes == 105

    # 5. RollupDaily
    rollup_daily = RollupDaily(
        logical_day=date(2026, 11, 15),
        coverage_ratio=0.92,
        low_coverage=False,
        avg_session_duration_mins=45.5,
        total_breaks_count=6,
        lunch_skipped_flag=False,
    )
    assert rollup_daily.logical_day == date(2026, 11, 15)
    assert rollup_daily.total_breaks_count == 6

    # 6. MetricBatch
    batch = MetricBatch(
        batch_id=uuid4(),
        device_id="device-test-1234",
        rollups=[rollup_15m, rollup_daily],
    )
    assert len(batch.rollups) == 2
    assert batch.device_id == "device-test-1234"


def test_unknown_fields_are_rejected():
    """Verify that every schema strictly forbids unexpected extra fields."""
    now = datetime.now(timezone.utc)

    # ActivityEvent rejects extra fields
    with pytest.raises(ValidationError):
        ActivityEvent(
            ts_utc=now,
            kind=EventKind.KEY_CHAR,
            unexpected_field="disallowed",
        )

    # WindowBlocks rejects extra fields
    with pytest.raises(ValidationError):
        WindowBlocks(
            n_char=10,
            bogus_stat=123,
        )

    # Rollup15Min rejects extra fields
    blocks = WindowBlocks()
    with pytest.raises(ValidationError):
        Rollup15Min(
            window_start=now,
            window_end=now,
            coverage_ratio=1.0,
            low_coverage=False,
            blocks=blocks,
            unknown_column=99.9,
        )

    # RollupDaily rejects extra fields
    with pytest.raises(ValidationError):
        RollupDaily(
            logical_day=date(2026, 11, 15),
            coverage_ratio=1.0,
            extra_field="rejected",
        )

    # MetricBatch rejects extra fields
    with pytest.raises(ValidationError):
        MetricBatch(
            batch_id=uuid4(),
            device_id="dev-1",
            ip_address="192.168.1.1",
        )


def test_no_model_can_carry_typed_text():
    """Verify that models cannot carry typed characters, text, titles, or clipboard data."""
    forbidden_field_names = {
        "text", "typed_text", "key", "raw_key", "key_name", "char", "character",
        "clipboard", "window_title", "url", "title"
    }

    models = [ActivityEvent, WindowBlocks, Rollup15Min, RollupDaily, MetricBatch]
    for model in models:
        declared_fields = set(model.model_fields.keys())
        overlap = declared_fields.intersection(forbidden_field_names)
        assert not overlap, f"{model.__name__} must not define forbidden field(s): {overlap}"

    # Verify runtime injection of sensitive data is rejected
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        ActivityEvent(ts_utc=now, kind=EventKind.KEY_CHAR, text="confidential password")

    with pytest.raises(ValidationError):
        ActivityEvent(ts_utc=now, kind=EventKind.KEY_CHAR, key="A")

    with pytest.raises(ValidationError):
        ActivityEvent(ts_utc=now, kind=EventKind.KEY_CHAR, clipboard="copied snippet")


def test_merge_equals_concatenate():
    """Verify that merging two WindowBlocks gives identical statistics to computing on concatenated data."""
    # Raw observations for Interval 1
    flight_times_1 = [120.0, 150.0, 220.0, 450.0, 800.0, 1500.0]
    click_intervals_1 = [1.2, 2.5, 0.8]
    speeds_1 = [100.0, 200.0, 150.0]
    accels_1 = [50.0, 25.0]

    # Raw observations for Interval 2
    flight_times_2 = [85.0, 190.0, 310.0, 600.0, 1200.0]
    click_intervals_2 = [0.5, 3.1]
    speeds_2 = [180.0, 220.0]
    accels_2 = [40.0]

    def build_blocks_from_raw(flight_times, click_intervals, speeds, accels, counts):
        """Helper to compute sufficient statistics from raw numeric intervals."""
        # Histogram bins for flight times
        b0, b1, b2, b3, b4, b5 = 0, 0, 0, 0, 0, 0
        for ft in flight_times:
            if 0 <= ft < 100:
                b0 += 1
            elif 100 <= ft < 200:
                b1 += 1
            elif 200 <= ft < 300:
                b2 += 1
            elif 300 <= ft < 500:
                b3 += 1
            elif 500 <= ft < 1000:
                b4 += 1
            elif 1000 <= ft <= 2000:
                b5 += 1

        return WindowBlocks(
            n_char=counts["n_char"],
            n_backspace=counts["n_backspace"],
            n_delete=counts["n_delete"],
            n_other_key=counts["n_other_key"],
            n_clicks=counts["n_clicks"],
            n_double_clicks=counts["n_double_clicks"],
            n_rapid_click_runs=counts["n_rapid_click_runs"],
            n_scroll_ticks_abs=counts["n_scroll_ticks_abs"],
            n_scroll_reversals=counts["n_scroll_reversals"],
            flight_time_n=len(flight_times),
            flight_time_sum_ms=sum(flight_times),
            flight_time_sum_sq_ms=sum(x * x for x in flight_times),
            flight_bin_0_100=b0,
            flight_bin_100_200=b1,
            flight_bin_200_300=b2,
            flight_bin_300_500=b3,
            flight_bin_500_1000=b4,
            flight_bin_1000_2000=b5,
            click_interval_n=len(click_intervals),
            click_interval_sum_s=sum(click_intervals),
            click_interval_sum_sq_s=sum(c * c for c in click_intervals),
            n_moving_bins=len(speeds),
            sum_speed_px_s=sum(speeds),
            n_accel_samples=len(accels),
            sum_abs_accel_px_s2=sum(accels),
            covered_s=counts["covered_s"],
            active_typing_s=counts["active_typing_s"],
            active_minutes=counts["active_minutes"],
            idle_s=counts["idle_s"],
            n_bursts=counts["n_bursts"],
            sum_burst_len=counts["sum_burst_len"],
            n_long_silences_after_burst=counts["n_long_silences_after_burst"],
            n_correction_runs=counts["n_correction_runs"],
            n_backspace_bursts=counts["n_backspace_bursts"],
            sum_pause_before_correction_ms=counts["sum_pause_before_correction_ms"],
            dwell_n=counts["dwell_n"],
            dwell_sum_ms=counts["dwell_sum_ms"],
            dwell_sum_sq_ms=counts["dwell_sum_sq_ms"],
        )

    counts_1 = {
        "n_char": 25, "n_backspace": 2, "n_delete": 1, "n_other_key": 3,
        "n_clicks": 3, "n_double_clicks": 1, "n_rapid_click_runs": 0,
        "n_scroll_ticks_abs": 15, "n_scroll_reversals": 1,
        "covered_s": 900.0, "active_typing_s": 180.0, "active_minutes": 12, "idle_s": 300.0,
        "n_bursts": 2, "sum_burst_len": 14, "n_long_silences_after_burst": 1,
        "n_correction_runs": 1, "n_backspace_bursts": 0, "sum_pause_before_correction_ms": 320.0,
        "dwell_n": 25, "dwell_sum_ms": 2100.0, "dwell_sum_sq_ms": 185000.0,
    }

    counts_2 = {
        "n_char": 18, "n_backspace": 4, "n_delete": 0, "n_other_key": 2,
        "n_clicks": 2, "n_double_clicks": 0, "n_rapid_click_runs": 1,
        "n_scroll_ticks_abs": 8, "n_scroll_reversals": 2,
        "covered_s": 900.0, "active_typing_s": 120.0, "active_minutes": 8, "idle_s": 450.0,
        "n_bursts": 1, "sum_burst_len": 8, "n_long_silences_after_burst": 1,
        "n_correction_runs": 2, "n_backspace_bursts": 1, "sum_pause_before_correction_ms": 480.0,
        "dwell_n": 18, "dwell_sum_ms": 1550.0, "dwell_sum_sq_ms": 142000.0,
    }

    # Combined counts
    counts_concat = {k: counts_1[k] + counts_2[k] for k in counts_1}

    # 1. Compute block 1 and block 2 separately
    block1 = build_blocks_from_raw(flight_times_1, click_intervals_1, speeds_1, accels_1, counts_1)
    block2 = build_blocks_from_raw(flight_times_2, click_intervals_2, speeds_2, accels_2, counts_2)

    # 2. Merge them
    merged_block = block1.merge(block2)
    plus_block = block1 + block2
    assert merged_block == plus_block

    # 3. Compute block directly on concatenated raw data
    concatenated_block = build_blocks_from_raw(
        flight_times_1 + flight_times_2,
        click_intervals_1 + click_intervals_2,
        speeds_1 + speeds_2,
        accels_1 + accels_2,
        counts_concat,
    )

    # 4. Strict assertion: merged totals must be identical to concatenated totals
    assert merged_block == concatenated_block

    # 5. Hand-computed expected values verification
    assert merged_block.n_char == 43  # 25 + 18
    assert merged_block.n_backspace == 6  # 2 + 4
    assert merged_block.n_delete == 1  # 1 + 0
    assert merged_block.flight_time_n == 11  # 6 + 5
    # sum of flight times: 120+150+220+450+800+1500 + 85+190+310+600+1200 = 3240 + 2385 = 5625
    assert merged_block.flight_time_sum_ms == pytest.approx(5625.0)
    # click interval sum: (1.2 + 2.5 + 0.8) + (0.5 + 3.1) = 4.5 + 3.6 = 8.1
    assert merged_block.click_interval_sum_s == pytest.approx(8.1)
    # histogram bins:
    assert merged_block.flight_bin_0_100 == 1  # [85.0]
    assert merged_block.flight_bin_100_200 == 3  # [120.0, 150.0, 190.0]
    assert merged_block.flight_bin_200_300 == 1  # [220.0]
    assert merged_block.flight_bin_300_500 == 2  # [450.0, 310.0]
    assert merged_block.flight_bin_500_1000 == 2  # [800.0, 600.0]
    assert merged_block.flight_bin_1000_2000 == 2  # [1500.0, 1200.0]
    total_bins = (
        merged_block.flight_bin_0_100
        + merged_block.flight_bin_100_200
        + merged_block.flight_bin_200_300
        + merged_block.flight_bin_300_500
        + merged_block.flight_bin_500_1000
        + merged_block.flight_bin_1000_2000
    )
    assert total_bins == merged_block.flight_time_n
