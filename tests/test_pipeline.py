"""Layers 2–5 — no temporal leakage, model gates, decision rule, PFR@L, ledger."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from baseera.core.config import get_settings
from baseera.core.db import session_scope
from baseera.core.models import AssetWeek, FailureEvent, LedgerMonth, ListItem, WeeklyList
from baseera.services.decision.rank import build_list, score_frame
from baseera.services.features.build import FEATURES, frame
from baseera.services.ledger.pfr import leads_for_failures
from tests.conftest import AS_OF


def test_features_have_no_future_labels(pipeline_ready):
    s = get_settings()
    with session_scope() as db:
        rows = db.query(AssetWeek).all()
        assert rows
        for r in rows:
            known = r.week_start + timedelta(days=s.horizon_days) <= AS_OF
            assert (r.label_h is not None) == known, f"label leak at {r.week_start}"
            assert set(FEATURES) <= set(r.x)


def test_history_features_only_use_past_failures(pipeline_ready):
    """days_since_last_fail at week W must never be computed from a failure dated ≥ W."""
    with session_scope() as db:
        df = frame(db)
        F = pd.DataFrame([(f.asset_id, f.failed_on) for f in db.query(FailureEvent).filter_by(run_tag="live")], columns=["asset_id", "failed_on"])
        sample = df.sample(min(400, len(df)), random_state=1)
        for r in sample.itertuples():
            past = F[(F.asset_id == r.asset_id) & (F.failed_on < r.week_start)]
            expected = min(999.0, (r.week_start - past.failed_on.max()).days) if len(past) else 999.0
            assert abs(r.days_since_last_fail - expected) < 1e-6


def test_model_metrics_and_gates_reported(pipeline_ready):
    m, g = pipeline_ready["metrics"], pipeline_ready["gates"]
    assert 0.5 <= m["auc"] <= 1.0 and 0 <= m["brier"] <= 0.25
    assert set(g) == {"auc", "brier_not_worse", "pfr_gain_over_age", "single_group_share"}
    assert all("pass" in v for v in g.values())


def test_decision_rule_is_declared_and_capacity_bound():
    s = get_settings()
    df = pd.DataFrame(dict(asset_id=[f"a{i}" for i in range(20)], p_fail=[0.05, 0.2, 0.9, 0.5, 0.12] * 4,
                           asset_type=["LED", "HAL", "CAB", "LED", "SOL"] * 4, street_class=["main", "sec"] * 10,
                           criticality=["none", "crossing", "none", "none", "hospital"] * 4, kind=["pole", "pole", "cabinet", "pole", "pole"] * 4,
                           age_y=[3, 5, 15, 20, 4] * 4))
    sc = score_frame(df)
    # risk formula, element by element
    r = sc.iloc[2]  # cabinet, p=0.9
    expected = 0.9 * (s.cost_planned["CAB"] * (s.emergency_multiplier - 1) + 1.8 * 1.0 * 40 * s.consequence_sar_per_unit)
    assert abs(r.risk_sar - expected) < 1e-6
    assert r.action == "replace" and sc.iloc[3].action == "replace" and sc.iloc[1].action == "inspect"
    lst = build_list(sc, capacity=5)
    assert len(lst) == 5 and list(lst["rank"]) == [1, 2, 3, 4, 5]
    assert (lst.p_fail >= s.alert_probability).all()
    assert lst.priority.is_monotonic_decreasing


def test_pfr_lead_logic():
    lists = {date(2026, 1, 4): {"a"}, date(2026, 1, 11): {"a", "b"}, date(2026, 3, 1): {"c"}}
    fails = [("a", date(2026, 1, 20)), ("b", date(2026, 1, 12)), ("c", date(2026, 2, 1)), ("d", date(2026, 1, 20))]
    assert leads_for_failures(fails, lists) == [16, 1, -1, -1]


def test_weekly_list_persisted_with_reasons(pipeline_ready):
    with session_scope() as db:
        wl = db.get(WeeklyList, pipeline_ready["list_id"])
        assert wl.week_start == AS_OF and wl.status in ("proposed", "approved")  # test_api may have approved it first
        assert 0 < len(wl.items) <= wl.capacity
        for i in wl.items:
            assert i.reason and i.action in ("inspect", "service", "replace") and i.p_fail >= get_settings().alert_probability


def test_ledger_months_exist_and_are_consistent(pipeline_ready):
    with session_scope() as db:
        rows = db.query(LedgerMonth).filter_by(run_tag="live").order_by(LedgerMonth.month).all()
        assert len(rows) >= 12
        for r in rows:
            assert r.n_failures >= 0 and set(r.pfr) >= {"2", "7", "14", "own"}
            if r.n_failures:
                assert 0 <= r.pfr["own"] <= 1


def test_backtest_regression(pipeline_ready):
    """The backtest is the project's regression test: Baseera must beat the age rule with the same crew."""
    from baseera.services.backtest import run_backtest
    with session_scope() as db:
        res = run_backtest(db, split=AS_OF - timedelta(days=140), end=AS_OF, out_path="./data/test/backtest.json")
    assert res["n_failures"] > 0 and res["weeks"] >= 15
    assert res["pfr_own_L"]["baseera"] > res["pfr_own_L"]["age_rule"]
    assert 0 <= res["emergency_share"]["baseera"] < 1.0 and res["dark_days"]["baseera"] <= res["dark_days"]["reactive"]
    assert res["lead_hist"]["counts"] and sum(res["lead_hist"]["counts"]) == res["n_failures"] - res["missed"]
