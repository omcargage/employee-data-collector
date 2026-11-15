"""Data wiping utility for permanently deleting all local EDC data upon confirmation.

Clears all rollups, queues, self-reports, consent records, and agent states from SQLite.
"""
from pathlib import Path
from typing import Optional, Union
import sys

from edc_agent.storage.database import Database


def delete_all_data(db: Database, confirmed: bool = False) -> bool:
    """Wipe all local data from SQLite after explicit confirmation.

    Returns True if data was wiped, False if operation was cancelled.
    """
    if not confirmed:
        sys.stdout.write("======================================================================\n")
        sys.stdout.write("  WARNING: PERMANENT DATA DELETION REQUESTED\n")
        sys.stdout.write("  This will wipe ALL local rollups, self-reports, audit logs, and\n")
        sys.stdout.write("  consent records from the local SQLite database.\n")
        sys.stdout.write("  This action CANNOT be undone.\n")
        sys.stdout.write("======================================================================\n")
        sys.stdout.write("Type 'DELETE' to confirm and permanently erase all data: ")
        sys.stdout.flush()

        try:
            user_input = sys.stdin.readline().strip()
            if user_input != "DELETE":
                sys.stdout.write("[EDC] Data deletion cancelled.\n")
                sys.stdout.flush()
                return False
        except (OSError, EOFError, KeyboardInterrupt):
            sys.stdout.write("\n[EDC] Data deletion cancelled.\n")
            sys.stdout.flush()
            return False

    db.clear_all_data()
    sys.stdout.write("[EDC] All local data wiped successfully.\n")
    sys.stdout.flush()
    return True
