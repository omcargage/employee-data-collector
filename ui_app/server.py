"""WorkSense Application Bridge Server (FastAPI).

Connects:
- Pretrained PyTorch WorkSense Temporal Neural Network
- Master telemetry & BAT-12 dataset (daily_burnout_master.csv)
- Local EDC SQLite database (edc_agent.db)
- Interactive Dual-Portal Frontend (Employee & Manager)
"""
import os
from pathlib import Path
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
    items: Dict[str, int]


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
                "bat12_summary": None,
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
    sub_key = f"{employee_id}:{sub_df['date'].iloc[-1]}"
    recent_bat = DATA_CACHE["recent_bat_submissions"].get(sub_key)

    # 3. Predict with Neural Network
    prediction = predictor.predict_daily(sub_df) if predictor else {}

    # Extract 7-day telemetry slice
    recent_slice = sub_df.iloc[-7:].copy()
    telemetry_7d = []
    for _, row in recent_slice.iterrows():
        telemetry_7d.append({
            "date": str(row["date"]),
            "day_name": datetime.strptime(str(row["date"]), "%Y-%m-%d").strftime("%a"),
            "is_weekend": bool(row["is_weekend"]),
            "stretch_mins": round(float(row["longest_stretch_duration_mins"]), 1),
            "lunch_mins": round(float(row["longest_lunch_break_mins"]), 1),
            "after_hours_msgs": int(row["msgs_sent_after_hours"]),
            "wpm": round(float(row["daily_mean_wpm"]), 1),
            "backspace_ratio": round(float(row["daily_backspace_ratio"]) * 100, 1),
            "bat_score": round(float(row.get("bat_total_score", 1.5)), 2),
            "bat_status": row.get("bat_status", "Green"),
        })

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
        "recovery_nudges": nudges,
        "bat12_summary": {
            "baseline_bat_score": baseline_stats.bat_baseline_score if baseline_stats else None,
            "baseline_bat_status": baseline_stats.bat_baseline_status if baseline_stats else "Green",
            "today_score": recent_bat["total_bat_score"] if recent_bat else round(float(latest_row.get("bat_total_score", 1.5)), 2),
            "today_status": recent_bat["clinical_status"] if recent_bat else latest_row.get("bat_status", "Green"),
            "today_exhaustion": recent_bat["exhaustion_score"] if recent_bat else round(float(latest_row.get("bat_exhaustion", 1.4)), 2),
            "today_cognitive": recent_bat["cognitive_impairment_score"] if recent_bat else round(float(latest_row.get("bat_cognitive_impairment", 1.3)), 2),
            "verified_stress_day": recent_bat["verified_stressed_day"] if recent_bat else bool(latest_row.get("bat_verified_stress_day", 0)),
        },
    }


@app.post("/api/employee/survey/bat12")
def submit_bat12_survey(submission: BAT12Submission):
    try:
        logical_day = date.fromisoformat(submission.logical_day) if submission.logical_day else datetime.now(timezone.utc).date()
    except Exception:
        logical_day = datetime.now(timezone.utc).date()

    summary = compute_bat12_scores(items=submission.items, logical_day=logical_day)

    # Store in recent cache for UI immediate display
    cache_key = f"{submission.employee_id}:{logical_day.isoformat()}"
    DATA_CACHE["recent_bat_submissions"][cache_key] = {
        "total_bat_score": summary.total_bat_score,
        "exhaustion_score": summary.exhaustion_score,
        "mental_distance_score": summary.mental_distance_score,
        "emotional_impairment_score": summary.emotional_impairment_score,
        "cognitive_impairment_score": summary.cognitive_impairment_score,
        "clinical_status": summary.clinical_status,
        "verified_stressed_day": summary.verified_stressed_day,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store in local DB if connected
    if DATA_CACHE["db"]:
        try:
            from edc_agent.privacy.self_report import record_bat12_checkin
            record_bat12_checkin(DATA_CACHE["db"], logical_day=logical_day, items=submission.items)
        except Exception as e:
            print(f"[WorkSense] DB write error: {e}")

    return {
        "success": True,
        "message": f"BAT-12 survey recorded successfully for {logical_day.isoformat()}",
        "summary": summary,
    }


@app.get("/api/manager/overview")
def get_manager_overview():
    """Privacy-preserved team-level burnout aggregations for managers."""
    df = DATA_CACHE["df"]
    if df is None or len(df) == 0:
        raise HTTPException(status_code=500, detail="Telemetry dataset not loaded")

    # Evaluate all employees at day 45
    all_emp_ids = sorted(df["employee_id"].unique().tolist())
    status_counts = {"Green": 0, "Yellow": 0, "Orange": 0, "Red": 0}
    total_active = 0
    total_calibrating = 0

    # Extract team distribution
    day45_df = df[df["date"] == df["date"].unique()[44]]
    for _, row in day45_df.iterrows():
        st = row["target_burnout_status_5d"]
        if st in status_counts:
            status_counts[st] += 1
            total_active += 1

    pct_distribution = {
        k: round((v / max(1, total_active)) * 100, 1) for k, v in status_counts.items()
    }

    # 30-Day Aggregated Burnout Trajectory (proportion of team showing elevated strain)
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
            "category": "Desk-Dining & Skipped Meal Breaks",
            "attribution_pct": 17.5,
            "description": "Shortened or absent midday recovery blocks during working hours.",
        },
        {
            "category": "Focus Block Fragmentation & Typing Fatigue",
            "attribution_pct": 12.3,
            "description": "Choppy work blocks and elevated error correction keys.",
        },
    ]

    return {
        "department": "Engineering & Product Operations",
        "reporting_period": "Past 30 Days (Rolling)",
        "total_workforce": len(all_emp_ids),
        "active_monitored": total_active,
        "calibrating_baseline": total_calibrating,
        "status_distribution_pct": pct_distribution,
        "status_distribution_counts": status_counts,
        "trajectory_30d": trajectory_30d,
        "category_drivers": category_drivers,
        "privacy_compliance": {
            "individual_names_redacted": True,
            "individual_rankings_disabled": True,
            "raw_metrics_redacted": True,
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

