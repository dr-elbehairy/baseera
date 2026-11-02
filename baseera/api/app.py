"""FastAPI application: REST API under /api, supervisor web app at /, technician PWA at /field."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..core.config import get_settings
from ..core.db import create_all, session_scope
from ..core.models import Asset, Job
from ..core.params import apply_overrides
from ..core.security import seed_demo_users
from ..services import jobs
from .routers import admin, assets, auth, field, ledger, lists

APPS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "apps")


def _recover_jobs(db) -> None:
    """A job that was running when the process died can never finish; mark it so the UI does not wait forever."""
    for j in db.query(Job).filter(Job.status.in_(("queued", "running"))).all():
        j.status, j.error = "failed", "process restarted while the job was running"


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Baseera — Predictive Maintenance for Urban Assets", version="0.2.0",
                  description="بصيرة: سجل قابلية التنبؤ وقائمة الأسبوع لصيانة الأصول الحضرية", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    for r in (auth, assets, lists, field, ledger, admin):
        app.include_router(r.router, prefix="/api")

    @app.get("/api/health", tags=["ops"])
    def health():
        return {"status": "ok", "env": s.env, "version": app.version}

    @app.on_event("startup")
    def _startup():
        create_all()
        with session_scope() as db:
            seed_demo_users(db)
            apply_overrides(db)
            _recover_jobs(db)
            if s.auto_demo and db.query(Asset).count() == 0 and not jobs.running(db):
                # fresh cloud deployment: seed the tagged simulation so the platform is usable the moment it comes up
                jobs.submit(db, "seed_sim", {"as_of": s.auto_demo_as_of, "by": "startup"}, by="startup")

    if os.path.isdir(APPS):
        app.mount("/field", StaticFiles(directory=os.path.join(APPS, "field"), html=True), name="field")
        app.mount("/static", StaticFiles(directory=os.path.join(APPS, "web")), name="web-static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(os.path.join(APPS, "web", "index.html"))
    return app


app = create_app()
