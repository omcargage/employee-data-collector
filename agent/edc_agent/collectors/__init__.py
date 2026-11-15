"""Collectors subpackage for capturing raw behavioural input events.

Gathers keyboard, mouse, and system activity events in-memory using platform input providers.
"""
from .activity_collector import ActivityCollector, WindowAccumulator
from .gap_classifier import GapType, HeartbeatManager, classify_gap

__all__ = [
    "ActivityCollector",
    "WindowAccumulator",
    "GapType",
    "classify_gap",
    "HeartbeatManager",
]
