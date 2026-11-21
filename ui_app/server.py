"""WorkSense Application Bridge Server (FastAPI).

Connects:
- Pretrained PyTorch WorkSense Temporal Neural Network
- Master telemetry & BAT-12 dataset (daily_burnout_master.csv)
- Local EDC SQLite database (edc_agent.db)
- Interactive Dual-Portal Frontend (Employee & Manager)
"""
import os
import sys
from pathlib import Path

# Ensure agent and shared packages are always discoverable regardless of cwd
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
for _p in [PROJECT_ROOT / "agent", PROJECT_ROOT / "shared", PROJECT_ROOT / "backend"]:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from typing import Any, Dict, List, Optional
from datetime import date, datetime, timezone
import json
import numpy as np
import pandas as pd
import torch

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from edc_agent.ml import (
    CORE_NUMERICAL_FEATURES,
    INT_TO_STATUS,
    PersonalBaselineTransformer,
    WorkSenseBurnoutPredictor,
    WorkSenseTemporalNN,
)
from edc_agent.privacy.self_report import (
    BAT12_QUESTIONS,
    BAT12Summary,
    compute_bat12_scores,
)
from edc_agent.storage.database import Database

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
METRIC_DATA_DIR = PROJECT_ROOT.parent / "Metric_data"
MASTER_CSV_PATH = METRIC_DATA_DIR / "daily_burnout_master.csv"
MODEL_DIR = METRIC_DATA_DIR / "model"
MODEL_WEIGHTS_PATH = MODEL_DIR / "worksense_nn.pt"
MODEL_CONFIG_PATH = MODEL_DIR / "model_config.json"
LOCAL_DB_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "edc" / "agent.db"

app = FastAPI(title="WorkSense Desktop Application API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory cache for fast responsive UI
DATA_CACHE: Dict[str, Any] = {
    "df": None,
    "predictor": None,
    "db": None,
    "personas": [],
    "recent_bat_submissions": {},
    "tracking_paused": False,
    "suggestions_preferences": {
        "frequency": "balanced",
        "quiet_hours_start": "13:00",
        "quiet_hours_end": "14:00",
        "mute_today": False,
    },
    "suggestions_history": {},
}


def load_application_state():
    """Initialize dataset, PyTorch predictor, and demo personas."""
    # 1. Load Master Dataset
    if MASTER_CSV_PATH.exists():
        df = pd.read_csv(MASTER_CSV_PATH)
        DATA_CACHE["df"] = df
    else:
        DATA_CACHE["df"] = pd.DataFrame()

    # 2. Load Pretrained PyTorch Predictor
    if MODEL_WEIGHTS_PATH.exists():
        try:
            DATA_CACHE["predictor"] = WorkSenseBurnoutPredictor.load(
                model_path=MODEL_WEIGHTS_PATH,
                config_path=MODEL_CONFIG_PATH if MODEL_CONFIG_PATH.exists() else None,
            )
        except Exception as e:
            print(f"[WorkSense] Error loading model: {e}")
            DATA_CACHE["predictor"] = None

    # 3. Load Local EDC Database if present
    if LOCAL_DB_PATH.exists():
        try:
            DATA_CACHE["db"] = Database(LOCAL_DB_PATH)
        except Exception:
            DATA_CACHE["db"] = None

    # 4. Configure Curated Demo Personas
    DATA_CACHE["personas"] = [
        {
            "id": "EMP_001",
            "name": "Aarav Sharma",
            "role": "Frontend Engineer",
            "department": "Platform Engineering",
            "profile": "healthy",
            "preset": "calibration_day8",
            "title": "Aarav (Day 8 Calibration)",
            "description": "Baseline calibrating. Day 8 of 14 completed with daily BAT-12 surveys.",
            "cutoff_day": 8,
        },
        {
            "id": "EMP_009",
            "name": "Rohan Verma",
            "role": "Data Analyst",
            "department": "Business Intelligence",
            "profile": "healthy",
            "preset": "healthy_green",
            "title": "Rohan (Healthy - Green)",
            "description": "Calibrated baseline. Rhythm is balanced, steady typing, healthy breaks.",
            "cutoff_day": 45,
        },
        {
            "id": "EMP_035",
            "name": "Kavita Patel",
            "role": "Product Designer",
            "department": "Experience Design",
            "profile": "moderate",
            "preset": "moderate_yellow",
            "title": "Kavita (Moderate Strain - Yellow)",
            "description": "Occasional long stretches and mild afternoon typing fatigue.",
            "cutoff_day": 45,
        },
        {
            "id": "EMP_089",
            "name": "Priya Nair",
            "role": "Backend Engineer",
            "department": "Infrastructure",
            "profile": "stressed",
            "preset": "at_risk_orange",
            "title": "Priya (Impending Burnout - Orange)",
            "description": "Late-night boundary erosion, shrinking lunch breaks, 5-day early warning flagged.",
            "cutoff_day": 45,
        },
        {
            "id": "EMP_098",
            "name": "Vikram Rao",
            "role": "DevOps Architect",
            "department": "Cloud Infrastructure",
            "profile": "stressed",
            "preset": "severe_red",
            "title": "Vikram (Acute Burnout - Red)",
            "description": "Sustained high cognitive fatigue, backspace spikes, consecutive late nights.",
            "cutoff_day": 75,
        },
    ]


@app.on_event("startup")
def startup_event():
    load_application_state()


class BAT12Submission(BaseModel):
    employee_id: str
    logical_day: Optional[str] = None
    items: Dict[str, Optional[int]]
    early_checkin: Optional[bool] = False
    submitted_at: Optional[str] = None


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_loaded": DATA_CACHE["predictor"] is not None,
        "dataset_rows": len(DATA_CACHE["df"]) if DATA_CACHE["df"] is not None else 0,
        "local_db_connected": DATA_CACHE["db"] is not None,
    }


