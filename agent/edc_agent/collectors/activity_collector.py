"""Thread-safe activity collector decoupling input hooks from window metric accumulation.

Provides a bounded drop-oldest event queue and routes consumed events to time-aligned window accumulators.
"""
from collections import deque
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple, Union
import threading
import zoneinfo

from edc_agent.timeutil import window_bounds
from edc_schemas import ActivityEvent


class WindowAccumulator:
    """Accumulates raw ActivityEvents belonging to a specific 15-minute time window."""

    def __init__(self, window_start: datetime, window_end: datetime):
        self.window_start = window_start
        self.window_end = window_end
        self.events: List[ActivityEvent] = []

    def add_event(self, event: ActivityEvent) -> None:
        """Add an event to this window."""
        self.events.append(event)

    @property
    def event_count(self) -> int:
        """Return total events accumulated in this window."""
        return len(self.events)


class ActivityCollector:
    """Consumes input events via a non-blocking bounded queue and routes them to window accumulators."""

    def __init__(
        self,
        timezone_name: str = "Asia/Kolkata",
        max_queue_size: int = 10000,
        window_minutes: int = 15,
        on_window_event: Optional[Callable[[Tuple[datetime, datetime], ActivityEvent], None]] = None,
    ):
        self.timezone = timezone_name
        self.max_queue_size = max_queue_size
        self.window_minutes = window_minutes
        self.on_window_event = on_window_event

        self._queue: deque[ActivityEvent] = deque()
        self._condition = threading.Condition()
        self._is_running = False
        self._is_paused = False
        self._worker_thread: Optional[threading.Thread] = None

        self._dropped_events_count = 0
        self._accumulators_lock = threading.Lock()
        self._accumulators: Dict[Tuple[datetime, datetime], WindowAccumulator] = {}

    @property
    def is_paused(self) -> bool:
        """Return whether collector is in paused state."""
        with self._condition:
            return self._is_paused

    def pause(self) -> None:
        """Pause collection; incoming hook events are dropped while paused."""
        with self._condition:
            self._is_paused = True

    def resume(self) -> None:
        """Resume collection; incoming hook events are accepted again."""
        with self._condition:
            self._is_paused = False

    @property
    def dropped_events_count(self) -> int:
        """Return total number of events dropped due to queue saturation."""
        with self._condition:
            return self._dropped_events_count

    @property
    def queue_size(self) -> int:
        """Return current number of items waiting in queue."""
        with self._condition:
            return len(self._queue)

    def on_event(self, event: ActivityEvent) -> None:
        """Hook callback. Non-blocking enqueue with drop-oldest policy if queue is full."""
        with self._condition:
            if self._is_paused:
                return
            if len(self._queue) >= self.max_queue_size:
                self._queue.popleft()
                self._dropped_events_count += 1
            self._queue.append(event)
            self._condition.notify()

    def start(self) -> None:
        """Start the background consumer worker thread."""
        with self._condition:
            if self._is_running:
                return
            self._is_running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self, drain: bool = True) -> None:
        """Stop consumer thread, optionally draining remaining items first."""
        with self._condition:
            self._is_running = False
            self._condition.notify_all()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        if drain:
            self.drain_sync()

    def drain_sync(self) -> None:
        """Process any remaining queued items synchronously."""
        while True:
            with self._condition:
                if not self._queue:
                    break
                event = self._queue.popleft()
            self._route_event(event)

    def _worker_loop(self) -> None:
        """Background loop consuming events from the queue."""
        while True:
            with self._condition:
                while self._is_running and not self._queue:
                    self._condition.wait(timeout=0.1)

                if not self._queue:
                    if not self._is_running:
                        break
                    continue

                event = self._queue.popleft()

            self._route_event(event)

    def _route_event(self, event: ActivityEvent) -> None:
        """Route an event to its corresponding time-aligned window accumulator."""
        bounds = window_bounds(event.ts_utc, self.timezone, self.window_minutes)
        with self._accumulators_lock:
            if bounds not in self._accumulators:
                self._accumulators[bounds] = WindowAccumulator(bounds[0], bounds[1])
            self._accumulators[bounds].add_event(event)

        if self.on_window_event:
            self.on_window_event(bounds, event)

    def get_accumulator(self, bounds: Tuple[datetime, datetime]) -> Optional[WindowAccumulator]:
        """Fetch window accumulator for given (start_utc, end_utc) bounds."""
        with self._accumulators_lock:
            return self._accumulators.get(bounds)

    def pop_accumulator(self, bounds: Tuple[datetime, datetime]) -> Optional[WindowAccumulator]:
        """Remove and return the window accumulator, discarding raw events from active tracking."""
        with self._accumulators_lock:
            return self._accumulators.pop(bounds, None)

    def get_all_accumulators(self) -> Dict[Tuple[datetime, datetime], WindowAccumulator]:
        """Return shallow copy of all registered window accumulators."""
        with self._accumulators_lock:
            return dict(self._accumulators)
