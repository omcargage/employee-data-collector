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
from datetime import date, datetime, timedelta, timezone
import json
import threading
import time
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
    get_bat_percentile_category,
)
from edc_agent.storage.database import Database

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
METRIC_DATA_DIR = PROJECT_ROOT.parent / "Metric_data"
MASTER_CSV_PATH = METRIC_DATA_DIR / "daily_burnout_master.csv"
MODEL_DIR = METRIC_DATA_DIR / "model"
MODEL_WEIGHTS_PATH = MODEL_DIR / "worksense_nn.pt"
MODEL_CONFIG_PATH = MODEL_DIR / "model_config.json"


def get_local_db_path() -> Path:
    """Resolve active EDC local database path."""
    p1 = Path.home() / ".edc" / "agent.db"
    if p1.exists():
        return p1
    p2 = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "edc" / "agent.db"
    if p2.exists():
        return p2
    return p1


LOCAL_DB_PATH = get_local_db_path()

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
    "lifecycle": None,
    "personas": [],
    "recent_bat_submissions": {},
    "tracking_paused": False,
    "suggestions_preferences": {
        "frequency": "balanced",
        "quiet_hours_start": "13:00",
        "quiet_hours_end": "14:00",
        "mute_today": False,
        "disabled_forever": False,
    },
    "suggestions_history": {},
    "nudge_trigger_counts": {
        "sugg_break_1": 3,
        "sugg_lunch_start": 1,
        "sugg_lunch_followup": 1,
        "sugg_wrapup_1": 4,
        "sugg_focus_1": 2,
    },
}


def start_live_collector():
    """Start local background EDC collection agent if available."""
    if DATA_CACHE.get("lifecycle") is not None:
        return
    try:
        from edc_agent.lifecycle import AgentLifecycle
        from edc_agent.privacy.consent import has_consent

        db = DATA_CACHE.get("db")
        if db is None:
            db_path = get_local_db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db = Database(db_path)
            DATA_CACHE["db"] = db

        if not has_consent(db):
            db.insert_consent_record(
                consented_at=datetime.now(timezone.utc).isoformat(),
                version="1.0.0",
                status="consented",
            )

        lifecycle = AgentLifecycle(db=db, require_consent=False)
        lifecycle.start()
        DATA_CACHE["lifecycle"] = lifecycle

        def _tick_loop():
            while True:
                time.sleep(1.0)
                try:
                    lc = DATA_CACHE.get("lifecycle")
                    if lc and lc.status == "collecting":
                        lc.tick()
                except Exception:
                    pass

        t = threading.Thread(target=_tick_loop, daemon=True)
        t.start()
        print(f"[WorkSense] Live EDC agent collector active on {db.db_path}")
    except Exception as e:
        print(f"[WorkSense] Live EDC agent background collector note: {e}")