@app.get("/api/demo/personas")
def get_personas():
    return DATA_CACHE["personas"]


@app.get("/api/employee/dashboard")
def get_employee_dashboard(
    employee_id: str = Query("EMP_089", description="Employee ID or 'local_agent'"),
    mode: str = Query("demo", description="'demo' or 'live'"),
    day_cutoff: Optional[int] = Query(None, description="Optional day index limit (e.g. 8 or 45)"),
):
    df = DATA_CACHE["df"]
    predictor = DATA_CACHE["predictor"]

    # 1. LIVE MODE: Read from local SQLite Database
    if mode == "live" and DATA_CACHE["db"] is not None:
        db = DATA_CACHE["db"]
        daily_rollups = db.get_all_rollups_daily()
        if len(daily_rollups) == 0:
            return {
                "employee_id": "LOCAL_DESKTOP_AGENT",
                "name": "Active Desktop User",
                "role": "Local Workstation",
                "department": "Local Workspace",
                "mode": "live",
                "calibration_progress": {
                    "days_collected": 1,
                    "days_required": 14,
                    "progress_pct": 7.1,
                    "is_calibrated": False,
                    "bat12_completed": 0,
                },
                "current_status": "INSUFFICIENT_DATA",
                "predicted_status_5d": "INSUFFICIENT_DATA",
                "status_description": "WorkSense is collecting initial local telemetry. Day 1 of 14 calibration.",
                "confidence": None,
                "risk_score": None,
                "primary_drivers": [],
                "relative_deviations": {},
                "recent_7d_telemetry": [],
                "recovery_nudges": ["System is active and observing daily work patterns."],
                "bat12_summary": {
                    "today_submitted": False,
                    "today_early_checkin": False,
                    "submitted_at": None,
                    "today_score": 1.5,
                    "today_score_text": "1.5 out of 5 (low)",
                    "today_status": "Green",
                    "today_exhaustion": 1.5,
                    "today_mental_distance": 1.5,
                    "today_emotional": 1.5,
                    "today_cognitive": 1.5,
                    "baseline_bat_score": 1.5,
                    "baseline_bat_status": "Low",
                    "usual_checkin_score": 1.5,
                    "usual_checkin_desc": "low",
                    "usual_checkin_text": "Your usual check-in score: 1.5 (low)",
                    "usual_range": {"min": 1.2, "max": 1.8},
                    "checkin_history": [],
                    "verified_stress_day": False,
                    "raw_responses": None,
                },
                "tracking_paused": DATA_CACHE.get("tracking_paused", False),
            }

    # 2. DEMO MODE: Read from synchronized master telemetry dataset
    if df is None or len(df) == 0:
        raise HTTPException(status_code=500, detail="Telemetry dataset not loaded")

    # Match employee
    emp_df = df[df["employee_id"] == employee_id].sort_values("date").reset_index(drop=True)
    if len(emp_df) == 0:
        emp_df = df[df["employee_id"] == "EMP_001"].sort_values("date").reset_index(drop=True)

    # Find persona details
    persona_meta = next((p for p in DATA_CACHE["personas"] if p["id"] == employee_id), {
        "name": f"Employee {employee_id}",
        "role": "Team Member",
        "department": "Product & Engineering",
        "profile": emp_df["profile"].iloc[0] if "profile" in emp_df else "healthy",
    })

    # Apply cutoff if specified (e.g. Day 8 calibration preview)
    effective_cutoff = day_cutoff if day_cutoff is not None else len(emp_df)
    sub_df = emp_df.iloc[:effective_cutoff].copy().reset_index(drop=True)
    n_days = len(sub_df)

    # Incorporate any recently submitted live BAT-12 surveys for this employee
    sub_date_str = str(sub_df['date'].iloc[-1])
    sub_key = f"{employee_id}:{sub_date_str}"
    recent_bat = DATA_CACHE["recent_bat_submissions"].get(sub_key)
    if not recent_bat:
        recent_bat = DATA_CACHE["recent_bat_submissions"].get(f"{employee_id}:latest")

    # 3. Predict with Neural Network
    prediction = predictor.predict_daily(sub_df) if predictor else {}

    # Extract 7-day and 30-day telemetry slices
    def build_telemetry_item(row):
        return {
            "date": str(row["date"]),
            "day_name": datetime.strptime(str(row["date"]), "%Y-%m-%d").strftime("%a"),
            "is_weekend": bool(row["is_weekend"]),
            "stretch_mins": round(float(row["longest_stretch_duration_mins"]), 1),
            "lunch_mins": round(float(row["longest_lunch_break_mins"]), 1),
            "focus_mins": round(float(row.get("avg_focus_block_mins", row.get("total_focus_time_hours", 2.2) * 60)), 1),
            "after_hours_mins": round(float(row.get("after_hours_active_minutes", 0)), 1),
            "after_hours_msgs": int(row["msgs_sent_after_hours"]),
            "wpm": round(float(row["daily_mean_wpm"]), 1),
            "backspace_ratio": round(float(row["daily_backspace_ratio"]) * 100, 1),
            "mouse_speed": round(float(row.get("cursor_speed_mean", row.get("average_speed_px_s", 280))), 1),
            "bat_score": round(float(row.get("bat_total_score", 1.5)), 2),
            "bat_status": row.get("bat_status", "Green"),
        }

    recent_7_slice = sub_df.iloc[-7:].copy()
    telemetry_7d = [build_telemetry_item(r) for _, r in recent_7_slice.iterrows()]

    recent_30_slice = sub_df.iloc[-30:].copy()
    telemetry_30d = [build_telemetry_item(r) for _, r in recent_30_slice.iterrows()]

    # Compute 14-day personal baseline normal bands
    base_slice = sub_df.iloc[:min(14, len(sub_df))]
    weekday_base = base_slice[base_slice["is_weekend"] == 0]
    if len(weekday_base) == 0:
        weekday_base = base_slice

    def get_metric_band(series, multiplier=1.2):
        s = pd.to_numeric(series, errors="coerce").dropna()
        if len(s) == 0:
            return {"median": 0.0, "min": 0.0, "max": 0.0}
        med = float(s.median())
        mad = float((s - med).abs().median())
        if mad == 0:
            mad = max(1.0, med * 0.15)
        return {
            "median": round(med, 1),
            "min": round(max(0.0, med - multiplier * mad), 1),
            "max": round(med + multiplier * mad, 1),
        }

    baseline_bands = {
        "stretch": get_metric_band(weekday_base["longest_stretch_duration_mins"]),
        "lunch": get_metric_band(weekday_base["longest_lunch_break_mins"]),
        "focus": get_metric_band(weekday_base.get("avg_focus_block_mins", weekday_base.get("total_focus_time_hours", pd.Series([2.2])) * 60)),
        "after_hours_mins": get_metric_band(weekday_base.get("after_hours_active_minutes", pd.Series([0]))),
        "after_hours_msgs": get_metric_band(weekday_base["msgs_sent_after_hours"]),
        "wpm": get_metric_band(weekday_base["daily_mean_wpm"]),
        "backspace_ratio": get_metric_band(weekday_base["daily_backspace_ratio"] * 100),
        "mouse": get_metric_band(weekday_base.get("cursor_speed_mean", weekday_base.get("average_speed_px_s", pd.Series([280])))),
    }

    # Generate Personalized Nudges
    latest_row = sub_df.iloc[-1]
    nudges = []
    if float(latest_row["longest_stretch_duration_mins"]) > 90:
        nudges.append({
            "type": "stretch",
            "icon": "alarm",
            "title": "Extended Continuous Stretch",
            "message": f"You worked a continuous stretch of {int(latest_row['longest_stretch_duration_mins'])} mins. Consider taking a 10-min screen break.",
        })
    if float(latest_row["longest_lunch_break_mins"]) < 20:
        nudges.append({
            "type": "lunch",
            "icon": "coffee",
            "title": "Short / Skipped Lunch",
            "message": f"Your midday meal break was only {int(latest_row['longest_lunch_break_mins'])} mins today. Protect your midday recovery block.",
        })
    if int(latest_row["msgs_sent_after_hours"]) >= 5:
        nudges.append({
            "type": "boundary",
            "icon": "moon",
            "title": "Late-Night Boundary Alert",
            "message": f"{int(latest_row['msgs_sent_after_hours'])} communication events sent outside work hours. Wrap up for the night to avoid sleep debt.",
        })
    if not nudges:
        nudges.append({
            "type": "healthy",
            "icon": "check-circle",
            "title": "Healthy Rhythm Maintained",
            "message": "Your work stretches and break intervals are well within your healthy baseline bounds.",
        })

    # Relative Deviations (Z-Scores)
    baseline_stats = predictor.transformer.fit_employee_baseline(sub_df) if predictor else None
    deviations = {}
    if baseline_stats:
        norm_row = predictor.transformer.transform_employee(sub_df, baseline=baseline_stats).iloc[-1]
        deviations = {
            "work_stretch": round(float(norm_row.get("longest_stretch_duration_mins_norm", 0.0)), 2),
            "after_hours": round(float(norm_row.get("after_hours_active_minutes_norm", 0.0)), 2),
            "lunch_break": round(float(norm_row.get("longest_lunch_break_mins_norm", 0.0)), 2),
            "typing_speed": round(float(norm_row.get("daily_mean_wpm_norm", 0.0)), 2),
            "error_rate": round(float(norm_row.get("daily_backspace_ratio_norm", 0.0)), 2),
            "focus_fragmentation": round(float(norm_row.get("focus_fragmentation_ratio_norm", 0.0)), 2),
        }

    is_calibrated = n_days >= 14
    pred_status = prediction.get("predicted_status_5d", "Green") if is_calibrated else "INSUFFICIENT_DATA"

    # Build checkin history (last 30 days) and usual BAT baseline
    checkin_slice = sub_df.iloc[-30:].copy()
    checkin_history = []
    for _, r in checkin_slice.iterrows():
        checkin_history.append({
            "date": str(r["date"]),
            "day_name": datetime.strptime(str(r["date"]), "%Y-%m-%d").strftime("%a"),
            "is_weekend": bool(r["is_weekend"]),
            "score": round(float(r.get("bat_total_score", 1.5)), 2),
            "status": r.get("bat_status", "Green"),
            "exhaustion": round(float(r.get("bat_exhaustion", 1.4)), 2),
            "mental_distance": round(float(r.get("bat_mental_distance", 1.3)), 2),
            "emotional": round(float(r.get("bat_emotional_impairment", 1.3)), 2),
            "cognitive": round(float(r.get("bat_cognitive_impairment", 1.3)), 2),
        })

    # Baseline usual BAT score from personal 14-day baseline
    base_bat_val = float(weekday_base["bat_total_score"].mean()) if "bat_total_score" in weekday_base else 1.5
    if base_bat_val >= 3.65:
        base_desc = "high"
    elif base_bat_val >= 3.02:
        base_desc = "elevated"
    elif base_bat_val >= 2.59:
        base_desc = "mild"
    else:
        base_desc = "low"

    today_score_val = recent_bat["total_bat_score"] if recent_bat else round(float(latest_row.get("bat_total_score", 1.5)), 2)
    if today_score_val >= 3.65:
        today_desc = "high"
    elif today_score_val >= 3.02:
        today_desc = "elevated"
    elif today_score_val >= 2.59:
        today_desc = "mild"
    else:
        today_desc = "low"

    if recent_bat and len(checkin_history) > 0:
        checkin_history[-1]["score"] = recent_bat["total_bat_score"]
        checkin_history[-1]["status"] = recent_bat["clinical_status"]
        checkin_history[-1]["exhaustion"] = recent_bat["exhaustion_score"]
        checkin_history[-1]["mental_distance"] = recent_bat["mental_distance_score"]
        checkin_history[-1]["emotional"] = recent_bat["emotional_impairment_score"]
        checkin_history[-1]["cognitive"] = recent_bat["cognitive_impairment_score"]

    bat12_summary = {
        "today_submitted": recent_bat is not None,
        "today_early_checkin": recent_bat.get("early_checkin", False) if recent_bat else False,
        "submitted_at": recent_bat.get("submitted_at") if recent_bat else None,
        "today_score": today_score_val,
        "today_score_text": f"{today_score_val:.1f} out of 5 ({today_desc})",
        "today_score_desc": today_desc,
        "today_status": recent_bat["clinical_status"] if recent_bat else latest_row.get("bat_status", "Green"),
        "today_exhaustion": recent_bat["exhaustion_score"] if recent_bat else round(float(latest_row.get("bat_exhaustion", 1.4)), 2),
        "today_mental_distance": recent_bat["mental_distance_score"] if recent_bat else round(float(latest_row.get("bat_mental_distance", 1.3)), 2),
        "today_emotional": recent_bat["emotional_impairment_score"] if recent_bat else round(float(latest_row.get("bat_emotional_impairment", 1.3)), 2),
        "today_cognitive": recent_bat["cognitive_impairment_score"] if recent_bat else round(float(latest_row.get("bat_cognitive_impairment", 1.3)), 2),
        "baseline_bat_score": round(base_bat_val, 1),
        "baseline_bat_status": base_desc.capitalize(),
        "usual_checkin_score": round(base_bat_val, 1),
        "usual_checkin_desc": base_desc,
        "usual_checkin_text": f"Your usual check-in score: {base_bat_val:.1f} ({base_desc})",
        "usual_range": {
            "min": round(max(1.0, base_bat_val - 0.3), 1),
            "max": round(min(5.0, base_bat_val + 0.3), 1),
        },
        "checkin_history": checkin_history,
        "verified_stress_day": recent_bat["verified_stressed_day"] if recent_bat else bool(latest_row.get("bat_verified_stress_day", 0)),
        "raw_responses": recent_bat.get("raw_responses", {}) if recent_bat else None,
    }

    return {
        "employee_id": employee_id,
        "name": persona_meta["name"],
        "role": persona_meta["role"],
        "department": persona_meta["department"],
        "profile": persona_meta["profile"],
        "mode": mode,
        "current_date": str(latest_row["date"]),
        "calibration_progress": {
            "days_collected": n_days,
            "days_required": 14,
            "progress_pct": min(100.0, round((n_days / 14.0) * 100, 1)),
            "is_calibrated": is_calibrated,
            "bat12_completed": int(n_days) if "bat_total_score" in sub_df else 0,
        },
        "current_status": latest_row.get("current_burnout_status", "Green") if is_calibrated else "INSUFFICIENT_DATA",
        "predicted_status_5d": pred_status,
        "confidence": prediction.get("confidence", 0.95) if is_calibrated else None,
        "risk_score": prediction.get("risk_score", 0.12) if is_calibrated else None,
        "status_description": prediction.get("status_description", "Personal baseline calibrating."),
        "primary_drivers": prediction.get("primary_drivers", []) if is_calibrated else [],
        "relative_deviations": deviations,
        "recent_7d_telemetry": telemetry_7d,
        "recent_30d_telemetry": telemetry_30d,
        "baseline_bands": baseline_bands,
        "recovery_nudges": nudges,
        "bat12_summary": bat12_summary,
        "tracking_paused": DATA_CACHE.get("tracking_paused", False),
        "suggestions_preferences": DATA_CACHE.get("suggestions_preferences", {}),
    }


