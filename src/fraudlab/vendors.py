"""
Third-party data provider governance: vendor scorecards and emerging-vendor POC evaluation.

Vendors are fictionalised archetypes of the categories a lender typically buys:
  A  Identity verification / PII linkage (KYC)
  B  Synthetic-identity scoring
  C  Device & behavioural intelligence
  D  Income & employment verification
  E  EMERGING consortium identity-graph (retro proof-of-concept, 35% sample)

The scorecard answers the questions a credit-risk committee asks at renewal:
  * Does the signal separate fraud on its own?           -> standalone AUC / KS
  * Does it add anything on top of everything else?      -> incremental (leave-one-out) lift
  * What does each catch cost?                           -> cost per incremental fraud caught
  * Is it worth the money?                               -> annualised net benefit / ROI
  * Is it reliable?                                      -> hit rate, latency, uptime vs SLA
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .model import FraudModel, capture_at_rate, ks_stat

VENDORS = {
    "vendor_a_idv_risk": dict(name="Vendor A - Identity Verification", category="KYC / PII linkage",
                             cost_per_call=0.85, latency_ms_p95=420, uptime=0.9993, hit_rate=0.982),
    "vendor_b_synth_score": dict(name="Vendor B - Synthetic ID Score", category="Synthetic identity",
                                cost_per_call=0.60, latency_ms_p95=310, uptime=0.9991, hit_rate=0.951),
    "vendor_c_device_risk": dict(name="Vendor C - Device Intelligence", category="Device / behavioural",
                                cost_per_call=0.35, latency_ms_p95=180, uptime=0.9978, hit_rate=0.934),
    "vendor_d_income_flag_prob": dict(name="Vendor D - Income Verification", category="Income / employment",
                                     cost_per_call=1.40, latency_ms_p95=1350, uptime=0.9962, hit_rate=0.889),
    "vendor_e_consortium_risk": dict(name="Vendor E - Consortium ID Graph (POC)", category="Consortium identity graph",
                                    cost_per_call=0.95, latency_ms_p95=260, uptime=0.9995, hit_rate=0.968),
}
SLA = {"latency_ms_p95": 800, "uptime": 0.999, "hit_rate": 0.92}


def _annualise(value, df):
    return value * 12 / df.app_month.nunique()


def _usd_at_rate(y, s, loss, rate):
    n = int(len(s) * rate)
    top = np.argsort(-s)[:n]
    return loss[top][y[top] == 1].sum()


def vendor_scorecard(train, calib, test, full_model: FraudModel, review_rate: float = 0.05,
                     annual_apps: int | None = None, seeds=(7, 17, 27)) -> pd.DataFrame:
    """
    Leave-one-vendor-out retraining to measure incremental value of each incumbent vendor.
    Full and reduced models are refit over several seeds and averaged, so the measured lift
    reflects the vendor's signal rather than training noise (early-stopping splits).
    """
    y = test.is_fraud.values
    loss = test.loss_if_funded.values
    full = [FraudModel(features=full_model.features, random_state=s).fit(train, calib).predict(test)
            for s in seeds]
    base_cap = np.mean([capture_at_rate(y, s, review_rate) for s in full])
    base_auc = np.mean([roc_auc_score(y, s) for s in full])
    annual_apps = annual_apps or int(_annualise(len(test), test))
    rows = []
    for col, meta in VENDORS.items():
        if col == "vendor_e_consortium_risk":
            continue
        sig = test[col].values
        ok = ~np.isnan(sig)
        stand_auc = roc_auc_score(y[ok], sig[ok])
        feats = [f for f in full_model.features if f != col]
        red = [FraudModel(features=feats, random_state=sd).fit(train, calib).predict(test) for sd in seeds]
        cap_wo = np.mean([capture_at_rate(y, s, review_rate) for s in red])
        auc_wo = np.mean([roc_auc_score(y, s) for s in red])
        # incremental $ = incremental capture x fraud $ exposure (stabler than raw $ at small n)
        inc_usd_annual = _annualise((base_cap - cap_wo) * loss[y == 1].sum(), test)
        inc_fraud_annual = _annualise((base_cap - cap_wo) * y.sum(), test)
        cost_annual = meta["cost_per_call"] * annual_apps
        rows.append({
            "vendor": meta["name"], "category": meta["category"], "feature": col,
            "standalone_auc": stand_auc, "standalone_ks": ks_stat(y[ok], sig[ok]),
            "incremental_auc": base_auc - auc_wo,
            "incremental_capture_pts": base_cap - cap_wo,
            "incremental_loss_prevented_annual": inc_usd_annual,
            "annual_cost": cost_annual,
            "net_benefit_annual": inc_usd_annual - cost_annual,
            "roi": (inc_usd_annual - cost_annual) / cost_annual,
            "cost_per_incremental_catch": cost_annual / inc_fraud_annual if inc_fraud_annual > 0 else np.inf,
            "latency_ms_p95": meta["latency_ms_p95"], "uptime": meta["uptime"], "hit_rate": meta["hit_rate"],
            "sla_breaches": sum([meta["latency_ms_p95"] > SLA["latency_ms_p95"], meta["uptime"] < SLA["uptime"],
                                 meta["hit_rate"] < SLA["hit_rate"]]),
        })
    out = pd.DataFrame(rows)
    out["recommendation"] = np.select(
        [(out.roi > 1.0) & (out.sla_breaches >= 2), out.roi > 1.0, out.roi > 0, out.roi <= 0],
        ["Renew with SLA remediation plan", "Renew", "Renegotiate price / tier usage",
         "Replace or tier to high-risk only"], "")
    return out.sort_values("net_benefit_annual", ascending=False).reset_index(drop=True)


def emerging_vendor_poc(df: pd.DataFrame, review_rate: float = 0.05, seeds=(7, 17, 27)) -> dict:
    """
    Retro POC for Vendor E on the 35% sample it scored. Champion = current full model;
    challenger = same model + vendor E. Time-ordered split inside the POC sample to avoid leakage.
    """
    from .model import BASE_FEATURES, ENGINEERED, VENDOR_FEATURES
    poc = df[df.vendor_e_in_poc == 1]
    months = sorted(poc.app_month.unique())
    tr = poc[poc.app_month.isin(months[:6])]
    ca = poc[poc.app_month.isin(months[6:8])]
    te = poc[poc.app_month.isin(months[8:])]
    base_feats = BASE_FEATURES + VENDOR_FEATURES + ENGINEERED
    y = te.is_fraud.values
    S0 = [FraudModel(features=base_feats, random_state=sd).fit(tr, ca).predict(te) for sd in seeds]
    S1 = [FraudModel(features=base_feats + ["vendor_e_consortium_risk"], random_state=sd).fit(tr, ca).predict(te)
          for sd in seeds]
    s0, s1 = np.mean(S0, axis=0), np.mean(S1, axis=0)  # seed-averaged ensembles
    sig = te.vendor_e_consortium_risk.values
    n = int(len(te) * review_rate)
    loss = te.loss_if_funded.values
    t0, t1 = np.argsort(-s0)[:n], np.argsort(-s1)[:n]
    cap0, cap1 = capture_at_rate(y, s0, review_rate), capture_at_rate(y, s1, review_rate)
    # incremental $ = incremental capture x fraud exposure, scaled from POC sample to full portfolio
    scale = len(df[df.app_month.isin(te.app_month.unique())]) / len(te)
    inc_annual = (cap1 - cap0) * loss[y == 1].sum() * scale * 12 / te.app_month.nunique()
    annual_apps = len(df) * 12 / df.app_month.nunique()
    cost = VENDORS["vendor_e_consortium_risk"]["cost_per_call"] * annual_apps
    by_type = {}
    for t in ["synthetic_identity", "straw_buyer", "application_fraud", "income_misrep"]:
        m = te.fraud_type.values == t
        if m.sum() > 0:
            by_type[t] = {
                "capture_without": float(np.isin(np.flatnonzero(m), t0).mean()),
                "capture_with": float(np.isin(np.flatnonzero(m), t1).mean()),
            }
    return {
        "poc_sample_size": int(len(poc)),
        "test_size": int(len(te)),
        "standalone_auc": float(roc_auc_score(y, sig)),
        "auc_without": float(roc_auc_score(y, s0)),
        "auc_with": float(roc_auc_score(y, s1)),
        "capture_without": cap0,
        "capture_with": cap1,
        "incremental_loss_prevented_annual": float(inc_annual),
        "annual_cost": float(cost),
        "net_benefit_annual": float(inc_annual - cost),
        "roi": float((inc_annual - cost) / cost),
        "by_typology": by_type,
        "recommendation": ("Proceed to production integration (shadow mode 60 days)"
                           if inc_annual > cost * 1.5 else
                           "Negotiate risk-tiered pricing; deploy on high-risk segment only"
                           if inc_annual > cost * 0.5 else "Do not contract"),
    }


def vendor_overlap(df: pd.DataFrame, thresholds: dict | None = None) -> pd.DataFrame:
    """Share of confirmed fraud flagged by vendor X that is also flagged by vendor Y (redundancy view)."""
    thresholds = thresholds or {"vendor_a_idv_risk": 600, "vendor_b_synth_score": 600,
                                "vendor_c_device_risk": 550, "vendor_d_income_flag_prob": 0.5}
    f = df[df.is_fraud == 1]
    flags = pd.DataFrame({VENDORS[c]["name"].split(" - ")[0]: f[c] >= t for c, t in thresholds.items()})
    mat = pd.DataFrame(index=flags.columns, columns=flags.columns, dtype=float)
    for a in flags:
        for b in flags:
            mat.loc[a, b] = (flags[a] & flags[b]).sum() / max(1, flags[a].sum())
    return mat
