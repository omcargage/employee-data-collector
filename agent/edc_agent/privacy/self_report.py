"""Self-report module for voluntary end-of-day employee check-ins.

Captures 1-5 Likert scale ratings for stress, energy, and workload, mapped to a logical day.
Stores responses in SQLite self_reports for export alongside behavioural features.
"""
from datetime import date, datetime, timezone
import json
from typing import Dict, Optional, Tuple
import sys

from edc_agent.storage.database import Database


def validate_rating(name: str, value: int) -> int:
    """Validate that a self-report rating falls within the 1-5 Likert scale."""
    if not isinstance(value, int) or value < 1 or value > 5:
        raise ValueError(f"{name} rating must be an integer between 1 and 5 (got {value})")
    return value


def record_checkin(
    db: Database,
    logical_day: date,
    stress: int,
    energy: int,
    workload: int,
) -> None:
    """Validate and store daily check-in ratings in self_reports."""
    stress_val = validate_rating("stress", stress)
    energy_val = validate_rating("energy", energy)
    workload_val = validate_rating("workload", workload)

    now_utc = datetime.now(timezone.utc).isoformat()
    day_iso = logical_day.isoformat()

    # Store combined check-in payload
    payload = {
        "logical_day": day_iso,
        "stress": stress_val,
        "energy": energy_val,
        "workload": workload_val,
    }
    db.insert_self_report(ts_utc=now_utc, label="checkin", value=json.dumps(payload))

    # Store individual label rows for flexible queries
    db.insert_self_report(ts_utc=now_utc, label=f"checkin:{day_iso}:stress", value=str(stress_val))
    db.insert_self_report(ts_utc=now_utc, label=f"checkin:{day_iso}:energy", value=str(energy_val))
    db.insert_self_report(ts_utc=now_utc, label=f"checkin:{day_iso}:workload", value=str(workload_val))


def get_checkin_for_day(db: Database, logical_day: date) -> Optional[Dict[str, int]]:
    """Retrieve the check-in ratings for a specific logical day, if present."""
    day_iso = logical_day.isoformat()
    rows = db.get_self_reports()
    for row in reversed(rows):
        if row["label"] == "checkin":
            try:
                data = json.loads(row["value"])
                if data.get("logical_day") == day_iso:
                    return {
                        "stress": int(data["stress"]),
                        "energy": int(data["energy"]),
                        "workload": int(data["workload"]),
                    }
            except Exception:
                continue
    return None


def get_all_checkins_by_day(db: Database) -> Dict[str, Dict[str, int]]:
    """Retrieve all check-ins mapped by logical_day string YYYY-MM-DD."""
    results: Dict[str, Dict[str, int]] = {}
    rows = db.get_self_reports()
    for row in rows:
        if row["label"] == "checkin":
            try:
                data = json.loads(row["value"])
                d_str = data.get("logical_day")
                if d_str:
                    results[d_str] = {
                        "stress": int(data["stress"]),
                        "energy": int(data["energy"]),
                        "workload": int(data["workload"]),
                    }
            except Exception:
                continue
    return results


def prompt_checkin(
    db: Database,
    logical_day: Optional[date] = None,
    ratings: Optional[Tuple[int, int, int]] = None,
    skip: bool = False,
) -> bool:
    """Prompt the user for an end-of-day check-in. Skippable on empty input.

    Returns True if submitted, False if skipped.
    """
    target_day = logical_day or datetime.now(timezone.utc).date()

    if skip:
        sys.stdout.write("[EDC] End-of-day check-in skipped.\n")
        sys.stdout.flush()
        return False

    if ratings is not None:
        s, e, w = ratings
        record_checkin(db, target_day, stress=s, energy=e, workload=w)
        sys.stdout.write(f"[EDC] Check-in for {target_day.isoformat()} recorded: stress={s}, energy={e}, workload={w}.\n")
        sys.stdout.flush()
        return True

    sys.stdout.write("\n======================================================================\n")
    sys.stdout.write(f"           END-OF-DAY CHECK-IN ({target_day.isoformat()})\n")
    sys.stdout.write("  Rate each item on a 1-5 scale (1=Lowest, 5=Highest).\n")
    sys.stdout.write("  Press Enter on any prompt to skip without submitting.\n")
    sys.stdout.write("======================================================================\n")
    sys.stdout.flush()

    try:
        sys.stdout.write("1. Stress level (1-5, Enter to skip): ")
        sys.stdout.flush()
        s_input = sys.stdin.readline().strip()
        if not s_input:
            sys.stdout.write("[EDC] Check-in skipped.\n")
            return False
        stress = int(s_input)

        sys.stdout.write("2. Energy level (1-5, Enter to skip): ")
        sys.stdout.flush()
        e_input = sys.stdin.readline().strip()
        if not e_input:
            sys.stdout.write("[EDC] Check-in skipped.\n")
            return False
        energy = int(e_input)

        sys.stdout.write("3. Workload level (1-5, Enter to skip): ")
        sys.stdout.flush()
        w_input = sys.stdin.readline().strip()
        if not w_input:
            sys.stdout.write("[EDC] Check-in skipped.\n")
            return False
        workload = int(w_input)

        record_checkin(db, target_day, stress=stress, energy=energy, workload=workload)
        sys.stdout.write(f"[EDC] Thank you! Check-in recorded for {target_day.isoformat()}.\n")
        sys.stdout.flush()
        return True
    except (ValueError, EOFError, KeyboardInterrupt):
        sys.stdout.write("\n[EDC] Check-in skipped.\n")
        sys.stdout.flush()
        return False
