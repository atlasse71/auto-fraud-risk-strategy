# Monthly Underwriting Fraud Report — 2026-10

**To:** CFO; Credit Risk Committee  
**From:** Director, Fraud Analytics, Risk & Strategy  
**Policy version:** `2026.11-v3` · **Data:** fully synthetic prototype dataset (60,000 applications, 12 months)

## 1. Headline

- **Fraud pressure is rising.** Attempted fraud reached **4.54%** of applications in 2026-10, up from 3.15% twelve months ago. Income misrep and synthetic identity account for most of the growth.
- **The legacy rules are not keeping up.** In production, the champion rules stopped only **41.4%** of fraud dollar exposure this month. Residual fraud losses were **152 bps** of originations.
- **The challenger strategy (rules + calibrated ML) is ready.** Over the out-of-time window it captures **84.4%** of fraud dollars against 36.9% for the champion. That cuts net fraud loss from 173 to **43 bps**, while keeping auto-approval at 83.0% and the review queue within capacity (642 of 714 reviews/month).
- **Emerging vendor (Vendor E, consortium identity graph):** the POC shows $753K a year in incremental loss prevented against $57K in cost. Most of the lift comes from **straw buyers**. Recommendation: *Proceed to production integration (shadow mode 60 days)*.

### Decisions requested from the Committee

1. **Approve** promotion of challenger strategy `2026.11-v3` to production on 2026-12-01 (ML review cutoff 0.15, decline cutoff 0.5). Roll out with a 10% champion holdout for 60 days.
2. **Approve** a 60-day shadow integration of Vendor E. The contract will use risk-tiered pricing.
3. **Note** the vendor renewal actions in §5: renegotiate or tier the low-ROI vendors.
4. **Note** the dealer actions in §6: enhanced review or suspension for the outlier dealers.

## 2. KPI scorecard

Challenger values are from the shadow backtest; champion values are production. Targets are defined in `playbook/KPI_FRAMEWORK.md`.

| KPI | Target | Champion 2026-10 | Challenger 2026-10 | Challenger 2026-09 | Status (challenger) |
|---|---|---|---|---|---|
| Fraud capture rate (count) | >= 80% | 34.4% | **84.9%** | 81.4% | 🟢 On target |
| Fraud capture rate ($) | >= 85% | 41.4% | **86.6%** | 83.0% | 🟢 On target |
| Auto-approval rate | >= 80% | 90.2% | **82.4%** | 82.2% | 🟢 On target |
| Manual review rate | <= 15% | 8.7% | **13.2%** | 13.1% | 🟢 On target |
| False-positive rate (good apps flagged) | <= 15% | 8.4% | **14.1%** | 14.5% | 🟢 On target |
| Review queue hit rate | >= 20% | 19.1% | **11.2%** | 8.8% | 🔴 Off target |
| Residual fraud loss (bps of originations) | <= 60 bps | 151.6 | **34.6** | 49.6 | 🟢 On target |
| Manual review volume | ≤ 714/mo | 481 | **730** | 684 | 🔴 Over capacity |

*Off-target, review hit rate:* the ML score now declines the highest-risk applications outright, so the queue is left with the ambiguous middle band. On top of that, low-precision soft rules keep routing good applicants to review: `ID-003` (11.9%), `STR-002` (5.7%). **Action:** move these rules from REVIEW to ML-score features or risk-tiered STIPs in the next policy release. Backtesting the change is on the 30-day plan.

## 3. Fraud trends by typology (OOT window)

| Typology | Fraud apps | Loss exposure | Champion capture | Challenger capture |
|---|---|---|---|---|
| Synthetic Identity | 143 | $2.42M | 52.4% | **91.0%** |
| Application Fraud | 72 | $1.58M | 53.6% | **86.1%** |
| Straw Buyer | 98 | $1.50M | 13.5% | **69.6%** |
| Income Misrep | 176 | $1.44M | 17.3% | **83.8%** |

*Observation:* **straw buyer** is still the weakest-captured typology. Straw buyers in particular look creditworthy on bureau data, so the next step is consortium and dealer-network signals (§5) rather than more bureau rules.

## 4. Strategy performance & cutoff optimisation (OOT)

| Metric | Champion | Challenger | Δ |
|---|---|---|---|
| Auto-approval | 90.0% | 83.0% | -7.0 pts |
| Manual review | 8.9% | 11.9% | +3.1 pts |
| Fraud decline | 0.2% | 4.1% | +3.9 pts |
| Capture (count) | 32.1% | 83.4% | +51.3 pts |
| Capture ($) | 36.9% | 84.4% | +47.5 pts |
| False-positive rate | 8.7% | 13.7% | +5.0 pts |
| Alerts per confirmed fraud | 5.8 | 4.3 | -1.5 |
| Residual fraud loss | $4.37M | $1.08M | $-3.29M |
| Good-customer friction cost | $112K | $358K | $246K |
| Total cost (loss + friction + ops) | $4.52M | $1.49M | $-3.03M |

