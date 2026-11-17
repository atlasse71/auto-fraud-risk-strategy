# First 90 Days: Director, Fraud Analytics, Risk & Strategy

## Days 0–30: Diagnose

- **Baseline the KPIs.** Rebuild the KPI framework (`KPI_FRAMEWORK.md`) on production data: capture rate, auto-approval, review queue, false positives, and residual loss in bps. Agree on targets with the CFO.
- **Label audit.** Reconcile fraud labels across investigations, FPD/EPD and charge-off reason codes, then build the label waterfall. Most fraud programmes under-count straw-buyer and income fraud, which end up booked as credit losses.
- **Rule inventory.** Measure the precision, capture and false-positive cost of every live rule (`rule_performance.csv`). Flag rules with precision below 12% for retirement or tiering.
- **Vendor inventory.** List contracts, costs, SLAs and renewal dates. Run leave-one-vendor-out incremental analysis on each vendor.
- **Dealer risk.** Stand up the dealer watchlist (z-score) and agree the escalation path with Dealer Risk.
- **Quick win.** Make bank-data income verification mandatory, as a STIP, when the stated-to-verified income ratio exceeds 1.35×.

## Days 31–60: Design

- **Challenger strategy.** Combine rules and a calibrated ML score, built with Data Science. Optimise cutoffs on expected cost under review-capacity and auto-approval constraints (`optimise_cutoffs`).
- **Emerging vendor POC.** Run a blind retro file with one or two identity-intelligence vendors, prioritising consortium identity graphs for straw buyers. Use a time-ordered evaluation and a fixed review rate.
- **Typology playbooks.** Finalise the control matrix (`FRAUD_TYPOLOGY_CONTROLS.md`) and the analyst review scripts for each typology.
- **MRM package.** Prepare the model card, validation and fair-lending review for the challenger model.

## Days 61–90: Deploy and institutionalise

- **Shadow, then a controlled rollout** of the challenger with a 10% champion holdout.
- **Vendor actions.** Renew, renegotiate or tier based on the scorecard. Move vendors to a risk-tiered calling waterfall.
- **Monthly governance cadence.** The fraud trend report, vendor scorecard and loss forecast go to the CFO and the Credit Risk Committee (`reports/`).
- **Roadmap for the next two quarters:**
  - link analysis / graph features
  - document and liveness step-up
  - eCBSV SSN verification
  - real-time dealer monitoring
  - typology-specific models, with a dedicated straw-buyer model

## Success measures at day 90

| Measure | Target |
|---|---|
| Fraud $ capture | +25 pts vs baseline |
| Residual fraud loss | −50% (bps) |
| Auto-approval | ≥ 80% maintained |
| Vendor spend | −20% via tiering, with no capture loss |
| Governance | Committee-approved policy, KPI pack and MRM documentation in place |
