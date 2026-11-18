"""Windows platform input provider using pynput.

Captures keyboard and mouse events using Windows low-level hooks (WH_KEYBOARD_LL / WH_MOUSE_LL).
Strictly adheres to the privacy boundary: key identity is immediately converted to an anonymous
event category and discarded; raw keys are never stored, logged, or passed on.
"""
from datetime import datetime, timezone
import time
from typing import Any, Callable, Dict, Optional
import threading

from pynput.keyboard import Key, KeyCode, Listener as KeyboardListener
from pynput.mouse import Button, Listener as MouseListener

from edc_agent.platforms.base import InputProvider
from edc_schemas import ActivityEvent, EventKind


# Known modifier keys in pynput
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


class WindowsInputProvider(InputProvider):
    """Windows input provider capturing peripheral events via pynput low-level hooks."""

    def __init__(
        self,
        callback: Callable[[ActivityEvent], None],
        mouse_bin_ms: int = 100,
    ):
        super().__init__(callback)
        self.mouse_bin_ms = mouse_bin_ms
        self._coalesce_interval_s = mouse_bin_ms / 1000.0

        self._keyboard_listener: Optional[KeyboardListener] = None
        self._mouse_listener: Optional[MouseListener] = None

        self._state_lock = threading.Lock()
        self._held_non_modifier: Optional[EventKind] = None
        self._last_move_mono = 0.0

    def get_capabilities(self) -> Dict[str, bool]:
        """Return provider capabilities.

        key_dwell is False because pairing key-down to key-up without retaining key identity
        is unreliable in userspace hooks.
        """
        return {
            "key_dwell": False,
            "mouse_move": True,
            "mouse_click": True,
            "mouse_scroll": True,
        }

    def start(self) -> None:
        """Initialize and start keyboard and mouse low-level listeners."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True

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
        """Convert a pynput key object into an anonymous EventKind.

        The raw key is evaluated solely for category classification and never stored.
        """
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
        Enforces auto-repeat rules per Spec Section 4: repeats of backspace/delete
        count as corrections; repeats of char/other are collapsed.
        """
        now_utc = datetime.now(timezone.utc)
        is_enter = False
        try:
            is_enter = (key == Key.enter)
            kind = self._classify_key(key)
        finally:
            del key  # Non-negotiable privacy: discard raw key object immediately

        with self._state_lock:
            if kind == EventKind.KEY_MODIFIER:
                # Modifiers do not participate in typing flight auto-repeat collapse
                self.emit(ActivityEvent(ts_utc=now_utc, kind=kind))
                return

            if self._held_non_modifier == kind:
                # Held-key auto-repeat detected (key-down without intervening key-up)
                if kind in (EventKind.KEY_BACKSPACE, EventKind.KEY_DELETE):
                    # Count repeated backspace/delete as genuine corrections
                    self.emit(ActivityEvent(ts_utc=now_utc, kind=kind))
                else:
                    # Collapse held char / other keys into single keystroke
                    pass
                return

            # Initial key press
            self._held_non_modifier = kind
            self.emit(ActivityEvent(ts_utc=now_utc, kind=kind, is_enter=True if is_enter else None))

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
        """Mouse click callback. Emits button-down events only."""
        if not pressed:
            return

        btn_num = 1
        if button == Button.right:
            btn_num = 2
        elif button == Button.middle:
            btn_num = 3

        self.emit(
            ActivityEvent(
                ts_utc=datetime.now(timezone.utc),
                kind=EventKind.MOUSE_CLICK,
                x=float(x),
                y=float(y),
                button=btn_num,
            )
        )

    def _on_scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        """Mouse scroll callback. Emits signed scroll tick count."""
        ticks = int(dy) if dy != 0 else int(dx)
        self.emit(
            ActivityEvent(
                ts_utc=datetime.now(timezone.utc),
                kind=EventKind.MOUSE_SCROLL,
                x=float(x),
                y=float(y),
                scroll_ticks=ticks,
            )
        )
