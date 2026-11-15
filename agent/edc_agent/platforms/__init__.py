"""Platforms subpackage providing OS-specific hooks behind an InputProvider interface.

Isolates Windows, macOS, and Linux implementation details from cross-platform agent logic.
"""
from .base import InputProvider
from .fake import FakeInputProvider

__all__ = ["InputProvider", "FakeInputProvider"]
