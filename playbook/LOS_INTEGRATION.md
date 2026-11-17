# LOS Integration: Where Fraud Decisioning Sits in the Auto Origination Flow

```
Dealer portal (DealerTrack / RouteOne)
        │  credit application + deal structure
        ▼
┌──────────────────────── LOS / Decision engine ───────────────────────────┐
│ 1. Data acquisition     bureau pull · bank-data link (cash-flow) · IDV   │
│                          · device · (tiered) synthetic-ID / consortium   │
│ 2. Credit decision       AI credit model → approve / counter / decline   │
│ 3. ► FRAUD DECISION ◄    rules (policy YAML) + calibrated ML score       │
│                          → APPROVE · STIP · REVIEW · DECLINE + reasons   │
│ 4. Pricing & structure   APR · term · max LTV / PTI                      │
└──────────────────────────────────────────────────────────────────────────┘
        │                      │                       │
   auto-approve           STIP to dealer          Fraud review queue
   → contract             (bank-link, POI,        (4h SLA, case mgmt,
                           POR, insurance)         call-back, doc check)
        ▼
 Funding checklist (pre-fund verification) ──► FUNDED
        ▼
 Post-funding: FPD/EPD monitoring, title & registration checks → labels back to the analytics mart
```

## Design principles

1. **Fraud runs after credit and before structure.** This avoids spending review effort on applications credit would decline anyway. Re-run fraud on any **dealer re-submission**, because re-keying income or employer is itself a signal (`INC-003`).
2. **Policy as configuration.** Rules and cutoffs live in a versioned YAML file (`config/decision_rules.yaml`) that the decision engine loads, so a rule change does not need a code deployment. Every decision logs the policy version.
3. **Deterministic and auditable.** Each decision stores the fired rule IDs, the ML score, the model version and the vendor responses, which is what adverse-action notices and audit need.
4. **Latency budget.** The fraud step should add no more than about 1.5 s. Vendors are called in parallel with timeouts. If a vendor times out, the application **routes to STIP rather than auto-approve**.
5. **Feedback loop.** Review outcomes, STIP results and FPD/EPD labels flow into the analytics mart (`sql/01_schema.sql`) for monthly retuning.

## Deployment pattern for a new strategy

| Phase | Duration | Description |
|---|---|---|
| Offline backtest | 1–2 weeks | `run_pipeline.py` on 12 months of history; Credit Risk Committee sign-off |
| Shadow mode | 30–60 days | Challenger scored and logged, but production decisions unchanged |
| Controlled rollout | 60 days | 90% challenger / 10% champion holdout; monitor KPIs weekly |
| Full production | — | Champion retired; holdout reduced to 5% for ongoing measurement |
