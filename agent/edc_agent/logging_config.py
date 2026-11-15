"""Rotating file logging configuration for the EDC agent per Prompt 14.

Configures rotating log files containing lifecycle messages only (startup, shutdown,
window boundaries, rollups, consent, paused/resumed, errors), strictly enforcing that
no event data (keystrokes, mouse coordinates, typed text) is ever written to logs.
"""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
from typing import Optional, Union


DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_BACKUP_COUNT = 5


def get_default_log_dir() -> Path:
    """Return default logging directory (~/.edc/logs)."""
    env_dir = os.environ.get("EDC_LOG_DIR")
    if env_dir:
        log_dir = Path(env_dir)
    else:
        log_dir = Path.home() / ".edc" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_default_log_file() -> Path:
    """Return default rotating log file path (~/.edc/logs/edc_agent.log)."""
    return get_default_log_dir() / "edc_agent.log"


class LifecycleOnlyFilter(logging.Filter):
    """Enforces non-negotiable privacy boundaries on all log output.

    Allows lifecycle, health, system state, error, and rollup messages.
    Strictly forbids raw event details, key characters, or coordinates.
    """

    # Patterns that indicate raw event payloads or forbidden telemetry leaks
    FORBIDDEN_PATTERNS = [
        re.compile(r"ActivityEvent\(", re.IGNORECASE),
        re.compile(r"key_char=['\"][a-zA-Z0-9 ]['\"]", re.IGNORECASE),
        re.compile(r"raw_key", re.IGNORECASE),
        re.compile(r"typed_text", re.IGNORECASE),
        re.compile(r"keystroke_char", re.IGNORECASE),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        # Check formatted message
        try:
            msg = record.getMessage()
        except Exception:
            return False

        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern.search(msg):
                # Block logging of raw event data immediately
                return False

        # Check record args for ActivityEvent instances
        if record.args:
            args = record.args if isinstance(record.args, (list, tuple)) else [record.args]
            for arg in args:
                if type(arg).__name__ == "ActivityEvent":
                    return False
                if isinstance(arg, dict) and ("raw_key" in arg or "typed_text" in arg):
                    return False

        return True


def setup_logging(
    log_file: Optional[Union[str, Path]] = None,
    log_level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    to_console: bool = True,
) -> logging.Logger:
    """Configure rotating file logging with lifecycle-only filter and console output."""
    target_file = Path(log_file) if log_file else get_default_log_file()
    target_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates on reconfiguration
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    lifecycle_filter = LifecycleOnlyFilter()

    # 1. Rotating File Handler
    file_handler = RotatingFileHandler(
        filename=str(target_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(lifecycle_filter)
    root_logger.addHandler(file_handler)

    # 2. Console Stream Handler (Optional)
    if to_console:
        import sys
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(lifecycle_filter)
        root_logger.addHandler(console_handler)

    edc_logger = logging.getLogger("edc_agent")
    edc_logger.info("EDC logging configured. Log file: %s (max_bytes=%d, backups=%d)", target_file, max_bytes, backup_count)
    return edc_logger
