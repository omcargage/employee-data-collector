"""Abstract base class for platform input providers.

Defines the InputProvider contract: start(), stop(), capabilities discovery, and event delivery callback.
"""
from abc import ABC, abstractmethod
from typing import Callable, Dict
import threading

from edc_schemas import ActivityEvent


class InputProvider(ABC):
    """Abstract interface isolating OS-specific input hooks from collector logic."""

    def __init__(self, callback: Callable[[ActivityEvent], None]):
        self._callback = callback
        self._is_running = False
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Return whether the input provider is currently active."""
        with self._lock:
            return self._is_running

    @abstractmethod
    def start(self) -> None:
        """Start listening to input events and dispatching to callback."""

    @abstractmethod
    def stop(self) -> None:
        """Stop listening to input events and release system hooks."""

    @abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Return dictionary of supported features, e.g. {'key_dwell': False, 'mouse_move': True}."""

    def emit(self, event: ActivityEvent) -> None:
        """Thread-safe dispatcher delivering an anonymized ActivityEvent to the registered callback."""
        try:
            self._callback(event)
        except Exception:
            # Prevent unhandled callback errors from crashing OS hook threads
            pass
