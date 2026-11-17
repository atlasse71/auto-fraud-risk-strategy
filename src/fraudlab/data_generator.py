"""
Synthetic auto-loan application generator.

Produces a realistic, fully synthetic origination dataset (no real PII) covering
12 months of dealer-channel applications, including:

  * Applicant / identity attributes (SSN issuance vs DOB, phone/email tenure, address type)
  * Credit bureau attributes (thick, thin and no-file consumers, AU tradelines, inquiries)
  * Bank-data (cash-flow) verified income vs stated income
  * Deal structure (LTV, PTI, DTI, down payment, vehicle price)
  * Dealer, device and velocity signals
  * Third-party vendor signals (identity, synthetic-ID, device, income, consortium POC)
  * Ground-truth fraud typology and funded-loss outcome

Fraud typologies modelled (each with its own signature in the data):
  synthetic_identity   - manufactured identity, piggy-backed AU tradelines, young SSN, new phone/email
  straw_buyer          - creditworthy front buyer for a third party; buyer/vehicle mismatch, distance,
                         dealer concentration, mismatched co-buyer/device
  income_misrep        - inflated stated income vs bank-verified income, unverifiable employer
  application_fraud    - stolen identity / doctored docs; address & IP mismatch, device velocity,
                         mail-drop addresses

All parameters are configurable; the random seed makes the dataset reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TYPOLOGIES = ["synthetic_identity", "straw_buyer", "income_misrep", "application_fraud"]

STATES = ["MA", "NY", "NJ", "PA", "FL", "GA", "TX", "IL", "CA", "AZ", "NC", "VA", "OH", "MI", "WA"]


@dataclass
class GeneratorConfig:
    n_apps: int = 60_000
    start: str = "2025-11-01"
    months: int = 12
    n_dealers: int = 900
    seed: int = 42
    # base fraud prevalence by typology (share of all applications)
    rates: dict | None = None
    # monthly growth in fraud pressure (fraud rings scale over time)
    fraud_trend: float = 0.035
    # probability a fraud record "looks normal" on any given attribute (see _camouflage)
    camouflage: float = 0.45

    def __post_init__(self):
        if self.rates is None:
            self.rates = {
                "synthetic_identity": 0.0090,
                "straw_buyer": 0.0060,
                "income_misrep": 0.0110,
                "application_fraud": 0.0055,
            }


def _clip(x, lo, hi):
    return np.clip(x, lo, hi)


def generate(cfg: GeneratorConfig | None = None) -> pd.DataFrame:
    cfg = cfg or GeneratorConfig()
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n_apps

    # ------------------------------------------------------------------ dates
    start = pd.Timestamp(cfg.start)
    end = start + pd.DateOffset(months=cfg.months)
    span_days = (end - start).days
    # mild volume growth over time
    u = rng.random(n) ** 0.92
    app_date = start + pd.to_timedelta((u * span_days).astype(int), unit="D")
    month_idx = ((app_date.year - start.year) * 12 + (app_date.month - start.month)).values

    # ------------------------------------------------------------------ dealers
    dealer_ids = np.array([f"D{d:04d}" for d in range(cfg.n_dealers)])
    dealer_state = rng.choice(STATES, cfg.n_dealers)
    dealer_weight = rng.pareto(1.6, cfg.n_dealers) + 0.2
    dealer_weight /= dealer_weight.sum()
    # a small set of "complicit / compromised" dealers concentrate straw-buyer & app fraud
    risky_dealers = rng.choice(cfg.n_dealers, 30, replace=False)

    # ------------------------------------------------------------------ fraud label
    trend = (1 + cfg.fraud_trend) ** month_idx
    fraud_type = np.array(["none"] * n, dtype=object)
    draw = rng.random(n)
    cum = np.zeros(n)
    for t in TYPOLOGIES:
        p = cfg.rates[t] * trend
        mask = (draw >= cum) & (draw < cum + p) & (fraud_type == "none")
        fraud_type[mask] = t
        cum = cum + p
    is_fraud = (fraud_type != "none").astype(int)

    # dealer assignment: fraud skews to risky dealers
    dealer_idx = rng.choice(cfg.n_dealers, n, p=dealer_weight)
    skew_mask = np.isin(fraud_type, ["straw_buyer", "application_fraud"]) & (rng.random(n) < 0.25)
    dealer_idx[skew_mask] = rng.choice(risky_dealers, skew_mask.sum())
    syn_skew = (fraud_type == "synthetic_identity") & (rng.random(n) < 0.10)
    dealer_idx[syn_skew] = rng.choice(risky_dealers, syn_skew.sum())

    is_syn = fraud_type == "synthetic_identity"
    is_straw = fraud_type == "straw_buyer"
    is_inc = fraud_type == "income_misrep"
    is_app = fraud_type == "application_fraud"

    # ------------------------------------------------------------------ applicant
    age = _clip(rng.normal(36, 11, n), 18, 80).round()
    age[is_syn] = _clip(rng.normal(31, 6, is_syn.sum()), 21, 60).round()
    age[is_straw] = _clip(rng.normal(27, 7, is_straw.sum()), 18, 70).round()

    # Lendbuzz-like population: large share of thin / no-file borrowers
    file_type = rng.choice(["thick", "thin", "no_file"], n, p=[0.48, 0.32, 0.20])
    file_type[is_syn] = rng.choice(["thick", "thin"], is_syn.sum(), p=[0.55, 0.45])
    file_type[is_straw] = rng.choice(["thick", "thin"], is_straw.sum(), p=[0.80, 0.20])

    # SSN issuance age: synthetic IDs often use SSNs issued in adulthood / randomized-era
    ssn_issue_age = np.where(rng.random(n) < 0.80, _clip(rng.normal(1, 2, n), 0, 30),
                             _clip(rng.normal(22, 6, n), 0, 50))  # immigrants get SSNs as adults
    ssn_issue_age[is_syn] = _clip(rng.normal(age[is_syn] - 3, 4), 15, 60)
    ssn_issue_age = ssn_issue_age.round(1)

    phone_tenure_days = _clip(rng.lognormal(7.0, 0.9, n), 5, 6000).round()
    phone_tenure_days[is_syn] = _clip(rng.lognormal(4.6, 0.8, is_syn.sum()), 1, 2000).round()
    phone_tenure_days[is_app] = _clip(rng.lognormal(3.8, 1.0, is_app.sum()), 1, 2000).round()

    email_tenure_days = _clip(rng.lognormal(7.3, 0.9, n), 1, 8000).round()
    email_tenure_days[is_syn] = _clip(rng.lognormal(4.9, 0.8, is_syn.sum()), 1, 3000).round()
    email_tenure_days[is_app] = _clip(rng.lognormal(3.5, 1.1, is_app.sum()), 1, 3000).round()

    address_type = rng.choice(["residential", "apartment", "commercial", "mail_drop"], n,
                              p=[0.62, 0.355, 0.02, 0.005])
    address_type[is_app] = rng.choice(["residential", "apartment", "commercial", "mail_drop"],
                                      is_app.sum(), p=[0.35, 0.30, 0.15, 0.20])
    address_type[is_syn] = rng.choice(["residential", "apartment", "commercial", "mail_drop"],
                                      is_syn.sum(), p=[0.30, 0.45, 0.10, 0.15])
    time_at_address_months = _clip(rng.lognormal(3.3, 0.9, n), 1, 400).round()
    time_at_address_months[is_syn | is_app] = _clip(
        rng.lognormal(2.0, 0.8, (is_syn | is_app).sum()), 1, 200).round()

    # ------------------------------------------------------------------ bureau
    bureau_score = _clip(rng.normal(665, 70, n), 480, 850).round()
    bureau_score[is_syn] = _clip(rng.normal(712, 40, is_syn.sum()), 600, 820).round()  # "too good"
    bureau_score[is_straw] = _clip(rng.normal(705, 50, is_straw.sum()), 560, 840).round()
    bureau_score = np.where(file_type == "no_file", np.nan, bureau_score)

    tradelines = np.where(file_type == "thick", rng.poisson(14, n),
                          np.where(file_type == "thin", rng.poisson(2.5, n), 0))
    oldest_tl_months = np.where(file_type == "thick", _clip(rng.normal(110, 60, n), 24, 480),
                                np.where(file_type == "thin", _clip(rng.normal(20, 10, n), 1, 60), 0)).round()
    au_tradelines = np.where(file_type == "no_file", 0, rng.poisson(0.4, n))
    au_tradelines[is_syn] = rng.poisson(4.5, is_syn.sum())  # piggy-backing
    oldest_tl_months[is_syn] = _clip(rng.normal(40, 18, is_syn.sum()), 6, 120).round()
    inquiries_6m = rng.poisson(1.6, n)
    inquiries_6m[is_syn] = rng.poisson(4.0, is_syn.sum())
    inquiries_6m[is_app] = rng.poisson(3.2, is_app.sum())
    # ratio of tradeline age to SSN-implied credit age (synthetic IDs show "credit older than person")
    bureau_name_dob_mismatch = (rng.random(n) < 0.01).astype(int)
    bureau_name_dob_mismatch[is_app] = (rng.random(is_app.sum()) < 0.45).astype(int)
    bureau_name_dob_mismatch[is_syn] = (rng.random(is_syn.sum()) < 0.18).astype(int)

    # ------------------------------------------------------------------ income (stated vs bank-verified)
    true_income = _clip(rng.lognormal(8.35, 0.45, n), 1200, 25000)
    stated_income = true_income * _clip(rng.normal(1.04, 0.08, n), 0.8, 1.4)
    stated_income[is_inc] = true_income[is_inc] * _clip(rng.normal(1.75, 0.35, is_inc.sum()), 1.25, 3.5)
    stated_income[is_straw] = true_income[is_straw] * _clip(rng.normal(1.15, 0.15, is_straw.sum()), 0.9, 2)
    bank_data_linked = (rng.random(n) < 0.72).astype(int)
    verified_income = np.where(bank_data_linked == 1,
                               true_income * _clip(rng.normal(1.0, 0.06, n), 0.8, 1.2), np.nan)
    income_ratio = stated_income / verified_income
    employer_verified = (rng.random(n) < 0.86).astype(int)
    employer_verified[is_inc] = (rng.random(is_inc.sum()) < 0.38).astype(int)
    employer_verified[is_app] = (rng.random(is_app.sum()) < 0.45).astype(int)
    paystub_edit_flag = (rng.random(n) < 0.004).astype(int)  # doc forensics
    paystub_edit_flag[is_inc] = (rng.random(is_inc.sum()) < 0.30).astype(int)
    paystub_edit_flag[is_app] = (rng.random(is_app.sum()) < 0.22).astype(int)

    # ------------------------------------------------------------------ deal structure
    vehicle_price = _clip(rng.lognormal(10.1, 0.35, n), 6000, 95000).round(-2)
    vehicle_price[is_straw] = _clip(rng.lognormal(10.55, 0.30, is_straw.sum()), 15000, 120000).round(-2)
    vehicle_price[is_app] = _clip(rng.lognormal(10.4, 0.30, is_app.sum()), 10000, 110000).round(-2)
    down_payment = vehicle_price * _clip(rng.beta(2, 9, n), 0, 0.6)
    down_payment[is_syn | is_app] *= 0.35
    amount_financed = (vehicle_price - down_payment) * 1.09  # tax/fees/backend
    ltv = amount_financed / (vehicle_price * _clip(rng.normal(0.97, 0.06, n), 0.8, 1.15))
    term = rng.choice([48, 60, 72, 75, 84], n, p=[0.07, 0.25, 0.45, 0.08, 0.15])
    apr = _clip(rng.normal(12.5, 4, n), 3.9, 24.9)
    r = apr / 1200
    payment = amount_financed * r / (1 - (1 + r) ** (-term))
    pti = payment / stated_income
    dti = _clip(rng.normal(0.33, 0.10, n), 0.02, 0.65)

    # buyer-to-dealer distance; straw buyers & stolen IDs travel / are remote
    dist_to_dealer_km = _clip(rng.lognormal(3.0, 0.9, n), 0.5, 2000).round(1)
    dist_to_dealer_km[is_straw] = _clip(rng.lognormal(4.6, 0.8, is_straw.sum()), 5, 2500).round(1)
    dist_to_dealer_km[is_app] = _clip(rng.lognormal(4.9, 0.9, is_app.sum()), 5, 3000).round(1)
    ip_geo_mismatch_km = _clip(rng.lognormal(2.5, 1.0, n), 0, 4000).round(1)
    ip_geo_mismatch_km[is_app] = _clip(rng.lognormal(5.5, 1.0, is_app.sum()), 50, 6000).round(1)

    has_cobuyer = (rng.random(n) < 0.18).astype(int)
    has_cobuyer[is_straw] = (rng.random(is_straw.sum()) < 0.40).astype(int)
    # affordability mismatch: vehicle price relative to verified/stated income
    vehicle_to_income = vehicle_price / (stated_income * 12)

    # ------------------------------------------------------------------ velocity / device
    device_apps_30d = rng.poisson(0.15, n) + 1
    device_apps_30d[is_app] += rng.poisson(3.0, is_app.sum())
    device_apps_30d[is_syn] += rng.poisson(1.6, is_syn.sum())
    ssn_apps_30d = rng.poisson(0.25, n) + 1
    ssn_apps_30d[is_syn] += rng.poisson(1.8, is_syn.sum())
    ssn_apps_30d[is_app] += rng.poisson(1.2, is_app.sum())
    phone_shared_count = rng.poisson(0.05, n)
    phone_shared_count[is_syn] += rng.poisson(1.6, is_syn.sum())
    phone_shared_count[is_straw] += rng.poisson(0.9, is_straw.sum())
    dealer_rapid_resubmits = rng.poisson(0.2, n)  # dealer re-keys app with changed income/employer
    dealer_rapid_resubmits[is_inc] += rng.poisson(1.4, is_inc.sum())
    dealer_rapid_resubmits[is_straw] += rng.poisson(0.9, is_straw.sum())

    # ------------------------------------------------------------------ vendor signals (fictionalised)
    def noisy(signal, noise, lo=0, hi=1000):
        return _clip(signal + rng.normal(0, noise, n), lo, hi).round()

    # Vendor A - identity verification (PII linkage / KYC). High = risky
    va = 120 + 520 * is_app + 380 * is_syn + 40 * is_straw
    vendor_a_idv_risk = noisy(va, 220)
    # Vendor B - synthetic identity score
    vb = 150 + 560 * is_syn + 90 * is_app
    vendor_b_synth_score = noisy(vb, 230)
    # Vendor C - device & behavioural intelligence
    vc = 140 + 330 * is_app + 210 * is_syn + 160 * is_straw + 25 * (device_apps_30d - 1)
    vendor_c_device_risk = noisy(vc, 240)
    # Vendor D - income / employment verification (prob of mis-statement)
    vd = 0.08 + 0.55 * is_inc + 0.18 * is_straw + 0.12 * is_app
    vendor_d_income_flag_prob = _clip(vd + rng.normal(0, 0.22, n), 0, 1).round(3)
    # Vendor E - EMERGING consortium identity graph (POC; only on retro sample)
    ve = 130 + 470 * is_straw + 310 * is_syn + 250 * is_app + 120 * is_inc
    vendor_e_consortium_risk = noisy(ve, 210)
    vendor_e_in_poc = (rng.random(n) < 0.35).astype(int)
    vendor_e_consortium_risk = np.where(vendor_e_in_poc == 1, vendor_e_consortium_risk, np.nan)

    # OFAC / deceased / SSN-invalid hard hits (rare)
    ssn_deceased_or_invalid = (rng.random(n) < 0.0008).astype(int)
    ssn_deceased_or_invalid[is_app] = (rng.random(is_app.sum()) < 0.10).astype(int)
    ssn_deceased_or_invalid[is_syn] = (rng.random(is_syn.sum()) < 0.06).astype(int)

    # ------------------------------------------------------------------ outcome
    # first-payment default & loss if funded (fraud losses ~ 55-95% severity; credit losses lower)
    fpd_prob = 0.012 + 0.62 * is_syn + 0.55 * is_app + 0.35 * is_straw + 0.18 * is_inc
    first_payment_default = (rng.random(n) < fpd_prob).astype(int)
    severity = np.where(is_fraud == 1, _clip(rng.normal(0.72, 0.15, n), 0.3, 1.0),
                        _clip(rng.normal(0.45, 0.12, n), 0.1, 0.9))
    charge_off = np.where(is_fraud == 1, rng.random(n) < (0.55 + 0.35 * (is_syn | is_app)),
                          rng.random(n) < 0.045)
    loss_if_funded = np.where(charge_off, amount_financed * severity, 0).round(2)

    df = pd.DataFrame({
        "app_id": [f"A{i:07d}" for i in range(n)],
        "app_date": app_date.normalize(),
        "dealer_id": dealer_ids[dealer_idx],
        "dealer_state": dealer_state[dealer_idx],
        "applicant_age": age.astype(int),
        "credit_file_type": file_type,
        "ssn_issue_age": ssn_issue_age,
        "ssn_deceased_or_invalid": ssn_deceased_or_invalid,
        "phone_tenure_days": phone_tenure_days.astype(int),
        "email_tenure_days": email_tenure_days.astype(int),
        "address_type": address_type,
        "time_at_address_months": time_at_address_months.astype(int),
        "bureau_score": bureau_score,
        "tradelines": tradelines.astype(int),
        "oldest_tradeline_months": oldest_tl_months.astype(int),
        "au_tradelines": au_tradelines.astype(int),
        "inquiries_6m": inquiries_6m.astype(int),
        "bureau_name_dob_mismatch": bureau_name_dob_mismatch,
        "stated_income_monthly": stated_income.round(0),
        "bank_data_linked": bank_data_linked,
        "verified_income_monthly": np.round(verified_income, 0),
        "income_ratio": np.round(income_ratio, 3),
        "employer_verified": employer_verified,
        "paystub_edit_flag": paystub_edit_flag,
        "vehicle_price": vehicle_price,
        "down_payment": down_payment.round(0),
        "amount_financed": amount_financed.round(0),
        "ltv": ltv.round(3),
        "term_months": term,
        "apr": apr.round(2),
        "monthly_payment": payment.round(2),
        "pti": pti.round(4),
        "dti": dti.round(3),
        "vehicle_to_income": vehicle_to_income.round(3),
        "has_cobuyer": has_cobuyer,
        "dist_to_dealer_km": dist_to_dealer_km,
        "ip_geo_mismatch_km": ip_geo_mismatch_km,
        "device_apps_30d": device_apps_30d.astype(int),
        "ssn_apps_30d": ssn_apps_30d.astype(int),
        "phone_shared_count": phone_shared_count.astype(int),
        "dealer_rapid_resubmits": dealer_rapid_resubmits.astype(int),
        "vendor_a_idv_risk": vendor_a_idv_risk,
        "vendor_b_synth_score": vendor_b_synth_score,
        "vendor_c_device_risk": vendor_c_device_risk,
        "vendor_d_income_flag_prob": vendor_d_income_flag_prob,
        "vendor_e_in_poc": vendor_e_in_poc,
        "vendor_e_consortium_risk": vendor_e_consortium_risk,
        "fraud_type": fraud_type,
        "is_fraud": is_fraud,
        "first_payment_default": first_payment_default,
        "loss_if_funded": loss_if_funded,
    })
    df = _camouflage(df, rng, cfg.camouflage)
    df["app_month"] = df["app_date"].dt.to_period("M").astype(str)
    return df.sort_values("app_date").reset_index(drop=True)


CAMO_COLS = [
    "applicant_age", "ssn_issue_age", "phone_tenure_days", "email_tenure_days", "address_type",
    "time_at_address_months", "bureau_score", "au_tradelines", "oldest_tradeline_months",
    "inquiries_6m", "bureau_name_dob_mismatch", "stated_income_monthly", "employer_verified",
    "paystub_edit_flag", "vehicle_price", "dist_to_dealer_km", "ip_geo_mismatch_km",
    "device_apps_30d", "ssn_apps_30d", "phone_shared_count", "dealer_rapid_resubmits",
    "has_cobuyer", "vendor_a_idv_risk", "vendor_b_synth_score", "vendor_c_device_risk",
    "vendor_d_income_flag_prob", "vendor_e_consortium_risk", "ssn_deceased_or_invalid",
]


def _camouflage(df: pd.DataFrame, rng, p: float) -> pd.DataFrame:
    """
    Real fraud is not cleanly separable: sophisticated actors look 'normal' on many dimensions.
    For each fraud application, each attribute is independently replaced (with prob. p, scaled by a
    per-application sophistication level) by the value of a randomly chosen legitimate applicant.
    Derived ratios are then recomputed so the record stays internally consistent.
    """
    fraud_idx = np.flatnonzero(df.is_fraud.values == 1)
    good_idx = np.flatnonzero(df.is_fraud.values == 0)
    # Legitimate "look-alikes": good applicants who share fraud-like traits (recent immigrants with
    # new phones and adult-issued SSNs, students buying from distant dealers, gig-income earners).
    # These drive false positives and customer friction.
    look = rng.choice(good_idx, int(len(good_idx) * 0.03), replace=False)
    donors = rng.choice(fraud_idx, len(look))
    for col in CAMO_COLS:
        m = rng.random(len(look)) < 0.40
        df.iloc[look[m], df.columns.get_loc(col)] = df.iloc[donors[m], df.columns.get_loc(col)].values

    sophistication = rng.beta(2, 2, len(fraud_idx))  # 0 = sloppy, 1 = highly sophisticated
    sophistication[rng.random(len(fraud_idx)) < 0.12] = 10  # fully 'clean' professional fraud
    for col in CAMO_COLS:
        # vendor-observed signals (device graphs, consortium data) are harder for fraudsters to fake
        factor = 0.35 if col.startswith("vendor_") else 1.0
        m = rng.random(len(fraud_idx)) < p * factor * (0.4 + 1.2 * sophistication)
        tgt = fraud_idx[m]
        src = rng.choice(good_idx, len(tgt))
        df.iloc[tgt, df.columns.get_loc(col)] = df.iloc[src, df.columns.get_loc(col)].values
    # keep POC coverage consistent with the camouflaged vendor E values
    poc = df.vendor_e_in_poc.values == 1
    missing = poc & df.vendor_e_consortium_risk.isna().values
    pool = df.vendor_e_consortium_risk.values[poc & (df.is_fraud.values == 0)
                                              & ~df.vendor_e_consortium_risk.isna().values]
    vals = df.vendor_e_consortium_risk.values.copy()
    vals[missing] = rng.choice(pool, missing.sum())
    df["vendor_e_consortium_risk"] = np.where(poc, vals, np.nan)
    # enforce file-type integrity: no-file consumers have no bureau data
    nf = df.credit_file_type == "no_file"
    df.loc[nf, "bureau_score"] = np.nan
    df.loc[nf, ["au_tradelines", "oldest_tradeline_months"]] = 0
    # recompute derived fields
    df["income_ratio"] = (df.stated_income_monthly / df.verified_income_monthly).round(3)
    df["pti"] = (df.monthly_payment / df.stated_income_monthly).round(4)
    df["vehicle_to_income"] = (df.vehicle_price / (df.stated_income_monthly * 12)).round(3)
    return df


if __name__ == "__main__":
    d = generate()
    print(d.shape)
    print(d["fraud_type"].value_counts(normalize=True))
