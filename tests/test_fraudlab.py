import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from fraudlab.data_generator import GeneratorConfig, generate  # noqa: E402
from fraudlab.kpis import dealer_watchlist, monthly_kpis  # noqa: E402
from fraudlab.model import FraudModel, capture_at_rate, psi, time_split  # noqa: E402
from fraudlab.rules_engine import ACTION_RANK, decide, evaluate_rules, load_policy  # noqa: E402
from fraudlab.strategy import Economics, champion_vs_challenger, optimise_cutoffs  # noqa: E402


@pytest.fixture(scope="module")
def df():
    return generate(GeneratorConfig(n_apps=15_000, seed=1))


@pytest.fixture(scope="module")
def policy():
    return load_policy()


@pytest.fixture(scope="module")
def model_and_split(df):
    tr, ca, oot = time_split(df)
    return FraudModel().fit(tr, ca), tr, ca, oot


# ---------------------------------------------------------------- data
def test_generator_is_reproducible():
    a = generate(GeneratorConfig(n_apps=2000, seed=5))
    b = generate(GeneratorConfig(n_apps=2000, seed=5))
    pd.testing.assert_frame_equal(a, b)


def test_generator_shape_and_fraud_mix(df):
    assert len(df) == 15_000
    assert df.app_month.nunique() == 12
    assert 0.02 < df.is_fraud.mean() < 0.07
    assert set(df.fraud_type.unique()) >= {"none", "synthetic_identity", "straw_buyer",
                                           "income_misrep", "application_fraud"}


def test_fraud_pressure_trends_up(df):
    m = df.groupby("app_month").is_fraud.mean()
    assert m.iloc[-3:].mean() > m.iloc[:3].mean()


def test_no_file_has_no_bureau_score(df):
    assert df.loc[df.credit_file_type == "no_file", "bureau_score"].isna().all()


def test_vendor_e_only_in_poc(df):
    assert df.loc[df.vendor_e_in_poc == 0, "vendor_e_consortium_risk"].isna().all()
    assert df.loc[df.vendor_e_in_poc == 1, "vendor_e_consortium_risk"].notna().all()


# ---------------------------------------------------------------- rules
def test_all_rules_evaluate(df, policy):
    for strat in ("champion", "challenger"):
        hits = evaluate_rules(df, policy, strat)
        assert hits.dtypes.eq(bool).all()
        assert len(hits) == len(df)


def test_decision_hierarchy(policy):
    row = generate(GeneratorConfig(n_apps=200, seed=3)).iloc[[0]].copy()
    row["ssn_deceased_or_invalid"] = 1          # DECLINE rule
    row["address_type"] = "mail_drop"            # REVIEW rule
    out = decide(row, policy, "champion")
    assert out.decision.iloc[0] == "DECLINE"
    assert "ID-001" in out.reason_codes.iloc[0] and "ID-003" in out.reason_codes.iloc[0]


def test_ml_score_layers_on_rules(df, policy):
    sub = df.head(500)
    hi = decide(sub, policy, "challenger", model_score=np.full(len(sub), 0.99))
    assert (hi.decision == "DECLINE").all()
    lo = decide(sub, policy, "challenger", model_score=np.zeros(len(sub)))
    base = decide(sub, policy, "challenger")
    assert (lo.decision == base.decision).all()


def test_missing_values_never_fire(policy):
    row = generate(GeneratorConfig(n_apps=200, seed=3)).iloc[[0]].copy()
    row["income_ratio"] = np.nan
    hits = evaluate_rules(row, policy, "challenger")
    assert not hits["INC-001"].iloc[0]


def test_broken_rule_fails_loudly(df, policy):
    bad = {**policy, "rules": policy["rules"] + [{"id": "BAD", "name": "x", "typology": "x",
           "condition": "no_such_column > 1", "action": "REVIEW", "strategies": ["challenger"]}]}
    with pytest.raises(ValueError):
        evaluate_rules(df.head(10), bad, "challenger")


# ---------------------------------------------------------------- model
def test_model_oot_performance(model_and_split):
    m, _, _, oot = model_and_split
    r = m.evaluate(oot)
    assert r["auc"] > 0.88
    assert r["capture_at_10pct"] > 0.6


def test_scores_are_probabilities(model_and_split):
    m, _, _, oot = model_and_split
    s = m.predict(oot)
    assert s.min() >= 0 and s.max() <= 1


def test_psi_zero_for_identical():
    x = np.random.default_rng(0).random(5000)
    assert psi(x, x) < 1e-6


def test_capture_at_rate_perfect_ranker():
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    s = np.arange(10)[::-1].astype(float)
    assert capture_at_rate(y, s, 0.2) == 1.0


# ---------------------------------------------------------------- strategy & KPIs
def test_challenger_beats_champion(model_and_split, policy):
    m, _, _, oot = model_and_split
    res, _, _ = champion_vs_challenger(oot, policy, m.predict(oot))
    champ, chall = res.iloc[0], res.iloc[1]
    assert chall.fraud_capture_rate_usd > champ.fraud_capture_rate_usd
    assert chall.total_cost_usd < champ.total_cost_usd


def test_cutoff_grid_respects_ordering(model_and_split, policy):
    m, _, _, oot = model_and_split
    g = optimise_cutoffs(oot, policy, m.predict(oot))
    assert (g.decline_cutoff > g.review_cutoff).all()
    assert g.feasible.iloc[0] or not g.feasible.any()


def test_monthly_kpis_bounds(df, policy):
    dec = decide(df, policy, "champion").decision
    k = monthly_kpis(df, dec, Economics.from_policy(policy))
    for c in ["auto_approval_rate", "fraud_capture_rate", "false_positive_rate", "manual_review_rate"]:
        assert k[c].between(0, 1).all()


def test_dealer_watchlist_ranked(df):
    w = dealer_watchlist(df, min_apps=20)
    assert w.z_score.is_monotonic_decreasing


# ---------------------------------------------------------------- SQL
def test_sql_library_runs(df, policy):
    from run_pipeline import load_sql_mart, run_sql_library
    sub = df.head(4000)
    champ = decide(sub, policy, "champion")
    chall = decide(sub, policy, "challenger", model_score=np.zeros(len(sub)))
    con = load_sql_mart(sub, champ, chall, np.zeros(len(sub)))
    res = run_sql_library(con)
    assert {"monthly_kpis", "straw_buyer_dealer_concentration", "vendor_decile_lift",
            "reason_code_effectiveness"} <= set(res)
    assert len(res["monthly_kpis"]) > 0
