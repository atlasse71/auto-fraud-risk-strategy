"""
Underwriting fraud loss forecast.

Projects monthly fraud loss exposure (funded fraud x severity) using a log-linear trend on
application fraud pressure and volume, then applies the capture rate of each strategy.
Produces base / adverse / severe scenarios for the credit risk committee.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SCENARIOS = {"Base": 1.00, "Adverse": 1.25, "Severe (fraud-ring surge)": 1.60}


def forecast_losses(monthly: pd.DataFrame, horizon: int = 6, capture_by_strategy: dict | None = None
                    ) -> pd.DataFrame:
    """
    monthly: columns app_month, exposure_usd (gross fraud loss exposure before controls), originations_usd
    capture_by_strategy: {"Champion": dollar_capture_rate, "Challenger": ...}
    """
    m = monthly.copy().reset_index(drop=True)
    t = np.arange(len(m))
    b_exp = np.polyfit(t, np.log(m.exposure_usd.clip(lower=1)), 1)
    b_orig = np.polyfit(t, np.log(m.originations_usd), 1)
    resid_sd = np.std(np.log(m.exposure_usd) - np.polyval(b_exp, t), ddof=2)
    last = pd.Period(m.app_month.iloc[-1], "M")
    rows = []
    for h in range(1, horizon + 1):
        tt = len(m) - 1 + h
        exp_hat = float(np.exp(np.polyval(b_exp, tt)))
        orig_hat = float(np.exp(np.polyval(b_orig, tt)))
        for scen, mult in SCENARIOS.items():
            for strat, cap in (capture_by_strategy or {"No controls": 0.0}).items():
                loss = exp_hat * mult * (1 - cap)
                rows.append({
                    "month": str(last + h), "scenario": scen, "strategy": strat,
                    "gross_exposure_usd": exp_hat * mult, "originations_usd": orig_hat,
                    "net_fraud_loss_usd": loss, "net_fraud_loss_bps": 1e4 * loss / orig_hat,
                    "pi_low_usd": loss * np.exp(-1.64 * resid_sd), "pi_high_usd": loss * np.exp(1.64 * resid_sd),
                })
    return pd.DataFrame(rows)