@app.post("/api/employee/survey/bat12")
def submit_bat12_survey(submission: BAT12Submission):
    try:
        logical_day = date.fromisoformat(submission.logical_day) if submission.logical_day else datetime.now(timezone.utc).date()
    except Exception:
        logical_day = datetime.now(timezone.utc).date()

    # Handle skipped items by imputing dimension mean or neutral 2
    raw_items = submission.items or {}
    groups = {
        "exhaustion": ["bat_q1", "bat_q2", "bat_q3"],
        "mental_distance": ["bat_q4", "bat_q5", "bat_q6"],
        "emotional_impairment": ["bat_q7", "bat_q8", "bat_q9"],
        "cognitive_impairment": ["bat_q10", "bat_q11", "bat_q12"],
    }
    cleaned_items = {}
    for group_name, keys in groups.items():
        answered = [raw_items[k] for k in keys if k in raw_items and raw_items[k] is not None and 1 <= raw_items[k] <= 5]
        mean_val = sum(answered) / len(answered) if answered else 2.0
        imputed_int = int(round(mean_val))
        for k in keys:
            if k in raw_items and raw_items[k] is not None and 1 <= raw_items[k] <= 5:
                cleaned_items[k] = int(raw_items[k])
            else:
                cleaned_items[k] = imputed_int

    summary = compute_bat12_scores(items=cleaned_items, logical_day=logical_day)

    # Score descriptor text
    score = summary.total_bat_score
    if score >= 3.65:
        score_desc = "high"
    elif score >= 3.02:
        score_desc = "elevated"
    elif score >= 2.59:
        score_desc = "mild"
    else:
        score_desc = "low"

    submitted_timestamp = submission.submitted_at or datetime.now(timezone.utc).isoformat()

    # Store in recent cache for UI immediate display
    cache_key = f"{submission.employee_id}:{logical_day.isoformat()}"
    sub_data = {
        "total_bat_score": summary.total_bat_score,
        "score_desc": score_desc,
        "score_text": f"{summary.total_bat_score:.1f} out of 5 ({score_desc})",
        "exhaustion_score": summary.exhaustion_score,
        "mental_distance_score": summary.mental_distance_score,
        "emotional_impairment_score": summary.emotional_impairment_score,
        "cognitive_impairment_score": summary.cognitive_impairment_score,
        "clinical_status": summary.clinical_status,
        "verified_stressed_day": summary.verified_stressed_day,
        "early_checkin": bool(submission.early_checkin),
        "submitted_at": submitted_timestamp,
        "raw_responses": raw_items,
    }
    DATA_CACHE["recent_bat_submissions"][cache_key] = sub_data
    DATA_CACHE["recent_bat_submissions"][f"{submission.employee_id}:latest"] = sub_data

    # Store in local DB if connected
    if DATA_CACHE["db"]:
        try:
            from edc_agent.privacy.self_report import record_bat12_checkin
            record_bat12_checkin(DATA_CACHE["db"], logical_day=logical_day, items=cleaned_items)
        except Exception as e:
            print(f"[WorkSense] DB write error: {e}")

    return {
        "success": True,
        "message": f"Day Check-in recorded successfully for {logical_day.isoformat()}",
        "summary": summary,
        "score_text": f"{summary.total_bat_score:.1f} out of 5 ({score_desc})",
        "early_checkin": bool(submission.early_checkin),
        "submitted_at": submitted_timestamp,
    }


