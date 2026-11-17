# Fraud Model Governance (SR 11-7 aligned)

Fraud models used to decline credit applications are subject to model-risk-management expectations (SR 11-7 / OCC 2011-12 principles). Their adverse-action outputs also fall under ECOA / Reg B. This document records how the prototype model is built, validated, monitored and changed.

## Model card: `fraudlab.model.FraudModel`

| Item | Detail |
|---|---|
| Purpose | Estimate the probability that a credit-approved auto-loan application is fraudulent (any typology) before funding |
| Use | Decision input with cutoffs in the policy file: ≥ 0.50 decline, ≥ 0.15 manual review. Combined with deterministic rules |
| Algorithm | Histogram gradient-boosted trees (scikit-learn), class-weighted, with isotonic calibration on a held-out window |
| Features | 42 features: identity/contact tenure, bureau (thin and no-file aware), bank-data income verification, deal structure, velocity, dealer prior (smoothed target encoding on the training window only), and four incumbent vendor signals |
| Excluded | Any prohibited basis or close proxy: national origin, citizenship or visa status, ITIN flag, age as a direct decline driver (age is monitored for disparate impact), zip-level demographics |
| Training window | Months 1–8. Calibration: months 9–10. OOT test: months 11–12 |
| Performance (OOT) | AUC ≈ 0.97, KS ≈ 0.84, about 75% of fraud captured in the top 5% of scores (see `outputs/model_metrics.csv`) |
| Stability | Score PSI between train and OOT ≈ 0.00 |
| Limitations | Labels are lagging and partly inferred from FPD/EPD; sophisticated synthetics with organic history; straw buyers are under-represented in features |

## Development standards

1. **Out-of-time validation is mandatory.** Random splits overstate performance because fraud rings span many applications.
2. **No target leakage.** Dealer priors are fit on the training window only. Post-decision fields (funding, payments) are excluded.
3. **Calibrated probabilities**, so cutoffs carry economic meaning and survive retraining.
4. **Explainability.** Permutation importance runs globally. Per-decision reason codes are mapped from the top contributing features and fired rules to Reg B adverse-action language, for example "Unable to verify identity" or "Unable to verify income".
5. **Champion/challenger.** New models and strategies run in shadow, then roll out with a randomised **10% champion holdout** for at least 60 days before full rollout.

## Monitoring (monthly, automated in `run_pipeline.py`)

| Check | Trigger |
|---|---|
| OOT AUC / KS on matured labels | AUC < 0.85 or KS < 0.55 |
| Score and feature PSI | > 0.25 |
| Calibration by decile | Observed ÷ predicted outside ±20% in the top 3 deciles |
| Review-queue hit rate | < 15% for 2 months |
| **Fair-lending:** false-positive-rate parity across credit-file type and age bands | Adverse-impact ratio < 0.80 |

## Change management

| Change | Approval |
|---|---|
| Cutoff change within ±0.05 | Director, Fraud Strategy (documented) |
| New or retired rule | Fraud Strategy + Credit Policy; backtest attached |
| Retrain on the same specification | Fraud Strategy + Data Science; MRM notified |
| New feature, vendor or algorithm | Full MRM validation + Credit Risk Committee |
