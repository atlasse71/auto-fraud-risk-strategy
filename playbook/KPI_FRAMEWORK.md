# Underwriting Fraud KPI Framework

Single source of truth for how fraud performance is measured, reported and escalated. The definitions are implemented in `src/fraudlab/kpis.py` and `sql/02_kpi_queries.sql` (`monthly_kpis`).

## Tier 1: Executive KPIs (CFO / Credit Risk Committee, monthly)

| KPI | Definition | Target | Amber | Red / escalation |
|---|---|---|---|---|
| **Fraud capture rate ($)** | $ loss exposure stopped pre-funding ÷ total $ fraud exposure | ≥ 85% | 75–85% | < 75% for 2 consecutive months → strategy review |
| **Fraud capture rate (count)** | Fraud apps stopped ÷ fraud apps | ≥ 80% | 70–80% | < 70% |
| **Residual fraud loss (bps)** | Uncaught fraud loss ÷ $ originations | ≤ 60 bps | 60–90 | > 90 bps → CFO notification |
| **Auto-approval rate** | Apps auto-approved at the fraud step ÷ credit-approved apps | ≥ 80% | 75–80% | < 75% → dealer-experience review |
| **False-positive rate** | Good apps not auto-approved ÷ good apps | ≤ 15% | 15–20% | > 20% |

## Tier 2: Operational KPIs (Fraud Ops / Strategy, weekly)

| KPI | Definition | Target |
|---|---|---|
| Manual review rate | Apps routed to review ÷ apps | ≤ 15% |
| Review queue volume vs capacity | Reviews per day ÷ (analysts × reviews per analyst per day) | ≤ 90% utilisation |
| Review hit rate (queue precision) | Confirmed fraud in queue ÷ reviewed apps | ≥ 20% |
| Alert-to-fraud ratio | Flagged apps ÷ confirmed fraud | ≤ 5 |
| Review SLA | % of reviews decisioned within 4 business hours | ≥ 95% |
| STIP clearance rate | STIPs satisfied ÷ STIPs issued (good apps) | ≥ 85% |
| Good-customer friction | Good apps abandoned after review or STIP | ≤ 2% |

## Tier 3: Model & vendor health (MRM / Vendor Governance, monthly)

| KPI | Threshold |
|---|---|
| Model AUC (OOT, rolling 3 months) | ≥ 0.90; < 0.85 triggers recalibration review |
| KS | ≥ 0.60 |
| Score PSI vs development sample | < 0.10 stable; 0.10–0.25 monitor; > 0.25 investigate |
| Feature PSI (top 15 features) | Same thresholds |
| Calibration (observed ÷ predicted by decile) | Within ±20% in the top 3 deciles |
| Vendor hit rate / p95 latency / uptime | ≥ 92% / ≤ 800 ms / ≥ 99.9% (contract SLA) |
| Vendor incremental ROI | > 1.0× at renewal; < 0 → replace or tier |

## Lagging-indicator labelling

Fraud labels mature slowly. The framework uses a **label waterfall**:

1. Confirmed by investigation (immediate)
2. First-payment default with no contact (30–60 days)
3. Early-payment default with skip or vehicle-not-located flag (90–120 days)
4. Charge-off with fraud reason code (up to 12 months)

Current-month capture rates are therefore restated for **3 months**. The monthly report shows the restated values for prior months.

## Ownership

| Area | Owner |
|---|---|
| Strategy, rules, cutoffs, KPIs | Director, Fraud Analytics, Risk & Strategy |
| Model development | Data Science (with Fraud Strategy as model owner) |
| Deployment in the LOS decision engine | Engineering / Credit Decisioning |
| Review operations | Fraud Operations |
| Independent validation | Model Risk Management |
