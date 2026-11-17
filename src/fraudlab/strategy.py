"""
Fraud strategy economics: champion/challenger comparison and cutoff optimisation.

Every application reaching the fraud step is assumed credit-approved; the fraud decision
determines whether it is auto-approved, conditioned (STIP), manually reviewed, or declined.
The economic model converts each outcome into dollars so that cutoffs are set on
expected value, subject to manual-review capacity.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .rules_engine import decide


@dataclass
class Economics:
    review_catch_rate: float = 0.85      # analyst detects fraud in review
    review_good_abandon: float = 0.05    # good customers lost due to review delay
    stip_fraud_capture: float = 0.65     # fraud that fails / abandons a stip
    stip_good_abandon: float = 0.08
    profit_per_good_loan: float = 1_850.0  # lifetime NPV of a good funded loan
    cost_per_review: float = 38.0

    @classmethod
    def from_policy(cls, policy: dict) -> "Economics":
        s = policy.get("stip_assumptions", {})
        return cls(stip_fraud_capture=s.get("fraud_capture_rate", 0.65),
                   stip_good_abandon=s.get("good_abandon_rate", 0.08),
                   cost_per_review=policy["review_capacity"]["cost_per_review_usd"])


def outcome_economics(df: pd.DataFrame, decision: pd.Series, eco: Economics) -> pd.DataFrame:
    """Expected $ outcome per application given its decision."""
    f = df["is_fraud"].values == 1
    loss = df["loss_if_funded"].values
    d = decision.values
    caught = np.select(
        [d == "DECLINE", d == "REVIEW", d == "STIP"],
        [1.0, eco.review_catch_rate, eco.stip_fraud_capture], 0.0)
    good_lost = np.select(
        [d == "DECLINE", d == "REVIEW", d == "STIP"],
        [1.0, eco.review_good_abandon, eco.stip_good_abandon], 0.0)
    return pd.DataFrame({
        "fraud_caught": np.where(f, caught, 0.0),
        "fraud_loss": np.where(f, (1 - caught) * loss, 0.0),
        "loss_prevented": np.where(f, caught * loss, 0.0),
        "good_lost": np.where(~f, good_lost, 0.0),
        "friction_cost": np.where(~f, good_lost * eco.profit_per_good_loan, 0.0),
        "review_cost": np.where(d == "REVIEW", eco.cost_per_review, 0.0),
    }, index=df.index)


def summarise(df: pd.DataFrame, decision: pd.Series, eco: Economics, label: str) -> dict:
    e = outcome_economics(df, decision, eco)
    f = df.is_fraud == 1
    good = ~f
    months = df.app_month.nunique()
    total_loss = df.loc[f, "loss_if_funded"].sum()
    flagged = decision != "APPROVE"
    return {
        "strategy": label,
        "applications": int(len(df)),
        "auto_approval_rate": float((decision == "APPROVE").mean()),
        "stip_rate": float((decision == "STIP").mean()),
        "manual_review_rate": float((decision == "REVIEW").mean()),
        "decline_rate": float((decision == "DECLINE").mean()),
        "reviews_per_month": float((decision == "REVIEW").sum() / months),
        "fraud_capture_rate_count": float(e.loc[f, "fraud_caught"].sum() / max(1, f.sum())),
        "fraud_capture_rate_usd": float(e["loss_prevented"].sum() / max(1, total_loss)),
        "false_positive_rate": float(flagged[good].mean()),
        "alert_to_fraud_ratio": float(flagged.sum() / max(1, (flagged & f).sum())),
        "good_customer_friction_rate": float(e.loc[good, "good_lost"].mean()),
        "residual_fraud_loss_usd": float(e["fraud_loss"].sum()),
        "loss_prevented_usd": float(e["loss_prevented"].sum()),
        "friction_cost_usd": float(e["friction_cost"].sum()),
        "review_cost_usd": float(e["review_cost"].sum()),
        "total_cost_usd": float(e[["fraud_loss", "friction_cost", "review_cost"]].sum().sum()),
        "fraud_loss_bps": float(1e4 * e["fraud_loss"].sum() / df["amount_financed"].sum()),
    }


def champion_vs_challenger(df, policy, score, eco: Economics | None = None):
    eco = eco or Economics.from_policy(policy)
    champ = decide(df, policy, "champion")
    chall = decide(df, policy, "challenger", model_score=score)
    res = pd.DataFrame([
        summarise(df, champ.decision, eco, "Champion (legacy rules)"),
        summarise(df, chall.decision, eco, "Challenger (rules + ML)"),
    ])
    return res, champ, chall


def review_capacity_per_month(policy: dict) -> float:
    c = policy["review_capacity"]
    return c["analysts"] * c["reviews_per_analyst_per_day"] * c["working_days_per_month"]


def optimise_cutoffs(df, policy, score, eco: Economics | None = None,
                     review_grid=None, decline_grid=None,
                     min_auto_approval: float = 0.82) -> pd.DataFrame:
    """
    Grid search on (review, decline) ML cutoffs with challenger rules held fixed.
    Returns total expected cost and feasibility for each pair. A pair is feasible when manual
    review volume fits analyst capacity AND auto-approval stays above the dealer-experience floor
    (`min_auto_approval`) -- the two operating constraints that matter in a dealer-channel LOS.
    """
    eco = eco or Economics.from_policy(policy)
    review_grid = review_grid if review_grid is not None else [0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
    decline_grid = decline_grid if decline_grid is not None else [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    cap = review_capacity_per_month(policy)
    # rules-only base decision computed once
    base = decide(df, policy, "challenger")
    from .rules_engine import ACTION_RANK, RANK_ACTION
    base_rank = base.decision.map(ACTION_RANK).values
    s = np.asarray(score)
    rows = []
    for rc in review_grid:
        for dc in decline_grid:
            if dc <= rc:
                continue
            mr = np.where(s >= dc, 3, np.where(s >= rc, 2, 0))
            dec = pd.Series([RANK_ACTION[x] for x in np.maximum(base_rank, mr)], index=df.index)
            m = summarise(df, dec, eco, f"r{rc}_d{dc}")
            m.update(review_cutoff=rc, decline_cutoff=dc,
                     within_capacity=m["reviews_per_month"] <= cap,
                     feasible=(m["reviews_per_month"] <= cap) and (m["auto_approval_rate"] >= min_auto_approval))
            rows.append(m)
    return (pd.DataFrame(rows).sort_values(["feasible", "total_cost_usd"], ascending=[False, True])
            .reset_index(drop=True))
