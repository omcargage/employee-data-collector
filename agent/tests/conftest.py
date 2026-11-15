"""Pytest configuration and session hooks for EDC agent tests.

Configures test collection behavior and shared fixtures.
"""
import pytest


def pytest_sessionfinish(session, exitstatus):
    """Allow test suite to pass with zero tests collected during initial scaffold."""
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
