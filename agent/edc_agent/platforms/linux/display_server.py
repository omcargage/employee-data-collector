"""Linux display server detection (X11 vs. Wayland).

Wayland isolates graphical applications and prevents background processes from
eavesdropping on keystrokes and pointer events from other windows.
Consequently, global input monitoring is unsupported on Wayland without compositor-specific
or root /dev/input permissions.
"""
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger("edc_agent.platforms.linux.display_server")

WAYLAND_RESTRICTION_EXPLANATION = (
    "Wayland display server detected.\n\n"
    "The Wayland protocol enforces strict client-to-client security isolation. "
    "Unprivileged background processes cannot monitor global keystrokes or mouse activity.\n\n"
    "To enable activity metric collection on Linux:\n"
    "  1. Log out of your current desktop session.\n"
    "  2. At the login screen, click your username, then click the gear/settings icon.\n"
    "  3. Select 'Ubuntu on Xorg' (or 'GNOME on X11' / 'X11 session').\n"
    "  4. Log in and re-launch the EDC agent."
)


def detect_display_server(environ: Optional[Dict[str, str]] = None) -> str:
    """Detect whether the current Linux session is running on X11 or Wayland.

    Inspects standard Freedesktop / XDG environment variables:
    - XDG_SESSION_TYPE: 'wayland', 'x11', or 'tty'
    - WAYLAND_DISPLAY: e.g. 'wayland-0'
    - DISPLAY: e.g. ':0'

    Args:
        environ: Optional dictionary of environment variables (defaults to os.environ).

    Returns:
        'wayland', 'x11', or 'unknown'.
    """
    env = os.environ if environ is None else environ

    # 1. Primary check: XDG_SESSION_TYPE
    session_type = env.get("XDG_SESSION_TYPE", "").strip().lower()
    if session_type == "wayland":
        return "wayland"
    if session_type == "x11":
        return "x11"

    # 2. Secondary check: WAYLAND_DISPLAY socket
    wayland_display = env.get("WAYLAND_DISPLAY", "").strip()
    if wayland_display:
        return "wayland"

    # 3. Tertiary check: standard X11 DISPLAY variable
    x11_display = env.get("DISPLAY", "").strip()
    if x11_display:
        return "x11"

    return "unknown"


def is_wayland(environ: Optional[Dict[str, str]] = None) -> bool:
    """Return True if the current session is running under Wayland."""
    return detect_display_server(environ) == "wayland"


def is_x11(environ: Optional[Dict[str, str]] = None) -> bool:
    """Return True if the current session is running under X11."""
    return detect_display_server(environ) == "x11"
