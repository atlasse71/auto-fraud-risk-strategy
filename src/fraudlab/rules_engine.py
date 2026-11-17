"""
Config-driven fraud decisioning rules engine.

Mirrors how fraud rules are deployed inside an auto Loan Origination System (LOS):
a versioned policy file, deterministic evaluation, a decision hierarchy
(DECLINE > REVIEW > STIP > APPROVE), and adverse-action-ready reason codes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ACTION_RANK = {"APPROVE": 0, "STIP": 1, "REVIEW": 2, "DECLINE": 3}
RANK_ACTION = {v: k for k, v in ACTION_RANK.items()}

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "config" / "decision_rules.yaml"


def load_policy(path: str | Path = DEFAULT_POLICY) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def evaluate_rules(df: pd.DataFrame, policy: dict, strategy: str = "challenger") -> pd.DataFrame:
    """Return a boolean hit matrix (apps x rules) for rules active in `strategy`."""
    hits = {}
    for rule in policy["rules"]:
        if strategy not in rule["strategies"]:
            continue
        try:
            res = df.eval(rule["condition"], engine="python")
        except Exception as exc:  # fail loudly: a broken rule must never silently pass
            raise ValueError(f"Rule {rule['id']} failed to evaluate: {exc}") from exc
        hits[rule["id"]] = pd.Series(res, index=df.index).fillna(False).astype(bool)
    return pd.DataFrame(hits, index=df.index)


def decide(
    df: pd.DataFrame,
    policy: dict,
    strategy: str = "challenger",
    model_score: pd.Series | np.ndarray | None = None,
) -> pd.DataFrame:
    """
    Produce a fraud decision per application.

    Returns columns: decision, reason_codes, n_rules_hit, plus rule hit flags.
    For the challenger strategy, the ML score is layered on top of rules using
    the cutoffs in policy['model_cutoffs'].
    """
    hits = evaluate_rules(df, policy, strategy)
    rule_action = {r["id"]: r["action"] for r in policy["rules"]}
    rank = np.zeros(len(df), dtype=int)
    for rid in hits.columns:
        rank = np.where(hits[rid].values, np.maximum(rank, ACTION_RANK[rule_action[rid]]), rank)

    reasons = hits.apply(lambda row: ";".join(row.index[row.values]), axis=1)

    if model_score is not None and strategy == "challenger":
        s = np.asarray(model_score)
        cut = policy["model_cutoffs"]
        model_rank = np.where(s >= cut["decline_at_or_above"], ACTION_RANK["DECLINE"],
                              np.where(s >= cut["review_at_or_above"], ACTION_RANK["REVIEW"], 0))
        reasons = np.where(model_rank > 0,
                           np.where(reasons == "", "ML-SCORE", reasons + ";ML-SCORE"), reasons)
        rank = np.maximum(rank, model_rank)

    out = pd.DataFrame({
        "decision": [RANK_ACTION[r] for r in rank],
        "reason_codes": reasons,
        "n_rules_hit": hits.sum(axis=1).values,
    }, index=df.index)
    return pd.concat([out, hits.add_prefix("hit_")], axis=1)


def rule_performance(df: pd.DataFrame, hits: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """Per-rule hit rate, precision, fraud capture, and $ loss covered -- the rule-tuning view."""
    total_fraud = df["is_fraud"].sum()
    total_loss = df.loc[df.is_fraud == 1, "loss_if_funded"].sum()
    meta = {r["id"]: r for r in policy["rules"]}
    rows = []
    for rid in hits.columns:
        h = hits[rid]
        n = int(h.sum())
        tp = int((h & (df.is_fraud == 1)).sum())
        rows.append({
            "rule_id": rid,
            "name": meta[rid]["name"],
            "typology": meta[rid]["typology"],
            "action": meta[rid]["action"],
            "hits": n,
            "hit_rate": n / len(df),
            "precision": tp / n if n else np.nan,
            "fraud_capture": tp / total_fraud if total_fraud else np.nan,
            "false_positive_ratio": (n - tp) / tp if tp else np.nan,
            "loss_covered_usd": df.loc[h & (df.is_fraud == 1), "loss_if_funded"].sum(),
            "loss_covered_pct": df.loc[h & (df.is_fraud == 1), "loss_if_funded"].sum() / total_loss,
        })
    return pd.DataFrame(rows).sort_values("loss_covered_usd", ascending=False)
