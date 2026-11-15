"""Windows platform implementation for input monitoring, lock detection, and power events.

Uses Windows API / pynput hooks to provide raw input events adhering to the privacy contract.
"""
from .provider import WindowsInputProvider
from .system_state import SystemState, SystemStateEvent, WindowsSystemStateMonitor

__all__ = [
    "WindowsInputProvider",
    "SystemState",
    "SystemStateEvent",
    "WindowsSystemStateMonitor",
]
