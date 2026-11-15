"""Gap classification and heartbeat management per docs/metrics_spec.md Section 1.

Classifies time gaps between input events into idle, away (lock/sleep), or unknown (crash/missing data).
Manages periodic agent heartbeats written to SQLite agent_state.
"""
from datetime import datetime, timedelta, timezone
from enum import Enum
import threading
import time
from typing import List, Optional, Tuple, Union

from edc_agent.platforms.windows.system_state import SystemState, SystemStateEvent
from edc_agent.storage.database import Database


class GapType(str, Enum):
    """Permitted gap classifications per spec Section 1."""
    IDLE = "idle"       # Agent running, system awake, no input
    AWAY = "away"       # OS reported lock, sleep, or suspend
    UNKNOWN = "unknown" # Agent not running or crashed; missing data


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def classify_gap(
    gap_start: datetime,
    gap_end: datetime,
    state_events: Optional[List[SystemStateEvent]] = None,
    uptime_intervals: Optional[List[Tuple[datetime, datetime]]] = None,
    heartbeats: Optional[List[datetime]] = None,
    max_heartbeat_gap_s: float = 25.0,
) -> GapType:
    """Classify the input gap [gap_start, gap_end] as idle, away, or unknown.

    Precedence:
    1. If the agent crashed / was offline without OS sleep, classify as UNKNOWN.
    2. If system lock or sleep/suspend overlapped the gap, classify as AWAY.
    3. Otherwise, classify as IDLE.
    """
    start_utc = _to_utc(gap_start)
    end_utc = _to_utc(gap_end)
    events = sorted(state_events or [], key=lambda e: _to_utc(e.ts_utc))

    # Helper: Check if system was locked or suspended at or during the gap
    has_away_event = False
    for ev in events:
        ev_ts = _to_utc(ev.ts_utc)
        if start_utc <= ev_ts <= end_utc:
            if ev.state in (SystemState.LOCK, SystemState.SUSPEND):
                has_away_event = True
                break

    # Also check if system was already locked/suspended prior to gap_start
    if not has_away_event:
        prior_events = [e for e in events if _to_utc(e.ts_utc) <= start_utc]
        if prior_events:
            last_prior = prior_events[-1]
            if last_prior.state in (SystemState.LOCK, SystemState.SUSPEND):
                # Verify it wasn't unlocked/resumed before or during the gap
                subsequent_resumes = [
                    e for e in events
                    if _to_utc(e.ts_utc) > _to_utc(last_prior.ts_utc) and _to_utc(e.ts_utc) <= start_utc
                ]
                if not subsequent_resumes:
                    has_away_event = True

    # Check 1: Agent offline / crashed check
    if uptime_intervals is not None:
        # Verify if gap is covered by uptime intervals
        gap_covered = False
        for up_start, up_end in uptime_intervals:
            u_start = _to_utc(up_start)
            u_end = _to_utc(up_end)
            if u_start <= start_utc and u_end >= end_utc:
                gap_covered = True
                break
        if not gap_covered and not has_away_event:
            return GapType.UNKNOWN

    if heartbeats is not None and len(heartbeats) >= 2:
        hb_sorted = sorted(_to_utc(hb) for hb in heartbeats)
        # Find heartbeats spanning the gap
        margin = timedelta(seconds=max_heartbeat_gap_s * 2)
        relevant_hbs = [hb for hb in hb_sorted if (start_utc - margin <= hb <= end_utc + margin)]
        for i in range(len(relevant_hbs) - 1):
            h_gap = (relevant_hbs[i + 1] - relevant_hbs[i]).total_seconds()
            if h_gap > max_heartbeat_gap_s and not has_away_event:
                # Missing heartbeat during normal awake time indicates agent crash
                return GapType.UNKNOWN

    # Check 2: Lock or Sleep reported
    if has_away_event:
        return GapType.AWAY

    # Check 3: Normal idle
    return GapType.IDLE


class HeartbeatManager:
    """Writes agent heartbeats to SQLite agent_state every 10 seconds to detect crashes."""

    def __init__(self, db: Database, interval_s: float = 10.0):
        self.db = db
        self.interval_s = interval_s
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._history: List[datetime] = []
        self._lock = threading.Lock()

    def record_heartbeat(self, ts_utc: Optional[datetime] = None) -> datetime:
        """Record a single heartbeat to SQLite and memory."""
        now = _to_utc(ts_utc or datetime.now(timezone.utc))
        now_iso = now.isoformat()

        conn = self.db.get_connection()
        query = """
        INSERT OR REPLACE INTO agent_state (key, value, updated_at)
        VALUES ('last_heartbeat', ?, ?);
        """
        if self.db._is_memory:
            conn.execute(query, (now_iso, now_iso))
            conn.commit()
        else:
            with conn:
                conn.execute(query, (now_iso, now_iso))

        with self._lock:
            self._history.append(now)

        return now

    def get_heartbeats(self) -> List[datetime]:
        """Return shallow copy of recorded heartbeat timestamps."""
        with self._lock:
            return list(self._history)

    def start(self) -> None:
        """Start the background heartbeat writer thread."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background heartbeat writer."""
        with self._lock:
            self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run_loop(self) -> None:
        while True:
            with self._lock:
                if not self._is_running:
                    break
            self.record_heartbeat()
            time.sleep(self.interval_s)
