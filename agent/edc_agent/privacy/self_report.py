"""Self-report module for voluntary end-of-day employee check-ins and BAT-12 survey.

Implements the Burnout Assessment Tool (BAT-12 short version) with 4 core dimensions:
1. Exhaustion (Items 1-3)
2. Mental Distance / Disengagement (Items 4-6)
3. Emotional Impairment (Items 7-9)
4. Cognitive Impairment (Items 10-12)

Each item is scored on a 1-5 Likert scale (1=Never, 2=Rarely, 3=Sometimes, 4=Often, 5=Always).
Calculates subscale scores, overall BAT-12 score, and clinical cutoff status.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

from edc_agent.storage.database import Database

# BAT-12 Item Definitions from Schaufeli et al.
BAT12_QUESTIONS: List[Dict[str, Any]] = [
    {"id": 1, "key": "bat_q1", "dimension": "exhaustion", "text": "At work, I feel mentally exhausted"},
    {"id": 2, "key": "bat_q2", "dimension": "exhaustion", "text": "After a day at work, I find it hard to recover my energy"},
    {"id": 3, "key": "bat_q3", "dimension": "exhaustion", "text": "At work, I feel physically exhausted"},
    {"id": 4, "key": "bat_q4", "dimension": "mental_distance", "text": "I struggle to find any enthusiasm for my work"},
    {"id": 5, "key": "bat_q5", "dimension": "mental_distance", "text": "I feel a strong aversion towards my job"},
    {"id": 6, "key": "bat_q6", "dimension": "mental_distance", "text": "I'm cynical about what my work means to others"},
    {"id": 7, "key": "bat_q7", "dimension": "emotional_impairment", "text": "At work, I feel unable to control my emotions"},
    {"id": 8, "key": "bat_q8", "dimension": "emotional_impairment", "text": "I do not recognize myself in the way I react emotionally at work"},
    {"id": 9, "key": "bat_q9", "dimension": "emotional_impairment", "text": "At work I may overreact unintentionally"},
    {"id": 10, "key": "bat_q10", "dimension": "cognitive_impairment", "text": "At work, I have trouble staying focused"},
    {"id": 11, "key": "bat_q11", "dimension": "cognitive_impairment", "text": "When I'm working, I have trouble concentrating"},
    {"id": 12, "key": "bat_q12", "dimension": "cognitive_impairment", "text": "I make mistakes in my work because I have my mind on other things"},
]

LIKERT_LABELS = {
    1: "Never",
    2: "Rarely",
    3: "Sometimes",
    4: "Often",
    5: "Always",
}


@dataclass
class BAT12Summary:
    """Aggregated scores for a completed BAT-12 questionnaire."""
    logical_day: str
    items: Dict[str, int]
    exhaustion_score: float
    mental_distance_score: float
    emotional_impairment_score: float
    cognitive_impairment_score: float
    total_bat_score: float
    verified_stressed_day: bool
    clinical_status: str
    category: str = "Low"
    exhaustion_category: str = "Low"
    mental_distance_category: str = "Low"
    emotional_impairment_category: str = "Low"
    cognitive_impairment_category: str = "Low"


def get_bat_percentile_category(score: float, dimension: str = "total") -> str:
    """Map numerical score to percentile category according to official BAT norm tables.
    
    BAT-12 Norm Percentiles (Schaufeli et al.):
    - Low: score < 25th percentile
    - Average: 25th <= score < 75th percentile
    - High: 75th <= score < 95th percentile
    - Very high: score >= 95th percentile
    """
    s = float(score)
    # Norm cutoffs: (p25, p75, p95)
    if dimension in ("exhaustion", "cognitive_impairment", "cognitive"):
        p25, p75, p95 = 1.67, 2.67, 3.67
    elif dimension in ("mental_distance", "emotional_impairment", "emotional"):
        p25, p75, p95 = 1.33, 2.33, 3.33
    else:  # total
        p25, p75, p95 = 1.67, 2.67, 3.65

    if s < p25:
        return "Low"
    elif s < p75:
        return "Average"
    elif s < p95:
        return "High"
    else:
        return "Very high"


def validate_rating(name: str, value: int) -> int:
    """Validate that a self-report rating falls within the 1-5 Likert scale."""
    if not isinstance(value, int) or value < 1 or value > 5:
        raise ValueError(f"{name} rating must be an integer between 1 and 5 (got {value})")
    return value


def compute_bat12_scores(items: Dict[str, int], logical_day: Optional[date] = None) -> BAT12Summary:
    """Compute subscales, total mean, clinical cutoff status, percentile categories, and stress verification flag."""
    day_str = (logical_day or datetime.now(timezone.utc).date()).isoformat()

    # Validate all 12 items
    validated_items: Dict[str, int] = {}
    for i in range(1, 13):
        k = f"bat_q{i}"
        if k not in items:
            raise ValueError(f"Missing required BAT-12 item: {k}")
        validated_items[k] = validate_rating(k, int(items[k]))

    ex_score = (validated_items["bat_q1"] + validated_items["bat_q2"] + validated_items["bat_q3"]) / 3.0
    md_score = (validated_items["bat_q4"] + validated_items["bat_q5"] + validated_items["bat_q6"]) / 3.0
    ei_score = (validated_items["bat_q7"] + validated_items["bat_q8"] + validated_items["bat_q9"]) / 3.0
    ci_score = (validated_items["bat_q10"] + validated_items["bat_q11"] + validated_items["bat_q12"]) / 3.0
    total_score = sum(validated_items.values()) / 12.0

    # Clinical cutoff norms (Schaufeli et al. standard BAT guidelines)
    # < 2.59: Green (low risk)
    # 2.59 - 3.01: Yellow (caution / mild)
    # 3.02 - 3.64: Orange (elevated / warning)
    # >= 3.65: Red (severe burnout risk)
    if total_score >= 3.65:
        clinical_status = "Red"
    elif total_score >= 3.02:
        clinical_status = "Orange"
    elif total_score >= 2.59:
        clinical_status = "Yellow"
    else:
        clinical_status = "Green"

    # Official BAT-12 Percentile Category Mapping:
    # Low (< p25), Average (p25 <= score < p75), High (p75 <= score < p95), Very high (score >= p95)
    cat_total = get_bat_percentile_category(total_score, "total")
    cat_ex = get_bat_percentile_category(ex_score, "exhaustion")
    cat_md = get_bat_percentile_category(md_score, "mental_distance")
    cat_ei = get_bat_percentile_category(ei_score, "emotional_impairment")
    cat_ci = get_bat_percentile_category(ci_score, "cognitive_impairment")

    # Daily verified stress flag: True if total >= 3.02 or exhaustion >= 3.33
    is_stressed = bool(total_score >= 3.02 or ex_score >= 3.33)

    return BAT12Summary(
        logical_day=day_str,
        items=validated_items,
        exhaustion_score=round(ex_score, 3),
        mental_distance_score=round(md_score, 3),
        emotional_impairment_score=round(ei_score, 3),
        cognitive_impairment_score=round(ci_score, 3),
        total_bat_score=round(total_score, 3),
        verified_stressed_day=is_stressed,
        clinical_status=clinical_status,
        category=cat_total,
        exhaustion_category=cat_ex,
        mental_distance_category=cat_md,
        emotional_impairment_category=cat_ei,
        cognitive_impairment_category=cat_ci,
    )


def record_bat12_checkin(
    db: Database,
    logical_day: date,
    items: Dict[str, int],
) -> BAT12Summary:
    """Store complete BAT-12 questionnaire response in SQLite self_reports."""
    summary = compute_bat12_scores(items=items, logical_day=logical_day)
    now_utc = datetime.now(timezone.utc).isoformat()
    day_iso = logical_day.isoformat()

    payload = asdict(summary)
    db.insert_self_report(ts_utc=now_utc, label="bat12", value=json.dumps(payload))

    # Also insert indexed summary key for fast joins
    db.insert_self_report(ts_utc=now_utc, label=f"bat12:{day_iso}:total", value=str(summary.total_bat_score))
    db.insert_self_report(ts_utc=now_utc, label=f"bat12:{day_iso}:status", value=summary.clinical_status)
    db.insert_self_report(ts_utc=now_utc, label=f"bat12:{day_iso}:stressed", value="1" if summary.verified_stressed_day else "0")

    return summary


def get_bat12_for_day(db: Database, logical_day: date) -> Optional[BAT12Summary]:
    """Retrieve BAT-12 record for a given day, if completed."""
    day_iso = logical_day.isoformat()
    rows = db.get_self_reports()
    for row in reversed(rows):
        if row["label"] == "bat12":
            try:
                data = json.loads(row["value"])
                if data.get("logical_day") == day_iso:
                    return BAT12Summary(**data)
            except Exception:
                continue
    return None


def get_all_bat12_by_day(db: Database) -> Dict[str, BAT12Summary]:
    """Retrieve all BAT-12 records mapped by logical_day YYYY-MM-DD."""
    results: Dict[str, BAT12Summary] = {}
    rows = db.get_self_reports()
    for row in rows:
        if row["label"] == "bat12":
            try:
                data = json.loads(row["value"])
                d_str = data.get("logical_day")
                if d_str:
                    results[d_str] = BAT12Summary(**data)
            except Exception:
                continue
    return results


def prompt_bat12_checkin(
    db: Database,
    logical_day: Optional[date] = None,
    ratings: Optional[Dict[str, int]] = None,
    skip: bool = False,
) -> Optional[BAT12Summary]:
    """Prompt the user for end-of-day BAT-12 check-in.

    Supports direct ratings dictionary (for automated testing or UI submission)
    or interactive terminal prompting.
    """
    target_day = logical_day or datetime.now(timezone.utc).date()

    if skip:
        sys.stdout.write("[EDC] BAT-12 check-in skipped.\n")
        sys.stdout.flush()
        return None

    if ratings is not None:
        summary = record_bat12_checkin(db, target_day, items=ratings)
        sys.stdout.write(
            f"[EDC] BAT-12 recorded for {target_day.isoformat()}: "
            f"score={summary.total_bat_score:.2f} ({summary.clinical_status})\n"
        )
        sys.stdout.flush()
        return summary

    sys.stdout.write("\n" + "=" * 75 + "\n")
    sys.stdout.write(f"     END-OF-DAY BURNOUT ASSESSMENT (BAT-12) - {target_day.isoformat()}\n")
    sys.stdout.write("  Instruction: How often has each statement applied to you today?\n")
    sys.stdout.write("  Scoring: 1=Never | 2=Rarely | 3=Sometimes | 4=Often | 5=Always\n")
    sys.stdout.write("  Press Enter on any prompt to skip without submitting.\n")
    sys.stdout.write("=" * 75 + "\n")
    sys.stdout.flush()

    items: Dict[str, int] = {}
    try:
        for q in BAT12_QUESTIONS:
            prompt_str = f"[{q['id']}/12] {q['text']}\n  (1=Never, 2=Rarely, 3=Sometimes, 4=Often, 5=Always): "
            sys.stdout.write(prompt_str)
            sys.stdout.flush()
            val_input = sys.stdin.readline().strip()
            if not val_input:
                sys.stdout.write("[EDC] BAT-12 check-in skipped.\n")
                return None
            val = int(val_input)
            if val < 1 or val > 5:
                sys.stdout.write("Invalid rating (must be 1-5). Check-in cancelled.\n")
                return None
            items[q["key"]] = val

        summary = record_bat12_checkin(db, target_day, items=items)
        sys.stdout.write("\n" + "-" * 75 + "\n")
        sys.stdout.write(f"  BAT-12 Check-in Complete for {target_day.isoformat()}:\n")
        sys.stdout.write(f"  - Exhaustion Subscale:          {summary.exhaustion_score:.2f} / 5.0\n")
        sys.stdout.write(f"  - Mental Distance Subscale:     {summary.mental_distance_score:.2f} / 5.0\n")
        sys.stdout.write(f"  - Emotional Impairment:         {summary.emotional_impairment_score:.2f} / 5.0\n")
        sys.stdout.write(f"  - Cognitive Impairment:         {summary.cognitive_impairment_score:.2f} / 5.0\n")
        sys.stdout.write(f"  - Total Overall Score:          {summary.total_bat_score:.2f} / 5.0\n")
        sys.stdout.write(f"  - Status Category:              {summary.clinical_status}\n")
        sys.stdout.write(f"  - Day Stress Verified:          {'YES (Elevated)' if summary.verified_stressed_day else 'NO (Normal)'}\n")
        sys.stdout.write("-" * 75 + "\n")
        sys.stdout.flush()
        return summary
    except (ValueError, EOFError, KeyboardInterrupt):
        sys.stdout.write("\n[EDC] Check-in cancelled.\n")
        sys.stdout.flush()
        return None


# Legacy 3-item check-in functions for backwards compatibility
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

    payload = {
        "logical_day": day_iso,
        "stress": stress_val,
        "energy": energy_val,
        "workload": workload_val,
    }
    db.insert_self_report(ts_utc=now_utc, label="checkin", value=json.dumps(payload))
    db.insert_self_report(ts_utc=now_utc, label=f"checkin:{day_iso}:stress", value=str(stress_val))
    db.insert_self_report(ts_utc=now_utc, label=f"checkin:{day_iso}:energy", value=str(energy_val))
    db.insert_self_report(ts_utc=now_utc, label=f"checkin:{day_iso}:workload", value=str(workload_val))


def get_checkin_for_day(db: Database, logical_day: date) -> Optional[Dict[str, int]]:
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
    target_day = logical_day or datetime.now(timezone.utc).date()
    if skip:
        return False
    if ratings is not None:
        s, e, w = ratings
        record_checkin(db, target_day, stress=s, energy=e, workload=w)
        return True
    return False
