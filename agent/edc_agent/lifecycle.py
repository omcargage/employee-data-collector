"""Agent lifecycle coordinator managing collectors, providers, time windows, and storage.

Coordinates startup, periodic window aggregation into Rollup15Min, daily boundary RollupDaily
aggregation, crash/restart recovery, pause/resume state, and graceful shutdown.
"""
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import logging
import threading
import zoneinfo

from edc_schemas import (
    ActivityEvent,
    EventKind,
    Rollup15Min,
    RollupDaily,
    WindowBlocks,
)
from edc_agent.config import EDCConfig, load_config
from edc_agent.collectors import (
    ActivityCollector,
    CommunicationTracker,
    GapType,
    HeartbeatManager,
    accumulate_window_blocks,
)
from edc_agent.metrics import (
    ClassifiedGap,
    build_rollup_daily,
    compute_rollup_15min_metrics,
)
from edc_agent.platforms.base import InputProvider
from edc_agent.storage.database import Database
from edc_agent.storage.queue import UploadQueue
from edc_agent.timeutil import (
    CoverageTracker,
    is_weekend,
    local_decimal_hour,
    to_logical_day,
    window_bounds,
)

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class AgentLifecycle:
    """Central lifecycle and execution coordinator for the EDC desktop agent."""

    def __init__(
        self,
        config: Optional[EDCConfig] = None,
        db: Optional[Database] = None,
        provider: Optional[InputProvider] = None,
        state_monitor: Optional[Any] = None,
        window_minutes: int = 15,
        db_path: Optional[Union[str, Path]] = None,
        require_consent: bool = True,
    ):
        self.config = config or load_config()
        self.window_minutes = window_minutes
        self.require_consent = require_consent

        # Database setup
        if db is not None:
            self.db = db
        elif db_path is not None:
            self.db = Database(db_path)
        else:
            default_db = Path.home() / ".edc" / "agent.db"
            self.db = Database(default_db)

        # Core subsystems
        self.collector = ActivityCollector(
            timezone_name=self.config.timezone,
            window_minutes=self.window_minutes,
        )
        self.heartbeat_manager = HeartbeatManager(self.db, interval_s=10.0)
        self.upload_queue = UploadQueue(self.db)
        self.coverage_tracker = CoverageTracker()
        self.day_coverage_tracker = CoverageTracker()
        self.communication_tracker = CommunicationTracker(
            comm_apps=getattr(self.config, "comm_apps", None),
            db=self.db,
        )

        # Input provider & state monitor (platform specific or injected)
        self.provider = provider
        self.state_monitor = state_monitor

        # Thread synchronization & lifecycle state
        self._lock = threading.RLock()
        self._status = "stopped"  # "collecting", "paused", "error", "stopped"
        self._error_message: Optional[str] = None
        self._last_tick_utc: Optional[datetime] = None

        # Window & day tracking
        self.current_window: Optional[Tuple[datetime, datetime]] = None
        self.current_logical_day: Optional[date] = None
        self.closed_windows_count = 0

        # Day timeline for daily aggregation
        self.day_events: List[ActivityEvent] = []
        self.day_classified_gaps: List[ClassifiedGap] = []

        # Parse day start hour from config
        try:
            self._day_start_hour = int(self.config.logical_day_start.split(":")[0])
        except Exception:
            self._day_start_hour = 5

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def error_message(self) -> Optional[str]:
        with self._lock:
            return self._error_message

    def on_event(self, event: ActivityEvent) -> None:
        """Receive hook input event from provider."""
        with self._lock:
            if self._status != "collecting":
                return
            self.collector.on_event(event)
            self.communication_tracker.on_event(event)
            # Retain lightweight event for daily session & work-hour metrics
            self.day_events.append(ActivityEvent(ts_utc=event.ts_utc, kind=event.kind))

    def on_system_state_change(self, state_event: Any) -> None:
        """Receive power / session lock transition events from monitor."""
        with self._lock:
            state_val = getattr(state_event, "state", None)
            ts = getattr(state_event, "ts_utc", datetime.now(timezone.utc))
            logger.info("System state transition: %s at %s", state_val, ts)

    def start(self, start_time_utc: Optional[datetime] = None) -> None:
        """Start the agent, recover any interrupted window, and launch background threads."""
        with self._lock:
            if self._status == "collecting":
                return

            from edc_agent.privacy.consent import has_consent
            if self.require_consent and not has_consent(self.db):
                raise PermissionError(
                    "Data collection requires explicit user consent acknowledgement. "
                    "Run 'edc consent' or prompt_for_consent() before starting."
                )

            logger.info("Starting EDC agent lifecycle (window=%d mins)...", self.window_minutes)

            now_utc = _to_utc(start_time_utc) if start_time_utc else datetime.now(timezone.utc)

            # Handle crash / restart recovery
            self._handle_restart_recovery(now_utc=now_utc)

            # Initialize platform provider if none was injected
            if self.provider is None:
                self._init_default_provider()

            # Initialize platform state monitor if none was injected
            if self.state_monitor is None:
                self._init_default_state_monitor()

            # Start child components
            self.collector.start()
            self.heartbeat_manager.start()

            if self.state_monitor and hasattr(self.state_monitor, "start"):
                try:
                    self.state_monitor.start()
                except Exception as e:
                    logger.warning("Could not start state monitor: %s", e)

            if self.provider and hasattr(self.provider, "start"):
                self.provider.start()

            self._last_tick_utc = now_utc
            if start_time_utc is not None:
                self.current_window = window_bounds(now_utc, self.config.timezone, self.window_minutes)
                self.current_logical_day = to_logical_day(
                    now_utc, self.config.timezone, day_start_hour=self._day_start_hour
                )
                self.db.set_agent_state("active_window_start", self.current_window[0].isoformat())
                self.db.set_agent_state("active_window_end", self.current_window[1].isoformat())
            else:
                self.current_window = None
                self.current_logical_day = None

            self.db.set_agent_state("status", "collecting")
            self.db.set_agent_state("started_at", now_utc.isoformat())

            self._status = "collecting"
            self._error_message = None

    def _init_default_provider(self) -> None:
        """Instantiate default OS input provider using platform detection."""
        try:
            from edc_agent.platforms import get_platform_provider
            self.provider = get_platform_provider(
                callback=self.on_event,
                mouse_bin_ms=self.config.mouse_bin_ms,
            )
        except Exception as e:
            logger.warning("Failed to initialize platform input provider: %s; falling back to FakeInputProvider", e)
            from edc_agent.platforms.fake import FakeInputProvider
            self.provider = FakeInputProvider(callback=self.on_event)

    def _init_default_state_monitor(self) -> None:
        """Instantiate default system state monitor on Windows."""
        import sys
        if sys.platform == "win32":
            try:
                from edc_agent.platforms.windows.system_state import WindowsSystemStateMonitor
                self.state_monitor = WindowsSystemStateMonitor(
                    callback=self.on_system_state_change
                )
            except Exception as e:
                logger.warning("Failed to initialize WindowsSystemStateMonitor: %s", e)

    def _handle_restart_recovery(self, now_utc: Optional[datetime] = None) -> None:
        """Recover from a previous run or crash without double-counting an interrupted window."""
        prev_start_str = self.db.get_agent_state("active_window_start")
        prev_end_str = self.db.get_agent_state("active_window_end")
        if not prev_start_str or not prev_end_str:
            return

        try:
            prev_start = datetime.fromisoformat(prev_start_str)
            prev_end = datetime.fromisoformat(prev_end_str)
        except Exception:
            return

        now = now_utc or datetime.now(timezone.utc)
        if now >= prev_end:
            # Previous window elapsed while agent was down or crashed
            if not self.db.check_rollup_15min_exists(prev_start_str, prev_end_str):
                # Insert interrupted window rollup marked low coverage
                log_day = to_logical_day(prev_start, self.config.timezone, day_start_hour=self._day_start_hour)
                tz = zoneinfo.ZoneInfo(self.config.timezone)
                local_start = prev_start.astimezone(tz)
                dummy_blocks = WindowBlocks(
                    covered_s=0.0,
                    idle_s=0.0,
                    active_minutes=0,
                    display_scale=1.0,
                )
                interrupted_rollup = Rollup15Min(
                    schema_version="1.0.0",
                    agent_version="0.1.0",
                    window_start=prev_start,
                    window_end=prev_end,
                    coverage_ratio=0.0,
                    low_coverage=True,
                    day_of_week=log_day.weekday(),
                    is_weekend=is_weekend(log_day),
                    hour_of_day=local_start.hour,
                    decimal_hour=local_decimal_hour(prev_start, self.config.timezone),
                    blocks=dummy_blocks,
                )
                interrupted_id = self.db.insert_rollup_15min(interrupted_rollup)
                if interrupted_id:
                    self.upload_queue.enqueue("15min", interrupted_id)
                self.closed_windows_count += 1
                self.db.insert_gap_log(
                    start_ts=prev_start,
                    end_ts=now,
                    duration_s=(now - prev_start).total_seconds(),
                    gap_type="unknown",
                )
                logger.info("Recorded interrupted window [%s, %s] as low coverage.", prev_start_str, prev_end_str)

    def pause(self) -> None:
        """Pause data collection (e.g. from edc pause)."""
        with self._lock:
            if self._status != "collecting":
                return
            self._status = "paused"
            self.collector.pause()
            self.db.set_agent_state("status", "paused")
            logger.info("EDC agent paused.")

    def resume(self) -> None:
        """Resume data collection (e.g. from edc resume)."""
        with self._lock:
            if self._status != "paused":
                return
            self._status = "collecting"
            self._last_tick_utc = datetime.now(timezone.utc)
            self.collector.resume()
            self.db.set_agent_state("status", "collecting")
            logger.info("EDC agent resumed.")

    def tick(self, now_utc: Optional[datetime] = None) -> None:
        """Advance agent time, check IPC commands, close expired windows, and trigger daily rollups."""
        now = _to_utc(now_utc or datetime.now(timezone.utc))

        # Check for remote commands written to SQLite (edc pause / resume)
        self._check_remote_commands()

        with self._lock:
            if self._status == "collecting":
                # Record coverage interval
                if self._last_tick_utc is not None and self._last_tick_utc < now:
                    self.coverage_tracker.record_interval(self._last_tick_utc, now)
                    self.day_coverage_tracker.record_interval(self._last_tick_utc, now)
                self._last_tick_utc = now

                # Initialize current window if needed
                bounds = window_bounds(now, self.config.timezone, self.window_minutes)
                if self.current_window is None:
                    self.current_window = bounds
                    self.db.set_agent_state("active_window_start", bounds[0].isoformat())
                    self.db.set_agent_state("active_window_end", bounds[1].isoformat())

                # Close any windows that have elapsed
                while self.current_window is not None and now >= self.current_window[1]:
                    self._close_window(self.current_window)
                    next_start = self.current_window[1]
                    next_bounds = window_bounds(next_start, self.config.timezone, self.window_minutes)
                    self.current_window = next_bounds
                    self.db.set_agent_state("active_window_start", next_bounds[0].isoformat())
                    self.db.set_agent_state("active_window_end", next_bounds[1].isoformat())

                # Check logical-day boundary
                curr_log_day = to_logical_day(
                    now, self.config.timezone, day_start_hour=self._day_start_hour
                )
                if self.current_logical_day is None:
                    self.current_logical_day = curr_log_day
                elif curr_log_day != self.current_logical_day:
                    self._close_logical_day(self.current_logical_day)
                    self.current_logical_day = curr_log_day

    def _check_remote_commands(self) -> None:
        """Check SQLite agent_state for control commands (pause / resume)."""
        cmd = self.db.get_agent_state("command")
        if cmd:
            if cmd == "pause" and self.status == "collecting":
                self.pause()
            elif cmd == "resume" and self.status == "paused":
                self.resume()
            self.db.set_agent_state("command", "")

    def _close_window(self, closed_bounds: Tuple[datetime, datetime]) -> Optional[Rollup15Min]:
        """Aggregate and store a completed window as Rollup15Min; discard raw events."""
        w_start, w_end = closed_bounds
        start_iso = w_start.isoformat()
        end_iso = w_end.isoformat()

        # Drain queued events so accumulator has all window events
        self.collector.drain_sync()

        # Check if already inserted to prevent double-counting
        if self.db.check_rollup_15min_exists(start_iso, end_iso):
            self.collector.pop_accumulator(closed_bounds)
            return None

        # Discard and retrieve raw events from collector accumulator
        accumulator = self.collector.pop_accumulator(closed_bounds)
        events = accumulator.events if accumulator else []

        cov_s = self.coverage_tracker.coverage_seconds(w_start, w_end)
        cov_ratio = self.coverage_tracker.coverage_ratio(w_start, w_end)
        low_cov = cov_ratio < 0.5

        # Compute additive WindowBlocks
        blocks = accumulate_window_blocks(
            events,
            covered_s=cov_s,
            idle_threshold_s=self.config.idle_threshold_s,
            typing_gap_max_ms=self.config.typing_gap_max_ms,
            burst_min_keys=self.config.burst_min_keys,
            burst_max_flight_ms=self.config.burst_max_flight_ms,
            long_silence_s=self.config.long_silence_s,
            backspace_burst_min=self.config.backspace_burst_min,
            backspace_burst_gap_ms=self.config.backspace_burst_gap_ms,
            mouse_bin_ms=self.config.mouse_bin_ms,
            mouse_jump_px=self.config.mouse_jump_px,
            double_click_ms=self.config.double_click_ms,
            double_click_px=self.config.double_click_px,
            rapid_click_n=self.config.rapid_click_n,
            rapid_click_s=self.config.rapid_click_s,
        )

        capabilities = self.provider.get_capabilities() if self.provider else {}
        metrics_dict = compute_rollup_15min_metrics(
            blocks,
            covered_s=cov_s,
            min_keystrokes=self.config.min_keystrokes,
            min_flight_intervals=self.config.min_flight_intervals,
            key_dwell_capable=capabilities.get("key_dwell", False),
            min_clicks=self.config.min_clicks,
        )

        tz = zoneinfo.ZoneInfo(self.config.timezone)
        local_start = w_start.astimezone(tz)
        log_day = to_logical_day(w_start, self.config.timezone, day_start_hour=self._day_start_hour)

        tot_keys = metrics_dict.get("total_keystrokes")
        mean_fl = metrics_dict.get("mean_flight_time_ms")
        std_fl = metrics_dict.get("flight_time_std_ms")
        alias_dict = {
            "keystroke_count": tot_keys,
            "average_keystroke_interval_seconds": round(mean_fl / 1000.0, 6) if mean_fl is not None else None,
            "keystroke_interval_stdev_seconds": round(std_fl / 1000.0, 6) if std_fl is not None else None,
            "timestamp": w_start,
            "profile": getattr(self.config, "profile", None),
        }

        rollup = Rollup15Min(
            schema_version="1.0.0",
            agent_version="0.1.0",
            window_start=w_start,
            window_end=w_end,
            coverage_ratio=cov_ratio,
            low_coverage=low_cov,
            day_of_week=log_day.weekday(),
            is_weekend=is_weekend(log_day),
            hour_of_day=local_start.hour,
            decimal_hour=local_decimal_hour(w_start, self.config.timezone),
            blocks=blocks,
            **metrics_dict,
            **alias_dict,
        )

        rollup_id = self.db.insert_rollup_15min(rollup)
        if rollup_id:
            self.upload_queue.enqueue("15min", rollup_id)
        self.closed_windows_count += 1
        self.db.set_agent_state("last_closed_window_end", end_iso)
        self.db.set_dropped_events_count(self.collector.dropped_events_count)
        logger.info("Stored Rollup15Min for [%s, %s] (coverage=%.2f)", start_iso, end_iso, cov_ratio)
        return rollup

    def _close_logical_day(self, completed_day: date) -> Optional[RollupDaily]:
        """Aggregate and store completed day metrics as RollupDaily at day boundary."""
        day_iso = completed_day.isoformat()
        if self.db.get_rollup_daily(day_iso) is not None:
            return None

        tz = zoneinfo.ZoneInfo(self.config.timezone)
        day_start_local = datetime.combine(completed_day, time(self._day_start_hour, 0), tzinfo=tz)
        day_end_local = day_start_local + timedelta(hours=24)
        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)

        day_cov_ratio = self.day_coverage_tracker.coverage_ratio(day_start_utc, day_end_utc)
        history_days = self.db.get_recent_rollups_daily(limit=7)

        # Compute communication metrics via process heuristic tracker
        comm_metrics = self.communication_tracker.compute_daily_metrics(
            completed_day,
            tz_name=self.config.timezone,
            shift_start=self.config.shift_start,
            shift_end=self.config.shift_end,
            late_night_window=self.config.late_night_window,
        )

        rollup_daily = build_rollup_daily(
            logical_day=completed_day,
            events=self.day_events,
            coverage_ratio=day_cov_ratio,
            classified_gaps=self.day_classified_gaps,
            history_days=history_days,
            tz_name=self.config.timezone,
            shift_start=self.config.shift_start,
            shift_end=self.config.shift_end,
            lunch_window=self.config.lunch_window,
            late_night_window=self.config.late_night_window,
            after_hours_day_min=self.config.after_hours_day_min,
            late_night_min=self.config.late_night_min,
            no_lunch_break_min=self.config.no_lunch_break_min,
            session_break_gap_s=self.config.session_break_gap_s,
            break_max_s=self.config.break_max_s,
            min_session_s=self.config.min_session_s,
            extended_session_min=self.config.extended_session_min,
            stretch_break_gap_s=self.config.stretch_break_gap_s,
            focus_gap_s=self.config.focus_gap_s,
            focus_block_min=self.config.focus_block_min,
            deep_work_min=self.config.deep_work_min,
            comm_metrics=comm_metrics,
            profile=getattr(self.config, "profile", None),
        )
        self.communication_tracker.reset_day()

        daily_id = self.db.insert_rollup_daily(rollup_daily)
        if daily_id:
            self.upload_queue.enqueue("daily", daily_id)
        for gap in self.day_classified_gaps:
            gap_type_str = gap.gap_type.value if hasattr(gap.gap_type, "value") else str(gap.gap_type)
            self.db.insert_gap_log(gap.start_utc, gap.end_utc, gap.duration_s, gap_type_str)
        self.day_events.clear()
        self.day_classified_gaps.clear()
        self.day_coverage_tracker = CoverageTracker()
        logger.info("Stored RollupDaily for logical day %s", day_iso)
        return rollup_daily

    def stop(self) -> None:
        """Gracefully stop all subsystems and persist agent state."""
        with self._lock:
            if self._status == "stopped":
                return

            logger.info("Stopping EDC agent...")
            self._status = "stopped"

            if self.provider and hasattr(self.provider, "stop"):
                try:
                    self.provider.stop()
                except Exception as e:
                    logger.warning("Error stopping provider: %s", e)

            if self.state_monitor and hasattr(self.state_monitor, "stop"):
                try:
                    self.state_monitor.stop()
                except Exception as e:
                    logger.warning("Error stopping state monitor: %s", e)

            self.collector.stop(drain=True)
            self.heartbeat_manager.stop()
            self.db.set_dropped_events_count(self.collector.dropped_events_count)

            now_iso = datetime.now(timezone.utc).isoformat()
            self.db.set_agent_state("status", "stopped")
            self.db.set_agent_state("last_shutdown", now_iso)
            logger.info("EDC agent stopped successfully.")

    def get_status_line(self) -> str:
        """Produce the human-readable visible status line for terminal display."""
        with self._lock:
            status_text = self._status.upper()
            win_str = ""
            if self.current_window:
                ws = self.current_window[0].strftime("%H:%M")
                we = self.current_window[1].strftime("%H:%M")
                win_str = f"Window: {ws}-{we} UTC | "

            q_len = self.collector.queue_size
            return (
                f"[EDC STATUS: {status_text}] "
                f"{win_str}"
                f"Closed windows: {self.closed_windows_count} | "
                f"Queue: {q_len} items"
            )
