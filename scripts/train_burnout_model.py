"""Train and evaluate the WorkSense Temporal Neural Network for Burnout Early Warning.

Features:
- Personal 14-day baseline normalization (Median / MAD)
- 7-day sliding sequence inputs with BiGRU and Temporal Attention
- Multi-task output: 4-class prediction (Green, Yellow, Orange, Red) + continuous risk score
- Split-by-Person cross-validation (Train 70%, Val 15%, Test 15%)
- Privacy-preserving broad category attribution
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import torch

from edc_agent.ml import (
    CORE_NUMERICAL_FEATURES,
    INT_TO_STATUS,
    PersonalBaselineTransformer,
    WorkSenseBurnoutPredictor,
    WorkSenseTemporalNN,
    WorkSenseTrainer,
    prepare_dataloaders,
)


def run_training_pipeline(
    data_path: Path,
    output_dir: Path,
    epochs: int = 40,
    batch_size: int = 32,
    hidden_dim: int = 64,
    lr: float = 1e-3,
    seed: int = 42,
) -> dict:
    print("=" * 70)
    print(" WorkSense Neural Network Training & Evaluation Pipeline")
    print("=" * 70)

    output_dir.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    print(f"Loading master dataset: {data_path}")

    df = pd.read_csv(data_path)
    print(f"Total dataset shape: {df.shape[0]} rows across {df['employee_id'].nunique()} employees")

    # 1. Setup Transformer & DataLoaders with strict Split-by-Person
    print("\n[Step 1/5] Setting up Personal 14-Day Baseline Normalization & Split-by-Person...")
    transformer = PersonalBaselineTransformer(
        features=CORE_NUMERICAL_FEATURES,
        baseline_days=14,
        sequence_length=7,
    )

    data_bundle = prepare_dataloaders(
        df=df,
        transformer=transformer,
        batch_size=batch_size,
        train_ratio=0.70,
        val_ratio=0.15,
        seed=seed,
    )

    counts = data_bundle["split_counts"]
    print(f"  Train: {counts['train_employees']} employees ({counts['train_samples']} 7-day windows)")
    print(f"  Val:   {counts['val_employees']} employees ({counts['val_samples']} 7-day windows)")
    print(f"  Test:  {counts['test_employees']} employees ({counts['test_samples']} 7-day windows)")
    print(f"  Class Weights (Balanced CE): {data_bundle['class_weights'].numpy().round(3)}")

    # 2. Instantiate Neural Network Architecture
    print(f"\n[Step 2/5] Initializing WorkSense Temporal BiGRU Attention Neural Network...")
    input_dim = len(CORE_NUMERICAL_FEATURES)
    model = WorkSenseTemporalNN(
        input_dim=input_dim,
        hidden_dim=hidden_dim,
        num_classes=4,
        dropout=0.2,
    )
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Input Features: {input_dim}")
    print(f"  Sequence Length: 7 days")
    print(f"  Hidden Dimension: {hidden_dim} (BiGRU)")
    print(f"  Trainable Parameters: {n_params:,}")

    # 3. Model Training with Early Stopping
    print(f"\n[Step 3/5] Training for up to {epochs} epochs (Early stopping patience = 8)...")
    checkpoint_path = output_dir / "worksense_nn.pt"
    trainer = WorkSenseTrainer(
        model=model,
        class_weights=data_bundle["class_weights"],
        lr=lr,
        device=device,
    )

    history = trainer.fit(
        train_loader=data_bundle["train_loader"],
        val_loader=data_bundle["val_loader"],
        epochs=epochs,
        early_stopping_patience=8,
        checkpoint_path=checkpoint_path,
    )
    print(f"  Training finished after {len(history)} epochs.")
    print(f"  Best Validation Macro F1: {max(h.val_macro_f1 for h in history):.4f}")

    # 4. Out-of-Sample Evaluation on Unseen Test Employees
    print("\n[Step 4/5] Evaluating on completely unseen Test Employees...")
    test_results = trainer.evaluate(data_bundle["test_loader"])

    test_acc = test_results["accuracy"]
    test_macro_f1 = test_results["macro_f1"]
    test_weighted_f1 = test_results["weighted_f1"]
    test_mse = test_results["mse"]
    test_sensitivity = test_results["warning_sensitivity"]
    cm = test_results["confusion_matrix"]

    print(f"\n--- TEST SET EVALUATION METRICS (Split-by-Person) ---")
    print(f"  Overall Accuracy:            {test_acc * 100:.2f}%")
    print(f"  Macro F1-Score:              {test_macro_f1:.4f}")
    print(f"  Weighted F1-Score:           {test_weighted_f1:.4f}")
    print(f"  Continuous Risk MSE:         {test_mse:.4f}")
    print(f"  5-Day Warning Sensitivity:   {test_sensitivity * 100:.2f}% (Orange/Red true positive rate)")

    print("\nPer-Class Classification Report:")
    for cls_name in ["Green", "Yellow", "Orange", "Red"]:
        metrics = test_results["report"].get(cls_name, {})
        prec = metrics.get("precision", 0.0)
        rec = metrics.get("recall", 0.0)
        f1 = metrics.get("f1-score", 0.0)
        support = metrics.get("support", 0)
        print(f"  {cls_name:8s} | Prec: {prec:.3f} | Recall: {rec:.3f} | F1: {f1:.3f} | Support: {support}")

    print("\nConfusion Matrix (Rows=True, Cols=Pred):")
    print("         Green Yellow Orange   Red")
    for idx, row in enumerate(cm):
        name = INT_TO_STATUS[idx]
        print(f"  {name:6s} {row[0]:6d} {row[1]:6d} {row[2]:6d} {row[3]:5d}")

    # 5. Save Model Config and Evaluation Summary
    print("\n[Step 5/5] Saving model artifacts...")
    model_config = {
        "input_dim": input_dim,
        "hidden_dim": hidden_dim,
        "num_classes": 4,
        "sequence_length": 7,
        "baseline_days": 14,
        "features": CORE_NUMERICAL_FEATURES,
        "classes": [INT_TO_STATUS[i] for i in range(4)],
    }
    with open(output_dir / "model_config.json", "w", encoding="utf-8") as f:
        json.dump(model_config, f, indent=2)

    eval_summary = {
        "test_accuracy": round(test_acc, 4),
        "test_macro_f1": round(test_macro_f1, 4),
        "test_weighted_f1": round(test_weighted_f1, 4),
        "continuous_risk_mse": round(test_mse, 4),
        "5d_warning_sensitivity": round(test_sensitivity, 4),
        "confusion_matrix": cm,
        "per_class_report": {
            cls: test_results["report"].get(cls)
            for cls in ["Green", "Yellow", "Orange", "Red"]
        },
        "split_counts": counts,
        "epochs_trained": len(history),
    }
    with open(output_dir / "evaluation_report.json", "w", encoding="utf-8") as f:
        json.dump(eval_summary, f, indent=2)

    # 6. Test Production Predictor with Sample Profiles
    print("\n[Verification] Testing production predictor on test profiles...")
    predictor = WorkSenseBurnoutPredictor.load(
        model_path=checkpoint_path,
        config_path=output_dir / "model_config.json",
    )

    # Pick 1 healthy employee and 1 stressed employee from the test set
    test_df = df[df["employee_id"].isin(
        [m["employee_id"] for m in data_bundle["test_dataset"].metadata]
    )]
    
    sample_healthy_id = None
    sample_stressed_id = None
    for emp_id, g in test_df.groupby("employee_id"):
        prof = g["profile"].iloc[0]
        if prof == "healthy" and sample_healthy_id is None:
            sample_healthy_id = emp_id
        elif prof == "stressed" and sample_stressed_id is None:
            sample_stressed_id = emp_id

    for test_id, label in [(sample_healthy_id, "HEALTHY PROFILE"), (sample_stressed_id, "STRESSED PROFILE")]:
        if not test_id:
            continue
        emp_records = df[df["employee_id"] == test_id].sort_values("date")
        
        # Test calibration day 7 (should be INSUFFICIENT_DATA)
        res_calib = predictor.predict_daily(emp_records.iloc[:7])
        print(f"\n  [{label}] Calibration Check (Day 7):")
        print(f"    Status: {res_calib['status']} - {res_calib['explanation']}")

        # Test day 45 (fully calibrated active inference)
        res_active = predictor.predict_daily(emp_records.iloc[:45])
        print(f"  [{label}] Active Prediction (Day 45):")
        print(f"    Employee: {res_active['employee_id']} | Date: {res_active['date']}")
        print(f"    5-Day Forward Status: {res_active['predicted_status_5d']} (Confidence: {res_active['confidence'] * 100:.1f}%)")
        print(f"    Continuous Burnout Risk: {res_active['risk_score']:.3f}")
        print(f"    Status Guidance: {res_active['status_description']}")
        print(f"    Primary Privacy-Preserving Drivers:")
        for d in res_active.get("primary_drivers", []):
            print(f"      - {d['label']}: {d['attribution_pct']}% attribution")

    print("\n" + "=" * 70)
    print(f" Pipeline completed successfully! Artifacts written to: {output_dir.resolve()}")
    print("=" * 70)

    return eval_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train WorkSense Burnout Neural Network")
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("Metric_data/daily_burnout_master.csv"),
        help="Path to daily_burnout_master.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("Metric_data/model"),
        help="Directory to save model weights and reports",
    )
    parser.add_argument("--epochs", type=int, default=30, help="Max training epochs")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--hidden-dim", type=int, default=64, help="BiGRU hidden dimension")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()
    run_training_pipeline(
        data_path=args.data,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        hidden_dim=args.hidden_dim,
        lr=args.lr,
        seed=args.seed,
    )
