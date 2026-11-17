"""
Monthly executive fraud report (Markdown) and dashboard builder.

The report follows the structure a CFO / Credit Risk Committee expects each month:
  1. Headline & decisions requested
  2. KPI scorecard vs targets (month, prior month, trend)
  3. Fraud trends by typology
  4. Strategy performance (champion vs challenger shadow)
  5. Third-party vendor performance & emerging vendor POC
  6. Dealer risk watchlist
  7. Underwriting fraud loss forecast
  8. Model health (MRM)
"""
from __future__ import annotations

import json
from pathlib import Path

TARGETS = {
    "fraud_capture_rate": (">=", 0.80),
    "dollar_capture_rate": (">=", 0.85),
    "auto_approval_rate": (">=", 0.80),
    "manual_review_rate": ("<=", 0.15),
    "false_positive_rate": ("<=", 0.15),
    "review_hit_rate": (">=", 0.20),
    "residual_loss_bps": ("<=", 60.0),
}
LABELS = {
    "fraud_capture_rate": "Fraud capture rate (count)",
    "dollar_capture_rate": "Fraud capture rate ($)",
    "auto_approval_rate": "Auto-approval rate",
    "manual_review_rate": "Manual review rate",
    "false_positive_rate": "False-positive rate (good apps flagged)",
    "review_hit_rate": "Review queue hit rate",
    "residual_loss_bps": "Residual fraud loss (bps of originations)",
}


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def usd(x):
    if x is None:
        return "n/a"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"${x / 1e3:,.0f}K"
    return f"${x:,.0f}"


def _fmt(k, v):
    return f"{v:.1f}" if k.endswith("bps") else pct(v)


def _status(k, v):
    op, t = TARGETS[k]
    ok = v >= t if op == ">=" else v <= t
    return "🟢 On target" if ok else "🔴 Off target"


