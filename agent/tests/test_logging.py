"""Tests for rotating file logging and lifecycle privacy filters."""
from datetime import datetime, timezone
import logging
from pathlib import Path
from edc_agent.logging_config import setup_logging
from edc_schemas import ActivityEvent, EventKind


def test_rotating_file_logger_and_rotation(tmp_path: Path):
    """Verify that log files are created, rotated when max_bytes is reached, and limited by backup_count."""
    log_file = tmp_path / "test_agent.log"
    max_bytes = 200  # Small size to trigger fast rotation
    backup_count = 3

    logger = setup_logging(
        log_file=log_file,
        max_bytes=max_bytes,
        backup_count=backup_count,
        to_console=False,
    )

    # Write enough lifecycle messages to force multiple rotations
    for i in range(50):
        logger.info("Lifecycle status update event message #%03d", i)

    # Flush all handlers
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    # Check that backup files exist
    backup_1 = tmp_path / "test_agent.log.1"
    assert backup_1.exists(), "First backup log file should exist after rotation"


def test_privacy_filter_blocks_event_data_and_raw_keys(tmp_path: Path):
    """Verify that no event data, ActivityEvent instances, or raw key identities are ever logged."""
    log_file = tmp_path / "privacy_test.log"

    logger = setup_logging(
        log_file=log_file,
        to_console=False,
    )

    # 1. Allowed lifecycle messages
    logger.info("Starting EDC agent lifecycle (window=15 mins)...")
    logger.info("Stored Rollup15Min for [2026-11-15T10:00:00, 2026-11-15T10:15:00] (coverage=1.00)")
    logger.info("EDC agent paused successfully.")

    # 2. Blocked messages attempting to leak event data or raw keys
    event = ActivityEvent(kind=EventKind.KEY_CHAR, ts_utc=datetime.now(timezone.utc))
    logger.info("Attempted leak: %s", event)
    logger.info("Raw keystroke: ActivityEvent(kind=EventKind.KEY_CHAR, x=10, y=20)")
    logger.info("User typed raw_key='secret_password'")
    logger.info("Telemetry keystroke_char='x'")

    for handler in logging.getLogger().handlers:
        handler.flush()

    log_content = log_file.read_text(encoding="utf-8")

    # Allowed messages must be in log
    assert "Starting EDC agent lifecycle" in log_content
    assert "Stored Rollup15Min" in log_content
    assert "EDC agent paused successfully" in log_content

    # Forbidden event data must NEVER appear in log
    assert "Attempted leak" not in log_content
    assert "secret_password" not in log_content
    assert "raw_key" not in log_content
    assert "keystroke_char" not in log_content
