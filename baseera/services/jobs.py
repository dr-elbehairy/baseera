"""Background jobs with live progress. One worker thread per job; state lives in sys_job so any API worker can report it.

Kinds: recompute (features → train → plan → ledger), features, train, plan, ledger, backtest, seed_sim, purge.
"""
from __future__ import annotations

import threading
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import session_scope
from ..core.models import Job

KINDS = ("recompute", "features", "train", "plan", "ledger", "backtest", "seed_sim", "purge")
_lock = threading.Lock()


def last_sunday(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


class Progress:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def __call__(self, pct: int, step: str) -> None:
        with session_scope() as db:
            j = db.get(Job, self.job_id)
            j.progress, j.step = int(pct), step[:256]
            j.log = list(j.log or []) + [f"{datetime.utcnow():%H:%M:%S} {step}"]


def running(db: Session) -> Job | None:
    return db.query(Job).filter(Job.status.in_(("queued", "running"))).order_by(Job.created_at.desc()).first()


def submit(db: Session, kind: str, params: dict | None, by: str) -> Job:
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind}")
    with _lock:
        if running(db):
            raise RuntimeError("a job is already running; wait for it to finish")
        j = Job(kind=kind, params=params or {}, created_by=by); db.add(j); db.commit()
    t = threading.Thread(target=_run, args=(j.job_id,), daemon=True, name=f"job-{kind}")
    t.start()
    return j


def _run(job_id: str) -> None:
    p = Progress(job_id)
    with session_scope() as db:
        j = db.get(Job, job_id); j.status, j.started_at = "running", datetime.utcnow(); kind, params = j.kind, dict(j.params or {})
    try:
        with session_scope() as db:
            result = RUNNERS[kind](db, params, p)
        with session_scope() as db:
            j = db.get(Job, job_id); j.status, j.progress, j.step, j.result, j.finished_at = "done", 100, "اكتمل", result, datetime.utcnow()
    except Exception as e:  # noqa: BLE001 — reported to the UI
        with session_scope() as db:
            j = db.get(Job, job_id); j.status, j.error, j.finished_at = "failed", f"{e}\n{traceback.format_exc()[-1500:]}", datetime.utcnow()
            j.log = list(j.log or []) + [f"{datetime.utcnow():%H:%M:%S} فشل: {e}"]


def _as_of(params: dict) -> date:
    return date.fromisoformat(params["as_of"]) if params.get("as_of") else date.today()


def run_features(db, params, p):
    from .features.build import build_features
    from .ledger.failures import derive_failures
    from .twin.sesi import compute as sesi_compute
    p(5, "اشتقاق أحداث العطل من أوامر العمل"); n_f = derive_failures(db)
    p(12, "حساب مؤشر الإجهاد البيئي SESI يوميًا"); n_s = sesi_compute(db)
    p(25, "بناء الخصائص الأسبوعية as-of (علامات، إشارات، SESI، اعتماديات)"); n = build_features(db, as_of=_as_of(params))
    return dict(failures=n_f, sesi_days=n_s, feature_rows=n)


def run_train(db, params, p):
    from .model.core import train
    p(10, "تدريب النموذج (تقسيم زمني + معايرة + بوابات)")
    mv = train(db, as_of=_as_of(params), force=bool(params.get("force")), approved_by=params.get("by"))
    return dict(model_version_id=mv.model_version_id, promoted=mv.promoted, auc=mv.metrics["auc"], gates={k: v["pass"] for k, v in mv.gates.items()})


def run_plan(db, params, p):
    from .plan import plan_week
    wk = date.fromisoformat(params["week_start"]) if params.get("week_start") else last_sunday(_as_of(params))
    p(20, f"بناء قائمة أسبوع {wk}"); wl = plan_week(db, wk)
    return dict(week_start=str(wk), items=len(wl.items), status=wl.status, list_id=wl.list_id)


def run_ledger(db, params, p):
    from .ledger.failures import derive_failures
    from .ledger.monthly import compute_months
    p(20, "اشتقاق الأعطال"); derive_failures(db)
    p(50, "حساب السجل الشهري"); rows = compute_months(db)
    return dict(months=len(rows))


