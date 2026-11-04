"""v0.4 — the seven layers of the vision: telemetry, SESI, dependency graph, diagnosis, conformal window, consequences,
optimiser (tiers / routes / Pareto / constraints), assistant and generated work orders."""
from __future__ import annotations

import time

from tests.conftest import AS_OF, login


def test_telemetry_and_graph_ingested(db_ready):
    runs = db_ready["runs"]
    assert runs["telemetry"]["ok"] > 1000 and runs["telemetry"]["quarantined"] == 0
    assert runs["dependencies"]["ok"] > 100


def test_sesi_and_new_features(pipeline_ready):
    from baseera.core.db import session_scope
    from baseera.core.models import AssetWeek, SesiDay
    with session_scope() as db:
        assert db.query(SesiDay).count() > 300
        r = db.query(AssetWeek).filter_by(week_start=AS_OF).first()
        for k in ("tele_anom_7d", "tele_trend_30d", "sesi_30d", "equiv_age_y", "dep_children", "parent_anom_7d"):
            assert k in r.x
        assert 0 <= r.x["sesi_30d"] <= 1


def test_window_model_trained_and_stored(pipeline_ready):
    m = pipeline_ready["metrics"]
    assert m["window_q_days"] is not None and m["window_q_days"] > 0 and 0.7 <= m["window_coverage_validation"] <= 1.0


def test_predictions_carry_prognosis_and_consequences(pipeline_ready):
    from baseera.core.db import session_scope
    from baseera.core.models import Prediction
    with session_scope() as db:
        P = db.query(Prediction).filter_by(week_start=AS_OF, run_tag="live").order_by(Prediction.priority.desc()).limit(30).all()
        assert P and all(p.cof and p.cof["total"] > 0 and set(p.cof) >= {"financial", "service", "safety", "environment", "reputation"} for p in P)
        withw = [p for p in P if p.window_lo is not None]
        assert len(withw) >= 10 and all(p.window_hi >= p.window_lo for p in withw)   # windows only where a signal or alert exists
        assert all(p.tier in ("immediate", "urgent", "planned", "monitor") for p in P)
        assert any(p.mode_pred for p in P)


def test_schedule_tiers_routes_pareto(client):
    sup = login(client, "supervisor")
    sc = client.get("/api/schedule/current", headers=sup).json()
    assert sc["items"] and sc["routes"] and len(sc["routes"]) <= sc["crews"]
    assert all(i["route"] and i["seq"] and i["safe_window"] and i["tier_ar"] for i in sc["items"])
    assert sum(sc["tiers"].values()) == len(sc["items"])
    assert sc["pareto"] and sc["pareto"][-1]["share"] >= sc["pareto"][0]["share"]
    assert sc["total_cost"] > 0


def test_twin_view(client):
    sup = login(client, "supervisor")
    sc = client.get("/api/schedule/current", headers=sup).json()
    pump = next((i for i in sc["items"] if i["category"] == "pumping"), None) or sc["items"][0]
    tw = client.get(f"/api/twin/assets/{pump['code']}", headers=sup).json()
    assert tw["sesi"]["index"] is not None and tw["sesi"]["equivalent_age_y"] is not None
    assert "diagnosis" in tw and tw["prediction"]["cof"]["total"] > 0
    if pump["category"] == "pumping":
        assert tw["channels"] and all("series" in c and c["baseline"] is not None for c in tw["channels"])


def test_assistant_and_work_order(client):
    sup = login(client, "supervisor")
    sc = client.get("/api/schedule/current", headers=sup).json()
    a, b = sc["items"][0], sc["items"][-1]
    r = client.post("/api/assistant/ask", json={"question": f"لماذا {a['code']} قبل {b['code']}؟"}, headers=sup).json()
    assert "العائد لكل ريال" in r["answer"] or "الاحتمال" in r["answer"]
    r = client.post("/api/assistant/ask", json={"question": "ملخص الأسبوع"}, headers=sup).json()
    assert "مهمة" in r["answer"]
    wo = client.post(f"/api/assistant/work-order/{a['item_id']}", headers=sup).json()
    d = wo["details"]
    assert d["parts"] and d["checklist"] and d["safe_window"] and d["text"] and d["asset"] == a["code"]
    wos = client.get("/api/assistant/work-orders", headers=sup).json()
    assert any(w["details"]["asset"] == a["code"] for w in wos)
    tasks = client.get("/api/field/tasks", headers=login(client, "technician")).json()
    assert all(("work_order" in t and t["safe_window"]) for t in tasks)
