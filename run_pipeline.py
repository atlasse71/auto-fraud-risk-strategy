#!/usr/bin/env python3
"""
End-to-end underwriting fraud analytics pipeline.

    python run_pipeline.py            # full run (~1-2 min)

Steps
  1. Generate 12 months of synthetic dealer-channel auto-loan applications
  2. Train + validate the ML fraud model (out-of-time), calibrate, explain
  3. Score champion (legacy rules) vs challenger (rules + ML) strategies
  4. Optimise ML cutoffs under review-capacity & auto-approval constraints
  5. Rule-level performance, typology capture, dealer watchlist
  6. Vendor scorecards + emerging-vendor (consortium) POC
  7. Underwriting fraud loss forecast (base / adverse / severe)
  8. Load SQL mart (SQLite) and execute the KPI query library
  9. Write the monthly executive report + interactive dashboard
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from fraudlab.data_generator import generate  # noqa: E402
from fraudlab.forecast import forecast_losses  # noqa: E402
from fraudlab.kpis import dealer_watchlist, monthly_kpis, typology_capture  # noqa: E402
from fraudlab.model import FraudModel, out_of_time_backtest_scores, psi, time_split  # noqa: E402
from fraudlab.report import build_dashboard, write_monthly_report  # noqa: E402
from fraudlab.rules_engine import decide, evaluate_rules, load_policy, rule_performance  # noqa: E402
from fraudlab.strategy import (Economics, champion_vs_challenger, optimise_cutoffs,  # noqa: E402
                               review_capacity_per_month)
from fraudlab.vendors import emerging_vendor_poc, vendor_overlap, vendor_scorecard  # noqa: E402

OUT = ROOT / "outputs"
DATA = ROOT / "data"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_sql_mart(df: pd.DataFrame, champ: pd.DataFrame, chall: pd.DataFrame, score) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "sql" / "01_schema.sql").read_text())
    app_cols = [c for c in pd.read_sql("SELECT * FROM applications LIMIT 0", con).columns]
    a = df[app_cols].copy()
    a["app_date"] = a.app_date.dt.strftime("%Y-%m-%d")
    a.to_sql("applications", con, if_exists="append", index=False)
    vmap = {"vendor_a_idv_risk": "A_IDV", "vendor_b_synth_score": "B_SYNTH", "vendor_c_device_risk": "C_DEVICE",
            "vendor_d_income_flag_prob": "D_INCOME", "vendor_e_consortium_risk": "E_CONSORTIUM"}
    vr = []
    for col, v in vmap.items():
        s = df[col] * (1000 if col == "vendor_d_income_flag_prob" else 1)
        vr.append(pd.DataFrame({"app_id": df.app_id, "vendor": v, "risk_score": s}).dropna())
    pd.concat(vr).to_sql("vendor_responses", con, if_exists="append", index=False)
    for name, dec, sc in (("champion", champ, None), ("challenger", chall, score)):
        pd.DataFrame({"app_id": df.app_id, "strategy": name, "decision": dec.decision.values,
                      "ml_score": sc, "reason_codes": dec.reason_codes.values}
                     ).to_sql("fraud_decisions", con, if_exists="append", index=False)
    df[["app_id", "is_fraud", "fraud_type", "first_payment_default", "loss_if_funded"]].to_sql(
        "fraud_outcomes", con, if_exists="append", index=False)
    return con


def run_sql_library(con) -> dict:
    text = (ROOT / "sql" / "02_kpi_queries.sql").read_text()
    results = {}
    for name, body in re.findall(r"^-- name: (\w+)\n(.*?)(?=^-- name: |\Z)", text, flags=re.M | re.S):
        results[name] = pd.read_sql(body.strip().rstrip(";"), con)
    return results


def main():
    OUT.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    policy = load_policy()
    eco = Economics.from_policy(policy)

    log("1/9 Generating synthetic application data")
    df = generate()
    df.head(2000).to_csv(DATA / "applications_sample.csv", index=False)
    df.to_parquet(DATA / "applications.parquet", index=False) if _has_parquet() else None

    log("2/9 Training & validating ML fraud model (out-of-time)")
    train, calib, oot = time_split(df)
    model = FraudModel().fit(train, calib)
    metrics = [model.evaluate(train, "train"), model.evaluate(calib, "calibration"), model.evaluate(oot, "oot")]
    s_train, s_oot = model.predict(train), model.predict(oot)
    stability = {"score_psi_train_vs_oot": psi(s_train, s_oot)}
    importance = model.importance(oot)
    # calibration table (deciles on OOT)
    cal = pd.DataFrame({"score": s_oot, "y": oot.is_fraud.values})
    cal["decile"] = pd.qcut(cal.score.rank(method="first"), 10, labels=False) + 1
    calibration = cal.groupby("decile").agg(apps=("y", "size"), avg_score=("score", "mean"),
                                            fraud_rate=("y", "mean")).reset_index()

    log("3/9 Champion vs challenger on OOT sample")
    cvc, champ_oot, chall_oot = champion_vs_challenger(oot, policy, s_oot, eco)

    log("4/9 Optimising ML cutoffs")
    grid = optimise_cutoffs(oot, policy, s_oot, eco)
    cap = review_capacity_per_month(policy)

    log("5/9 Rule performance, typology capture, dealer watchlist")
    rule_perf = rule_performance(oot, evaluate_rules(oot, policy, "challenger"), policy)
    typ = typology_capture(oot, {"Champion": champ_oot.decision, "Challenger": chall_oot.decision}, eco)
    watch = dealer_watchlist(df)

    log("   12-month shadow backtest for monthly KPI trend")
    s_bt = out_of_time_backtest_scores(df)
    champ_all = decide(df, policy, "champion")
    chall_all = decide(df, policy, "challenger", model_score=s_bt)
    mk_champ = monthly_kpis(df, champ_all.decision, eco).assign(strategy="Champion")
    mk_chall = monthly_kpis(df, chall_all.decision, eco).assign(strategy="Challenger")
    mk = pd.concat([mk_champ, mk_chall], ignore_index=True)

    log("6/9 Vendor scorecards + emerging vendor POC")
    vs = vendor_scorecard(train, calib, oot, model)
    poc = emerging_vendor_poc(df)
    overlap = vendor_overlap(oot)

    log("7/9 Loss forecast")
    f = df[df.is_fraud == 1].groupby("app_month").loss_if_funded.sum().rename("exposure_usd")
    o = df.groupby("app_month").amount_financed.sum().rename("originations_usd")
    hist = pd.concat([f, o], axis=1).reset_index()
    capture = {"Champion": float(cvc.iloc[0].fraud_capture_rate_usd),
               "Challenger": float(cvc.iloc[1].fraud_capture_rate_usd)}
    fc = forecast_losses(hist, horizon=6, capture_by_strategy=capture)

    log("8/9 Loading SQL mart & running query library")
    con = load_sql_mart(df, champ_all, chall_all, s_bt)
    sql_results = run_sql_library(con)
    for k, v in sql_results.items():
        v.to_csv(OUT / f"sql_{k}.csv", index=False)

    log("9/9 Writing outputs, monthly report & dashboard")
    pd.DataFrame(metrics).to_csv(OUT / "model_metrics.csv", index=False)
    importance.to_csv(OUT / "model_feature_importance.csv", index=False)
    calibration.to_csv(OUT / "model_calibration.csv", index=False)
    cvc.to_csv(OUT / "champion_vs_challenger.csv", index=False)
    grid.to_csv(OUT / "cutoff_grid.csv", index=False)
    rule_perf.to_csv(OUT / "rule_performance.csv", index=False)
    typ.to_csv(OUT / "typology_capture.csv", index=False)
    watch.to_csv(OUT / "dealer_watchlist.csv", index=False)
    mk.to_csv(OUT / "monthly_kpis.csv", index=False)
    vs.to_csv(OUT / "vendor_scorecard.csv", index=False)
    overlap.to_csv(OUT / "vendor_overlap.csv")
    fc.to_csv(OUT / "loss_forecast.csv", index=False)
    hist.to_csv(OUT / "loss_history.csv", index=False)

    bundle = {
        "generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "policy_version": policy["version"],
        "report_month": df.app_month.max(),
        "typology_growth": _typology_growth(df),
        "portfolio": {"applications": int(len(df)), "months": int(df.app_month.nunique()),
                      "fraud_rate": float(df.is_fraud.mean()),
                      "originations_usd": float(df.amount_financed.sum()),
                      "fraud_mix": df[df.is_fraud == 1].fraud_type.value_counts(normalize=True).to_dict()},
        "model_metrics": metrics, "stability": stability,
        "importance": importance.head(15).to_dict("records"),
        "calibration": calibration.to_dict("records"),
        "cvc": cvc.to_dict("records"),
        "cutoffs": policy["model_cutoffs"], "review_capacity_per_month": cap,
        "grid_best": grid.head(10).to_dict("records"),
        "grid": grid[["review_cutoff", "decline_cutoff", "total_cost_usd", "reviews_per_month",
                      "auto_approval_rate", "fraud_capture_rate_usd", "feasible"]].to_dict("records"),
        "rules": rule_perf.to_dict("records"),
        "typology": typ.to_dict("records"),
        "dealers": watch.to_dict("records"),
        "monthly": mk.to_dict("records"),
        "vendors": vs.replace([np.inf], None).to_dict("records"),
        "poc": poc,
        "overlap": overlap.reset_index().rename(columns={"index": "vendor"}).to_dict("records"),
        "forecast": fc.to_dict("records"),
        "history": hist.to_dict("records"),
        "sql_income": sql_results["income_misrep_by_file_type"].to_dict("records"),
    }
    bundle = _clean(json.loads(json.dumps(bundle, default=_json_default)))
    (OUT / "results.json").write_text(json.dumps(bundle, indent=1, allow_nan=False))
    write_monthly_report(bundle, ROOT / "reports")
    build_dashboard(bundle, ROOT / "dashboard" / "template.html", ROOT / "docs" / "index.html")
    log("Done. Dashboard: docs/index.html | Report: reports/ | Tables: outputs/")


def _typology_growth(df):
    months = sorted(df.app_month.unique())
    first = df[df.app_month.isin(months[:3])].fraud_type.value_counts()
    last = df[df.app_month.isin(months[-3:])].fraud_type.value_counts()
    return {t: int(last.get(t, 0) - first.get(t, 0)) for t in last.index if t != "none"}


def _has_parquet():
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def _clean(o):
    """Replace NaN/inf with None so the JSON is valid for browsers."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    return str(o)


if __name__ == "__main__":
    main()
