# Third-Party Fraud Data Provider Governance

Framework for selecting, measuring, renewing and retiring identity-intelligence and fraud-data vendors. It is implemented in `src/fraudlab/vendors.py`. Results appear in §5 of the monthly report and in the *Vendors* tab of the dashboard.

> Vendor names in this prototype are fictional archetypes (A–E). They represent the categories a lender typically buys: KYC / identity verification, synthetic-ID scoring, device intelligence, income and employment verification, and consortium identity graphs.

## 1. Vendor lifecycle

```
Market scan → RFI → Retro POC (blind file) → Business case → Contract (SLA + pricing tiers)
     → Shadow integration (60d) → Production → Monthly scorecard → Annual renewal decision
```

## 2. Retro POC protocol (emerging vendors)

1. **Blind sample.** Send the vendor 6–12 months of historical applications, with no labels and with time stamps preserved. Include a **known-fraud oversample** and enough goods to measure the false-positive rate.
2. **Time-ordered evaluation.** Train on earlier months and test on later months. Never random-split, because random splits leak fraud-ring patterns.
3. **Measure incremental value, not standalone value.** A vendor that scores AUC 0.80 alone can add nothing if its signal overlaps with vendors you already pay for. The test is to retrain the production model **with and without** the vendor and compare capture at a **fixed review rate** (capacity-neutral).
4. **Segment the lift** by typology, credit-file depth (thick, thin, no-file) and dealer tier.
5. **Price the lift.** Incremental $ loss prevented per year minus annual cost gives the net benefit. Compare against tiered usage, such as calling the vendor only when the ML score is above 0.05.
6. **Check the non-financials:** latency (p95 below 800 ms inside the LOS call chain), uptime, hit or match rate, FCRA/GLBA permissible-purpose posture, data-retention terms, adverse-action reason-code support, and SOC 2.

**Current POC: Vendor E (consortium identity graph).** Its largest lift is on straw buyers, the typology that bureau and IDV data can't see, and it delivers a strongly positive ROI (see §5 of the latest monthly report for current figures). Recommendation: 60-day shadow integration with risk-tiered pricing.

## 3. Incumbent scorecard (monthly)

| Dimension | Metric | Source |
|---|---|---|
| Discrimination | Standalone AUC / KS; decile lift | `sql_vendor_decile_lift.csv` |
| Incremental value | Leave-one-vendor-out ΔAUC, Δcapture at 5% review, $ value | `vendor_scorecard.csv` |
| Redundancy | Overlap on confirmed fraud between vendors | `vendor_overlap.csv` |
| Economics | Annual cost, net benefit, ROI, cost per incremental catch | `vendor_scorecard.csv` |
| Reliability | Hit rate, p95 latency, uptime against SLA | Vendor logs |

### Decision rules

| Condition | Action |
|---|---|
| ROI > 1× and ≤ 1 SLA breach | **Renew** |
| ROI > 1× and ≥ 2 SLA breaches | **Renew with an SLA remediation plan** (service credits) |
| 0 < ROI ≤ 1× | **Renegotiate price or tier usage** (call only for high-risk segments) |
| ROI ≤ 0 | **Replace, or tier to high-risk only** |

## 4. Waterfall and tiered calling

Not every application needs every vendor. The target architecture is a **risk-tiered waterfall** in the LOS:

1. Always call: bureau, IDV (Vendor A), device (Vendor C), which are cheap and fast.
2. If score ≥ 0.05, or the file is thin or no-file: synthetic-ID (Vendor B) and consortium (Vendor E).
3. If PTI > 15% and bank data is not linked: income verification (Vendor D), or require bank-link as a STIP.

Tiering typically cuts vendor spend by 30–50% while keeping more than 95% of the incremental capture.

## 5. Compliance checklist (per vendor)

- [ ] FCRA status (consumer report or not); permissible purpose documented
- [ ] Adverse-action reason codes available and mapped to Reg B notice language
- [ ] Data-retention and deletion terms; GLBA safeguards; SOC 2 Type II
- [ ] Fair-lending review: no prohibited-basis proxies (for example, national origin via ITIN or visa)
- [ ] Contract SLAs: latency, uptime, hit rate, with service credits
- [ ] Exit plan and data portability
