"""Fake input provider for testing and deterministic event pipeline validation.

Replays a scripted list of ActivityEvent instances to the registered callback.
"""
from typing import Any, Callable, Dict, List, Optional
import threading

from edc_schemas import ActivityEvent
from .base import InputProvider


class FakeInputProvider(InputProvider):
    """Test provider that replays a predefined sequence of ActivityEvents."""

    def __init__(
        self,
        callback: Callable[[ActivityEvent], None],
        events: Optional[List[ActivityEvent]] = None,
        capabilities: Optional[Dict[str, bool]] = None,
    ):
        super().__init__(callback)
        self._events: List[ActivityEvent] = list(events) if events else []
        self._capabilities: Dict[str, bool] = capabilities or {
            "key_dwell": False,
            "mouse_move": True,
            "mouse_click": True,
            "mouse_scroll": True,
        }
        self._thread: Optional[threading.Thread] = None

    def set_events(self, events: List[ActivityEvent]) -> None:
        """Replace the scripted event sequence."""
        self._events = list(events)

    def add_event(self, event: ActivityEvent) -> None:
        """Append an event to the scripted sequence."""
        self._events.append(event)

    def start(self) -> None:
        """Start replaying the scripted events in a background worker thread."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True

        self._thread = threading.Thread(target=self._run_replay, daemon=True)
        self._thread.start()

    def replay_sync(self) -> None:
        """Replay all scripted events synchronously on the calling thread."""
        for event in self._events:
            self.emit(event)

    def emit_key(self, kind: Any = None, ts: Optional[Any] = None, is_enter: bool = False) -> None:
        """Emit a single synthetic key event."""
        from datetime import datetime, timezone
        from edc_schemas import EventKind
        k = kind or EventKind.KEY_CHAR
        now = ts or datetime.now(timezone.utc)
        self.emit(ActivityEvent(ts_utc=now, kind=k, is_enter=True if is_enter else None))

    def _run_replay(self) -> None:
        for event in self._events:
            with self._lock:
                if not self._is_running:
                    break
            self.emit(event)
        with self._lock:
            self._is_running = False

    def stop(self) -> None:
        """Stop replaying events."""
        with self._lock:
            self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_capabilities(self) -> Dict[str, bool]:
        """Return declared fake capabilities."""
        return dict(self._capabilities)
