"""Predictive model: probability that a market resolves YES.

Gradient boosting with isotonic calibration so output probabilities are usable
directly as fair-value estimates. Persisted with joblib; versioned in the DB.
"""

import os
from dataclasses import dataclass

import joblib
import numpy as np

from app.config import get_settings
from app.logging_config import get_logger
from app.ml.features import FEATURE_NAMES

log = get_logger(__name__)

MODEL_NAME = "outcome_gbm"


@dataclass
class TrainReport:
    n_samples: int
    brier: float
    log_loss: float
    baseline_brier: float  # market implied as predictor
    path: str


class OutcomeModel:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None

    # ------------------------------------------------------------ paths

    def _model_path(self) -> str:
        os.makedirs(self.settings.models_dir, exist_ok=True)
        return os.path.join(self.settings.models_dir, f"{MODEL_NAME}.joblib")

    # ------------------------------------------------------------ train

    def train(self, X: np.ndarray, y: np.ndarray) -> TrainReport:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import brier_score_loss, log_loss
        from sklearn.model_selection import train_test_split

        if len(X) < self.settings.ml_min_training_samples:
            raise ValueError(
                f"not enough training samples: {len(X)} < {self.settings.ml_min_training_samples}"
            )
        if len(np.unique(y)) < 2:
            raise ValueError("training labels are single-class; need both YES and NO outcomes")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
        base = GradientBoostingClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05, random_state=42
        )
        model = CalibratedClassifierCV(base, method="isotonic", cv=3)
        model.fit(X_train, y_train)

        probs = model.predict_proba(X_test)[:, 1]
        brier = float(brier_score_loss(y_test, probs))
        ll = float(log_loss(y_test, np.clip(probs, 1e-6, 1 - 1e-6)))
        implied_idx = FEATURE_NAMES.index("implied_prob")
        baseline = float(brier_score_loss(y_test, np.clip(X_test[:, implied_idx], 0.01, 0.99)))

        path = self._model_path()
        joblib.dump(model, path)
        self._model = model
        log.info("trained %s on %d samples — brier %.4f (market baseline %.4f)",
                 MODEL_NAME, len(X), brier, baseline)
        return TrainReport(n_samples=len(X), brier=brier, log_loss=ll, baseline_brier=baseline, path=path)

    # ------------------------------------------------------------ predict

    def load(self) -> bool:
        path = self._model_path()
        if not os.path.exists(path):
            return False
        try:
            self._model = joblib.load(path)
            return True
        except Exception:
            log.exception("failed to load model from %s", path)
            return False

    @property
    def available(self) -> bool:
        return self._model is not None or self.load()

    def predict_proba(self, features: list[float]) -> float | None:
        if not self.available:
            return None
        try:
            prob = float(self._model.predict_proba(np.asarray([features], dtype=float))[0, 1])
            return min(max(prob, 0.01), 0.99)
        except Exception:
            log.exception("model prediction failed")
            return None


_model: OutcomeModel | None = None


def get_outcome_model() -> OutcomeModel:
    global _model
    if _model is None:
        _model = OutcomeModel()
    return _model