def run_backtest(db, params, p):
    from .backtest import run_backtest as bt
    end = _as_of(params); split = date.fromisoformat(params["split"]) if params.get("split") else end - timedelta(days=int(params.get("test_days", 365)))
    p(10, f"اختبار رجعي {split} → {end} (يستغرق دقيقتين تقريبًا)")
    res = bt(db, split=split, end=end, train_model=True)
    return dict(split=str(split), end=str(end), pfr_own_L=res["pfr_own_L"], auc=res["metrics"]["auc"], n_failures=res["n_failures"])


def run_recompute(db, params, p):
    out = {}
    p(2, "1/4 أحداث العطل والخصائص"); out["features"] = run_features(db, params, lambda a, b: p(2 + a * 0.25, b))
    p(30, "2/4 تدريب النموذج"); out["train"] = run_train(db, params, lambda a, b: p(30 + a * 0.3, b))
    p(62, "3/4 قائمة الأسبوع"); out["plan"] = run_plan(db, params, lambda a, b: p(62 + a * 0.2, b))
    p(85, "4/4 السجل الشهري"); out["ledger"] = run_ledger(db, params, lambda a, b: p(85 + a * 0.14, b))
    return out


def run_seed_sim(db, params, p):
    from ..sim.generate import SimConfig
    from .ingest.simulated import seed_simulated
    cfg = SimConfig(n_poles=int(params.get("poles", 1200)), n_cabinets=int(params.get("cabinets", 24)), days=int(params.get("days", 736)),
                    seed=int(params.get("seed", 2026)), vis_main=float(params.get("vis_main", 0.70)), vis_sec=float(params.get("vis_sec", 0.55)))
    p(5, f"توليد المحاكاة ({cfg.n_poles} عمود، {cfg.n_cabinets} خزانة، {cfg.days} يومًا) وتمريرها بخطوط الاستيعاب")
    summ = seed_simulated(db, cfg)
    if params.get("then_recompute", True):
        p(40, "إعادة الحساب الكاملة على المحاكاة")
        summ["recompute"] = run_recompute(db, {"as_of": params.get("as_of")}, lambda a, b: p(40 + a * 0.6, b))
    return summ


def run_purge(db, params, p):
    """Delete all operational, feature and ledger data (users, audit, settings and jobs are kept)."""
    from sqlalchemy import delete
    from ..core import models as M
    import os, shutil
    p(10, "حذف البيانات التشغيلية والمشتقة")
    for t in (M.Outcome, M.ListItem, M.WeeklyList, M.Prediction, M.AssetWeek, M.FailureEvent, M.LedgerMonth, M.Observation, M.WorkOrder,
              M.Report, M.Quarantine, M.IngestRun, M.ModelVersion, M.TelemetryDay, M.Dependency, M.SesiDay, M.WeatherDay, M.Asset, M.Cabinet):
        db.execute(delete(t))
    db.commit()
    s = get_settings()
    for sub in ("models", "sim", "uploads"):
        shutil.rmtree(os.path.join(s.data_dir, sub), ignore_errors=True)
    bt = os.path.join(s.data_dir, "backtest.json")
    if os.path.exists(bt):
        os.remove(bt)
    return dict(purged=True)


RUNNERS = {"recompute": run_recompute, "features": run_features, "train": run_train, "plan": run_plan, "ledger": run_ledger,
           "backtest": run_backtest, "seed_sim": run_seed_sim, "purge": run_purge}


def to_dict(j: Job) -> dict:
    return dict(job_id=j.job_id, kind=j.kind, status=j.status, progress=j.progress, step=j.step, log=(j.log or [])[-30:], params=j.params,
                result=j.result, error=j.error, created_by=j.created_by, created_at=j.created_at.isoformat(),
                started_at=j.started_at.isoformat() if j.started_at else None, finished_at=j.finished_at.isoformat() if j.finished_at else None)
