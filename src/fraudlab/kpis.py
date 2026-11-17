"""
Underwriting fraud KPI framework.

KPI definitions (see docs/KPI_FRAMEWORK.md for owners, targets and escalation triggers):
  fraud_capture_rate      fraud apps stopped (declined / caught in review / failed stip) / all fraud apps
  dollar_capture_rate     $ loss prevented / $ loss exposure of all fraud apps
  auto_approval_rate      apps auto-approved by fraud step / all apps reaching fraud step
  manual_review_rate      apps routed to manual fraud review / all apps
  review_hit_rate         confirmed fraud in review queue / reviewed apps (queue precision)
  false_positive_rate     good apps not auto-approved / all good apps
  alert_to_fraud_ratio    flagged apps per confirmed fraud
  residual_loss_bps       uncaught fraud loss / $ amount financed (bps)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .strategy import Economics, outcome_economics


def monthly_kpis(df: pd.DataFrame, decision: pd.Series, eco: Economics) -> pd.DataFrame:
    e = outcome_economics(df, decision, eco)
    x = pd.concat([df[["app_month", "is_fraud", "loss_if_funded", "amount_financed"]],
                   decision.rename("decision"), e], axis=1)
    x["flagged"] = x.decision != "APPROVE"
    x["review"] = x.decision == "REVIEW"
    x["good"] = x.is_fraud == 0

    def agg(g):
        f = g.is_fraud == 1
        return pd.Series({
            "applications": len(g),
            "fraud_apps": int(f.sum()),
            "fraud_rate": f.mean(),
            "auto_approval_rate": (g.decision == "APPROVE").mean(),
            "manual_review_rate": g.review.mean(),
            "review_volume": int(g.review.sum()),
            "decline_rate": (g.decision == "DECLINE").mean(),
            "fraud_capture_rate": g.loc[f, "fraud_caught"].sum() / max(1, f.sum()),
            "dollar_capture_rate": g.loss_prevented.sum() / max(1, g.loc[f, "loss_if_funded"].sum()),
            "review_hit_rate": (g.review & f).sum() / max(1, g.review.sum()),
            "false_positive_rate": g.loc[g.good, "flagged"].mean(),
            "alert_to_fraud_ratio": g.flagged.sum() / max(1, (g.flagged & f).sum()),
            "loss_prevented_usd": g.loss_prevented.sum(),
            "residual_loss_usd": g.fraud_loss.sum(),
            "residual_loss_bps": 1e4 * g.fraud_loss.sum() / g.amount_financed.sum(),
        })

    return x.groupby("app_month").apply(agg, include_groups=False).reset_index()


def typology_capture(df: pd.DataFrame, decisions: dict[str, pd.Series], eco: Economics) -> pd.DataFrame:
    rows = []
    for name, dec in decisions.items():
        e = outcome_economics(df, dec, eco)
        for t, g in df[df.is_fraud == 1].groupby("fraud_type"):
            rows.append({"strategy": name, "typology": t, "fraud_apps": len(g),
                         "capture_rate": e.loc[g.index, "fraud_caught"].mean(),
                         "loss_exposure_usd": g.loss_if_funded.sum(),
                         "loss_prevented_usd": e.loc[g.index, "loss_prevented"].sum()})
    return pd.DataFrame(rows)


def dealer_watchlist(df: pd.DataFrame, min_apps: int = 40, top: int = 15) -> pd.DataFrame:
    """
    Dealer-level fraud concentration (straw-buyer & application-fraud rings commonly run through
    a small set of dealers). Uses a binomial z-score vs portfolio rate to rank statistically
    significant outliers rather than raw rates.
    """
    p0 = df.is_fraud.mean()
    g = df.groupby("dealer_id").agg(
        state=("dealer_state", "first"),
        apps=("app_id", "count"),
        fraud=("is_fraud", "sum"),
        straw=("fraud_type", lambda s: (s == "straw_buyer").sum()),
        app_fraud=("fraud_type", lambda s: (s == "application_fraud").sum()),
        avg_dist_km=("dist_to_dealer_km", "median"),
        resubmits=("dealer_rapid_resubmits", "mean"),
        exposure_usd=("loss_if_funded", lambda s: s[df.loc[s.index, "is_fraud"] == 1].sum()),
    )
    g = g[g.apps >= min_apps].copy()
    g["fraud_rate"] = g.fraud / g.apps
    g["z_score"] = (g.fraud - g.apps * p0) / np.sqrt(g.apps * p0 * (1 - p0))
    g["action"] = np.select([g.z_score >= 8, g.z_score >= 4], ["Suspend & audit", "Enhanced review"],
                            "Monitor")
    return g.sort_values("z_score", ascending=False).head(top).reset_index()
