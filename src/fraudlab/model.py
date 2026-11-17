"""
Underwriting fraud ML model: feature engineering, training, calibration and validation.

Design choices (documented for Model Risk Management):
  * Gradient-boosted trees (HistGradientBoosting) - native missing-value handling, which matters
    for thin/no-file applicants where bureau and bank-data fields are legitimately absent.
  * Out-of-time validation: train on months 1-8, calibrate on 9-10, test on 11-12.
  * Isotonic calibration so the score is a probability usable directly as a policy cutoff.
  * Monitoring: AUC, KS, capture-at-review-rate, PSI (stability), permutation importance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

BASE_FEATURES = [
    "applicant_age", "ssn_issue_age", "phone_tenure_days", "email_tenure_days",
    "time_at_address_months", "bureau_score", "tradelines", "oldest_tradeline_months",
    "au_tradelines", "inquiries_6m", "bureau_name_dob_mismatch", "stated_income_monthly",
    "bank_data_linked", "income_ratio", "employer_verified", "paystub_edit_flag",
    "vehicle_price", "down_payment", "ltv", "term_months", "pti", "dti", "vehicle_to_income",
    "has_cobuyer", "dist_to_dealer_km", "ip_geo_mismatch_km", "device_apps_30d", "ssn_apps_30d",
    "phone_shared_count", "dealer_rapid_resubmits",
]
VENDOR_FEATURES = [
    "vendor_a_idv_risk", "vendor_b_synth_score", "vendor_c_device_risk", "vendor_d_income_flag_prob",
]
ENGINEERED = [
    "file_thin", "file_none", "addr_high_risk", "ssn_age_gap", "au_share",
    "credit_age_vs_ssn", "down_pct", "dealer_fraud_rate_prior",
]


def engineer(df: pd.DataFrame, dealer_rates: pd.Series | None = None) -> pd.DataFrame:
    X = df.copy()
    X["file_thin"] = (X.credit_file_type == "thin").astype(int)
    X["file_none"] = (X.credit_file_type == "no_file").astype(int)
    X["addr_high_risk"] = X.address_type.isin(["mail_drop", "commercial"]).astype(int)
    X["ssn_age_gap"] = X.applicant_age - X.ssn_issue_age
    X["au_share"] = X.au_tradelines / X.tradelines.replace(0, np.nan)
    # credit history older than the SSN has existed -> synthetic tell
    X["credit_age_vs_ssn"] = X.oldest_tradeline_months / 12 - (X.applicant_age - X.ssn_issue_age)
    X["down_pct"] = X.down_payment / X.vehicle_price
    if dealer_rates is not None:
        X["dealer_fraud_rate_prior"] = X.dealer_id.map(dealer_rates).fillna(dealer_rates.median())
    else:
        X["dealer_fraud_rate_prior"] = np.nan
    return X


def dealer_prior(train: pd.DataFrame, k: float = 50.0) -> pd.Series:
    """Bayesian-smoothed dealer fraud rate (target encoding fit on training window only)."""
    g = train.groupby("dealer_id")["is_fraud"].agg(["sum", "count"])
    p0 = train["is_fraud"].mean()
    return (g["sum"] + k * p0) / (g["count"] + k)


def ks_stat(y, s) -> float:
    fpr, tpr, _ = roc_curve(y, s)
    return float(np.max(tpr - fpr))


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    q = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    q[0], q[-1] = -np.inf, np.inf
    e = np.histogram(expected, q)[0] / len(expected)
    a = np.histogram(actual, q)[0] / len(actual)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


def capture_at_rate(y, s, rate: float) -> float:
    """Share of fraud captured when the top `rate` share of applications by score is flagged."""
    n = max(1, int(len(s) * rate))
    idx = np.argsort(-np.asarray(s))[:n]
    return float(np.asarray(y)[idx].sum() / max(1, np.asarray(y).sum()))


@dataclass
class FraudModel:
    features: list[str] = field(default_factory=lambda: BASE_FEATURES + VENDOR_FEATURES + ENGINEERED)
    random_state: int = 7
    model: object | None = None
    calibrated: object | None = None
    dealer_rates: pd.Series | None = None

    def _X(self, df):
        return engineer(df, self.dealer_rates)[self.features]

    def fit(self, train: pd.DataFrame, calib: pd.DataFrame):
        self.dealer_rates = dealer_prior(train)
        self.model = HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=100,
            l2_regularization=3.0, class_weight={0: 1, 1: 4}, random_state=self.random_state,
        )
        self.model.fit(self._X(train), train["is_fraud"])
        self.calibrated = CalibratedClassifierCV(FrozenEstimator(self.model), method="isotonic")
        self.calibrated.fit(self._X(calib), calib["is_fraud"])
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.calibrated.predict_proba(self._X(df))[:, 1]

    def evaluate(self, df: pd.DataFrame, name: str = "oot") -> dict:
        s = self.predict(df)
        y = df["is_fraud"].values
        return {
            "sample": name,
            "n": int(len(df)),
            "fraud_rate": float(y.mean()),
            "auc": float(roc_auc_score(y, s)),
            "pr_auc": float(average_precision_score(y, s)),
            "ks": ks_stat(y, s),
            "capture_at_2pct": capture_at_rate(y, s, 0.02),
            "capture_at_5pct": capture_at_rate(y, s, 0.05),
            "capture_at_10pct": capture_at_rate(y, s, 0.10),
        }

    def importance(self, df: pd.DataFrame, n_repeats: int = 3) -> pd.DataFrame:
        X = self._X(df)
        r = permutation_importance(self.model, X, df["is_fraud"], scoring="roc_auc",
                                   n_repeats=n_repeats, random_state=self.random_state, n_jobs=-1)
        return (pd.DataFrame({"feature": X.columns, "auc_drop": r.importances_mean})
                .sort_values("auc_drop", ascending=False).reset_index(drop=True))


def time_split(df: pd.DataFrame):
    months = sorted(df.app_month.unique())
    train = df[df.app_month.isin(months[:8])]
    calib = df[df.app_month.isin(months[8:10])]
    oot = df[df.app_month.isin(months[10:])]
    return train, calib, oot


def out_of_time_backtest_scores(df: pd.DataFrame, n_folds: int = 4) -> np.ndarray:
    """
    Shadow-mode backtest scores for every month: each block of months is scored by a model
    that never saw it (trained/calibrated on the remaining months). Used to show what the
    challenger *would* have done historically; the OOT test in `time_split` remains the
    official validation sample.
    """
    months = sorted(df.app_month.unique())
    blocks = np.array_split(np.array(months), n_folds)
    scores = np.full(len(df), np.nan)
    for blk in blocks:
        rest = [m for m in months if m not in blk]
        tr = df[df.app_month.isin(rest[:-2])]
        ca = df[df.app_month.isin(rest[-2:])]
        m = FraudModel().fit(tr, ca)
        idx = np.flatnonzero(df.app_month.isin(blk).values)
        scores[idx] = m.predict(df.iloc[idx])
    return scores
