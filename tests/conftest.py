"""Test fixtures: a fresh SQLite database per session, seeded with a small simulation (fast), and an API client."""
from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("BASEERA_DATABASE_URL", "sqlite:///./data/test/baseera-test.db")
os.environ.setdefault("BASEERA_DATA_DIR", "./data/test")
os.environ.setdefault("BASEERA_MODEL_DIR", "./data/test/models")
os.environ.setdefault("BASEERA_JWT_SECRET", "test-secret")
os.environ.setdefault("BASEERA_CREW_JOBS_PER_WEEK", "8")

from baseera.core.db import create_all, reset_engine, session_scope  # noqa: E402
from baseera.core.security import seed_demo_users  # noqa: E402

SIM_KW = dict(n_poles=160, n_cabinets=4, days=560, seed=7)   # 2024-10-27 → 2026-05-09
AS_OF = date(2026, 5, 3)                                      # a Sunday inside the simulated range


@pytest.fixture(scope="session")
def db_ready():
    path = "./data/test/baseera-test.db"
    if os.path.exists(path):
        os.remove(path)
    os.makedirs("./data/test/models", exist_ok=True)
    reset_engine(); create_all()
    from baseera.services.ingest.simulated import seed_simulated
    from baseera.sim.generate import SimConfig
    with session_scope() as db:
        seed_demo_users(db)
        summary = seed_simulated(db, SimConfig(**SIM_KW), outdir="./data/test/sim")
    return summary


@pytest.fixture(scope="session")
def pipeline_ready(db_ready):
    from baseera.services.features.build import build_features
    from baseera.services.ledger.failures import derive_failures
    from baseera.services.model.core import train
    from baseera.services.plan import plan_week
    from baseera.services.ledger.monthly import compute_months
    with session_scope() as db:
        derive_failures(db)
        build_features(db, as_of=AS_OF)
        mv = train(db, as_of=AS_OF, force=True, approved_by="tests")
        wl = plan_week(db, AS_OF)
        compute_months(db)
        return dict(model_version_id=mv.model_version_id, list_id=wl.list_id, n_items=len(wl.items), metrics=mv.metrics, gates=mv.gates)


@pytest.fixture(scope="session")
def client(pipeline_ready):
    from fastapi.testclient import TestClient
    from baseera.api.app import create_app
    with TestClient(create_app()) as c:
        yield c


def login(client, user: str) -> dict:
    r = client.post("/api/auth/login", data={"username": user, "password": "demo"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
