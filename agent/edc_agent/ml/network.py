"""WorkSense Temporal Attention Neural Network for Burnout Early Warning."""
from typing import Any, Dict, List, Optional, Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F

from edc_agent.ml.features import CATEGORY_MAPPINGS, CORE_NUMERICAL_FEATURES, INT_TO_STATUS


class TemporalAttention(nn.Module):
    """Computes learnable temporal attention weights over sequential days."""

    def __init__(self, hidden_dim: int):
        super().__init__()
        self.proj = nn.Linear(hidden_dim, hidden_dim // 2)
        self.v = nn.Linear(hidden_dim // 2, 1, bias=False)

    def forward(self, hidden_states: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        # hidden_states: (batch_size, seq_len, hidden_dim)
        scores = torch.tanh(self.proj(hidden_states))  # (B, T, H//2)
        attn_logits = self.v(scores)  # (B, T, 1)
        weights = F.softmax(attn_logits, dim=1)  # (B, T, 1)
        context = torch.sum(weights * hidden_states, dim=1)  # (B, H)
        return context, weights.squeeze(-1)  # context: (B, H), weights: (B, T)


class WorkSenseTemporalNN(nn.Module):
    """Temporal BiGRU Attention Neural Network for WorkSense Burnout Prediction.

    Architecture:
    1. Feature projection with LayerNorm and GELU
    2. 2-layer Bidirectional GRU capturing multi-day trajectory momentum
    3. Temporal Attention Pooling identifying high-stress transition days
    4. Dual heads:
       - Multi-class classification (Green / Yellow / Orange / Red)
       - Continuous risk regression (0.0 to 1.0)
    5. Privacy-preserving Category Attribution engine
    """

    def __init__(
        self,
        input_dim: int = len(CORE_NUMERICAL_FEATURES),
        hidden_dim: int = 64,
        num_classes: int = 4,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_classes = num_classes

        # 1. Feature Projection
        self.feature_proj = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout * 0.75),
        )

        # 2. Recurrent Temporal Backbone (BiGRU)
        self.gru = nn.GRU(
            input_size=hidden_dim,
            hidden_size=hidden_dim // 2,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if dropout > 0 else 0.0,
        )

        # 3. Temporal Attention
        self.attention = TemporalAttention(hidden_dim)
        self.post_attn_norm = nn.LayerNorm(hidden_dim)

        # 4. Classification Head (4 Classes)
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.LayerNorm(hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, num_classes),
        )

        # 5. Continuous Risk Regression Head (0.0 to 1.0)
        self.regressor = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout * 0.5),
            nn.Linear(hidden_dim // 2, 1),
            nn.Sigmoid(),
        )

        # Store feature index mapping for category explainability
        self.feature_indices = {feat: idx for idx, feat in enumerate(CORE_NUMERICAL_FEATURES[:input_dim])}

    def forward(
        self, x: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Forward pass.

        Args:
            x: Tensor of shape (batch_size, seq_len, input_dim) with normalized features.

        Returns:
            logits: (batch_size, num_classes)
            risk: (batch_size, 1) continuous score in [0.0, 1.0]
            attn_weights: (batch_size, seq_len) attention over days
        """
        # x: (B, T, D)
        proj = self.feature_proj(x)  # (B, T, H)
        gru_out, _ = self.gru(proj)  # (B, T, H)

        # Temporal attention pooling
        context, attn_weights = self.attention(gru_out)  # context: (B, H), attn: (B, T)

        # Residual skip connection from the most recent day (timestep -1)
        h_last = gru_out[:, -1, :]
        fused = self.post_attn_norm(context + h_last)  # (B, H)

        logits = self.classifier(fused)  # (B, num_classes)
        risk = self.regressor(fused)  # (B, 1)

        return logits, risk, attn_weights

    def explain_prediction(
        self,
        x_single: torch.Tensor,
        attn_weights: torch.Tensor,
    ) -> Dict[str, Any]:
        """Generate privacy-preserving broad category attributions for an individual sequence.

        Aggregates deviation magnitudes across the 4 WorkSense categories weighted by daily attention.
        Never reveals raw metrics or keystroke contents to managers.

        Args:
            x_single: Tensor of shape (seq_len, input_dim) with normalized z-scores.
            attn_weights: Tensor of shape (seq_len,) from the attention layer.

        Returns:
            Dict containing relative category percentages and top contributing factors.
        """
        # Attention-weighted absolute deviation across time for each feature
        # (T, 1) * (T, D) -> (D,)
        weights = attn_weights.unsqueeze(-1).to(x_single.device)
        weighted_deviations = torch.sum(torch.abs(x_single) * weights, dim=0).detach().cpu().numpy()

        category_scores: Dict[str, float] = {}
        for cat_name, cat_feats in CATEGORY_MAPPINGS.items():
            valid_indices = [
                self.feature_indices[feat]
                for feat in cat_feats
                if feat in self.feature_indices
            ]
            if valid_indices:
                cat_sum = float(weighted_deviations[valid_indices].sum())
                category_scores[cat_name] = cat_sum
            else:
                category_scores[cat_name] = 0.0

        total_score = sum(category_scores.values()) + 1e-6
        category_percentages = {
            k: round((v / total_score) * 100.0, 1) for k, v in category_scores.items()
        }

        # Human-readable labels for manager reports
        category_labels = {
            "boundary_erosion": "Late-Night & After-Hours Communication",
            "work_pattern_changes": "Extended Work Stretches & Irregular Breaks",
            "recovery_deficit": "Skipped Lunch & Midday Break Recovery",
            "cognitive_and_focus_fatigue": "Focus Block Fragmentation & Typing Fatigue",
        }

        # Sort categories by attribution percentage descending
        ranked_categories = sorted(
            category_percentages.items(), key=lambda item: item[1], reverse=True
        )

        top_drivers = [
            {
                "category_key": k,
                "label": category_labels.get(k, k),
                "attribution_pct": pct,
            }
            for k, pct in ranked_categories
            if pct >= 15.0  # Only include meaningful contributors
        ]

        return {
            "category_attributions": category_percentages,
            "primary_drivers": top_drivers,
            "attention_timeline": attn_weights.detach().cpu().tolist(),
        }
