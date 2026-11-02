"""Layer 4 — the weekly cycle end to end through the API: login → list → approve/override → QR → symptom → outcome → ledger."""
from __future__ import annotations

from tests.conftest import login


def test_health_and_auth(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/weekly-lists/current").status_code == 401
    assert client.post("/api/auth/login", data={"username": "supervisor", "password": "wrong"}).status_code == 401


def test_rbac(client):
    tech = login(client, "technician")
    assert client.get("/api/ledger/months", headers=tech).status_code == 403
    assert client.post("/api/admin/ledger/compute", headers=tech).status_code == 403
    assert client.get("/api/field/tasks", headers=tech).status_code == 200


def test_supervisor_cycle(client):
    sup = login(client, "supervisor")
    cur = client.get("/api/weekly-lists/current", headers=sup).json()
    assert cur["status"] == "proposed" and cur["items"]
    first, second = cur["items"][0], cur["items"][1]
    assert first["reason"] and first["action_ar"]
    # override requires a reason
    assert client.patch(f"/api/weekly-lists/items/{second['item_id']}", json={"status": "overridden"}, headers=sup).status_code == 400
    r = client.patch(f"/api/weekly-lists/items/{second['item_id']}", json={"status": "overridden", "override_reason": "الطاقم مشغول بالخزانة", "action": "inspect"}, headers=sup)
    assert r.status_code == 200 and r.json()["status"] == "overridden" and r.json()["action"] == "inspect"
    r = client.post(f"/api/weekly-lists/{cur['list_id']}/approve", headers=sup)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # map + card
    assets = client.get("/api/assets?limit=50", headers=sup).json()
    assert assets["n"] == 50 and assets["week_start"] == cur["week_start"]
    card = client.get(f"/api/assets/{first['asset_id']}", headers=sup).json()
    assert card["prediction"]["p"] >= 0.1 and card["list_item"]["rank"] == 1 and "explanation" in card["prediction"]


def test_technician_cycle_with_offline_batch(client):
    sup, tech = login(client, "supervisor"), login(client, "technician")
    tasks = client.get("/api/field/tasks", headers=tech).json()
    assert tasks
    t = tasks[0]
    card = client.get(f"/api/field/assets/{t['code'].lower().replace('-', '')}", headers=tech).json()  # sloppy code still resolves
    assert card["code"] == t["code"] and card["task"]["item_id"] == t["item_id"]
    batch = [dict(asset_code=t["code"], symptom_code="flicker", severity=2, client_ref="dev1-0001"),
             dict(asset_code=t["code"], symptom_code="flicker", severity=2, client_ref="dev1-0001"),   # replayed after reconnect
             dict(asset_code="LP-10002", symptom_code="unicorn", severity=1, client_ref="dev1-0002")]
    r = client.post("/api/field/observations", json=batch, headers=tech)
    assert r.status_code == 201
    st = [x["status"] for x in r.json()]
    assert st == ["created", "duplicate", "rejected"]
    r = client.post("/api/field/outcomes", json=[dict(item_id=t["item_id"], finding="confirmed_degradation", action_taken="driver replaced", cost_sar=640, client_ref="dev1-o1")], headers=tech)
    assert r.status_code == 201 and r.json()[0]["status"] == "created"
    cur = client.get("/api/weekly-lists/current", headers=sup).json()
    item = next(i for i in cur["items"] if i["item_id"] == t["item_id"])
    assert item["status"] == "done" and item["outcome"]["finding"] == "confirmed_degradation"
    card = client.get(f"/api/assets/{t['code']}", headers=sup).json()
    assert card["observations"][0]["symptom"] == "flicker" and card["observations"][0]["source"] == "technician_qr"


def test_manager_ledger_and_models(client):
    mgr = login(client, "manager")
    led = client.get("/api/ledger/months", headers=mgr).json()
    assert led["months"] and set(led["months"][-1]["pfr"]) >= {"2", "7", "14", "own"}
    models = client.get("/api/ledger/models", headers=mgr).json()
    assert models and models[0]["promoted"] is True
    assert client.get("/api/ledger/backtest", headers=mgr).status_code in (200, 404)


def test_admin_quarantine_and_openapi(client):
    adm = login(client, "admin")
    q = client.get("/api/admin/quarantine", headers=adm).json()
    assert "items" in q
    spec = client.get("/api/openapi.json").json()
    assert "/api/weekly-lists/current" in spec["paths"] and "/api/field/observations" in spec["paths"]
    assert client.get("/").status_code == 200 and client.get("/field/").status_code == 200
