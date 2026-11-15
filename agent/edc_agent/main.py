"""Main entry point and CLI commands for the Employee Data Collector (EDC) desktop agent.

Supports running foreground collection, pausing/resuming, checking status,
privacy notice consent, voluntary daily check-ins, registry-compliant CSV export,
and full data deletion upon confirmation.
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
from edc_agent.logging_config import setup_logging
from edc_agent.privacy.consent import has_consent, prompt_for_consent, record_consent
from edc_agent.privacy.delete import delete_all_data
from edc_agent.privacy.export import export_data_to_csv
from edc_agent.privacy.self_report import prompt_checkin, record_checkin
from edc_agent.storage.database import Database

setup_logging()
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
    auto_consent: bool = False,
) -> int:
    """Run the EDC agent in the foreground with live status line until interrupted."""
    cfg = load_config(override_path=config_path)
    database_path = Path(db_path) if db_path else get_default_db_path()

    db = Database(database_path)

    # Consent check: No collection before acknowledgement!
    if not has_consent(db):
        sys.stdout.write("[EDC] Privacy disclosure notice has not been acknowledged.\n")
        accepted = prompt_for_consent(db, auto_ack=auto_consent)
        if not accepted:
            sys.stderr.write("[EDC ERROR] Collection aborted: user consent was declined.\n")
            return 1

    lifecycle = AgentLifecycle(
        config=cfg,
        window_minutes=window_minutes,
        db=db,
        require_consent=True,
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
    consent = has_consent(db)

    sys.stdout.write(f"[EDC STATUS: {status.upper()}]\n")
    sys.stdout.write(f"  Consent Status: {'Consented' if consent else 'Not Consented'}\n")
    if active_start and active_end:
        sys.stdout.write(f"  Current Window: {active_start} to {active_end}\n")
    if last_shutdown:
        sys.stdout.write(f"  Last Shutdown:  {last_shutdown}\n")
    sys.stdout.write(f"  Stored Rollups: {win_count} 15-min windows, {daily_count} daily rollups\n")
    return 0


def cmd_consent(db_path: Optional[str] = None, auto_ack: bool = False) -> int:
    """Show the plain-language privacy notice and record acknowledgement."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    db = Database(database_path)
    accepted = prompt_for_consent(db, auto_ack=auto_ack)
    return 0 if accepted else 1


def cmd_checkin(
    db_path: Optional[str] = None,
    stress: Optional[int] = None,
    energy: Optional[int] = None,
    workload: Optional[int] = None,
    skip: bool = False,
) -> int:
    """Run the voluntary end-of-day check-in (1-5 Likert scales)."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    db = Database(database_path)

    ratings = (stress, energy, workload) if (stress and energy and workload) else None
    prompt_checkin(db, ratings=ratings, skip=skip)
    return 0


def cmd_export_data(
    db_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    prefix: str = "edc_export",
) -> int:
    """Export 15-minute and daily rollups joined with self-report labels to CSV."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    if not database_path.exists():
        sys.stderr.write(f"[EDC ERROR] Database not found at {database_path}.\n")
        return 1

    db = Database(database_path)
    out_dir = Path(output_dir) if output_dir else Path(".")
    f_15min, f_daily = export_data_to_csv(db, output_dir=out_dir, prefix=prefix)

    sys.stdout.write(f"[EDC] Exported 15-minute features to: {f_15min.resolve()}\n")
    sys.stdout.write(f"[EDC] Exported daily features to:     {f_daily.resolve()}\n")
    return 0


def cmd_delete_all_data(db_path: Optional[str] = None, confirmed: bool = False) -> int:
    """Permanently wipe all local data from SQLite upon confirmation."""
    database_path = Path(db_path) if db_path else get_default_db_path()
    if not database_path.exists():
        sys.stdout.write("[EDC] Database does not exist. Nothing to delete.\n")
        return 0

    db = Database(database_path)
    deleted = delete_all_data(db, confirmed=confirmed)
    return 0 if deleted else 1


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
    run_parser.add_argument(
        "--auto-consent",
        action="store_true",
        help="Automatically acknowledge privacy notice (non-interactive mode)",
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

    # consent command
    consent_parser = subparsers.add_parser("consent", help="Show privacy notice and acknowledge consent")
    consent_parser.add_argument("--db", help="Path to SQLite database file")
    consent_parser.add_argument("--yes", "-y", action="store_true", help="Acknowledge notice automatically")

    # check-in command
    checkin_parser = subparsers.add_parser("check-in", help="Submit end-of-day stress/energy/workload check-in")
    checkin_parser.add_argument("--db", help="Path to SQLite database file")
    checkin_parser.add_argument("--stress", type=int, choices=[1, 2, 3, 4, 5], help="Stress level (1-5)")
    checkin_parser.add_argument("--energy", type=int, choices=[1, 2, 3, 4, 5], help="Energy level (1-5)")
    checkin_parser.add_argument("--workload", type=int, choices=[1, 2, 3, 4, 5], help="Workload level (1-5)")
    checkin_parser.add_argument("--skip", action="store_true", help="Skip check-in without recording")

    # export-data command
    export_parser = subparsers.add_parser("export-data", help="Export features joined with labels to CSV")
    export_parser.add_argument("--db", help="Path to SQLite database file")
    export_parser.add_argument("--output-dir", "-o", default=".", help="Directory to save CSV files")
    export_parser.add_argument("--prefix", default="edc_export", help="CSV filename prefix")

    # delete-all-data command
    delete_parser = subparsers.add_parser("delete-all-data", help="Permanently delete all local data")
    delete_parser.add_argument("--db", help="Path to SQLite database file")
    delete_parser.add_argument("--yes", "-y", action="store_true", help="Confirm deletion non-interactively")

    args, unknown = parser.parse_known_args()

    # Default to 'run' if no subcommand specified
    if args.subcommand is None:
        return run_agent()
    elif args.subcommand == "run":
        return run_agent(
            config_path=args.config,
            db_path=args.db,
            window_minutes=args.window_minutes,
            auto_consent=getattr(args, "auto_consent", False),
        )
    elif args.subcommand == "pause":
        return cmd_pause(db_path=args.db)
    elif args.subcommand == "resume":
        return cmd_resume(db_path=args.db)
    elif args.subcommand == "status":
        return cmd_status(db_path=args.db)
    elif args.subcommand == "consent":
        return cmd_consent(db_path=args.db, auto_ack=getattr(args, "yes", False))
    elif args.subcommand == "check-in":
        return cmd_checkin(
            db_path=args.db,
            stress=args.stress,
            energy=args.energy,
            workload=args.workload,
            skip=args.skip,
        )
    elif args.subcommand == "export-data":
        return cmd_export_data(
            db_path=args.db,
            output_dir=args.output_dir,
            prefix=args.prefix,
        )
    elif args.subcommand == "delete-all-data":
        return cmd_delete_all_data(
            db_path=args.db,
            confirmed=getattr(args, "yes", False),
        )

    parser.print_help()
    return 0


def cli_entrypoint() -> None:
    """Entry point for setuptools console_scripts."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
