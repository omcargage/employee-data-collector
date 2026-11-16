"""macOS Input Monitoring permission detection.

macOS Catalina (10.15) and later enforce TCC (Transparency, Consent, and Control)
access controls for global input observation (kTCCServiceListenEvent).
Without this permission, CGEventTapCreate fails and pynput cannot observe background input events.
"""
import ctypes
from ctypes import util
import logging
import sys
from typing import Optional, Tuple

logger = logging.getLogger("edc_agent.platforms.macos.permissions")

INPUT_MONITORING_EXPLANATION = (
    "macOS Input Monitoring permission is not granted.\n\n"
    "macOS (Catalina 10.15+) restricts global keystroke and mouse event capture "
    "by background applications for user privacy and security.\n\n"
    "To grant Input Monitoring permission:\n"
    "  1. Open System Settings (or System Preferences on macOS Monterey and earlier).\n"
    "  2. Navigate to 'Privacy & Security' -> 'Input Monitoring'.\n"
    "  3. Toggle ON the switch next to Terminal, iTerm2, VS Code, or the EDC executable.\n"
    "  4. When prompted, select 'Quit & Reopen' for permission changes to take effect."
)


DEFAULT_APP_SERVICES_FRAMEWORK = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)


def is_input_monitoring_granted() -> bool:
    """Check if the current process has been granted macOS Input Monitoring permission.

    Calls the native ApplicationServices/CoreGraphics C API `CGPreflightListenEventAccess()`
    introduced in macOS 10.15 Catalina.

    Returns:
        True if Input Monitoring permission is granted, False otherwise.
    """
    if sys.platform != "darwin":
        # Non-macOS environments do not require or support this check
        return False

    try:
        app_services = ctypes.cdll.LoadLibrary(DEFAULT_APP_SERVICES_FRAMEWORK)
        if hasattr(app_services, "CGPreflightListenEventAccess"):
            app_services.CGPreflightListenEventAccess.restype = ctypes.c_bool
            return bool(app_services.CGPreflightListenEventAccess())
    except Exception as exc:
        logger.debug("Error checking CGPreflightListenEventAccess: %s", exc)

    return False


def request_input_monitoring_permission() -> bool:
    """Trigger the macOS native dialog requesting Input Monitoring permission.

    Calls `CGRequestListenEventAccess()` which opens the OS permission prompt if
    the user has not yet decided.

    Returns:
        True if already granted, False otherwise.
    """
    if sys.platform != "darwin":
        return False

    try:
        app_services = ctypes.cdll.LoadLibrary(DEFAULT_APP_SERVICES_FRAMEWORK)
        if hasattr(app_services, "CGRequestListenEventAccess"):
            app_services.CGRequestListenEventAccess.restype = ctypes.c_bool
            return bool(app_services.CGRequestListenEventAccess())
    except Exception as exc:
        logger.debug("Error requesting CGRequestListenEventAccess: %s", exc)

    return False


def check_input_monitoring_permission() -> Tuple[bool, str]:
    """Check Input Monitoring permission and return status with explanatory guidance.

    Returns:
        A tuple of (is_granted, explanation_message).
    """
    granted = is_input_monitoring_granted()
    if granted:
        return True, "macOS Input Monitoring permission is granted."
    return False, INPUT_MONITORING_EXPLANATION