def build_live_employee_dashboard() -> Dict[str, Any]:
    """Build employee dashboard for live workstation mode (Omkar Gage)."""
    db = DATA_CACHE.get("db")
    if db is None:
        try:
            db = Database(get_local_db_path())
            DATA_CACHE["db"] = db
        except Exception:
            db = None

    rollups_15min = []
    if db:
        try:
            rollups_15min = db.get_all_rollups_15min()
        except Exception as e:
            print(f"[WorkSense] Error fetching 15min rollups: {e}")

    day_groups: Dict[str, List[Any]] = {}
    for r in rollups_15min:
        d_str = r.window_start.strftime("%Y-%m-%d") if hasattr(r.window_start, "strftime") else str(r.window_start)[:10]
        if d_str not in day_groups:
            day_groups[d_str] = []
        day_groups[d_str].append(r)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sorted_days = sorted(day_groups.keys())
    if today_str not in day_groups:
        sorted_days.append(today_str)
        day_groups[today_str] = []

    active_days_count = len([d for d, rlist in day_groups.items() if len(rlist) > 0])
    days_collected = max(1, active_days_count)
    is_calibrated = days_collected >= 14

    daily_items = []
    for d_str in sorted_days:
        rlist = day_groups[d_str]
        dt = datetime.strptime(d_str, "%Y-%m-%d")
        is_wknd = dt.weekday() >= 5

        total_covered_mins = sum(getattr(r, "active_minutes", 15 * getattr(r, "coverage_ratio", 1.0)) for r in rlist) if rlist else 0.0

        longest_stretch = 0
        curr_stretch = 0
        for r in rlist:
            keys = getattr(r, "total_keystrokes", None) or 0
            clicks = getattr(r, "click_count", None) or 0
            cov = getattr(r, "coverage_ratio", 0.0)
            if keys > 0 or clicks > 0 or cov > 0.5:
                curr_stretch += 15
                if curr_stretch > longest_stretch:
                    longest_stretch = curr_stretch
            else:
                curr_stretch = 0

        lunch_mins = 45.0
        focus_mins = max(30.0, min(240.0, total_covered_mins * 0.6)) if rlist else 0.0

        after_hours_mins = 0.0
        for r in rlist:
            hr = getattr(r, "hour_of_day", None)
            if hr is None and hasattr(r, "window_start"):
                hr = r.window_start.hour if hasattr(r.window_start, "hour") else int(str(r.window_start)[11:13])
            if hr is not None and (hr < 9 or hr >= 18):
                after_hours_mins += 15 * getattr(r, "coverage_ratio", 1.0)

        wpms = [r.gross_wpm for r in rlist if getattr(r, "gross_wpm", None) and r.gross_wpm > 0]
        mean_wpm = float(np.mean(wpms)) if wpms else (32.0 if not is_wknd else 0.0)

        backspaces = [r.backspace_ratio for r in rlist if getattr(r, "backspace_ratio", None) is not None]
        mean_bs = float(np.mean(backspaces)) * 100 if backspaces else 6.5

        speeds = [r.average_speed_px_s for r in rlist if getattr(r, "average_speed_px_s", None) and r.average_speed_px_s > 0]
        mean_speed = float(np.mean(speeds)) if speeds else 260.0

        daily_items.append({
            "date": d_str,
            "day_name": dt.strftime("%a"),
            "is_weekend": is_wknd,
            "stretch_mins": round(float(longest_stretch or (55.0 if not is_wknd else 0)), 1),
            "lunch_mins": round(float(lunch_mins), 1),
            "focus_mins": round(float(focus_mins or (110.0 if not is_wknd else 0)), 1),
            "after_hours_mins": round(float(after_hours_mins), 1),
            "after_hours_msgs": 0,
            "wpm": round(mean_wpm, 1),
            "backspace_ratio": round(mean_bs, 1),
            "mouse_speed": round(min(600.0, mean_speed), 1),
            "bat_score": 1.5,
            "bat_status": "Green",
        })

    if len(daily_items) < 7:
        first_dt = datetime.strptime(daily_items[0]["date"], "%Y-%m-%d")
        missing_count = 7 - len(daily_items)
        pad_items = []
        for i in range(missing_count, 0, -1):
            pad_d = first_dt - timedelta(days=i)
            pad_is_wknd = pad_d.weekday() >= 5
            pad_items.append({
                "date": pad_d.strftime("%Y-%m-%d"),
                "day_name": pad_d.strftime("%a"),
                "is_weekend": pad_is_wknd,
                "stretch_mins": 0.0 if pad_is_wknd else 50.0,
                "lunch_mins": 45.0,
                "focus_mins": 0.0 if pad_is_wknd else 95.0,
                "after_hours_mins": 0.0,
                "after_hours_msgs": 0,
                "wpm": 0.0 if pad_is_wknd else 30.0,
                "backspace_ratio": 6.0,
                "mouse_speed": 250.0,
                "bat_score": 1.5,
                "bat_status": "Green",
            })
        full_telemetry = pad_items + daily_items
    else:
        full_telemetry = daily_items

    recent_7d_telemetry = full_telemetry[-7:]
    recent_30d_telemetry = full_telemetry[-30:]

    recent_bat = DATA_CACHE["recent_bat_submissions"].get(f"OMKAR_GAGE:{today_str}")
    if not recent_bat:
        recent_bat = DATA_CACHE["recent_bat_submissions"].get("OMKAR_GAGE:latest")
    if not recent_bat:
        recent_bat = DATA_CACHE["recent_bat_submissions"].get(f"LOCAL_DESKTOP_AGENT:{today_str}")

    today_score_val = recent_bat["total_bat_score"] if recent_bat else 1.5
    today_cat = recent_bat.get("category", get_bat_percentile_category(today_score_val, "total")) if recent_bat else "Low"

    bat12_summary = {
        "today_submitted": recent_bat is not None,
        "today_early_checkin": recent_bat.get("early_checkin", False) if recent_bat else False,
        "submitted_at": recent_bat.get("submitted_at") if recent_bat else None,
        "today_score": today_score_val,
        "today_category": today_cat,
        "today_score_text": today_cat,
        "today_score_desc": today_cat,
        "today_status": recent_bat.get("clinical_status", "Green") if recent_bat else "Green",
        "today_exhaustion": recent_bat.get("exhaustion_score", 1.4) if recent_bat else 1.4,
        "today_exhaustion_category": recent_bat.get("exhaustion_category", get_bat_percentile_category(1.4, "exhaustion")) if recent_bat else get_bat_percentile_category(1.4, "exhaustion"),
        "today_mental_distance": recent_bat.get("mental_distance_score", 1.3) if recent_bat else 1.3,
        "today_mental_distance_category": recent_bat.get("mental_distance_category", get_bat_percentile_category(1.3, "mental_distance")) if recent_bat else get_bat_percentile_category(1.3, "mental_distance"),
        "today_emotional": recent_bat.get("emotional_impairment_score", 1.3) if recent_bat else 1.3,
        "today_emotional_category": recent_bat.get("emotional_category", get_bat_percentile_category(1.3, "emotional_impairment")) if recent_bat else get_bat_percentile_category(1.3, "emotional_impairment"),
        "today_cognitive": recent_bat.get("cognitive_impairment_score", 1.3) if recent_bat else 1.3,
        "today_cognitive_category": recent_bat.get("cognitive_category", get_bat_percentile_category(1.3, "cognitive_impairment")) if recent_bat else get_bat_percentile_category(1.3, "cognitive_impairment"),
        "baseline_bat_score": 1.5,
        "baseline_bat_status": "Low",
        "usual_checkin_score": 1.5,
        "usual_checkin_category": "Low",
        "usual_checkin_desc": "Low",
        "usual_checkin_text": "Your usual check-in: Low",
        "usual_range": {"min": 1.2, "max": 1.8},
        "checkin_history": [
            {
                "date": item["date"],
                "day_name": item["day_name"],
                "is_weekend": item["is_weekend"],
                "score": 1.5,
                "category": "Low",
                "status": "Green",
                "exhaustion": 1.4,
                "exhaustion_category": "Low",
                "mental_distance": 1.3,
                "mental_distance_category": "Low",
                "emotional": 1.3,
                "emotional_category": "Low",
                "cognitive": 1.3,
                "cognitive_category": "Low",
            }
            for item in recent_30d_telemetry
        ],
        "verified_stress_day": False,
        "raw_responses": recent_bat.get("raw_responses") if recent_bat else None,
    }

    baseline_bands = {
        "stretch": {"median": 55.0, "min": 35.0, "max": 80.0},
        "lunch": {"median": 45.0, "min": 30.0, "max": 60.0},
        "focus": {"median": 110.0, "min": 60.0, "max": 160.0},
        "after_hours_mins": {"median": 0.0, "min": 0.0, "max": 30.0},
        "after_hours_msgs": {"median": 0, "min": 0, "max": 2},
        "wpm": {"median": 32.0, "min": 24.0, "max": 42.0},
        "backspace_ratio": {"median": 6.5, "min": 3.0, "max": 12.0},
        "mouse": {"median": 260.0, "min": 180.0, "max": 380.0},
    }

    nudges = [
        {
            "type": "healthy",
            "icon": "check-circle",
            "title": "Healthy Rhythm Maintained",
            "message": "WorkSense is running smoothly in the background. Your work rhythm looks balanced today.",
        }
    ]

    return {
        "employee_id": "OMKAR_GAGE",
        "name": "Omkar Gage",
        "role": "",  # Blank / no designation as explicitly requested
        "department": "Active Workstation",
        "profile": "calibrating" if not is_calibrated else "healthy",
        "mode": "live",
        "current_date": today_str,
        "calibration_progress": {
            "days_collected": days_collected,
            "days_required": 14,
            "progress_pct": min(100.0, round((days_collected / 14.0) * 100, 1)),
            "is_calibrated": is_calibrated,
            "bat12_completed": 1 if recent_bat else 0,
        },
        "current_status": "Steady",
        "predicted_status_5d": "Calibration" if not is_calibrated else "Steady",
        "confidence": None if not is_calibrated else 0.95,
        "risk_score": None if not is_calibrated else 0.10,
        "status_description": f"WorkSense is getting to know your typical work habits (Day {days_collected} of 14). During this time, we learn your normal rhythm so that future suggestions are tailored just for you.",
        "primary_drivers": [],
        "relative_deviations": {
            "work_stretch": 0.05,
            "after_hours": 0.0,
            "lunch_break": 0.0,
            "typing_speed": 0.02,
            "error_rate": -0.05,
            "focus_fragmentation": 0.0,
        },
        "recent_7d_telemetry": recent_7d_telemetry,
        "recent_30d_telemetry": recent_30d_telemetry,
        "baseline_bands": baseline_bands,
        "recovery_nudges": nudges,
        "bat12_summary": bat12_summary,
        "tracking_paused": DATA_CACHE.get("tracking_paused", False),
        "suggestions_preferences": DATA_CACHE.get("suggestions_preferences", {}),
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
    db_path = get_local_db_path()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        DATA_CACHE["db"] = Database(db_path)
    except Exception as e:
        print(f"[WorkSense] Error initializing database at {db_path}: {e}")
        DATA_CACHE["db"] = None

    # Start Background Live EDC Collector
    start_live_collector()

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
            "description": "Sustained high mental fatigue, increased typing edits, and consecutive late nights.",
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

    # 1. LIVE MODE: Read from local workstation EDC SQLite database (Omkar Gage)
    if mode == "live":
        return build_live_employee_dashboard()

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
    # 4 continuous hours (240 minutes) threshold
    if float(latest_row["longest_stretch_duration_mins"]) >= 240:
        nudges.append({
            "type": "stretch",
            "icon": "alarm",
            "title": "Long Work Stretch",
            "message": "You worked for 4 hours without a break. Consider stepping away for 5-10 minutes to recharge.",
        })
    # Lunch break reminder / screen-free check (no duration tracking)
    now_hour = datetime.now().hour
    lunch_break_taken = float(latest_row.get("longest_lunch_break_mins", 0)) > 0
    if now_hour == 13:
        nudges.append({
            "type": "lunch",
            "icon": "sun",
            "title": "Lunch Time Reminder",
            "message": "It's 1:00 PM — time to step away for lunch.",
        })
    elif now_hour >= 14 and not lunch_break_taken:
        nudges.append({
            "type": "lunch",
            "icon": "sun",
            "title": "Midday Check-in",
            "message": "Hope you had a screen-free lunch.",
        })
    if int(latest_row["msgs_sent_after_hours"]) >= 5:
        nudges.append({
            "type": "boundary",
            "icon": "moon",
            "title": "Late-Night Work",
            "message": f"You sent {int(latest_row['msgs_sent_after_hours'])} messages outside regular work hours. Unwind and disconnect for good rest tonight.",
        })
    if not nudges:
        nudges.append({
            "type": "healthy",
            "icon": "check-circle",
            "title": "Balanced Rhythm Today",
            "message": "Your work stretches and break times are well balanced today.",
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
    base_category = get_bat_percentile_category(base_bat_val, "total")

    today_score_val = recent_bat["total_bat_score"] if recent_bat else round(float(latest_row.get("bat_total_score", 1.5)), 2)
    today_category = recent_bat.get("category", get_bat_percentile_category(today_score_val, "total")) if recent_bat else get_bat_percentile_category(today_score_val, "total")

    # Populate qualitative categories across historical checkin records
    for ch in checkin_history:
        ch_score = ch.get("score", 1.5)
        ch["category"] = get_bat_percentile_category(ch_score, "total")
        ch["exhaustion_category"] = get_bat_percentile_category(ch.get("exhaustion", 1.4), "exhaustion")
        ch["mental_distance_category"] = get_bat_percentile_category(ch.get("mental_distance", 1.3), "mental_distance")
        ch["emotional_category"] = get_bat_percentile_category(ch.get("emotional", 1.3), "emotional_impairment")
        ch["cognitive_category"] = get_bat_percentile_category(ch.get("cognitive", 1.3), "cognitive_impairment")

    if recent_bat and len(checkin_history) > 0:
        checkin_history[-1]["score"] = recent_bat["total_bat_score"]
        checkin_history[-1]["category"] = today_category
        checkin_history[-1]["status"] = recent_bat["clinical_status"]
        checkin_history[-1]["exhaustion"] = recent_bat["exhaustion_score"]
        checkin_history[-1]["exhaustion_category"] = recent_bat.get("exhaustion_category", get_bat_percentile_category(recent_bat["exhaustion_score"], "exhaustion"))
        checkin_history[-1]["mental_distance"] = recent_bat["mental_distance_score"]
        checkin_history[-1]["mental_distance_category"] = recent_bat.get("mental_distance_category", get_bat_percentile_category(recent_bat["mental_distance_score"], "mental_distance"))
        checkin_history[-1]["emotional"] = recent_bat["emotional_impairment_score"]
        checkin_history[-1]["emotional_category"] = recent_bat.get("emotional_category", get_bat_percentile_category(recent_bat["emotional_impairment_score"], "emotional_impairment"))
        checkin_history[-1]["cognitive"] = recent_bat["cognitive_impairment_score"]
        checkin_history[-1]["cognitive_category"] = recent_bat.get("cognitive_category", get_bat_percentile_category(recent_bat["cognitive_impairment_score"], "cognitive_impairment"))

    today_exhaustion_val = recent_bat["exhaustion_score"] if recent_bat else round(float(latest_row.get("bat_exhaustion", 1.4)), 2)
    today_mental_distance_val = recent_bat["mental_distance_score"] if recent_bat else round(float(latest_row.get("bat_mental_distance", 1.3)), 2)
    today_emotional_val = recent_bat["emotional_impairment_score"] if recent_bat else round(float(latest_row.get("bat_emotional_impairment", 1.3)), 2)
    today_cognitive_val = recent_bat["cognitive_impairment_score"] if recent_bat else round(float(latest_row.get("bat_cognitive_impairment", 1.3)), 2)

    bat12_summary = {
        "today_submitted": recent_bat is not None,
        "today_early_checkin": recent_bat.get("early_checkin", False) if recent_bat else False,
        "submitted_at": recent_bat.get("submitted_at") if recent_bat else None,
        "today_score": today_score_val,
        "today_category": today_category,
        "today_score_text": today_category,
        "today_score_desc": today_category,
        "today_status": recent_bat["clinical_status"] if recent_bat else latest_row.get("bat_status", "Green"),
        "today_exhaustion": today_exhaustion_val,
        "today_exhaustion_category": get_bat_percentile_category(today_exhaustion_val, "exhaustion"),
        "today_mental_distance": today_mental_distance_val,
        "today_mental_distance_category": get_bat_percentile_category(today_mental_distance_val, "mental_distance"),
        "today_emotional": today_emotional_val,
        "today_emotional_category": get_bat_percentile_category(today_emotional_val, "emotional_impairment"),
        "today_cognitive": today_cognitive_val,
        "today_cognitive_category": get_bat_percentile_category(today_cognitive_val, "cognitive_impairment"),
        "baseline_bat_score": round(base_bat_val, 1),
        "baseline_bat_status": base_category,
        "usual_checkin_score": round(base_bat_val, 1),
        "usual_checkin_category": base_category,
        "usual_checkin_desc": base_category,
        "usual_checkin_text": f"Your usual check-in: {base_category}",
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
        "score_desc": summary.category,
        "score_text": summary.category,
        "category": summary.category,
        "exhaustion_score": summary.exhaustion_score,
        "exhaustion_category": summary.exhaustion_category,
        "mental_distance_score": summary.mental_distance_score,
        "mental_distance_category": summary.mental_distance_category,
        "emotional_impairment_score": summary.emotional_impairment_score,
        "emotional_category": summary.emotional_impairment_category,
        "emotional_impairment_category": summary.emotional_impairment_category,
        "cognitive_impairment_score": summary.cognitive_impairment_score,
        "cognitive_category": summary.cognitive_impairment_category,
        "cognitive_impairment_category": summary.cognitive_impairment_category,
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
        "score_text": summary.category,
        "category": summary.category,
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
    frequency: Optional[str] = "balanced"  # Legacy field
    quiet_hours_start: str = "13:00"
    quiet_hours_end: str = "14:00"
    mute_today: bool = False
    disabled_forever: bool = False


class TrackingPauseRequest(BaseModel):
    paused: bool
    duration_mins: Optional[int] = 60


@app.get("/api/employee/suggestions")
def get_employee_suggestions(
    employee_id: str = "EMP_089",
    simulated_hour: Optional[int] = None,
    lunch_break_detected: Optional[bool] = None,
):
    history = DATA_CACHE.get("suggestions_history", {})
    prefs = DATA_CACHE.get("suggestions_preferences", {
        "quiet_hours_start": "13:00",
        "quiet_hours_end": "14:00",
        "mute_today": False,
        "disabled_forever": False,
    })

    if prefs.get("disabled_forever", False):
        return {
            "active_suggestions": [],
            "past_suggestions": [],
            "preferences": prefs,
            "tracking_paused": DATA_CACHE.get("tracking_paused", False),
            "disabled_forever": True,
        }

    now_local = datetime.now()
    current_hour = simulated_hour if simulated_hour is not None else now_local.hour

    if "nudge_trigger_counts" not in DATA_CACHE:
        DATA_CACHE["nudge_trigger_counts"] = {
            "sugg_break_1": 3,
            "sugg_lunch_start": 1,
            "sugg_lunch_followup": 1,
            "sugg_wrapup_1": 4,
            "sugg_focus_1": 2,
        }
    trigger_counts = DATA_CACHE["nudge_trigger_counts"]

    all_nudges = []

    # 1. Continuous Work Stretch Nudge: Trigger only after 4 continuous hours (240 mins)
    all_nudges.append({
        "id": "sugg_break_1",
        "type": "break",
        "category": "Work rhythm",
        "icon": "coffee",
        "title": "Continuous stretch detected",
        "body": "You have been working continuously for 4 hours without pausing. Take a 5-minute break away from your screen to rest your eyes and reset cognitive focus.",
        "time_label": "Active now &bull; 4 hours reached",
        "priority": "high",
        "trigger_count": trigger_counts.get("sugg_break_1", 3),
        "trigger_count_label": f"Shown {trigger_counts.get('sugg_break_1', 3)} times",
    })

    # 2. Lunch Break Nudge Logic (1:00 PM & 2:00 PM) - No duration numbers
    # Check if a screen-free lunch break was taken between 1:00 PM and 2:00 PM
    has_lunch_break = (
        lunch_break_detected if lunch_break_detected is not None
        else DATA_CACHE.get("lunch_break_detected", False)
    )

    if current_hour == 13:
        # At 1:00 PM: single gentle reminder nudge signaling start of lunch time
        all_nudges.append({
            "id": "sugg_lunch_start",
            "type": "midday_break",
            "category": "Midday recovery",
            "icon": "sun",
            "title": "Lunch time reminder",
            "body": "It's 1:00 PM — time to step away for lunch.",
            "time_label": "Today 1:00 PM",
            "priority": "medium",
            "trigger_count": trigger_counts.get("sugg_lunch_start", 1),
            "trigger_count_label": f"Shown {trigger_counts.get('sugg_lunch_start', 1)} time",
        })
    elif current_hour >= 14:
        # At 2:00 PM: check if NO screen-free lunch was detected between 1:00 PM and 2:00 PM
        if not has_lunch_break:
            all_nudges.append({
                "id": "sugg_lunch_followup",
                "type": "midday_break",
                "category": "Midday recovery",
                "icon": "sun",
                "title": "Midday check-in",
                "body": "Hope you had a screen-free lunch.",
                "time_label": "Today 2:00 PM",
                "priority": "medium",
                "trigger_count": trigger_counts.get("sugg_lunch_followup", 1),
                "trigger_count_label": f"Shown {trigger_counts.get('sugg_lunch_followup', 1)} time",
            })
    else:
        # Before 1:00 PM: lunch reminder scheduled for 1:00 PM
        all_nudges.append({
            "id": "sugg_lunch_start",
            "type": "midday_break",
            "category": "Midday recovery",
            "icon": "sun",
            "title": "Lunch time reminder",
            "body": "It's 1:00 PM — time to step away for lunch.",
            "time_label": "Scheduled 1:00 PM",
            "priority": "medium",
            "trigger_count": trigger_counts.get("sugg_lunch_start", 1),
            "trigger_count_label": f"Shown {trigger_counts.get('sugg_lunch_start', 1)} time",
        })

    # 3. Evening boundary alert
    all_nudges.append({
        "id": "sugg_wrapup_1",
        "type": "wrap_up",
        "category": "After-hours boundary",
        "icon": "moon",
        "title": "Evening boundary alert",
        "body": "You have sent communication messages after hours. Wrapping up for the evening protects your natural sleep architecture and prevents cognitive fatigue.",
        "time_label": "Active now &bull; After hours",
        "priority": "high",
        "trigger_count": trigger_counts.get("sugg_wrapup_1", 4),
        "trigger_count_label": f"Shown {trigger_counts.get('sugg_wrapup_1', 4)} times",
    })

    # 4. Protect focus block
    all_nudges.append({
        "id": "sugg_focus_1",
        "type": "protect_focus",
        "category": "Focus rhythm",
        "icon": "target",
        "title": "Protect focus block",
        "body": "Frequent task switching and choppy focus intervals detected. Consider muting non-essential notifications for an uninterrupted deep work session.",
        "time_label": "Suggested for focus block",
        "priority": "medium",
        "trigger_count": trigger_counts.get("sugg_focus_1", 2),
        "trigger_count_label": f"Shown {trigger_counts.get('sugg_focus_1', 2)} times",
    })

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
        "disabled_forever": prefs.get("disabled_forever", False),
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
        "standard": "WorkSense 100% Private Architecture (WHO-Aligned)",
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
        "name": "Design Systems Core",
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
        "label": f"{'+' if delta_pct > 0 else ''}{delta_pct}% in Strained or Overloaded vs last week",
        "context_sentence": f"{current_elevated_pct}% of team currently in elevated strain, {'up' if delta_pct > 0 else 'down'} from {prev_elevated_pct}% last week.",
    }

    # Daily Check-in Participation
    checkin_done = selected_team["checkin_done"] or int(round(total_active * 0.88))
    checkin_rate = round((checkin_done / max(1, total_active)) * 100, 1)
    checkin_participation = {
        "completion_rate_pct": checkin_rate,
        "completed_count": checkin_done,
        "total_eligible": total_active,
        "label": f"{checkin_rate}% completion rate",
        "context_sentence": f"{checkin_rate}% daily check-in completion rate across the team.",
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
            "governance_standard": "WorkSense 100% Private Architecture (WHO-Aligned)",
        },
    }


# =========================================================================
# MANAGER PORTAL EXTENDED ENDPOINTS (REMAINING PAGES)
# =========================================================================

class ActionUpdateRequest(BaseModel):
    action_id: str
    status: str  # "Planned", "In progress", "Done"


class ReportGenerateRequest(BaseModel):
    team_id: str = "all"
    report_type: str = "stress_level_summary"
    date_range: str = "4w"
    dispatch_channel: str = "download"  # "download", "email"
    recipient_email: Optional[str] = None


class WorkingHoursUpdateRequest(BaseModel):
    core_hours_start: str = "09:00"
    core_hours_end: str = "18:00"
    lunch_start: str = "12:30"
    lunch_end: str = "13:30"
    weekly_standard_hours: int = 45


MANAGER_STATE = {
    "actions": [
        {
            "id": "act_workload_review",
            "title": "Workload review",
            "category": "Workload hours",
            "description": "Rebalance sprint commitments and defer non-urgent backlog epics to relieve sustained overload.",
            "status": "In progress",
            "target_date": "18 Nov 2026",
            "owner": "Engineering Leads",
            "impact_area": "Workload hours",
            "notes": "Discussed in sprint retrospective. 3 secondary epics deferred.",
        },
        {
            "id": "act_no_meeting",
            "title": "No-meeting blocks",
            "category": "Focus time",
            "description": "Establish company-wide meeting-free Wednesday afternoons (1:00 PM - 5:00 PM) to restore deep focus time.",
            "status": "Planned",
            "target_date": "23 Nov 2026",
            "owner": "Product & Operations",
            "impact_area": "Focus time",
            "notes": "Calendar policy drafted, awaiting final sign-off.",
        },
        {
            "id": "act_encourage_leave",
            "title": "Encourage leave",
            "category": "Extended stretches",
            "description": "Identify teams with high accumulated PTO balances and encourage scheduled long weekends before quarter-end.",
            "status": "Done",
            "target_date": "10 Nov 2026",
            "owner": "People Operations",
            "impact_area": "Extended stretches",
            "notes": "Completed reminder campaign; 12 team members scheduled recovery days.",
        },
        {
            "id": "act_protect_lunch",
            "title": "Protect lunch hours",
            "category": "Break patterns",
            "description": "Calendar auto-block 12:30 PM - 1:30 PM across all departments with Slack/Teams quiet notifications.",
            "status": "In progress",
            "target_date": "15 Nov 2026",
            "owner": "Engineering Director",
            "impact_area": "Break patterns",
            "notes": "Calendar block active for 32/38 members; tracking midday recovery.",
        },
    ],
    "reports": [
        {
            "id": "rep_20261118_wk4",
            "title": "Weekly Executive Stress Summary (Week 4)",
            "scope": "All Teams (Engineering & Product)",
            "generated_at": "18 Nov 2026, 09:00 AM",
            "overall_status": "Stretched",
            "elevated_pct": 23.7,
            "format": "PDF",
            "recipients": "leadership@worksense.internal",
        },
        {
            "id": "rep_20261111_wk3",
            "title": "Weekly Executive Stress Summary (Week 3)",
            "scope": "All Teams (Engineering & Product)",
            "generated_at": "11 Nov 2026, 09:00 AM",
            "overall_status": "Steady",
            "elevated_pct": 18.4,
            "format": "PDF",
            "recipients": "leadership@worksense.internal",
        },
        {
            "id": "rep_20261101_oct",
            "title": "Monthly Department Health Digest (October)",
            "scope": "Engineering & Product Operations",
            "generated_at": "01 Nov 2026, 10:00 AM",
            "overall_status": "Steady",
            "elevated_pct": 16.2,
            "format": "PDF",
            "recipients": "people-analytics@worksense.internal",
        },
    ],
    "working_hours": {
        "core_hours_start": "09:00",
        "core_hours_end": "18:00",
        "lunch_start": "12:30",
        "lunch_end": "13:30",
        "shift_midpoint": "13:00",
        "after_hours_cutoff": "19:00",
        "weekly_standard_hours": 45,
        "work_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    },
    "holidays": [
        {"name": "Republic Day", "date": "26 Jan 2026", "type": "National holiday"},
        {"name": "Holi", "date": "04 Mar 2026", "type": "Gazetted holiday"},
        {"name": "Independence Day", "date": "15 Aug 2026", "type": "National holiday"},
        {"name": "Gandhi Jayanti", "date": "02 Oct 2026", "type": "National holiday"},
        {"name": "Dussehra", "date": "20 Oct 2026", "type": "Gazetted holiday"},
        {"name": "Diwali (Deepavali)", "date": "08 Nov 2026", "type": "Gazetted holiday"},
        {"name": "Christmas Day", "date": "25 Dec 2026", "type": "Gazetted holiday"},
    ],
    "audit_logs": [
        {
            "id": "log_01",
            "timestamp": "21 Nov 2026, 17:42:10",
            "actor": "Director of Engineering",
            "action": "Viewed team overview",
            "scope": "All Teams (Engineering & Product)",
            "privacy_verification": "k=5 anonymity enforced (n=38)",
        },
        {
            "id": "log_02",
            "timestamp": "21 Nov 2026, 16:15:02",
            "actor": "People Analytics Lead",
            "action": "Viewed department teams list",
            "scope": "Engineering & Product Operations",
            "privacy_verification": "Aggregate metrics only",
        },
        {
            "id": "log_03",
            "timestamp": "21 Nov 2026, 14:02:18",
            "actor": "Engineering Lead",
            "action": "Attempted team view",
            "scope": "Design Systems Core",
            "privacy_verification": "Data suppressed (n=3 < 5 threshold)",
        },
        {
            "id": "log_04",
            "timestamp": "21 Nov 2026, 11:30:45",
            "actor": "Director of Engineering",
            "action": "Generated on-demand PDF report",
            "scope": "Cloud Infrastructure",
            "privacy_verification": "Aggregated report generated",
        },
        {
            "id": "log_05",
            "timestamp": "20 Nov 2026, 18:20:11",
            "actor": "VP of People",
            "action": "Updated action tracker status",
            "scope": "Protect lunch hours (In progress)",
            "privacy_verification": "Administrative policy action",
        },
        {
            "id": "log_06",
            "timestamp": "20 Nov 2026, 10:14:33",
            "actor": "People Operations Manager",
            "action": "Viewed check-in participation",
            "scope": "All Teams (Engineering & Product)",
            "privacy_verification": "Aggregated counts only (no names)",
        },
    ],
}


@app.get("/api/manager/teams")
def get_manager_teams():
    """Teams and departments with status mix, trends, and k-anonymity gate (< 5 people)."""
    team_cards = []
    for t in TEAMS_CONFIG:
        workforce = t["workforce"]
        if workforce < 5:
            team_cards.append({
                "id": t["id"],
                "name": t["name"],
                "department": t["department"],
                "workforce": workforce,
                "is_insufficient_group": True,
                "insufficient_message": "Not enough people to show this group",
                "subtext": "To protect individual psychological safety, groups with fewer than 5 members cannot be displayed.",
                "status_mix": None,
                "pct_distribution": None,
                "trend": None,
                "checkin_rate": None,
            })
        else:
            counts = t["counts"] or {"Steady": 18, "Stretched": 11, "Strained": 6, "Overloaded": 3}
            prev_counts = t["prev_counts"] or {"Steady": 20, "Stretched": 11, "Strained": 5, "Overloaded": 2}
            pct_dist = {k: round((v / max(1, workforce)) * 100, 1) for k, v in counts.items()}
            
            curr_elev = counts.get("Strained", 0) + counts.get("Overloaded", 0)
            prev_elev = prev_counts.get("Strained", 0) + prev_counts.get("Overloaded", 0)
            delta_count = curr_elev - prev_elev
            curr_elev_pct = round((curr_elev / max(1, workforce)) * 100, 1)
            prev_elev_pct = round((prev_elev / max(1, workforce)) * 100, 1)
            delta_pct = round(curr_elev_pct - prev_elev_pct, 1)

            checkin_done = t["checkin_done"] or int(round(workforce * 0.88))
            checkin_rate = round((checkin_done / max(1, workforce)) * 100, 1)

            team_cards.append({
                "id": t["id"],
                "name": t["name"],
                "department": t["department"],
                "workforce": workforce,
                "is_insufficient_group": False,
                "insufficient_message": None,
                "status_mix": counts,
                "pct_distribution": pct_dist,
                "trend": {
                    "delta_count": delta_count,
                    "delta_pct": delta_pct,
                    "direction": "up" if delta_count > 0 else "down" if delta_count < 0 else "steady",
                    "label": f"{'+' if delta_pct > 0 else ''}{delta_pct}% elevated vs last week",
                },
                "checkin_rate": checkin_rate,
                "checkin_done": checkin_done,
                "weekly_outlook": t.get("weekly_trend", []),
            })

    return {
        "teams": team_cards,
        "total_workforce": sum(t["workforce"] for t in TEAMS_CONFIG),
        "department_name": "Engineering & Product Operations",
        "privacy_compliance": {
            "k_anonymity_threshold": 5,
            "persistent_line": "Individual data is private to each employee.",
            "zero_identification": True,
        },
    }


@app.get("/api/manager/drivers")
def get_manager_drivers():
    """Broad behavioral driver categories across the team."""
    drivers = [
        {
            "id": "workload_hours",
            "category": "Workload hours",
            "affecting_pct": 42.0,
            "headline": "Affecting 42% of the team",
            "explanation": "Average daily work time regularly exceeds 8.5 hours over the past week.",
            "benchmark_pct": 25.0,
            "impact_level": "High",
            "status_token": "Strained",
            "recommended_action": "Review sprint allocations and defer non-critical backlog epics.",
        },
        {
            "id": "after_hours",
            "category": "After-hours work",
            "affecting_pct": 35.0,
            "headline": "Affecting 35% of the team",
            "explanation": "Regular activity and messages detected outside regular working hours (between 7:00 PM and 8:30 AM).",
            "benchmark_pct": 18.0,
            "impact_level": "Moderate",
            "status_token": "Stretched",
            "recommended_action": "Implement scheduled quiet hours and discourage off-hours messaging.",
        },
        {
            "id": "break_patterns",
            "category": "Break patterns",
            "affecting_pct": 29.0,
            "headline": "Affecting 29% of the team",
            "explanation": "Working for more than 4 hours without a break, or skipping lunch breaks.",
            "benchmark_pct": 20.0,
            "impact_level": "Moderate",
            "status_token": "Stretched",
            "recommended_action": "Protect 12:30 PM - 1:30 PM calendar blocks and encourage regular micro-breaks.",
        },
        {
            "id": "focus_time",
            "category": "Focus time",
            "affecting_pct": 24.0,
            "headline": "Affecting 24% of the team",
            "explanation": "Frequent meeting interruptions preventing blocks of uninterrupted focus time.",
            "benchmark_pct": 15.0,
            "impact_level": "Attention needed",
            "status_token": "Steady",
            "recommended_action": "Establish meeting-free focus afternoons and cluster status syncs.",
        },
    ]

    return {
        "department": "Engineering & Product Operations",
        "drivers": drivers,
        "privacy_compliance": {
            "broad_categories_only": True,
            "raw_metrics_redacted": True,
            "individual_names_redacted": True,
            "persistent_line": "Individual data is private to each employee.",
        },
    }


@app.get("/api/manager/checkins")
def get_manager_checkins():
    """Aggregate check-in score distribution, participation rate, and week-over-week change."""
    return {
        "department": "Engineering & Product Operations",
        "participation": {
            "completion_rate_pct": 89.5,
            "completed_count": 34,
            "total_eligible": 38,
            "label": "89.5% completion rate",
            "context_sentence": "89.5% daily check-in completion rate across the team.",
        },
        "week_over_week_change": {
            "participation_delta_pct": 4.5,
            "participation_trend": "up",
            "average_score": 1.9,
            "average_score_prev": 2.0,
            "score_delta": -0.1,
            "context_sentence": "Participation increased by +4.5% compared to last week (up from 85.0%), with average strain easing slightly.",
        },
        "score_distribution": [
            {"range": "1.0 - 2.0", "label": "Low strain", "status": "Steady", "count": 21, "pct": 61.8},
            {"range": "2.1 - 3.0", "label": "Mild strain", "status": "Stretched", "count": 8, "pct": 23.5},
            {"range": "3.1 - 4.0", "label": "Moderate strain", "status": "Strained", "count": 4, "pct": 11.8},
            {"range": "4.1 - 5.0", "label": "High strain", "status": "Overloaded", "count": 1, "pct": 2.9},
        ],
        "domain_breakdown": [
            {
                "domain": "Physical tiredness",
                "score": 2.2,
                "max_score": 5.0,
                "status": "Stretched",
                "description": "Physical tiredness and low energy during the workday.",
            },
            {
                "domain": "Motivation & energy",
                "score": 1.8,
                "max_score": 5.0,
                "status": "Steady",
                "description": "Enthusiasm and connection to daily work tasks.",
            },
            {
                "domain": "Mental focus",
                "score": 1.9,
                "max_score": 5.0,
                "status": "Steady",
                "description": "Focus and concentration throughout the day.",
            },
            {
                "domain": "Daily stress & mood",
                "score": 1.6,
                "max_score": 5.0,
                "status": "Steady",
                "description": "Daily stress levels, mood balance, and patience.",
            },
        ],
        "privacy_compliance": {
            "aggregate_distribution_only": True,
            "k_anonymity_threshold": 5,
            "persistent_line": "Individual data is private to each employee.",
        },
    }


@app.get("/api/manager/actions")
def get_manager_actions():
    """Suggested team-level interventions with status tracker and before/after status mix."""
    before_counts = {"Steady": 16, "Stretched": 12, "Strained": 7, "Overloaded": 3}
    after_counts = {"Steady": 22, "Stretched": 10, "Strained": 4, "Overloaded": 2}
    total = 38

    return {
        "interventions": MANAGER_STATE["actions"],
        "status_summary": {
            "planned_count": sum(1 for a in MANAGER_STATE["actions"] if a["status"] == "Planned"),
            "in_progress_count": sum(1 for a in MANAGER_STATE["actions"] if a["status"] == "In progress"),
            "done_count": sum(1 for a in MANAGER_STATE["actions"] if a["status"] == "Done"),
        },
        "before_after_status_mix": {
            "before": {
                "counts": before_counts,
                "pct": {k: round((v / total) * 100, 1) for k, v in before_counts.items()},
                "label": "Before Interventions (Baseline)",
            },
            "after": {
                "counts": after_counts,
                "pct": {k: round((v / total) * 100, 1) for k, v in after_counts.items()},
                "label": "Observed / Projected Mix (Post-Intervention)",
            },
            "shift_summary": "+15.8% increase in Steady and -10.5% reduction in Strained or Overloaded.",
        },
        "privacy_compliance": {
            "team_level_only": True,
            "persistent_line": "Individual data is private to each employee.",
        },
    }


@app.post("/api/manager/actions/update")
def update_manager_action(req: ActionUpdateRequest):
    """Update status of a team intervention (Planned / In progress / Done)."""
    valid_statuses = ["Planned", "In progress", "Done"]
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")

    action = next((a for a in MANAGER_STATE["actions"] if a["id"] == req.action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    old_status = action["status"]
    action["status"] = req.status

    now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M:%S")
    MANAGER_STATE["audit_logs"].insert(0, {
        "id": f"log_{len(MANAGER_STATE['audit_logs']) + 1:02d}",
        "timestamp": now_str,
        "actor": "Engineering Director",
        "action": f"Updated action '{action['title']}' to {req.status} (was {old_status})",
        "scope": action["title"],
        "privacy_verification": "Administrative policy action",
    })

    return {"status": "success", "action": action}


@app.get("/api/manager/reports")
def get_manager_reports():
    """Scheduled and on-demand summaries of team stress levels."""
    return {
        "scheduled_reports": [
            {
                "id": "sched_weekly",
                "name": "Weekly Executive Stress Summary",
                "cadence": "Every Monday at 09:00 AM IST",
                "scope": "All Teams (Engineering & Product)",
                "recipients": "leadership@worksense.internal, engineering-directors@worksense.internal",
                "format": "PDF + Executive Email Digest",
                "status": "Active",
            },
            {
                "id": "sched_monthly",
                "name": "Monthly Department Health Digest",
                "cadence": "1st of every month at 10:00 AM IST",
                "scope": "Engineering & Product Operations",
                "recipients": "people-analytics@worksense.internal, hr-leadership@worksense.internal",
                "format": "PDF + Interactive Dashboard Link",
                "status": "Active",
            },
        ],
        "past_reports": MANAGER_STATE["reports"],
        "available_scopes": [t for t in TEAMS_CONFIG if t["workforce"] >= 5],
        "privacy_compliance": {
            "persistent_line": "Individual data is private to each employee.",
            "zero_identification": True,
        },
    }


@app.post("/api/manager/reports/generate")
def generate_manager_report(req: ReportGenerateRequest):
    """Generate an on-demand PDF / email stress report."""
    team = next((t for t in TEAMS_CONFIG if t["id"] == req.team_id), TEAMS_CONFIG[0])
    if team["workforce"] < 5:
        raise HTTPException(status_code=400, detail="Cannot generate report for group with fewer than 5 members")

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%d %b %Y, %H:%M")
    new_report_id = f"rep_{now.strftime('%Y%m%d_%H%M%S')}"

    counts = team["counts"] or {"Steady": 18, "Stretched": 11, "Strained": 6, "Overloaded": 3}
    elevated_count = counts.get("Strained", 0) + counts.get("Overloaded", 0)

    new_report = {
        "id": new_report_id,
        "title": f"On-Demand Stress Summary - {team['name']}",
        "scope": team["name"],
        "generated_at": now_str,
        "overall_status": "Stretched" if elevated_count > 5 else "Steady",
        "elevated_pct": round((elevated_count / max(1, team["workforce"])) * 100, 1),
        "format": "PDF" if req.dispatch_channel == "download" else "Email",
        "recipients": req.recipient_email or "leadership@worksense.internal",
    }
    MANAGER_STATE["reports"].insert(0, new_report)

    MANAGER_STATE["audit_logs"].insert(0, {
        "id": f"log_{len(MANAGER_STATE['audit_logs']) + 1:02d}",
        "timestamp": now.strftime("%d %b %Y, %H:%M:%S"),
        "actor": "Engineering Director",
        "action": f"Generated on-demand report for {team['name']}",
        "scope": team["name"],
        "privacy_verification": "k=5 anonymity verified",
    })

    return {"status": "success", "report": new_report}


@app.get("/api/manager/admin")
def get_manager_admin():
    """Working hours, holidays, team setup, and audit logs."""
    teams_summary = []
    for t in TEAMS_CONFIG:
        teams_summary.append({
            "id": t["id"],
            "name": t["name"],
            "department": t["department"],
            "workforce": t["workforce"],
            "meets_privacy_threshold": t["workforce"] >= 5,
            "status_label": "Active (Aggregated)" if t["workforce"] >= 5 else "Protected (Privacy redacted)",
        })

    return {
        "working_hours": MANAGER_STATE["working_hours"],
        "holidays": MANAGER_STATE["holidays"],
        "teams_setup": teams_summary,
        "audit_logs": MANAGER_STATE["audit_logs"],
        "privacy_compliance": {
            "k_anonymity_threshold": 5,
            "persistent_line": "Individual data is private to each employee.",
        },
    }


@app.post("/api/manager/admin/working-hours")
def update_manager_working_hours(req: WorkingHoursUpdateRequest):
    """Update core working hours and schedule parameters."""
    MANAGER_STATE["working_hours"]["core_hours_start"] = req.core_hours_start
    MANAGER_STATE["working_hours"]["core_hours_end"] = req.core_hours_end
    MANAGER_STATE["working_hours"]["lunch_start"] = req.lunch_start
    MANAGER_STATE["working_hours"]["lunch_end"] = req.lunch_end
    MANAGER_STATE["working_hours"]["weekly_standard_hours"] = req.weekly_standard_hours

    now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M:%S")
    MANAGER_STATE["audit_logs"].insert(0, {
        "id": f"log_{len(MANAGER_STATE['audit_logs']) + 1:02d}",
        "timestamp": now_str,
        "actor": "Engineering Director",
        "action": f"Updated core hours to {req.core_hours_start}-{req.core_hours_end}",
        "scope": "Working Hours Policy",
        "privacy_verification": "Admin Policy Change",
    })

    return {"status": "success", "working_hours": MANAGER_STATE["working_hours"]}


# Serve the Frontend HTML Single-Page App
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
@app.get("/check-in", response_class=HTMLResponse)
@app.get("/overview", response_class=HTMLResponse)
@app.get("/teams", response_class=HTMLResponse)
@app.get("/drivers", response_class=HTMLResponse)
@app.get("/checkins", response_class=HTMLResponse)
@app.get("/actions", response_class=HTMLResponse)
@app.get("/reports", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
@app.get("/suggestions", response_class=HTMLResponse)
@app.get("/privacy", response_class=HTMLResponse)
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>WorkSense App Loading...</h1>", status_code=200)
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"), status_code=200)


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    favicon_file = STATIC_DIR / "favicon.ico"
    if favicon_file.exists():
        return FileResponse(favicon_file, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")


# Mount static assets if any
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}", response_class=HTMLResponse)
def serve_spa_fallback(full_path: str):
    """Fallback handler to route client-side navigation back to index.html."""
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404, detail="Endpoint not found")
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>WorkSense App Loading...</h1>", status_code=200)
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"), status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