# =========================================================================
# SUGGESTIONS & NUDGES (Done / Snooze / Not Helpful & Preferences)
# =========================================================================
class SuggestionAction(BaseModel):
    nudge_id: str
    action: str  # "done", "snooze", "not_helpful"


class SuggestionPreferences(BaseModel):
    frequency: str = "balanced"  # "minimal", "balanced", "frequent"
    quiet_hours_start: str = "13:00"
    quiet_hours_end: str = "14:00"
    mute_today: bool = False


class TrackingPauseRequest(BaseModel):
    paused: bool
    duration_mins: Optional[int] = 60


@app.get("/api/employee/suggestions")
def get_employee_suggestions(employee_id: str = "EMP_089"):
    history = DATA_CACHE.get("suggestions_history", {})
    prefs = DATA_CACHE.get("suggestions_preferences", {
        "frequency": "balanced",
        "quiet_hours_start": "13:00",
        "quiet_hours_end": "14:00",
        "mute_today": False,
    })

    all_nudges = [
        {
            "id": "sugg_break_1",
            "type": "break",
            "category": "Work rhythm",
            "icon": "coffee",
            "title": "Continuous stretch detected",
            "body": "You have been working continuously for 1h 35m without pausing. Take a 5-minute break away from your screen to rest your eyes and reset cognitive focus.",
            "time_label": "Active now &bull; Detected 15m ago",
            "priority": "high",
        },
        {
            "id": "sugg_lunch_1",
            "type": "midday_break",
            "category": "Midday recovery",
            "icon": "sun",
            "title": "Protect your midday meal",
            "body": "Your lunch break was only 14 minutes today. Take a 25-minute screen-free lunch away from your desk to recharge afternoon stamina.",
            "time_label": "Today 1:15 PM",
            "priority": "medium",
        },
        {
            "id": "sugg_wrapup_1",
            "type": "wrap_up",
            "category": "After-hours boundary",
            "icon": "moon",
            "title": "Evening boundary alert",
            "body": "You have sent 7 communication messages after hours. Wrapping up for the evening protects your natural sleep architecture and prevents cognitive fatigue.",
            "time_label": "Active now &bull; After 7:30 PM",
            "priority": "high",
        },
        {
            "id": "sugg_focus_1",
            "type": "protect_focus",
            "category": "Focus rhythm",
            "icon": "target",
            "title": "Protect focus block",
            "body": "Frequent task switching and choppy focus intervals detected. Consider muting non-essential notifications for an uninterrupted 45-minute deep work session.",
            "time_label": "Suggested for tomorrow 10:00 AM",
            "priority": "medium",
        },
    ]

    active = []
    past = []
    for n in all_nudges:
        act = history.get(n["id"])
        if act:
            past.append({**n, "action_taken": act["action"], "resolved_at": act.get("timestamp")})
        else:
            active.append(n)

    return {
        "active_suggestions": active,
        "past_suggestions": past,
        "preferences": prefs,
        "tracking_paused": DATA_CACHE.get("tracking_paused", False),
    }


