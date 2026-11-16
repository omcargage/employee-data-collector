"""Platforms subpackage providing OS-specific hooks behind an InputProvider interface.

Isolates Windows, macOS, and Linux implementation details from cross-platform agent logic.
"""
from typing import Callable, Optional
import sys

from edc_schemas import ActivityEvent
from .base import InputProvider
from .fake import FakeInputProvider


def get_platform_provider(
    callback: Callable[[ActivityEvent], None],
    mouse_bin_ms: int = 100,
    platform_name: Optional[str] = None,
) -> InputProvider:
    """Return the appropriate InputProvider for the host operating system.

    Args:
        callback: Event ingestion callback receiving anonymized ActivityEvents.
        mouse_bin_ms: Aggregation bin interval for coalescing mouse movements.
        platform_name: Explicit OS override for testing (e.g. 'win32', 'darwin', 'linux').

    Returns:
        Configured InputProvider instance for the target platform.
    """
    plat = platform_name or sys.platform

    if plat == "win32":
        from .windows.provider import WindowsInputProvider
        return WindowsInputProvider(callback=callback, mouse_bin_ms=mouse_bin_ms)

    if plat == "darwin":
        from .macos.provider import MacOSInputProvider
        return MacOSInputProvider(callback=callback, mouse_bin_ms=mouse_bin_ms)

    if plat.startswith("linux"):
        from .linux.provider import LinuxInputProvider
        return LinuxInputProvider(callback=callback, mouse_bin_ms=mouse_bin_ms)

    return FakeInputProvider(callback=callback)


__all__ = ["InputProvider", "FakeInputProvider", "get_platform_provider"]
