"""Pure functions computing daily session, break, stretch, lunch, and focus metrics per Spec Section 6.

Calculates exact daily rollups:
- Sessions (gaps < session_break_gap_s, duration >= min_session_s).
- Breaks (gaps >= session_break_gap_s and <= break_max_s, type idle/away only, never unknown).
- Continuous stretches (gaps < stretch_break_gap_s, longest stretch, intensity, post-stretch break).
- Focus blocks (gaps < focus_gap_s, duration >= focus_block_min) and deep work (>= deep_work_min).
- Lunch metrics (overlapping lunch_window, lunch_active_mins, longest_lunch_break_mins, lunch_skipped_flag).
- desk_dining_flag is excluded and returns None per specification decision.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
import zoneinfo
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from edc_schemas import ActivityEvent, EventKind
from edc_agent.collectors.gap_classifier import GapType
from edc_agent.timeutil import local_decimal_hour


@dataclass(frozen=True)
class ClassifiedGap:
    """Classified gap interval between input events."""
    start_utc: datetime
    end_utc: datetime
    gap_type: GapType

    @property
    def duration_s(self) -> float:
        return (self.end_utc - self.start_utc).total_seconds()


@dataclass
class _SessionRecord:
    start_utc: datetime
    end_utc: datetime
    duration_s: float
    duration_mins: float


@dataclass
class _StretchRecord:
    start_utc: datetime
    end_utc: datetime
    duration_s: float
    duration_mins: float
    events: List[ActivityEvent]
    next_gap_s: Optional[float] = None


@dataclass
class _FocusRecord:
    start_utc: datetime
    end_utc: datetime
    duration_s: float
    duration_mins: float


def compute_session_metrics(
    events: Sequence[ActivityEvent],
    *,
    classified_gaps: Optional[Sequence[ClassifiedGap]] = None,
    tz_name: str = "Asia/Kolkata",
    session_break_gap_s: float = 300.0,
    break_max_s: float = 10800.0,
    min_session_s: float = 120.0,
    extended_session_min: float = 90.0,
    stretch_break_gap_s: float = 600.0,
    focus_gap_s: float = 120.0,
    focus_block_min: float = 10.0,
    deep_work_min: float = 25.0,
    lunch_window: str = "12:00-14:00",
    no_lunch_break_min: float = 15.0,
) -> Dict[str, Any]:
    """Compute daily session, break, stretch, lunch, and focus metrics.

    Pure function over plain data. No I/O, no side effects.
    """
    tz = zoneinfo.ZoneInfo(tz_name)

    # 1. Filter for active input events (exclude modifier-only key events)
    active_events = [
        ev for ev in events
        if ev.kind != EventKind.KEY_MODIFIER
    ]
    active_events.sort(key=lambda ev: ev.ts_utc)

    # Map classified gaps by (start_utc, end_utc) for fast lookup
    gap_lookup: Dict[Tuple[datetime, datetime], GapType] = {}
    if classified_gaps:
        for g in classified_gaps:
            gap_lookup[(g.start_utc, g.end_utc)] = g.gap_type

    def get_gap_type(start_dt: datetime, end_dt: datetime) -> GapType:
        if (start_dt, end_dt) in gap_lookup:
            return gap_lookup[(start_dt, end_dt)]
        # Check tolerance match
        for (g_start, g_end), g_type in gap_lookup.items():
            if abs((g_start - start_dt).total_seconds()) < 1.0 and abs((g_end - end_dt).total_seconds()) < 1.0:
                return g_type
        # Default to IDLE if agent running without state events
        return GapType.IDLE

    # 2. Identify candidate sessions & inter-session gaps
    # Session: consecutive gaps < session_break_gap_s
    candidate_sessions: List[_SessionRecord] = []
    inter_session_gaps: List[Tuple[datetime, datetime, float, GapType]] = []

    if active_events:
        sess_start = active_events[0]
        prev_ev = active_events[0]

        for i in range(1, len(active_events)):
            cur_ev = active_events[i]
            gap_s = (cur_ev.ts_utc - prev_ev.ts_utc).total_seconds()

            if gap_s >= session_break_gap_s:
                # Session ended at prev_ev
                dur_s = (prev_ev.ts_utc - sess_start.ts_utc).total_seconds()
                candidate_sessions.append(
                    _SessionRecord(
                        start_utc=sess_start.ts_utc,
                        end_utc=prev_ev.ts_utc,
                        duration_s=dur_s,
                        duration_mins=dur_s / 60.0,
                    )
                )
                g_type = get_gap_type(prev_ev.ts_utc, cur_ev.ts_utc)
                inter_session_gaps.append((prev_ev.ts_utc, cur_ev.ts_utc, gap_s, g_type))
                sess_start = cur_ev

            prev_ev = cur_ev

        # Tail session
        dur_s = (prev_ev.ts_utc - sess_start.ts_utc).total_seconds()
        candidate_sessions.append(
            _SessionRecord(
                start_utc=sess_start.ts_utc,
                end_utc=prev_ev.ts_utc,
                duration_s=dur_s,
                duration_mins=dur_s / 60.0,
            )
        )

    # Filter for valid sessions (duration >= min_session_s)
    valid_sessions = [s for s in candidate_sessions if s.duration_s >= min_session_s]

    avg_session_duration_mins: Optional[float] = None
    max_session_duration_mins: Optional[float] = None
    extended_sessions_count: Optional[int] = None
    total_work_minutes = 0.0

    if valid_sessions:
        durations = [s.duration_mins for s in valid_sessions]
        total_work_minutes = sum(durations)
        avg_session_duration_mins = total_work_minutes / len(valid_sessions)
        max_session_duration_mins = max(durations)
        extended_sessions_count = sum(1 for d in durations if d >= extended_session_min)

    # 3. Breaks
    # Definition: a gap >= session_break_gap_s and <= break_max_s between two sessions,
    # and of type idle or away. Unknown gaps are NEVER breaks.
    # Breaks > break_max_s are long absences, excluded from avg_break_duration_mins.
    valid_breaks_mins: List[float] = []

    # Map breaks between valid sessions
    if len(valid_sessions) >= 2:
        for i in range(len(valid_sessions) - 1):
            s_prev = valid_sessions[i]
            s_next = valid_sessions[i + 1]
            gap_s = (s_next.start_utc - s_prev.end_utc).total_seconds()
            g_type = get_gap_type(s_prev.end_utc, s_next.start_utc)

            # Only idle or away can count as a break; unknown is never a break
            if g_type in (GapType.IDLE, GapType.AWAY):
                if gap_s >= session_break_gap_s and gap_s <= break_max_s:
                    valid_breaks_mins.append(gap_s / 60.0)

    total_breaks_count = len(valid_breaks_mins)
    avg_break_duration_mins: Optional[float] = None
    if valid_breaks_mins:
        avg_break_duration_mins = sum(valid_breaks_mins) / len(valid_breaks_mins)

    # 4. Continuous stretches (gaps < stretch_break_gap_s)
    stretches: List[_StretchRecord] = []
    if active_events:
        stretch_start = active_events[0]
        prev_ev = active_events[0]
        cur_stretch_events = [active_events[0]]

        for i in range(1, len(active_events)):
            cur_ev = active_events[i]
            gap_s = (cur_ev.ts_utc - prev_ev.ts_utc).total_seconds()

            if gap_s >= stretch_break_gap_s:
                dur_s = (prev_ev.ts_utc - stretch_start.ts_utc).total_seconds()
                stretches.append(
                    _StretchRecord(
                        start_utc=stretch_start.ts_utc,
                        end_utc=prev_ev.ts_utc,
                        duration_s=dur_s,
                        duration_mins=dur_s / 60.0,
                        events=list(cur_stretch_events),
                        next_gap_s=gap_s,
                    )
                )
                stretch_start = cur_ev
                cur_stretch_events = [cur_ev]
            else:
                cur_stretch_events.append(cur_ev)

            prev_ev = cur_ev

        dur_s = (prev_ev.ts_utc - stretch_start.ts_utc).total_seconds()
        stretches.append(
            _StretchRecord(
                start_utc=stretch_start.ts_utc,
                end_utc=prev_ev.ts_utc,
                duration_s=dur_s,
                duration_mins=dur_s / 60.0,
                events=list(cur_stretch_events),
                next_gap_s=None,
            )
        )

    longest_stretch_duration_mins: Optional[float] = None
    stretch_start_hour: Optional[float] = None
    post_stretch_break_mins: Optional[float] = None
    stretch_intensity_pct: Optional[float] = None
    stretch_to_total_work_ratio: Optional[float] = None

    if stretches:
        longest = max(stretches, key=lambda st: st.duration_mins)
        longest_stretch_duration_mins = longest.duration_mins
        stretch_start_hour = local_decimal_hour(longest.start_utc, tz_name)

        if longest.next_gap_s is not None:
            post_stretch_break_mins = longest.next_gap_s / 60.0

        # Stretch intensity: 100 * active_minutes_in_stretch / stretch_minutes
        active_mins_in_stretch = len({
            (ev.ts_utc.year, ev.ts_utc.month, ev.ts_utc.day, ev.ts_utc.hour, ev.ts_utc.minute)
            for ev in longest.events
        })
        if longest.duration_mins > 0:
            stretch_intensity_pct = 100.0 * (active_mins_in_stretch / longest.duration_mins)
        else:
            stretch_intensity_pct = 100.0

        if total_work_minutes > 0:
            stretch_to_total_work_ratio = longest.duration_mins / total_work_minutes

    # 5. Focus blocks (gaps < focus_gap_s, duration >= focus_block_min)
    focus_blocks: List[_FocusRecord] = []
    deep_work_count = 0

    if active_events:
        f_start = active_events[0]
        prev_ev = active_events[0]

        for i in range(1, len(active_events)):
            cur_ev = active_events[i]
            gap_s = (cur_ev.ts_utc - prev_ev.ts_utc).total_seconds()

            if gap_s >= focus_gap_s:
                dur_s = (prev_ev.ts_utc - f_start.ts_utc).total_seconds()
                dur_mins = dur_s / 60.0
                if dur_mins >= focus_block_min:
                    focus_blocks.append(_FocusRecord(f_start.ts_utc, prev_ev.ts_utc, dur_s, dur_mins))
                    if dur_mins >= deep_work_min:
                        deep_work_count += 1
                f_start = cur_ev

            prev_ev = cur_ev

        dur_s = (prev_ev.ts_utc - f_start.ts_utc).total_seconds()
        dur_mins = dur_s / 60.0
        if dur_mins >= focus_block_min:
            focus_blocks.append(_FocusRecord(f_start.ts_utc, prev_ev.ts_utc, dur_s, dur_mins))
            if dur_mins >= deep_work_min:
                deep_work_count += 1

    avg_focus_block_mins: Optional[float] = None
    max_focus_block_mins: Optional[float] = None
    deep_work_blocks_count = deep_work_count
    total_focus_time_hours = 0.0
    focus_fragmentation_ratio: Optional[float] = None

    if focus_blocks:
        f_durs = [fb.duration_mins for fb in focus_blocks]
        avg_focus_block_mins = sum(f_durs) / len(f_durs)
        max_focus_block_mins = max(f_durs)
        total_focus_mins = sum(f_durs)
        total_focus_time_hours = total_focus_mins / 60.0

        if total_work_minutes > 0:
            ratio = 1.0 - (total_focus_mins / total_work_minutes)
            focus_fragmentation_ratio = max(0.0, min(1.0, ratio))

    # 6. Lunch window metrics
    # Parse lunch window in local time (e.g. "12:00-14:00")
    lunch_active_mins = 0.0
    longest_lunch_break_mins: Optional[float] = None
    lunch_work_ratio: Optional[float] = None
    lunch_skipped_flag: Optional[bool] = None

    if active_events:
        ref_local = active_events[0].ts_utc.astimezone(tz)
        local_day_date = ref_local.date()

        try:
            start_str, end_str = lunch_window.split("-")
            sh, sm = map(int, start_str.strip().split(":"))
            eh, em = map(int, end_str.strip().split(":"))
            lunch_start_local = datetime.combine(local_day_date, time(sh, sm), tzinfo=tz)
            lunch_end_local = datetime.combine(local_day_date, time(eh, em), tzinfo=tz)
        except Exception:
            lunch_start_local = datetime.combine(local_day_date, time(12, 0), tzinfo=tz)
            lunch_end_local = datetime.combine(local_day_date, time(14, 0), tzinfo=tz)

        lunch_start_utc = lunch_start_local.astimezone(dt_timezone.utc)
        lunch_end_utc = lunch_end_local.astimezone(dt_timezone.utc)
        lunch_window_duration_mins = (lunch_end_utc - lunch_start_utc).total_seconds() / 60.0

        # Lunch active minutes
        lunch_active_minute_set = set()
        for ev in active_events:
            if lunch_start_utc <= ev.ts_utc <= lunch_end_utc:
                dt = ev.ts_utc.astimezone(tz)
                lunch_active_minute_set.add((dt.year, dt.month, dt.day, dt.hour, dt.minute))

        lunch_active_mins = float(len(lunch_active_minute_set))
        if lunch_window_duration_mins > 0:
            lunch_work_ratio = lunch_active_mins / lunch_window_duration_mins

        # Find input gaps overlapping lunch window clipped to the window
        all_gaps: List[Tuple[datetime, datetime, GapType]] = []
        for i in range(len(active_events) - 1):
            g_start = active_events[i].ts_utc
            g_end = active_events[i + 1].ts_utc
            g_type = get_gap_type(g_start, g_end)
            all_gaps.append((g_start, g_end, g_type))

        clipped_breaks: List[float] = []
        unknown_overlap_s = 0.0

        for g_start, g_end, g_type in all_gaps:
            clip_start = max(g_start, lunch_start_utc)
            clip_end = min(g_end, lunch_end_utc)

            if clip_start < clip_end:
                overlap_dur_s = (clip_end - clip_start).total_seconds()
                if g_type == GapType.UNKNOWN:
                    unknown_overlap_s += overlap_dur_s
                elif g_type in (GapType.IDLE, GapType.AWAY):
                    clipped_breaks.append(overlap_dur_s / 60.0)

        # Check pre-first event gap and post-last event gap if they overlap lunch
        first_ev_ts = active_events[0].ts_utc
        if first_ev_ts > lunch_start_utc:
            clip_start = lunch_start_utc
            clip_end = min(first_ev_ts, lunch_end_utc)
            g_type = get_gap_type(lunch_start_utc, first_ev_ts)
            if g_type == GapType.UNKNOWN:
                unknown_overlap_s += (clip_end - clip_start).total_seconds()
            elif g_type in (GapType.IDLE, GapType.AWAY):
                clipped_breaks.append((clip_end - clip_start).total_seconds() / 60.0)

        last_ev_ts = active_events[-1].ts_utc
        if last_ev_ts < lunch_end_utc:
            clip_start = max(last_ev_ts, lunch_start_utc)
            clip_end = lunch_end_utc
            g_type = get_gap_type(last_ev_ts, lunch_end_utc)
            if g_type == GapType.UNKNOWN:
                unknown_overlap_s += (clip_end - clip_start).total_seconds()
            elif g_type in (GapType.IDLE, GapType.AWAY):
                clipped_breaks.append((clip_end - clip_start).total_seconds() / 60.0)

        # Null if the lunch window is mostly unknown (> 50% unknown)
        total_lunch_s = lunch_window_duration_mins * 60.0
        if (unknown_overlap_s / total_lunch_s) > 0.5:
            longest_lunch_break_mins = None
            lunch_skipped_flag = None
        else:
            if clipped_breaks:
                longest_lunch_break_mins = max(clipped_breaks)
            else:
                longest_lunch_break_mins = 0.0
            lunch_skipped_flag = longest_lunch_break_mins < no_lunch_break_min

    return {
        "avg_session_duration_mins": avg_session_duration_mins,
        "max_session_duration_mins": max_session_duration_mins,
        "total_breaks_count": total_breaks_count,
        "avg_break_duration_mins": avg_break_duration_mins,
        "extended_sessions_count": extended_sessions_count,
        "longest_stretch_duration_mins": longest_stretch_duration_mins,
        "stretch_start_hour": stretch_start_hour,
        "post_stretch_break_mins": post_stretch_break_mins,
        "stretch_intensity_pct": stretch_intensity_pct,
        "stretch_to_total_work_ratio": stretch_to_total_work_ratio,
        "lunch_active_mins": lunch_active_mins,
        "longest_lunch_break_mins": longest_lunch_break_mins,
        "lunch_work_ratio": lunch_work_ratio,
        "lunch_skipped_flag": lunch_skipped_flag,
        "desk_dining_flag": None,  # Excluded per specification decision
        "avg_focus_block_mins": avg_focus_block_mins,
        "max_focus_block_mins": max_focus_block_mins,
        "deep_work_blocks_count": deep_work_blocks_count,
        "total_focus_time_hours": total_focus_time_hours,
        "focus_fragmentation_ratio": focus_fragmentation_ratio,
    }