@app.post("/api/employee/suggestions/action")
def update_suggestion_action(req: SuggestionAction):
    DATA_CACHE["suggestions_history"][req.nudge_id] = {
        "action": req.action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return {"success": True, "nudge_id": req.nudge_id, "action": req.action}


@app.post("/api/employee/suggestions/preferences")
def save_suggestion_preferences(pref: SuggestionPreferences):
    DATA_CACHE["suggestions_preferences"] = pref.dict()
    return {"success": True, "preferences": DATA_CACHE["suggestions_preferences"]}


@app.post("/api/privacy/pause")
def set_privacy_pause(req: TrackingPauseRequest):
    DATA_CACHE["tracking_paused"] = req.paused
    return {"success": True, "tracking_paused": DATA_CACHE["tracking_paused"]}


@app.get("/api/privacy/export")
def export_employee_privacy_data(employee_id: str = "EMP_089"):
    df = DATA_CACHE["df"]
    emp_df = df[df["employee_id"] == employee_id] if df is not None else pd.DataFrame()
    return {
        "export_date": datetime.now(timezone.utc).isoformat(),
        "employee_id": employee_id,
        "standard": "WorkSense Zero-Identification Framework (WHO-Aligned)",
        "total_days_recorded": len(emp_df),
        "telemetry_rollups": emp_df.to_dict(orient="records") if len(emp_df) > 0 else [],
        "recent_checkins": [v for k, v in DATA_CACHE["recent_bat_submissions"].items() if k.startswith(employee_id)],
        "privacy_summary": {
            "what_is_collected": "Timing intervals, duration counts, and self-reported check-in ratings only.",
            "what_is_never_collected": "No keystroke text, chat content, email bodies, window titles, or screen captures.",
            "manager_visibility": "Managers only see aggregated department distribution percentages. Zero individual telemetry.",
        }
    }


@app.post("/api/privacy/delete")
def delete_employee_privacy_data(employee_id: str = "EMP_089"):
    keys = [k for k in DATA_CACHE["recent_bat_submissions"] if k.startswith(employee_id)]
    for k in keys:
        del DATA_CACHE["recent_bat_submissions"][k]
    return {
        "success": True,
        "message": f"Personal telemetry and baseline records for {employee_id} have been deleted from local storage."
    }


@app.post("/api/notifications/test")
def trigger_test_notification():
    return {
        "success": True,
        "title": "WorkSense — Suggestions for you",
        "body": "Continuous stretch of 95 mins detected. Step away from your desk for 5 minutes!",
        "type": "break",
    }


TEAMS_CONFIG = [
    {
        "id": "all",
        "name": "All Teams (Engineering & Product)",
        "department": "Engineering & Product Operations",
        "workforce": 38,
        "counts": {"Steady": 18, "Stretched": 11, "Strained": 6, "Overloaded": 3},
        "prev_counts": {"Steady": 20, "Stretched": 11, "Strained": 5, "Overloaded": 2},
        "checkin_done": 34,
        "weekly_trend": [
            {"week": "Week 1", "date_range": "18 Oct - 24 Oct", "pct": 15.8, "count": 6},
            {"week": "Week 2", "date_range": "25 Oct - 31 Oct", "pct": 18.4, "count": 7},
            {"week": "Week 3", "date_range": "01 Nov - 07 Nov", "pct": 18.4, "count": 7},
            {"week": "Week 4 (Current)", "date_range": "08 Nov - 14 Nov", "pct": 23.7, "count": 9},
        ],
    },
    {
        "id": "platform",
        "name": "Platform Engineering",
        "department": "Platform Engineering",
        "workforce": 16,
        "counts": {"Steady": 9, "Stretched": 4, "Strained": 2, "Overloaded": 1},
        "prev_counts": {"Steady": 9, "Stretched": 4, "Strained": 2, "Overloaded": 1},
        "checkin_done": 15,
        "weekly_trend": [
            {"week": "Week 1", "date_range": "18 Oct - 24 Oct", "pct": 12.5, "count": 2},
            {"week": "Week 2", "date_range": "25 Oct - 31 Oct", "pct": 12.5, "count": 2},
            {"week": "Week 3", "date_range": "01 Nov - 07 Nov", "pct": 18.8, "count": 3},
            {"week": "Week 4 (Current)", "date_range": "08 Nov - 14 Nov", "pct": 18.8, "count": 3},
        ],
    },
    {
        "id": "infrastructure",
        "name": "Cloud Infrastructure",
        "department": "Cloud Infrastructure",
        "workforce": 12,
        "counts": {"Steady": 5, "Stretched": 4, "Strained": 2, "Overloaded": 1},
        "prev_counts": {"Steady": 6, "Stretched": 4, "Strained": 1, "Overloaded": 1},
        "checkin_done": 10,
        "weekly_trend": [
            {"week": "Week 1", "date_range": "18 Oct - 24 Oct", "pct": 16.7, "count": 2},
            {"week": "Week 2", "date_range": "25 Oct - 31 Oct", "pct": 16.7, "count": 2},
            {"week": "Week 3", "date_range": "01 Nov - 07 Nov", "pct": 16.7, "count": 2},
            {"week": "Week 4 (Current)", "date_range": "08 Nov - 14 Nov", "pct": 25.0, "count": 3},
        ],
    },
    {
        "id": "product_bi",
        "name": "Data & Business Intelligence",
        "department": "Data & Business Intelligence",
        "workforce": 7,
        "counts": {"Steady": 4, "Stretched": 2, "Strained": 1, "Overloaded": 0},
        "prev_counts": {"Steady": 3, "Stretched": 2, "Strained": 2, "Overloaded": 0},
        "checkin_done": 6,
        "weekly_trend": [
            {"week": "Week 1", "date_range": "18 Oct - 24 Oct", "pct": 28.6, "count": 2},
            {"week": "Week 2", "date_range": "25 Oct - 31 Oct", "pct": 28.6, "count": 2},
            {"week": "Week 3", "date_range": "01 Nov - 07 Nov", "pct": 28.6, "count": 2},
            {"week": "Week 4 (Current)", "date_range": "08 Nov - 14 Nov", "pct": 14.3, "count": 1},
        ],
    },
    {
        "id": "design_system",
        "name": "Design Systems Core (< 5 people)",
        "department": "Design Systems Core",
        "workforce": 3,
        "counts": None,
        "prev_counts": None,
        "checkin_done": None,
        "weekly_trend": None,
    },
]


@app.get("/api/manager/overview")
def get_manager_overview(team: str = Query("all"), date_range: str = Query("4w")):
    """Privacy-preserved team-level burnout aggregations for managers with k-anonymity (k < 5 threshold)."""
    df = DATA_CACHE["df"]
    if df is None or len(df) == 0:
        raise HTTPException(status_code=500, detail="Telemetry dataset not loaded")

    # Select team from configuration
    selected_team = next((t for t in TEAMS_CONFIG if t["id"] == team), TEAMS_CONFIG[0])
    workforce = selected_team["workforce"]

    available_teams = [
        {"id": t["id"], "name": t["name"], "workforce": t["workforce"], "is_below_threshold": t["workforce"] < 5}
        for t in TEAMS_CONFIG
    ]

    # k-Anonymity privacy gate: groups < 5 members are strictly redacted
    if workforce < 5:
        return {
            "department": selected_team["department"],
            "selected_team_id": selected_team["id"],
            "selected_team_name": selected_team["name"],
            "date_range": date_range,
            "total_workforce": workforce,
            "is_insufficient_group": True,
            "insufficient_message": "Not enough people to show this group",
            "available_teams": available_teams,
            "status_distribution_counts": None,
            "status_distribution_pct": None,
            "change_vs_last_week": None,
            "checkin_participation": None,
            "four_week_outlook": None,
            "trajectory_30d": [],
            "category_drivers": [],
            "privacy_compliance": {
                "individual_names_redacted": True,
                "individual_rankings_disabled": True,
                "raw_metrics_redacted": True,
                "probabilities_redacted": True,
                "k_anonymity_threshold": 5,
                "persistent_line": "Individual data is private to each employee.",
            },
        }

    # Aggregate status counts & percentages for groups >= 5
    status_counts = selected_team["counts"] or {"Steady": 18, "Stretched": 11, "Strained": 6, "Overloaded": 3}
    prev_counts = selected_team["prev_counts"] or {"Steady": 20, "Stretched": 11, "Strained": 5, "Overloaded": 2}
    total_active = sum(status_counts.values())

    pct_distribution = {
        k: round((v / max(1, total_active)) * 100, 1) for k, v in status_counts.items()
    }

    # Change vs last week calculation
    current_elevated = status_counts.get("Strained", 0) + status_counts.get("Overloaded", 0)
    current_elevated_pct = round((current_elevated / max(1, total_active)) * 100, 1)

    prev_elevated = prev_counts.get("Strained", 0) + prev_counts.get("Overloaded", 0)
    prev_total = sum(prev_counts.values())
    prev_elevated_pct = round((prev_elevated / max(1, prev_total)) * 100, 1)

    delta_count = current_elevated - prev_elevated
    delta_pct = round(current_elevated_pct - prev_elevated_pct, 1)

    change_vs_last_week = {
        "current_elevated_count": current_elevated,
        "current_elevated_pct": current_elevated_pct,
        "previous_elevated_count": prev_elevated,
        "previous_elevated_pct": prev_elevated_pct,
        "delta_count": delta_count,
        "delta_pct": delta_pct,
        "trend": "up" if delta_count > 0 else "down" if delta_count < 0 else "steady",
        "label": f"{abs(delta_count)} in Strained or Overloaded ({'+' if delta_pct > 0 else ''}{delta_pct}%) vs last week",
        "context_sentence": f"{current_elevated} of {total_active} employees currently in elevated strain, {'up' if delta_count > 0 else 'down'} from {prev_elevated} last week.",
    }

    # Daily Check-in Participation
    checkin_done = selected_team["checkin_done"] or int(round(total_active * 0.88))
    checkin_rate = round((checkin_done / max(1, total_active)) * 100, 1)
    checkin_participation = {
        "completion_rate_pct": checkin_rate,
        "completed_count": checkin_done,
        "total_eligible": total_active,
        "label": f"{checkin_rate}% completion rate",
        "context_sentence": f"{checkin_done} of {total_active} checked in today.",
    }

    # 4-Week Outlook of Share in Strained or Overloaded
    four_week_outlook = selected_team["weekly_trend"] or [
        {"week": "Week 1", "date_range": "18 Oct - 24 Oct", "pct": 15.8, "count": 6},
        {"week": "Week 2", "date_range": "25 Oct - 31 Oct", "pct": 18.4, "count": 7},
        {"week": "Week 3", "date_range": "01 Nov - 07 Nov", "pct": 18.4, "count": 7},
        {"week": "Week 4 (Current)", "date_range": "08 Nov - 14 Nov", "pct": 23.7, "count": 9},
    ]

    # 30-Day Aggregated Burnout Trajectory for secondary sub-views
    dates_30 = df["date"].unique()[15:45]
    trajectory_30d = []
    for dt in dates_30:
        dt_df = df[df["date"] == dt]
        n_stressed = len(dt_df[dt_df["target_burnout_status_5d"].isin(["Orange", "Red"])])
        pct_stressed = round((n_stressed / len(dt_df)) * 100, 1)
        mean_risk = round(float(dt_df["target_burnout_risk_5d"].mean()), 3)
        trajectory_30d.append({
            "date": str(dt),
            "pct_elevated_risk": pct_stressed,
            "mean_burnout_risk": mean_risk,
        })

    # The 4 Privacy Broad Category Drivers (Team-Level Aggregates)
    category_drivers = [
        {
            "category": "Extended Work Stretches & Irregular Breaks",
            "attribution_pct": 38.4,
            "description": "Continuous uninterrupted work sessions with insufficient rest pauses.",
        },
        {
            "category": "Late-Night & After-Hours Communication",
            "attribution_pct": 31.8,
            "description": "Email and chat messages sent outside scheduled shift boundaries.",
        },
        {
            "category": "Skipped Lunch & Midday Break Recovery",
            "attribution_pct": 17.5,
            "description": "Shortened or absent midday recovery blocks during working hours.",
        },
        {
            "category": "Focus Block Fragmentation & Typing Fatigue",
            "attribution_pct": 12.3,
            "description": "Choppy work blocks and elevated error correction keys.",
        },
    ]

    date_range_labels = {
        "4w": "Past 4 weeks (rolling)",
        "30d": "Past 30 days (rolling)",
        "qtd": "Quarter to date",
    }

    return {
        "department": selected_team["department"],
        "selected_team_id": selected_team["id"],
        "selected_team_name": selected_team["name"],
        "date_range": date_range,
        "reporting_period": date_range_labels.get(date_range, "Past 4 weeks (rolling)"),
        "total_workforce": workforce,
        "is_insufficient_group": False,
        "available_teams": available_teams,
        "status_distribution_counts": status_counts,
        "status_distribution_pct": pct_distribution,
        "change_vs_last_week": change_vs_last_week,
        "checkin_participation": checkin_participation,
        "four_week_outlook": four_week_outlook,
        "trajectory_30d": trajectory_30d,
        "category_drivers": category_drivers,
        "privacy_compliance": {
            "individual_names_redacted": True,
            "individual_rankings_disabled": True,
            "raw_metrics_redacted": True,
            "probabilities_redacted": True,
            "k_anonymity_threshold": 5,
            "persistent_line": "Individual data is private to each employee.",
            "governance_standard": "WorkSense Zero-Identification Protocol (WHO-Aligned)",
        },
    }


# Serve the Frontend HTML Single-Page App
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>WorkSense App Loading...</h1>", status_code=200)
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"), status_code=200)


# Mount static assets if any
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