def write_monthly_report(b: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    month = b["report_month"]
    months = sorted({r["app_month"] for r in b["monthly"]})
    prior = months[-2]
    m = {(r["strategy"], r["app_month"]): r for r in b["monthly"]}
    ch_now, ch_prev = m[("Challenger", month)], m[("Challenger", prior)]
    cp_now = m[("Champion", month)]
    cvc = {r["strategy"].split(" ")[0]: r for r in b["cvc"]}
    champ, chall = cvc["Champion"], cvc["Challenger"]
    oot = next(x for x in b["model_metrics"] if x["sample"] == "oot")
    poc = b["poc"]
    first_fraud = m[("Champion", months[0])]["fraud_rate"]
    best = b["grid_best"][0]
    base_fc = [r for r in b["forecast"] if r["scenario"] == "Base"]
    fc_ch = sum(r["net_fraud_loss_usd"] for r in base_fc if r["strategy"] == "Challenger")
    fc_cp = sum(r["net_fraud_loss_usd"] for r in base_fc if r["strategy"] == "Champion")
    sev_ch = sum(r["net_fraud_loss_usd"] for r in b["forecast"]
                 if r["scenario"].startswith("Severe") and r["strategy"] == "Challenger")

    gr = sorted(b["typology_growth"].items(), key=lambda kv: -kv[1])[:2]
    growth = " and ".join(t.replace("_", " ").capitalize() if i == 0 else t.replace("_", " ")
                          for i, (t, _) in enumerate(gr))
    weak_rules = [x for x in b["rules"] if x["action"] == "REVIEW" and (x["precision"] or 0) < 0.12]

    top_poc = max(poc["by_typology"].items(),
                  key=lambda kv: kv[1]["capture_with"] - kv[1]["capture_without"])[0].replace("_", " ") + "s"
    top_poc = top_poc.replace("misreps", "misrepresentation").replace("fraud" + "s", "fraud")

    L = []
    w = L.append
    w(f"# Monthly Underwriting Fraud Report — {month}")
    w("")
    w(f"**To:** CFO; Credit Risk Committee  ")
    w(f"**From:** Director, Fraud Analytics, Risk & Strategy  ")
    w(f"**Policy version:** `{b['policy_version']}` · **Data:** fully synthetic prototype dataset "
      f"({b['portfolio']['applications']:,} applications, {b['portfolio']['months']} months)")
    w("")
    w("## 1. Headline")
    w("")
    w(f"- **Fraud pressure is rising.** Attempted fraud reached **{pct(ch_now['fraud_rate'], 2)}** of applications in "
      f"{month}, up from {pct(first_fraud, 2)} twelve months ago. {growth} account for most of the growth.")
    w(f"- **The legacy rules are not keeping up.** In production, the champion rules stopped only "
      f"**{pct(cp_now['dollar_capture_rate'])}** of fraud dollar exposure this month. Residual fraud losses were "
      f"**{cp_now['residual_loss_bps']:.0f} bps** of originations.")
    w(f"- **The challenger strategy (rules + calibrated ML) is ready.** Over the out-of-time window it captures "
      f"**{pct(chall['fraud_capture_rate_usd'])}** of fraud dollars against {pct(champ['fraud_capture_rate_usd'])} "
      f"for the champion. That cuts net fraud loss from {champ['fraud_loss_bps']:.0f} to "
      f"**{chall['fraud_loss_bps']:.0f} bps**, while keeping auto-approval at {pct(chall['auto_approval_rate'])} and "
      f"the review queue within capacity ({chall['reviews_per_month']:.0f} of {b['review_capacity_per_month']:.0f} reviews/month).")
    w(f"- **Emerging vendor (Vendor E, consortium identity graph):** the POC shows "
      f"{usd(poc['incremental_loss_prevented_annual'])} a year in incremental loss prevented against "
      f"{usd(poc['annual_cost'])} in cost. Most of the lift comes from **{top_poc}**. Recommendation: "
      f"*{poc['recommendation']}*.")
    w("")
    w("### Decisions requested from the Committee")
    w("")
    w(f"1. **Approve** promotion of challenger strategy `{b['policy_version']}` to production on 2026-12-01 "
      f"(ML review cutoff {b['cutoffs']['review_at_or_above']}, decline cutoff {b['cutoffs']['decline_at_or_above']}). "
      f"Roll out with a 10% champion holdout for 60 days.")
    w("2. **Approve** a 60-day shadow integration of Vendor E. The contract will use risk-tiered pricing.")
    w("3. **Note** the vendor renewal actions in §5: renegotiate or tier the low-ROI vendors.")
    w("4. **Note** the dealer actions in §6: enhanced review or suspension for the outlier dealers.")
    w("")
    w("## 2. KPI scorecard")
    w("")
    w(f"Challenger values are from the shadow backtest; champion values are production. Targets are defined in `playbook/KPI_FRAMEWORK.md`.")
    w("")
    w(f"| KPI | Target | Champion {month} | Challenger {month} | Challenger {prior} | Status (challenger) |")
    w("|---|---|---|---|---|---|")
    for k in TARGETS:
        op, t = TARGETS[k]
        tgt = f"{op} {t:.0f} bps" if k.endswith("bps") else f"{op} {pct(t, 0)}"
        w(f"| {LABELS[k]} | {tgt} | {_fmt(k, cp_now[k])} | **{_fmt(k, ch_now[k])}** | {_fmt(k, ch_prev[k])} | "
          f"{_status(k, ch_now[k])} |")
    w(f"| Manual review volume | ≤ {b['review_capacity_per_month']:.0f}/mo | {cp_now['review_volume']:.0f} | "
      f"**{ch_now['review_volume']:.0f}** | {ch_prev['review_volume']:.0f} | "
      f"{'🟢 Within capacity' if ch_now['review_volume'] <= b['review_capacity_per_month'] else '🔴 Over capacity'} |")
    w("")
    if ch_now["review_hit_rate"] < TARGETS["review_hit_rate"][1]:
        w(f"*Off-target, review hit rate:* the ML score now declines the highest-risk applications outright, so the "
          f"queue is left with the ambiguous middle band. On top of that, low-precision soft rules keep routing good "
          f"applicants to review: " + ", ".join(f"`{x['rule_id']}` ({pct(x['precision'])})" for x in weak_rules) +
          ". **Action:** move these rules from REVIEW to ML-score features or risk-tiered STIPs in the next policy "
          "release. Backtesting the change is on the 30-day plan.")
        w("")
    w("## 3. Fraud trends by typology (OOT window)")
    w("")
    w("| Typology | Fraud apps | Loss exposure | Champion capture | Challenger capture |")
    w("|---|---|---|---|---|")
    typ = {}
    for r in b["typology"]:
        typ.setdefault(r["typology"], {})[r["strategy"]] = r
    for t, d in sorted(typ.items(), key=lambda kv: -kv[1]["Challenger"]["loss_exposure_usd"]):
        w(f"| {t.replace('_', ' ').title()} | {d['Challenger']['fraud_apps']} | {usd(d['Challenger']['loss_exposure_usd'])} | "
          f"{pct(d['Champion']['capture_rate'])} | **{pct(d['Challenger']['capture_rate'])}** |")
    w("")
    weakest = min(typ.items(), key=lambda kv: kv[1]["Challenger"]["capture_rate"])[0]
    w(f"*Observation:* **{weakest.replace('_', ' ')}** is still the weakest-captured typology. Straw buyers in "
      "particular look creditworthy on bureau data, so the next step is consortium and dealer-network signals (§5) "
      "rather than more bureau rules.")
    w("")
    w("## 4. Strategy performance & cutoff optimisation (OOT)")
    w("")
    w("| Metric | Champion | Challenger | Δ |")
    w("|---|---|---|---|")
    for k, lab, f in [("auto_approval_rate", "Auto-approval", pct), ("manual_review_rate", "Manual review", pct),
                      ("decline_rate", "Fraud decline", pct), ("fraud_capture_rate_count", "Capture (count)", pct),
                      ("fraud_capture_rate_usd", "Capture ($)", pct), ("false_positive_rate", "False-positive rate", pct),
                      ("alert_to_fraud_ratio", "Alerts per confirmed fraud", lambda v: f"{v:.1f}"),
                      ("residual_fraud_loss_usd", "Residual fraud loss", usd), ("friction_cost_usd", "Good-customer friction cost", usd),
                      ("total_cost_usd", "Total cost (loss + friction + ops)", usd)]:
        dv = chall[k] - champ[k]
        ds = (f"{dv * 100:+.1f} pts" if f is pct else usd(dv) if f is usd else f"{dv:+.1f}")
        w(f"| {lab} | {f(champ[k])} | {f(chall[k])} | {ds} |")
    w("")
    w(f"The cutoff grid search minimises *fraud loss + good-customer friction + review cost*. It is constrained so "
      f"that reviews fit analyst capacity and auto-approval stays at or above 82%. The optimum is a review cutoff of "
      f"**{best['review_cutoff']}** and a decline cutoff of **{best['decline_cutoff']}**, at a total cost of "
      f"{usd(best['total_cost_usd'])} over the OOT window. These cutoffs are adopted in the policy file.")
    w("")
    w("## 5. Third-party data providers")
    w("")
    w("| Vendor | Standalone AUC | Incremental $ prevented / yr | Annual cost | ROI | SLA breaches | Recommendation |")
    w("|---|---|---|---|---|---|---|")
    for v in b["vendors"]:
        w(f"| {v['vendor']} | {v['standalone_auc']:.3f} | {usd(v['incremental_loss_prevented_annual'])} | "
          f"{usd(v['annual_cost'])} | {v['roi']:.1f}x | {v['sla_breaches']} | {v['recommendation']} |")
    w("")
    w(f"**Emerging vendor POC (Vendor E):** retro-scored on a {poc['poc_sample_size']:,}-application sample, with a "
      f"time-ordered test set of {poc['test_size']:,} applications. Adding Vendor E to the model changes AUC from "
      f"{poc['auc_without']:.3f} to {poc['auc_with']:.3f}, and capture at a 5% review rate from "
      f"{pct(poc['capture_without'])} to {pct(poc['capture_with'])}.")
    w("")
    w("| Typology | Capture without E | Capture with E |")
    w("|---|---|---|")
    for t, d in poc["by_typology"].items():
        w(f"| {t.replace('_', ' ').title()} | {pct(d['capture_without'])} | {pct(d['capture_with'])} |")
    w("")
    w("## 6. Dealer risk watchlist")
    w("")
    w("These dealers have statistically significant fraud concentration (binomial z-score against the portfolio "
      "rate). This is the main lead source for straw-buyer and application-fraud rings.")
    w("")
    w("| Dealer | State | Apps | Fraud rate | Straw | App fraud | z | Action |")
    w("|---|---|---|---|---|---|---|---|")
    for d in b["dealers"][:10]:
        w(f"| {d['dealer_id']} | {d['state']} | {d['apps']} | {pct(d['fraud_rate'])} | {d['straw']} | {d['app_fraud']} | "
          f"{d['z_score']:.1f} | {d['action']} |")
    w("")
    w("## 7. Underwriting fraud loss forecast (next 6 months)")
    w("")
    w(f"| Scenario | Champion net loss | Challenger net loss | Avoided |")
    w("|---|---|---|---|")
    for scen in ["Base", "Adverse", "Severe (fraud-ring surge)"]:
        a = sum(r["net_fraud_loss_usd"] for r in b["forecast"] if r["scenario"] == scen and r["strategy"] == "Champion")
        c = sum(r["net_fraud_loss_usd"] for r in b["forecast"] if r["scenario"] == scen and r["strategy"] == "Challenger")
        w(f"| {scen} | {usd(a)} | {usd(c)} | **{usd(a - c)}** |")
    w("")
    w(f"Under the base case, deploying the challenger avoids about **{usd(fc_cp - fc_ch)}** of fraud losses over the "
      f"next six months. Even in the severe fraud-ring scenario, challenger losses ({usd(sev_ch)}) stay below the "
      f"champion's base-case losses.")
    w("")
    w("## 8. Model health (Model Risk Management)")
    w("")
    w("| Sample | N | Fraud rate | AUC | KS | Capture @5% |")
    w("|---|---|---|---|---|---|")
    for x in b["model_metrics"]:
        w(f"| {x['sample']} | {x['n']:,} | {pct(x['fraud_rate'], 2)} | {x['auc']:.3f} | {x['ks']:.3f} | {pct(x['capture_at_5pct'])} |")
    w("")
    w(f"Score PSI (train vs OOT) = **{b['stability']['score_psi_train_vs_oot']:.3f}**. A value below 0.10 is "
      f"considered stable. Top drivers by permutation importance: " +
      ", ".join(f"`{i['feature']}`" for i in b["importance"][:6]) + ".")
    w("")
    w("---")
    w("*Prototype built on fully synthetic data. Every figure is reproducible with `python run_pipeline.py`.*")
    path = out_dir / f"monthly_fraud_report_{month}.md"
    path.write_text("\n".join(L))
    return path


def build_dashboard(b: dict, template: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    chartjs = (template.parent / "vendor" / "chart.umd.js").read_text()  # inlined -> fully offline file
    html = (template.read_text()
            .replace("/*__CHARTJS__*/", chartjs)
            .replace("/*__DATA__*/null", json.dumps(b, allow_nan=False)))
    out.write_text(html)
    return out
