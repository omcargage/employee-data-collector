"""High-level WorkSense inference predictor for desktop agent and UI integration."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from edc_agent.ml.features import (
    CORE_NUMERICAL_FEATURES,
    INT_TO_STATUS,
    PersonalBaselineTransformer,
)
from edc_agent.ml.network import WorkSenseTemporalNN


class WorkSenseBurnoutPredictor:
    """Production inference engine for WorkSense 5-day forward burnout early warning."""

    def __init__(
        self,
        model: WorkSenseTemporalNN,
        transformer: PersonalBaselineTransformer,
        device: Optional[str] = None,
    ):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(self.device)
        self.model.eval()
        self.transformer = transformer

    @classmethod
    def load(
        cls,
        model_path: Union[str, Path],
        config_path: Optional[Union[str, Path]] = None,
        device: Optional[str] = None,
    ) -> "WorkSenseBurnoutPredictor":
        """Load trained model weights and architecture configuration from disk."""
        m_path = Path(model_path)
        if not m_path.exists():
            raise FileNotFoundError(f"Model file not found at: {m_path}")

        c_path = Path(config_path) if config_path else m_path.parent / "model_config.json"
        if c_path.exists():
            with open(c_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {
                "input_dim": len(CORE_NUMERICAL_FEATURES),
                "hidden_dim": 64,
                "num_classes": 4,
                "features": CORE_NUMERICAL_FEATURES,
            }

        features = config.get("features", CORE_NUMERICAL_FEATURES)
        transformer = PersonalBaselineTransformer(features=features)

        model = WorkSenseTemporalNN(
            input_dim=config.get("input_dim", len(features)),
            hidden_dim=config.get("hidden_dim", 64),
            num_classes=config.get("num_classes", 4),
        )
        state_dict = torch.load(m_path, map_location=device or "cpu", weights_only=True)
        model.load_state_dict(state_dict)

        return cls(model=model, transformer=transformer, device=device)

    @torch.no_grad()
    def predict_daily(
        self,
        employee_history_df: pd.DataFrame,
        current_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate 5-day forward burnout prediction from an employee's chronological history.

        Args:
            employee_history_df: DataFrame of daily observations for one employee.
            current_date: Optional specific date to evaluate. If None, uses latest date.

        Returns:
            Dict containing predicted status, confidence, risk score, and privacy-preserving explanations.
        """
        df = employee_history_df.sort_values("date").copy().reset_index(drop=True)
        if current_date:
            df = df[df["date"] <= current_date].reset_index(drop=True)

        n_days = len(df)
        emp_id = str(df["employee_id"].iloc[0]) if n_days > 0 and "employee_id" in df else "UNKNOWN"

        # 1. Check WorkSense 14-day calibration rule
        if n_days < self.transformer.baseline_days:
            return {
                "employee_id": emp_id,
                "date": str(df["date"].iloc[-1]) if n_days > 0 else "UNKNOWN",
                "status": "INSUFFICIENT_DATA",
                "status_code": -1,
                "calibration_progress": {
                    "days_collected": n_days,
                    "days_required": self.transformer.baseline_days,
                    "progress_pct": round((n_days / self.transformer.baseline_days) * 100, 1),
                },
                "risk_score": None,
                "confidence": None,
                "probabilities": None,
                "explanation": f"Personal baseline calibrating: Day {n_days} of {self.transformer.baseline_days} complete.",
                "drivers": [],
            }

        # 2. Compute personal baseline from initial 14 days
        baseline_stats = self.transformer.fit_employee_baseline(df)
        norm_df = self.transformer.transform_employee(df, baseline=baseline_stats)

        # 3. Extract 7-day temporal window
        seq_len = self.transformer.sequence_length
        if len(norm_df) < seq_len:
            # Fallback pad with first day if exactly 14 days
            pad_needed = seq_len - len(norm_df)
            pad_rows = pd.concat([norm_df.iloc[[0]] * 0] * pad_needed, ignore_index=True)
            norm_df = pd.concat([pad_rows, norm_df], ignore_index=True)

        norm_cols = [f"{col}_norm" for col in self.transformer.features]
        seq_slice = norm_df.iloc[-seq_len:][norm_cols].to_numpy(dtype=np.float32)
        seq_slice = np.nan_to_num(seq_slice, nan=0.0)

        # 4. Neural Network Inference
        x_tensor = torch.tensor(seq_slice, dtype=torch.float32, device=self.device).unsqueeze(0)  # (1, T, D)
        logits, pred_risk, attn_weights = self.model(x_tensor)

        probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
        pred_class_idx = int(np.argmax(probs))
        pred_status = INT_TO_STATUS.get(pred_class_idx, "Green")
        risk_scalar = float(pred_risk.squeeze().cpu().numpy())
        confidence = float(probs[pred_class_idx])

        # 5. Broad-category privacy-preserving explanation
        explanation_data = self.model.explain_prediction(x_tensor.squeeze(0), attn_weights.squeeze(0))

        # Status human descriptions
        status_guidance = {
            "Green": "Healthy behavioral patterns within personal baseline range.",
            "Yellow": "Mild deviations detected. Early cautionary signs in workload rhythm.",
            "Orange": "Elevated behavioral strain across multiple dimensions. Impending burnout risk flagged.",
            "Red": "Severe behavioral disruption and sustained fatigue patterns. Immediate intervention recommended.",
        }

        return {
            "employee_id": emp_id,
            "date": str(df["date"].iloc[-1]),
            "predicted_status_5d": pred_status,
            "status_code": pred_class_idx,
            "confidence": round(confidence, 3),
            "risk_score": round(risk_scalar, 3),
            "status_description": status_guidance.get(pred_status, ""),
            "class_probabilities": {
                INT_TO_STATUS[i]: round(float(probs[i]), 3) for i in range(4)
            },
            "category_attributions": explanation_data["category_attributions"],
            "primary_drivers": explanation_data["primary_drivers"],
            "temporal_attention": [round(w, 3) for w in explanation_data["attention_timeline"]],
        }
