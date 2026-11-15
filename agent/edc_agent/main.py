"""Main entry point and CLI commands for the Employee Data Collector (EDC) desktop agent.

Supports running the foreground collection loop, pausing and resuming via `edc pause` / `edc resume`,
checking status, and graceful shutdown on Ctrl+C.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import argparse
import logging
import signal
import sys
import threading
import time

from edc_agent.config import load_config
from edc_agent.lifecycle import AgentLifecycle
from edc_agent.storage.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("edc_agent.main")


def get_default_db_path() -> Path:
    """Return the default SQLite database path (~/.edc/agent.db)."""
    db_dir = Path.home() / ".edc"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "agent.db"


def run_agent(
    config_path: Optional[str] = None,
    db_path: Optional[str] = None,
    window_minutes: int = 15,
) -> int:
    """Run the EDC agent in the foreground with live status line until interrupted."""
    cfg = load_config(override_path=config_path)
    database_path = Path(db_path) if db_path else get_default_db_path()

    lifecycle = AgentLifecycle(
        config=cfg,
        window_minutes=window_minutes,
        db_path=database_path,
    )

    stop_event = threading.Event()

    def _sig_handler(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    lifecycle.start()

    sys.stdout.write("======================================================================\n")
    sys.stdout.write("  Employee Data Collector (EDC) Desktop Agent v0.1.0\n")
    sys.stdout.write(f"  Timezone: {lifecycle.config.timezone} | Shift: {lifecycle.config.shift_start}-{lifecycle.config.shift_end}\n")
    sys.stdout.write(f"  Storage:  {lifecycle.db.db_path}\n")
    sys.stdout.write("  Press Ctrl+C to stop collection gracefully\n")
    sys.stdout.write("======================================================================\n")
    sys.stdout.flush()

    try:
        while not stop_event.is_set():
            lifecycle.tick()
            status_line = lifecycle.get_status_line()
            sys.stdout.write(f"\r{status_line}")
            sys.stdout.flush()
            stop_event.wait(timeout=1.0)
    finally:
        sys.stdout.write("\n[EDC] Initiating graceful shutdown...\n")
        sys.stdout.flush()
        lifecycle.stop()
        sys.stdout.write("[EDC] Agent stopped successfully.\n")
        sys.stdout.flush()

    return 0


def cmd_pause(db_path: Optional[str] = None) -> int:
    """Command the running agent to pause data collection."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    if not database_path.exists():
        sys.stderr.write(f"[EDC ERROR] Database not found at {database_path}. Is the agent running?\n")
        return 1

    db = Database(database_path)
    db.set_agent_state("command", "pause")
    sys.stdout.write("[EDC] Sent PAUSE command to running agent.\n")
    return 0


def cmd_resume(db_path: Optional[str] = None) -> int:
    """Command the running agent to resume data collection."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    if not database_path.exists():
        sys.stderr.write(f"[EDC ERROR] Database not found at {database_path}. Is the agent running?\n")
        return 1

    db = Database(database_path)
    db.set_agent_state("command", "resume")
    sys.stdout.write("[EDC] Sent RESUME command to running agent.\n")
    return 0


def cmd_status(db_path: Optional[str] = None) -> int:
    """Check and display the current status of the agent from SQLite."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    if not database_path.exists():
        sys.stdout.write("[EDC STATUS: STOPPED] No database found.\n")
        return 0

    db = Database(database_path)
    status = db.get_agent_state("status") or "unknown"
    active_start = db.get_agent_state("active_window_start")
    active_end = db.get_agent_state("active_window_end")
    last_shutdown = db.get_agent_state("last_shutdown")
    win_count = db.get_rollups_15min_count()
    daily_count = db.get_rollups_daily_count()

    sys.stdout.write(f"[EDC STATUS: {status.upper()}]\n")
    if active_start and active_end:
        sys.stdout.write(f"  Current Window: {active_start} to {active_end}\n")
    if last_shutdown:
        sys.stdout.write(f"  Last Shutdown:  {last_shutdown}\n")
    sys.stdout.write(f"  Stored Rollups: {win_count} 15-min windows, {daily_count} daily rollups\n")
    return 0


def main() -> int:
    """CLI parser and dispatch."""
    parser = argparse.ArgumentParser(
        prog="edc",
        description="Employee Data Collector (EDC) Desktop Agent CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Agent commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Start agent collection in foreground")
    run_parser.add_argument("--config", "-c", help="Path to custom TOML config file")
    run_parser.add_argument("--db", help="Path to SQLite database file")
    run_parser.add_argument(
        "--window-minutes",
        type=int,
        default=15,
        help="Window duration in minutes (default: 15)",
    )

    # pause command
    pause_parser = subparsers.add_parser("pause", help="Pause data collection on running agent")
    pause_parser.add_argument("--db", help="Path to SQLite database file")

    # resume command
    resume_parser = subparsers.add_parser("resume", help="Resume data collection on running agent")
    resume_parser.add_argument("--db", help="Path to SQLite database file")

    # status command
    status_parser = subparsers.add_parser("status", help="Inspect agent status in SQLite")
    status_parser.add_argument("--db", help="Path to SQLite database file")

    args, unknown = parser.parse_known_args()

    # Default to 'run' if no subcommand specified
    if args.subcommand is None:
        return run_agent()
    elif args.subcommand == "run":
        return run_agent(
            config_path=args.config,
            db_path=args.db,
            window_minutes=args.window_minutes,
        )
    elif args.subcommand == "pause":
        return cmd_pause(db_path=args.db)
    elif args.subcommand == "resume":
        return cmd_resume(db_path=args.db)
    elif args.subcommand == "status":
        return cmd_status(db_path=args.db)

    parser.print_help()
    return 0


def cli_entrypoint() -> None:
    """Entry point for setuptools console_scripts."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
