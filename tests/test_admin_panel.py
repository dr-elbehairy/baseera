"""Admin panel — overview, templates, preview (dry run), manual records, quarantine retry, parameters, background jobs."""
from __future__ import annotations

import time

from tests.conftest import AS_OF, login


def test_overview_and_schema(client):
    adm = login(client, "admin")
    ov = client.get("/api/admin/overview", headers=adm).json()
    assert ov["tables"]["assets"]["n"] > 0 and "simulated" in ov["tables"]["assets"]["by_source"] and ov["model"]
    sch = client.get("/api/admin/ingest/schema", headers=adm).json()
    assert [p["name"] for p in sch] == ["cabinets", "assets", "dependencies", "weather", "reports", "work_orders", "observations", "telemetry"]
    tpl = client.get("/api/admin/ingest/assets/template.csv", headers=adm)
    assert tpl.status_code == 200 and tpl.text.startswith("asset_code,asset_type")


def test_preview_is_a_dry_run(client):
    adm = login(client, "admin")
    before = client.get("/api/admin/overview", headers=adm).json()["tables"]["assets"]["n"]
    csv = "asset_code,asset_type,lon,lat\nLP-77001,LED,46.70,24.80\nLP-77002,XXX,46.70,24.80\nLP-77003,LED,1,2\n"
    pv = client.post("/api/admin/ingest/assets/preview", files={"file": ("a.csv", csv, "text/csv")}, headers=adm).json()
    assert pv["rows"] == 3 and pv["ok"] == 1 and pv["quarantined"] == 2 and len(pv["reasons"]) == 2 and pv["sample"][0]["asset_code"] == "LP-77001"
    assert client.get("/api/admin/overview", headers=adm).json()["tables"]["assets"]["n"] == before  # nothing written
    r = client.post("/api/admin/ingest/assets/run?source=municipal", files={"file": ("a.csv", csv, "text/csv")}, headers=adm).json()
    assert r["n_ok"] == 1 and r["n_quarantined"] == 2
    assert client.get("/api/admin/overview", headers=adm).json()["tables"]["assets"]["n"] == before + 1


def test_manual_record_and_quarantine_retry(client):
    adm = login(client, "admin")
    r = client.post("/api/admin/records/observations", json={"row": {"asset_code": "LP-77001", "observed_at": "2026-05-01 21:00", "symptom_code": "flicker", "severity": 2}}, headers=adm)
    assert r.status_code == 200
    r = client.post("/api/admin/records/observations", json={"row": {"asset_code": "LP-1", "observed_at": "2026-05-01 21:00", "symptom_code": "flicker"}}, headers=adm)
    assert r.status_code == 422 and "unknown asset code" in r.json()["detail"]
    q = client.get("/api/admin/quarantine?pipeline=observations", headers=adm).json()
    row = next(i for i in q["items"] if i["payload"].get("asset_code") == "LP-1")
    fixed = {**row["payload"], "asset_code": "LP-77001"}
    r = client.post(f"/api/admin/quarantine/{row['row_id']}/retry", json={"payload": fixed}, headers=adm)
    assert r.status_code == 200 and r.json()["resolved"] is True
    assert all(i["row_id"] != row["row_id"] for i in client.get("/api/admin/quarantine?pipeline=observations", headers=adm).json()["items"])


def test_params_override_apply_and_audit(client):
    adm, sup = login(client, "admin"), login(client, "supervisor")
    from baseera.core.config import get_settings
    r = client.patch("/api/admin/params", json={"values": {"crew_jobs_per_week": 5, "lead_by_mode": {"lamp_eol": 4}}}, headers=adm)
    assert r.status_code == 200 and get_settings().crew_jobs_per_week == 5 and get_settings().lead_by_mode == {"lamp_eol": 4}
    assert client.patch("/api/admin/params", json={"values": {"jwt_secret": "x"}}, headers=adm).status_code == 422
    assert client.patch("/api/admin/params", json={"values": {"crew_jobs_per_week": 9}}, headers=sup).status_code == 403
    p = {x["key"]: x for x in client.get("/api/admin/params", headers=sup).json()}
    assert p["crew_jobs_per_week"]["overridden"] and p["crew_jobs_per_week"]["updated_by"] == "admin"
    assert any(a["action"] == "params.set" for a in client.get("/api/admin/audit", headers=adm).json())
    client.post("/api/admin/params/reset", json={}, headers=adm)
    assert get_settings().crew_jobs_per_week == 8 and not any(x["overridden"] for x in client.get("/api/admin/params", headers=adm).json())


def test_background_job_plan(client):
    adm = login(client, "admin")
    assert client.post("/api/admin/jobs/purge", json={"params": {}}, headers=adm).status_code == 400  # needs confirm
    j = client.post("/api/admin/jobs/plan", json={"params": {"as_of": str(AS_OF)}}, headers=adm).json()
    assert j["status"] in ("queued", "running")
    for _ in range(60):
        j = client.get(f"/api/admin/jobs/{j['job_id']}", headers=adm).json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j.get("error")
    assert j["progress"] == 100 and j["result"]["week_start"] == str(AS_OF) and j["log"]