The cutoff grid search minimises *fraud loss + good-customer friction + review cost*. It is constrained so that reviews fit analyst capacity and auto-approval stays at or above 82%. The optimum is a review cutoff of **0.1** and a decline cutoff of **0.5**, at a total cost of $1.48M over the OOT window. These cutoffs are adopted in the policy file.

## 5. Third-party data providers

| Vendor | Standalone AUC | Incremental $ prevented / yr | Annual cost | ROI | SLA breaches | Recommendation |
|---|---|---|---|---|---|---|
| Vendor D - Income Verification | 0.663 | $822K | $90K | 8.1x | 3 | Renew with SLA remediation plan |
| Vendor A - Identity Verification | 0.623 | $510K | $55K | 8.3x | 0 | Renew |
| Vendor B - Synthetic ID Score | 0.617 | $255K | $39K | 5.6x | 0 | Renew |
| Vendor C - Device Intelligence | 0.636 | $-28K | $23K | -2.3x | 1 | Replace or tier to high-risk only |

**Emerging vendor POC (Vendor E):** retro-scored on a 21,004-application sample, with a time-ordered test set of 7,583 applications. Adding Vendor E to the model changes AUC from 0.939 to 0.953, and capture at a 5% review rate from 63.7% to 65.5%.

| Typology | Capture without E | Capture with E |
|---|---|---|
| Synthetic Identity | 69.6% | 75.5% |
| Straw Buyer | 47.1% | 54.9% |
| Application Fraud | 78.0% | 66.1% |
| Income Misrep | 58.6% | 61.2% |

## 6. Dealer risk watchlist

These dealers have statistically significant fraud concentration (binomial z-score against the portfolio rate). This is the main lead source for straw-buyer and application-fraud rings.

| Dealer | State | Apps | Fraud rate | Straw | App fraud | z | Action |
|---|---|---|---|---|---|---|---|
| D0299 | VA | 50 | 36.0% | 8 | 6 | 11.7 | Suspend & audit |
| D0308 | PA | 40 | 37.5% | 2 | 10 | 11.0 | Suspend & audit |
| D0802 | TX | 70 | 27.1% | 8 | 6 | 10.0 | Suspend & audit |
| D0047 | NY | 58 | 27.6% | 11 | 4 | 9.3 | Suspend & audit |
| D0617 | TX | 68 | 23.5% | 4 | 6 | 8.4 | Suspend & audit |
| D0818 | PA | 56 | 25.0% | 7 | 6 | 8.2 | Suspend & audit |
| D0589 | VA | 49 | 24.5% | 4 | 3 | 7.4 | Enhanced review |
| D0078 | GA | 47 | 23.4% | 3 | 4 | 6.9 | Enhanced review |
| D0674 | MA | 103 | 16.5% | 5 | 4 | 6.6 | Enhanced review |
| D0593 | VA | 102 | 13.7% | 1 | 6 | 5.1 | Enhanced review |

## 7. Underwriting fraud loss forecast (next 6 months)

| Scenario | Champion net loss | Challenger net loss | Avoided |
|---|---|---|---|
| Base | $18.38M | $4.55M | **$13.83M** |
| Adverse | $22.98M | $5.69M | **$17.29M** |
| Severe (fraud-ring surge) | $29.41M | $7.28M | **$22.13M** |

Under the base case, deploying the challenger avoids about **$13.83M** of fraud losses over the next six months. Even in the severe fraud-ring scenario, challenger losses ($7.28M) stay below the champion's base-case losses.

## 8. Model health (Model Risk Management)

| Sample | N | Fraud rate | AUC | KS | Capture @5% |
|---|---|---|---|---|---|
| train | 38,294 | 3.62% | 0.991 | 0.921 | 92.0% |
| calibration | 10,952 | 4.24% | 0.968 | 0.834 | 77.2% |
| oot | 10,754 | 4.55% | 0.968 | 0.840 | 76.1% |

Score PSI (train vs OOT) = **0.002**. A value below 0.10 is considered stable. Top drivers by permutation importance: `income_ratio`, `vendor_d_income_flag_prob`, `oldest_tradeline_months`, `bureau_score`, `pti`, `dealer_fraud_rate_prior`.

---
*Prototype built on fully synthetic data. Every figure is reproducible with `python run_pipeline.py`.*