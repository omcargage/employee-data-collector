"""Linux platform input provider using pynput on X11 with Wayland capability detection.

Captures keyboard and mouse events using standard X11 event hooks.
If running under Wayland, reports capabilities unavailable and prevents listener startup.
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
from edc_agent.platforms.linux.display_server import (
    WAYLAND_RESTRICTION_EXPLANATION,
    detect_display_server,
)
from edc_schemas import ActivityEvent, EventKind

logger = logging.getLogger("edc_agent.platforms.linux.provider")

# Known modifier keys on Linux (X11)
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


class LinuxInputProvider(InputProvider):
    """Linux input provider capturing peripheral events via X11 hooks."""

    def __init__(
        self,
        callback: Callable[[ActivityEvent], None],
        mouse_bin_ms: int = 100,
        display_server_checker: Optional[Callable[[], str]] = None,
    ):
        super().__init__(callback)
        self.mouse_bin_ms = mouse_bin_ms
        self._coalesce_interval_s = mouse_bin_ms / 1000.0
        self._display_server_checker = display_server_checker or detect_display_server

        self._keyboard_listener: Optional[KeyboardListener] = None
        self._mouse_listener: Optional[MouseListener] = None

        self._state_lock = threading.Lock()
        self._held_non_modifier: Optional[EventKind] = None
        self._last_move_mono = 0.0

    def get_display_server(self) -> str:
        """Return the current display server type ('wayland', 'x11', 'unknown')."""
        return self._display_server_checker()

    def is_wayland(self) -> bool:
        """Return whether running under Wayland."""
        return self.get_display_server() == "wayland"

    def get_capabilities(self) -> Dict[str, Any]:
        """Return provider capabilities based on display server architecture.

        On Wayland, reports all input capabilities unavailable (False) due to compositor isolation.
        On X11, reports standard mouse and keyboard capture capabilities available (True).
        """
        server = self.get_display_server()
        if server == "wayland":
            return {
                "key_dwell": False,
                "mouse_move": False,
                "mouse_click": False,
                "mouse_scroll": False,
                "wayland_detected": True,
                "display_server": "wayland",
                "supported": False,
                "message": WAYLAND_RESTRICTION_EXPLANATION,
            }

        return {
            "key_dwell": False,
            "mouse_move": True,
            "mouse_click": True,
            "mouse_scroll": True,
            "wayland_detected": False,
            "display_server": server,
            "supported": True,
            "message": f"Input capture supported on {server.upper()}.",
        }

    def start(self) -> None:
        """Initialize and start keyboard and mouse low-level listeners if on X11."""
        with self._lock:
            if self._is_running:
                return

            if self.is_wayland():
                logger.warning(
                    "Cannot start Linux input listeners: Wayland display server detected.\n%s",
                    WAYLAND_RESTRICTION_EXPLANATION,
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
            logger.error("Failed to start X11 input listeners: %s", exc)
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
