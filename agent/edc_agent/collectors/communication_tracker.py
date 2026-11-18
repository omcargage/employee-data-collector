"""Communication and messaging activity tracker for EDC agent.

Uses lightweight OS-level process focus heuristics to detect activity in communication
applications (Slack, Teams, Outlook, Discord, etc.) and calculate daily communication metrics
without snooping, inspecting, or storing message contents:
- total_msgs_sent
- msgs_sent_after_hours
- msgs_sent_late_night
- first_msg_time
- last_msg_time
"""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
import json
from pathlib import Path
import sys
import time as time_mod
from typing import Any, Callable, Dict, List, Optional, Set
import zoneinfo

from edc_schemas import ActivityEvent, EventKind


DEFAULT_COMM_APPS: List[str] = [
    "slack",
    "teams",
    "ms-teams",
    "outlook",
    "thunderbird",
    "discord",
    "whatsapp",
    "telegram",
    "signal",
    "skype",
    "zoom",
    "element",
]


def default_get_active_process_name() -> Optional[str]:
    """Return lowercase executable name of the current foreground window."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD

            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE

            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value <= 0:
                return None

            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h_proc = kernel32.OpenProcess(0x1000, False, pid.value)
            if not h_proc:
                return None

            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                    return Path(buf.value).name.lower()
            finally:
                kernel32.CloseHandle(h_proc)
        except Exception:
            return None
    elif sys.platform == "darwin":
        try:
            import subprocess
            res = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=0.2
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().lower()
        except Exception:
            return None
    elif sys.platform.startswith("linux"):
        try:
            import subprocess
            res = subprocess.run(["xdotool", "getwindowfocus", "getwindowpid"], capture_output=True, text=True, timeout=0.2)
            if res.returncode == 0 and res.stdout.strip():
                pid = res.stdout.strip()
                comm_path = Path(f"/proc/{pid}/comm")
                if comm_path.exists():
                    return comm_path.read_text().strip().lower()
        except Exception:
            return None

    return None


class CommunicationTracker:
    """Tracks communication application activity and estimates sent messages."""

    def __init__(
        self,
        comm_apps: Optional[List[str]] = None,
        process_getter: Optional[Callable[[], Optional[str]]] = None,
        db: Optional[Any] = None,
        cache_ttl_s: float = 0.5,
    ):
        raw_apps = comm_apps if comm_apps is not None else DEFAULT_COMM_APPS
        self.comm_apps: Set[str] = {app.lower().rstrip(".exe") for app in raw_apps}
        self._get_process = process_getter or default_get_active_process_name
        self.db = db
        self._cache_ttl_s = cache_ttl_s

        self._last_process_check = 0.0
        self._cached_process: Optional[str] = None
        self._cached_is_comm: bool = False

        self.message_events: List[datetime] = []

        # In-progress burst tracking in communication apps
        self._in_comm_burst: bool = False
        self._comm_burst_keystrokes: int = 0
        self._last_comm_keystroke_ts: Optional[datetime] = None

        # Restore from database checkpoint if available
        self._restore_from_db()

    def _restore_from_db(self) -> None:
        """Restore stored message timestamps from SQLite checkpoint."""
        if not self.db:
            return
        try:
            val = self.db.get_agent_state("comm_events_json")
            if val:
                loaded = json.loads(val)
                parsed: List[datetime] = []
                for ts_str in loaded:
                    dt = datetime.fromisoformat(ts_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=dt_timezone.utc)
                    parsed.append(dt)
                self.message_events = parsed
        except Exception:
            pass

    def _save_to_db(self) -> None:
        """Persist message timestamps to SQLite checkpoint."""
        if not self.db:
            return
        try:
            payload = json.dumps([t.isoformat() for t in self.message_events])
            self.db.set_agent_state("comm_events_json", payload)
        except Exception:
            pass

    def is_communication_process(self, proc_name: Optional[str]) -> bool:
        """Check if an executable name corresponds to a registered communication app."""
        if not proc_name:
            return False
        clean = proc_name.lower().rstrip(".exe")
        return any(app in clean or clean in app for app in self.comm_apps)

    def get_current_process(self) -> Optional[str]:
        """Fetch active foreground process name with TTL caching."""
        now_mono = time_mod.monotonic()
        if (now_mono - self._last_process_check) >= self._cache_ttl_s:
            self._cached_process = self._get_process()
            self._cached_is_comm = self.is_communication_process(self._cached_process)
            self._last_process_check = now_mono
        return self._cached_process

    def is_current_app_comm(self) -> bool:
        """Check if active foreground process is a communication app with TTL caching."""
        self.get_current_process()
        return self._cached_is_comm

    def on_event(self, event: ActivityEvent) -> None:
        """Evaluate an input event for communication activity."""
        # Only evaluate keyboard events
        if event.kind not in (
            EventKind.KEY_CHAR,
            EventKind.KEY_BACKSPACE,
            EventKind.KEY_DELETE,
            EventKind.KEY_OTHER,
        ):
            return

        is_comm = self.is_current_app_comm()

        if not is_comm:
            # User switched away from communication app
            if self._in_comm_burst and self._comm_burst_keystrokes >= 3:
                self.record_message(self._last_comm_keystroke_ts or event.ts_utc)
            self._in_comm_burst = False
            self._comm_burst_keystrokes = 0
            return

        # Active in communication app
        if getattr(event, "is_enter", False):
            # Explicit Enter key in communication app -> Message send!
            self.record_message(event.ts_utc)
            self._in_comm_burst = False
            self._comm_burst_keystrokes = 0
        else:
            # Typing inside communication app
            if not self._in_comm_burst:
                self._in_comm_burst = True
                self._comm_burst_keystrokes = 1
            else:
                # If gap since last key is > 10 seconds, previous was a completed message
                if self._last_comm_keystroke_ts and (event.ts_utc - self._last_comm_keystroke_ts).total_seconds() > 10.0:
                    if self._comm_burst_keystrokes >= 3:
                        self.record_message(self._last_comm_keystroke_ts)
                    self._comm_burst_keystrokes = 1
                else:
                    self._comm_burst_keystrokes += 1

            self._last_comm_keystroke_ts = event.ts_utc

    def record_message(self, ts_utc: datetime) -> None:
        """Record an explicit or inferred sent message timestamp."""
        # Debounce: avoid counting multiple Enters within 1 second as separate messages
        if self.message_events:
            last_ts = self.message_events[-1]
            diff = (ts_utc - last_ts).total_seconds()
            if 0 <= diff < 1.0:
                return

        self.message_events.append(ts_utc)
        self._save_to_db()

    def compute_daily_metrics(
        self,
        logical_day: date,
        *,
        tz_name: str = "Asia/Kolkata",
        shift_start: str = "09:00",
        shift_end: str = "18:00",
        late_night_window: str = "22:00-05:00",
    ) -> Dict[str, Any]:
        """Compute the 5 daily communication metrics from collected message timestamps."""
        # Final flush: if still in a burst at day close
        if self._in_comm_burst and self._comm_burst_keystrokes >= 3:
            self.record_message(self._last_comm_keystroke_ts or datetime.now(dt_timezone.utc))
            self._in_comm_burst = False
            self._comm_burst_keystrokes = 0

        if not self.message_events:
            return {
                "total_msgs_sent": 0,
                "msgs_sent_after_hours": 0,
                "msgs_sent_late_night": 0,
                "first_msg_time": None,
                "last_msg_time": None,
            }

        tz = zoneinfo.ZoneInfo(tz_name)
        day_of_week = logical_day.weekday()
        is_weekend = day_of_week in (5, 6)

        sh, sm = map(int, shift_start.split(":"))
        eh, em = map(int, shift_end.split(":"))
        shift_start_time = time(sh, sm)
        shift_end_time = time(eh, em)

        ln_s, ln_e = late_night_window.split("-")
        lnh_s, lnm_s = map(int, ln_s.split(":"))
        lnh_e, lnm_e = map(int, ln_e.split(":"))
        ln_start_time = time(lnh_s, lnm_s)
        ln_end_time = time(lnh_e, lnm_e)

        def is_late_night(t_val: time) -> bool:
            if ln_start_time > ln_end_time:
                return t_val >= ln_start_time or t_val < ln_end_time
            return ln_start_time <= t_val < ln_end_time

        local_times: List[datetime] = []
        msgs_after_hours = 0
        msgs_late_night = 0

        for ts in self.message_events:
            loc = ts.astimezone(tz)
            local_times.append(loc)
            t_val = loc.time()

            if is_weekend or (t_val < shift_start_time or t_val >= shift_end_time):
                msgs_after_hours += 1

            if is_late_night(t_val):
                msgs_late_night += 1

        local_times.sort()
        first_time_str = local_times[0].strftime("%H:%M")
        last_time_str = local_times[-1].strftime("%H:%M")

        return {
            "total_msgs_sent": len(self.message_events),
            "msgs_sent_after_hours": msgs_after_hours,
            "msgs_sent_late_night": msgs_late_night,
            "first_msg_time": first_time_str,
            "last_msg_time": last_time_str,
        }

    def reset_day(self) -> None:
        """Reset communication metrics for a new logical day."""
        self.message_events.clear()
        self._in_comm_burst = False
        self._comm_burst_keystrokes = 0
        self._last_comm_keystroke_ts = None
        if self.db:
            try:
                self.db.set_agent_state("comm_events_json", "")
            except Exception:
                pass
