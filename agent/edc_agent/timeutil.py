"""Pure time manipulation functions, timezone handling, and coverage tracking for the EDC agent.

All functions are pure without I/O or side effects.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Tuple, Union
import zoneinfo


def _to_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware and converted to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_zone(tz: Union[str, zoneinfo.ZoneInfo]) -> zoneinfo.ZoneInfo:
    """Resolve a timezone identifier or ZoneInfo object."""
    if isinstance(tz, str):
        return zoneinfo.ZoneInfo(tz)
    return tz


def to_logical_day(
    ts_utc: datetime,
    tz: Union[str, zoneinfo.ZoneInfo],
    day_start_hour: int = 5,
) -> date:
    """Map a UTC timestamp to its logical day date based on local time.

    Events occurring before `day_start_hour` local time (e.g. 01:30 AM) are mapped
    to the preceding calendar date so late-night sessions across midnight remain unified.
    """
    zone = _get_zone(tz)
    local_dt = _to_utc(ts_utc).astimezone(zone)

    if local_dt.hour < day_start_hour:
        return local_dt.date() - timedelta(days=1)
    return local_dt.date()


def window_bounds(
    ts_utc: datetime,
    tz: Union[str, zoneinfo.ZoneInfo],
    window_minutes: int = 15,
) -> Tuple[datetime, datetime]:
    """Calculate the UTC start and end bounds of the 15-minute window enclosing ts_utc.

    Windows are aligned to :00, :15, :30, :45 in the local timezone. Performs offset
    arithmetic in UTC to maintain exact 15-minute intervals across DST changes.
    """
    zone = _get_zone(tz)
    utc_dt = _to_utc(ts_utc)
    local_dt = utc_dt.astimezone(zone)

    # Offset from window start in seconds
    offset_seconds = (
        (local_dt.minute % window_minutes) * 60
        + local_dt.second
        + local_dt.microsecond / 1_000_000.0
    )
    start_utc = utc_dt - timedelta(seconds=offset_seconds)
    end_utc = start_utc + timedelta(minutes=window_minutes)

    return start_utc, end_utc


def is_weekend(
    logical_day: Union[date, datetime],
    weekend_days: Tuple[int, ...] = (5, 6),
) -> bool:
    """Check if a logical day falls on a weekend (default Saturday=5, Sunday=6)."""
    if isinstance(logical_day, datetime):
        d = logical_day.date()
    else:
        d = logical_day
    return d.weekday() in weekend_days


def local_decimal_hour(
    dt: datetime,
    tz: Optional[Union[str, zoneinfo.ZoneInfo]] = None,
) -> float:
    """Compute local decimal hour (hour + minute/60 + second/3600) rounded to 4 decimals."""
    if tz is not None:
        zone = _get_zone(tz)
        dt = _to_utc(dt).astimezone(zone)
    return round(dt.hour + dt.minute / 60.0 + dt.second / 3600.0, 4)


class CoverageTracker:
    """Tracks time intervals when the agent was active and listening.

    Maintains merged non-overlapping UTC intervals and computes coverage ratios for windows.
    """

    def __init__(self):
        self._intervals: List[Tuple[datetime, datetime]] = []

    def record_interval(self, start: datetime, end: datetime) -> None:
        """Record an active listening interval [start, end].

        Normalizes to UTC and merges with existing overlapping or contiguous intervals.
        """
        start_utc = _to_utc(start)
        end_utc = _to_utc(end)

        if start_utc >= end_utc:
            return

        new_intervals: List[Tuple[datetime, datetime]] = []
        cur_start, cur_end = start_utc, end_utc
        placed = False

        for existing_start, existing_end in self._intervals:
            if cur_end < existing_start:
                # new interval comes strictly before existing
                if not placed:
                    new_intervals.append((cur_start, cur_end))
                    placed = True
                new_intervals.append((existing_start, existing_end))
            elif cur_start > existing_end:
                # new interval comes strictly after existing
                new_intervals.append((existing_start, existing_end))
            else:
                # overlapping or touching; merge
                cur_start = min(cur_start, existing_start)
                cur_end = max(cur_end, existing_end)

        if not placed:
            new_intervals.append((cur_start, cur_end))

        self._intervals = new_intervals

    def coverage_seconds(self, window_start: datetime, window_end: datetime) -> float:
        """Compute the total covered seconds intersecting [window_start, window_end]."""
        w_start = _to_utc(window_start)
        w_end = _to_utc(window_end)

        if w_start >= w_end:
            return 0.0

        total_seconds = 0.0
        for start, end in self._intervals:
            overlap_start = max(start, w_start)
            overlap_end = min(end, w_end)
            if overlap_start < overlap_end:
                total_seconds += (overlap_end - overlap_start).total_seconds()

        return total_seconds

    def coverage_ratio(self, window_start: datetime, window_end: datetime) -> float:
        """Compute coverage_ratio = covered_seconds / window_seconds, bounded [0.0, 1.0]."""
        w_start = _to_utc(window_start)
        w_end = _to_utc(window_end)
        window_duration = (w_end - w_start).total_seconds()

        if window_duration <= 0.0:
            return 0.0

        covered = self.coverage_seconds(w_start, w_end)
        return min(1.0, max(0.0, covered / window_duration))
