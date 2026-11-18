"""Training loop and evaluation harness for WorkSense Neural Network."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import classification_report, confusion_matrix, f1_score, mean_squared_error

from edc_agent.ml.features import INT_TO_STATUS
from edc_agent.ml.network import WorkSenseTemporalNN


@dataclass
class TrainingMetrics:
    epoch: int
    train_loss: float
    val_loss: float
    val_accuracy: float
    val_macro_f1: float
    val_mse: float


class WorkSenseTrainer:
    """Trains and evaluates the WorkSense Temporal Neural Network."""

    def __init__(
        self,
        model: WorkSenseTemporalNN,
        class_weights: Optional[torch.Tensor] = None,
        lr: float = 1e-3,
        weight_decay: float = 1e-4,
        reg_weight: float = 0.5,
        device: Optional[str] = None,
    ):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(self.device)
        self.reg_weight = reg_weight

        if class_weights is not None:
            self.class_weights = class_weights.to(self.device)
            self.ce_loss = nn.CrossEntropyLoss(weight=self.class_weights)
        else:
            self.ce_loss = nn.CrossEntropyLoss()

        self.mse_loss = nn.MSELoss()
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(), lr=lr, weight_decay=weight_decay
        )
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, mode="max", factor=0.5, patience=3
        )

    def train_epoch(self, dataloader) -> Tuple[float, float, float]:
        self.model.train()
        total_loss = 0.0
        total_ce = 0.0
        total_mse = 0.0
        n_batches = 0

        for X, y_class, y_risk in dataloader:
            X = X.to(self.device)
            y_class = y_class.to(self.device)
            y_risk = y_risk.to(self.device)

            self.optimizer.zero_grad()
            logits, pred_risk, _ = self.model(X)

            loss_ce = self.ce_loss(logits, y_class)
            loss_mse = self.mse_loss(pred_risk, y_risk)
            loss = loss_ce + (self.reg_weight * loss_mse)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            total_loss += loss.item()
            total_ce += loss_ce.item()
            total_mse += loss_mse.item()
            n_batches += 1

        denom = max(1, n_batches)
        return total_loss / denom, total_ce / denom, total_mse / denom

    @torch.no_grad()
    def evaluate(self, dataloader) -> Dict[str, Any]:
        self.model.eval()
        total_loss = 0.0
        n_batches = 0

        all_preds: List[int] = []
        all_targets: List[int] = []
        all_pred_risks: List[float] = []
        all_target_risks: List[float] = []

        for X, y_class, y_risk in dataloader:
            X = X.to(self.device)
            y_class = y_class.to(self.device)
            y_risk = y_risk.to(self.device)

            logits, pred_risk, _ = self.model(X)

            loss_ce = self.ce_loss(logits, y_class)
            loss_mse = self.mse_loss(pred_risk, y_risk)
            loss = loss_ce + (self.reg_weight * loss_mse)

            total_loss += loss.item()
            n_batches += 1

            preds = torch.argmax(logits, dim=-1).cpu().numpy()
            all_preds.extend(preds.tolist())
            all_targets.extend(y_class.cpu().numpy().tolist())

            all_pred_risks.extend(pred_risk.squeeze(-1).cpu().numpy().tolist())
            all_target_risks.extend(y_risk.squeeze(-1).cpu().numpy().tolist())

        y_true = np.array(all_targets)
        y_pred = np.array(all_preds)
        r_true = np.array(all_target_risks)
        r_pred = np.array(all_pred_risks)

        accuracy = float((y_true == y_pred).mean()) if len(y_true) > 0 else 0.0
        macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
        weighted_f1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
        mse = float(mean_squared_error(r_true, r_pred)) if len(r_true) > 0 else 0.0

        # Detailed classification report
        class_names = [INT_TO_STATUS.get(i, str(i)) for i in range(4)]
        report = classification_report(
            y_true, y_pred, target_names=class_names, output_dict=True, zero_division=0
        )
        conf_matrix = confusion_matrix(y_true, y_pred, labels=[0, 1, 2, 3]).tolist()

        # High-risk early warning sensitivity (detection of Orange and Red classes)
        high_risk_mask = (y_true >= 2)
        if high_risk_mask.sum() > 0:
            warning_sensitivity = float((y_pred[high_risk_mask] >= 2).sum() / high_risk_mask.sum())
        else:
            warning_sensitivity = 1.0

        return {
            "loss": total_loss / max(1, n_batches),
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "weighted_f1": weighted_f1,
            "mse": mse,
            "warning_sensitivity": warning_sensitivity,
            "report": report,
            "confusion_matrix": conf_matrix,
            "y_true": y_true,
            "y_pred": y_pred,
            "r_true": r_true,
            "r_pred": r_pred,
        }

    def fit(
        self,
        train_loader,
        val_loader,
        epochs: int = 35,
        early_stopping_patience: int = 8,
        checkpoint_path: Optional[Path] = None,
    ) -> List[TrainingMetrics]:
        """Fit the model using early stopping on validation Macro F1."""
        history: List[TrainingMetrics] = []
        best_val_f1 = -1.0
        patience_counter = 0

        for epoch in range(1, epochs + 1):
            train_loss, train_ce, train_mse = self.train_epoch(train_loader)
            val_results = self.evaluate(val_loader)

            val_loss = val_results["loss"]
            val_acc = val_results["accuracy"]
            val_f1 = val_results["macro_f1"]
            val_mse = val_results["mse"]

            self.scheduler.step(val_f1)

            metrics = TrainingMetrics(
                epoch=epoch,
                train_loss=train_loss,
                val_loss=val_loss,
                val_accuracy=val_acc,
                val_macro_f1=val_f1,
                val_mse=val_mse,
            )
            history.append(metrics)

            if val_f1 > best_val_f1:
                best_val_f1 = val_f1
                patience_counter = 0
                if checkpoint_path is not None:
                    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self.model.state_dict(), checkpoint_path)
            else:
                patience_counter += 1

            if patience_counter >= early_stopping_patience:
                break

        # Load best weights if saved
        if checkpoint_path is not None and checkpoint_path.exists():
            self.model.load_state_dict(
                torch.load(checkpoint_path, map_location=self.device, weights_only=True)
            )

        return history
