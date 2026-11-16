"""Linux platform implementation providing X11 input provider and Wayland capability detection."""
from .display_server import (
    WAYLAND_RESTRICTION_EXPLANATION,
    detect_display_server,
    is_wayland,
    is_x11,
)
from .provider import LinuxInputProvider

__all__ = [
    "LinuxInputProvider",
    "detect_display_server",
    "is_wayland",
    "is_x11",
    "WAYLAND_RESTRICTION_EXPLANATION",
]
