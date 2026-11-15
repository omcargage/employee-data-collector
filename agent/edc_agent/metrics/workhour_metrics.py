"""Pure functions computing work-hours and after-hours metrics and daily rollup aggregation per Spec Section 7.

Computes:
- shift_start, shift_end (from employee config).
- after_hours_active_minutes: active minutes outside shift hours, or all active minutes on non-working days.
- after_hours_ratio: after_hours_active_minutes / total_active_minutes (None if total is 0).
- late_night_flag: True if active minutes in late_night_window >= late_night_min.
- after_hours_ratio_7d_avg: 7-day rolling average over valid days (coverage >= 0.5), None if < 4 valid days.
- consecutive_after_hours_days: streak of consecutive days ending today with after_hours_active_minutes >= after_hours_day_min.
- build_rollup_daily: unified aggregator producing strict RollupDaily instances.
"""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
import zoneinfo
from typing import Any, Dict, List, Optional, Sequence, Union

from edc_schemas import ActivityEvent, EventKind, RollupDaily
from edc_agent.collectors.gap_classifier import GapType
from edc_agent.metrics.session_metrics import ClassifiedGap, compute_session_metrics


def compute_workhour_metrics(
    events: Sequence[ActivityEvent],
    logical_day: date,
    *,
    coverage_ratio: float = 1.0,
    tz_name: str = "Asia/Kolkata",
    shift_start: str = "09:00",
    shift_end: str = "18:00",
    late_night_window: str = "22:00-05:00",
    after_hours_day_min: int = 30,
    late_night_min: int = 10,
    history_days: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Compute daily work-hours and after-hours metrics.

    Pure function over plain data. No I/O, no side effects.
    """
    tz = zoneinfo.ZoneInfo(tz_name)

    # 1. Day of week and weekend determination
    day_of_week = logical_day.weekday()
    is_weekend = day_of_week in (5, 6)

    # 2. Filter for active input events (exclude modifier-only key events)
    active_events = [
        ev for ev in events
        if ev.kind != EventKind.KEY_MODIFIER
    ]

    # 3. Calendar active minutes in local time
    active_minutes_set = set()
    for ev in active_events:
        dt_local = ev.ts_utc.astimezone(tz)
        active_minutes_set.add((dt_local.year, dt_local.month, dt_local.day, dt_local.hour, dt_local.minute))

    total_active_minutes = len(active_minutes_set)

    # 4. Parse shift window (e.g. 09:00 to 18:00)
    sh, sm = map(int, shift_start.split(":"))
    eh, em = map(int, shift_end.split(":"))
    shift_start_time = time(sh, sm)
    shift_end_time = time(eh, em)

    # 5. Parse late night window (e.g. 22:00 to 05:00)
    ln_start_str, ln_end_str = late_night_window.split("-")
    lnh_s, lnm_s = map(int, ln_start_str.split(":"))
    lnh_e, lnm_e = map(int, ln_end_str.split(":"))
    ln_start_time = time(lnh_s, lnm_s)
    ln_end_time = time(lnh_e, lnm_e)

    def is_in_late_night(t_val: time) -> bool:
        if ln_start_time > ln_end_time:
            # Crosses midnight: e.g. >= 22:00 or < 05:00
            return t_val >= ln_start_time or t_val < ln_end_time
        return ln_start_time <= t_val < ln_end_time

    # 6. Classify active minutes
    after_hours_count = 0
    late_night_count = 0

    for yr, mo, dy, hr, mn in active_minutes_set:
        m_time = time(hr, mn)

        if is_weekend:
            # On non-working days, all active minutes are after-hours
            after_hours_count += 1
        else:
            if m_time < shift_start_time or m_time >= shift_end_time:
                after_hours_count += 1

        if is_in_late_night(m_time):
            late_night_count += 1

    after_hours_active_minutes = float(after_hours_count)
    after_hours_ratio: Optional[float] = None
    if total_active_minutes > 0:
        after_hours_ratio = after_hours_active_minutes / total_active_minutes

    late_night_flag = late_night_count >= late_night_min

    # 7. Rolling 7-day average and consecutive after-hours days streak
    # Assemble historical records dictionary mapped by logical_day
    day_records: Dict[date, Dict[str, Any]] = {}
    if history_days:
        for item in history_days:
            if hasattr(item, "model_dump"):
                d_dict = item.model_dump()
            elif isinstance(item, dict):
                d_dict = item
            else:
                continue

            d_date = d_dict.get("logical_day")
            if isinstance(d_date, str):
                d_date = date.fromisoformat(d_date)
            if isinstance(d_date, date):
                day_records[d_date] = d_dict

    # Include today
    day_records[logical_day] = {
        "logical_day": logical_day,
        "coverage_ratio": coverage_ratio,
        "after_hours_ratio": after_hours_ratio,
        "after_hours_active_minutes": after_hours_active_minutes,
    }

    # 7-day rolling window: [logical_day - 6 days, logical_day]
    valid_7d_ratios: List[float] = []
    for i in range(7):
        target_day = logical_day - timedelta(days=i)
        rec = day_records.get(target_day)
        if rec:
            cov = rec.get("coverage_ratio", 0.0)
            ratio_val = rec.get("after_hours_ratio")
            if cov >= 0.5 and ratio_val is not None:
                valid_7d_ratios.append(float(ratio_val))

    after_hours_ratio_7d_avg: Optional[float] = None
    if len(valid_7d_ratios) >= 4:
        after_hours_ratio_7d_avg = sum(valid_7d_ratios) / len(valid_7d_ratios)

    # Consecutive after-hours days ending today (after_hours_active_minutes >= after_hours_day_min)
    consecutive_after_hours_days = 0
    curr_day = logical_day
    while True:
        rec = day_records.get(curr_day)
        if not rec:
            break
        ah_mins = rec.get("after_hours_active_minutes", 0.0) or 0.0
        if ah_mins >= after_hours_day_min:
            consecutive_after_hours_days += 1
            curr_day = curr_day - timedelta(days=1)
        else:
            break

    return {
        "shift_start": shift_start,
        "shift_end": shift_end,
        "after_hours_active_minutes": after_hours_active_minutes,
        "after_hours_ratio": after_hours_ratio,
        "late_night_flag": late_night_flag,
        "after_hours_ratio_7d_avg": after_hours_ratio_7d_avg,
        "consecutive_after_hours_days": consecutive_after_hours_days,
    }


def build_rollup_daily(
    logical_day: date,
    events: Sequence[ActivityEvent],
    coverage_ratio: float,
    *,
    classified_gaps: Optional[Sequence[ClassifiedGap]] = None,
    history_days: Optional[Sequence[Any]] = None,
    tz_name: str = "Asia/Kolkata",
    shift_start: str = "09:00",
    shift_end: str = "18:00",
    late_night_window: str = "22:00-05:00",
    after_hours_day_min: int = 30,
    late_night_min: int = 10,
    **session_kwargs,
) -> RollupDaily:
    """Aggregate a day's event timeline into a validated RollupDaily instance."""
    day_of_week = logical_day.weekday()
    is_weekend = day_of_week in (5, 6)
    low_coverage = coverage_ratio < 0.5

    # Compute session, break, stretch, lunch, and focus metrics
    sess_metrics = compute_session_metrics(
        events,
        classified_gaps=classified_gaps,
        tz_name=tz_name,
        **session_kwargs,
    )

    # Compute work-hours, after-hours, and rolling stats
    work_metrics = compute_workhour_metrics(
        events,
        logical_day,
        coverage_ratio=coverage_ratio,
        tz_name=tz_name,
        shift_start=shift_start,
        shift_end=shift_end,
        late_night_window=late_night_window,
        after_hours_day_min=after_hours_day_min,
        late_night_min=late_night_min,
        history_days=history_days,
    )

    payload = {
        "schema_version": "1.0.0",
        "agent_version": "0.1.0",
        "logical_day": logical_day,
        "day": logical_day.isoformat(),
        "day_of_week": day_of_week,
        "is_weekend": is_weekend,
        "coverage_ratio": coverage_ratio,
        "low_coverage": low_coverage,
        **sess_metrics,
        **work_metrics,
    }

    valid_payload = {k: v for k, v in payload.items() if k in RollupDaily.model_fields}
    return RollupDaily(**valid_payload)
