"""macOS platform input provider using pynput and Quartz event taps.

Captures keyboard and mouse events using macOS event taps while respecting
macOS Input Monitoring (kTCCServiceListenEvent) permissions.
Strictly adheres to the privacy boundary: key identity is immediately converted
to an anonymous event category and discarded; raw keys are never stored, logged, or emitted.
"""
from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable, Dict, Optional
import threading

from pynput.keyboard import Key, Listener as KeyboardListener
from pynput.mouse import Listener as MouseListener

from edc_agent.platforms.base import InputProvider
from edc_agent.platforms.macos.permissions import (
    INPUT_MONITORING_EXPLANATION,
    is_input_monitoring_granted,
)
from edc_schemas import ActivityEvent, EventKind

logger = logging.getLogger("edc_agent.platforms.macos.provider")

# Known modifier keys including macOS Command keys
MODIFIER_KEYS = {
    getattr(Key, attr)
    for attr in [
        "shift", "shift_r", "shift_l",
        "ctrl", "ctrl_r", "ctrl_l",
        "alt", "alt_r", "alt_l", "alt_gr",
        "cmd", "cmd_r", "cmd_l",
    ]
    if hasattr(Key, attr)
}


class MacOSInputProvider(InputProvider):
    """macOS input provider capturing peripheral events via Quartz event taps."""

    def __init__(
        self,
        callback: Callable[[ActivityEvent], None],
        mouse_bin_ms: int = 100,
        permission_checker: Optional[Callable[[], bool]] = None,
    ):
        super().__init__(callback)
        self.mouse_bin_ms = mouse_bin_ms
        self._coalesce_interval_s = mouse_bin_ms / 1000.0
        self._permission_checker = permission_checker or is_input_monitoring_granted

        self._keyboard_listener: Optional[KeyboardListener] = None
        self._mouse_listener: Optional[MouseListener] = None

        self._state_lock = threading.Lock()
        self._held_non_modifier: Optional[EventKind] = None
        self._last_move_mono = 0.0

    def has_input_monitoring_permission(self) -> bool:
        """Check whether Input Monitoring permission is currently granted."""
        return self._permission_checker()

    def get_capabilities(self) -> Dict[str, Any]:
        """Return provider capabilities based on macOS permissions status.

        If Input Monitoring permission is not granted, all input capabilities are reported
        as unavailable (False) along with explanatory guidance on granting permission.
        """
        has_perm = self.has_input_monitoring_permission()
        if not has_perm:
            return {
                "key_dwell": False,
                "mouse_move": False,
                "mouse_click": False,
                "mouse_scroll": False,
                "input_monitoring_granted": False,
                "supported": False,
                "message": INPUT_MONITORING_EXPLANATION,
            }

        return {
            "key_dwell": False,
            "mouse_move": True,
            "mouse_click": True,
            "mouse_scroll": True,
            "input_monitoring_granted": True,
            "supported": True,
            "message": "Input Monitoring permission granted.",
        }

    def start(self) -> None:
        """Initialize and start keyboard and mouse low-level listeners if permitted."""
        with self._lock:
            if self._is_running:
                return

            if not self.has_input_monitoring_permission():
                logger.warning(
                    "Cannot start macOS input listeners: Input Monitoring permission missing.\n%s",
                    INPUT_MONITORING_EXPLANATION,
                )
                return

            self._is_running = True

        try:
            self._keyboard_listener = KeyboardListener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._mouse_listener = MouseListener(
                on_move=self._on_move,
                on_click=self._on_click,
                on_scroll=self._on_scroll,
            )

            self._keyboard_listener.start()
            self._mouse_listener.start()
        except Exception as exc:
            with self._lock:
                self._is_running = False
            logger.error(
                "Failed to start macOS event tap listeners (%s). Verify Input Monitoring permissions:\n%s",
                exc,
                INPUT_MONITORING_EXPLANATION,
            )
            raise

    def stop(self) -> None:
        """Stop low-level listeners and release hook handles."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None

        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def _classify_key(self, key: Any) -> EventKind:
        """Map raw key to privacy-preserving category."""
        if key == Key.backspace:
            return EventKind.KEY_BACKSPACE
        if key == Key.delete:
            return EventKind.KEY_DELETE
        if key in MODIFIER_KEYS:
            return EventKind.KEY_MODIFIER
        if key == Key.space:
            return EventKind.KEY_CHAR
        if hasattr(key, "char") and key.char is not None:
            return EventKind.KEY_CHAR
        return EventKind.KEY_OTHER

    def _on_press(self, key: Any) -> None:
        """Keyboard press callback.

        Converts key to category and immediately deletes the key object reference.
        Enforces auto-repeat rules per Spec Section 4.
        """
        now_utc = datetime.now(timezone.utc)
        try:
            kind = self._classify_key(key)
        finally:
            del key  # Non-negotiable privacy: discard raw key object immediately

        with self._state_lock:
            if kind == EventKind.KEY_MODIFIER:
                self.emit(ActivityEvent(ts_utc=now_utc, kind=kind))
                return

            if self._held_non_modifier == kind:
                if kind in (EventKind.KEY_BACKSPACE, EventKind.KEY_DELETE):
                    self.emit(ActivityEvent(ts_utc=now_utc, kind=kind))
                else:
                    pass
                return

            self._held_non_modifier = kind
            self.emit(ActivityEvent(ts_utc=now_utc, kind=kind))

    def _on_release(self, key: Any) -> None:
        """Keyboard release callback. Resets held key tracking."""
        try:
            kind = self._classify_key(key)
        finally:
            del key

        with self._state_lock:
            if self._held_non_modifier == kind:
                self._held_non_modifier = None

    def _on_move(self, x: float, y: float) -> None:
        """Mouse move callback. Coalesces high-frequency movement events per mouse_bin_ms."""
        now_mono = time.monotonic()
        if (now_mono - self._last_move_mono) < self._coalesce_interval_s:
            return

        self._last_move_mono = now_mono
        self.emit(
            ActivityEvent(
                ts_utc=datetime.now(timezone.utc),
                kind=EventKind.MOUSE_MOVE,
                x=float(x),
                y=float(y),
            )
        )

    def _on_click(self, x: float, y: float, button: Any, pressed: bool) -> None:
        """Mouse click callback. Emits click events on mouse-down only."""
        if not pressed:
            return

        self.emit(
            ActivityEvent(
                ts_utc=datetime.now(timezone.utc),
                kind=EventKind.MOUSE_CLICK,
                x=float(x),
                y=float(y),
            )
        )

    def _on_scroll(self, x: float, y: float, dx: int, dy: int) -> None:
        """Mouse scroll callback."""
        self.emit(
            ActivityEvent(
                ts_utc=datetime.now(timezone.utc),
                kind=EventKind.MOUSE_SCROLL,
                x=float(x),
                y=float(y),
                scroll_ticks=int(dy if dy != 0 else dx),
            )
        )
