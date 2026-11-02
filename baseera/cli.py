"""Command line: the same operations the scheduler and the admin API run, for engineers and CI.

  baseera migrate                      create schema + demo users
  baseera seed-sim [--poles N --days D --vis-main f --vis-sec f]
  baseera ingest <pipeline> <csv> [--source municipal]
  baseera derive-failures
  baseera build-features --as-of YYYY-MM-DD
  baseera train --as-of YYYY-MM-DD [--force]
  baseera plan [--week YYYY-MM-DD]
  baseera ledger
  baseera backtest --split YYYY-MM-DD --end YYYY-MM-DD
  baseera demo --as-of YYYY-MM-DD     everything above on the simulation, in order (≈ 2–4 min)
  baseera serve [--port 8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta

from .core.config import get_settings
from .core.db import create_all, session_scope
from .core.security import seed_demo_users


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def last_sunday(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def cmd_migrate(a):
    create_all()
    with session_scope() as db:
        n = seed_demo_users(db)
    print(f"schema ready; demo users created: {n}")


def cmd_seed_sim(a):
    from .services.ingest.simulated import seed_simulated
    from .sim.generate import SimConfig
    create_all()
    with session_scope() as db:
        summ = seed_simulated(db, SimConfig(n_poles=a.poles, n_cabinets=a.cabinets, days=a.days, seed=a.seed, vis_main=a.vis_main, vis_sec=a.vis_sec))
    print(json.dumps(summ, ensure_ascii=False, default=str, indent=1))


def cmd_ingest(a):
    from .services.ingest.pipelines.core import PIPELINES
    with session_scope() as db:
        run = PIPELINES[a.pipeline](db, source=a.source).run_csv(a.csv)
        print(f"{a.pipeline}: in={run.n_in} ok={run.n_ok} quarantined={run.n_quarantined}")


def cmd_derive(a):
    from .services.ledger.failures import derive_failures
    with session_scope() as db:
        print("failure events derived:", derive_failures(db))


def cmd_features(a):
    from .services.features.build import build_features
    from .services.ledger.failures import derive_failures
    with session_scope() as db:
        derive_failures(db)
        n = build_features(db, as_of=_d(a.as_of) or date.today())
    print("feature rows:", n)


def cmd_train(a):
    from .services.model.core import train
    with session_scope() as db:
        mv = train(db, as_of=_d(a.as_of) or date.today(), force=a.force, approved_by="cli")
        print(json.dumps(dict(model_version_id=mv.model_version_id, promoted=mv.promoted,
                              metrics={k: v for k, v in mv.metrics.items() if k != "importance"}, gates=mv.gates), indent=1, default=str))


def cmd_plan(a):
    from .services.plan import plan_week
    with session_scope() as db:
        wk = _d(a.week) or last_sunday(_d(a.as_of) or date.today())
        wl = plan_week(db, wk)
        print(f"weekly list {wk}: {len(wl.items)} items (capacity {wl.capacity}), status {wl.status}")
        for i in sorted(wl.items, key=lambda x: x.rank)[:10]:
            print(f"  {i.rank:2d}. {i.asset_id[:8]}  p={i.p_fail:.2f}  risk={i.risk_sar:7.0f}  {i.action:8s} {i.reason}")


def cmd_ledger(a):
    from .services.ledger.failures import derive_failures
    from .services.ledger.monthly import compute_months, drift
    with session_scope() as db:
        derive_failures(db)
        rows = compute_months(db)
        for r in rows[-6:]:
            print(f"{r.month}  failures={r.n_failures:3d}  PFR@own={r.pfr.get('own')}  emergency={r.emergency_share}  dark_days={r.dark_days}")
        print("drift:", drift(db))


def cmd_backtest(a):
    from .services.backtest import run_backtest
    t0 = time.time()
    with session_scope() as db:
        res = run_backtest(db, split=_d(a.split), end=_d(a.end))
    print(f"backtest {res['split']} → {res['end']}: {res['weeks']} weeks, {res['n_failures']} failures, AUC {res['metrics']['auc']:.3f}")
    print(f"  PFR@own-L  baseera {res['pfr_own_L']['baseera']:.1%}  age-rule {res['pfr_own_L']['age_rule']:.1%}  reactive 0%")
    print(f"  emergency share {res['emergency_share']['reactive']:.0%} → {res['emergency_share']['baseera']:.0%}; dark days {res['dark_days']['reactive']} → {res['dark_days']['baseera']}")
    print(f"  precision@30d {res['precision30']:.1%}; written to {get_settings().data_dir}/backtest.json ({time.time()-t0:.0f}s)")


def cmd_demo(a):
    """Full pipeline on the simulation so a new engineer sees the system working in one command."""
    from .services.backtest import run_backtest
    from .services.features.build import build_features
    from .services.ingest.simulated import seed_simulated
    from .services.ledger.failures import derive_failures
    from .services.ledger.monthly import compute_months
    from .services.model.core import train
    from .services.plan import plan_week
    from .sim.generate import SimConfig
    t0 = time.time(); as_of = _d(a.as_of) or date.today()
    create_all()
    with session_scope() as db:
        seed_demo_users(db)
        summ = seed_simulated(db, SimConfig(n_poles=a.poles, n_cabinets=a.cabinets, days=a.days, seed=a.seed, vis_main=a.vis_main, vis_sec=a.vis_sec))
        print(f"[1/6] simulated source ingested: {summ['runs']}  ({time.time()-t0:.0f}s)")
        derive_failures(db); n = build_features(db, as_of=as_of)
        print(f"[2/6] failures derived, {n} feature rows  ({time.time()-t0:.0f}s)")
        mv = train(db, as_of=as_of, approved_by="demo", force=a.force)
        gates_txt = ", ".join("%s:%s" % (k, v["pass"]) for k, v in mv.gates.items())
        print(f"[3/6] model {mv.model_version_id[:8]} promoted={mv.promoted} AUC={mv.metrics['auc']:.3f} gates={{{gates_txt}}}  ({time.time()-t0:.0f}s)")
        wk = last_sunday(as_of); wl = plan_week(db, wk)
        print(f"[4/6] weekly list {wk}: {len(wl.items)} items  ({time.time()-t0:.0f}s)")
        compute_months(db)
        print(f"[5/6] live ledger computed  ({time.time()-t0:.0f}s)")
        split = as_of - timedelta(days=a.test_days)
        res = run_backtest(db, split=split, end=as_of, train_model=True)
        print(f"[6/6] backtest {split}→{as_of}: PFR@L {res['pfr_own_L']['baseera']:.0%} vs age-rule {res['pfr_own_L']['age_rule']:.0%}; "
              f"emergency {res['emergency_share']['baseera']:.0%}; AUC {res['metrics']['auc']:.2f}  ({time.time()-t0:.0f}s)")
    print("done. run `baseera serve` and open http://localhost:8000 (supervisor/demo) or /field (technician/demo)")


def cmd_serve(a):
    import uvicorn
    uvicorn.run("baseera.api.app:app", host=a.host, port=a.port, reload=a.reload)


def main(argv=None):
    p = argparse.ArgumentParser(prog="baseera", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("migrate").set_defaults(f=cmd_migrate)
    s = sp.add_parser("seed-sim"); s.set_defaults(f=cmd_seed_sim)
    for s_ in (s,):
        s_.add_argument("--poles", type=int, default=1200); s_.add_argument("--cabinets", type=int, default=24); s_.add_argument("--days", type=int, default=736)
        s_.add_argument("--seed", type=int, default=2026); s_.add_argument("--vis-main", type=float, default=0.70); s_.add_argument("--vis-sec", type=float, default=0.55)
    s = sp.add_parser("ingest"); s.add_argument("pipeline"); s.add_argument("csv"); s.add_argument("--source", default="municipal"); s.set_defaults(f=cmd_ingest)
    sp.add_parser("derive-failures").set_defaults(f=cmd_derive)
    s = sp.add_parser("build-features"); s.add_argument("--as-of"); s.set_defaults(f=cmd_features)
    s = sp.add_parser("train"); s.add_argument("--as-of"); s.add_argument("--force", action="store_true"); s.set_defaults(f=cmd_train)
    s = sp.add_parser("plan"); s.add_argument("--week"); s.add_argument("--as-of"); s.set_defaults(f=cmd_plan)
    sp.add_parser("ledger").set_defaults(f=cmd_ledger)
    s = sp.add_parser("backtest"); s.add_argument("--split", required=True); s.add_argument("--end", required=True); s.set_defaults(f=cmd_backtest)
    s = sp.add_parser("demo"); s.add_argument("--as-of"); s.add_argument("--test-days", type=int, default=365); s.add_argument("--force", action="store_true")
    s.add_argument("--poles", type=int, default=1200); s.add_argument("--cabinets", type=int, default=24); s.add_argument("--days", type=int, default=736)
    s.add_argument("--seed", type=int, default=2026); s.add_argument("--vis-main", type=float, default=0.70); s.add_argument("--vis-sec", type=float, default=0.55)
    s.set_defaults(f=cmd_demo)
    s = sp.add_parser("serve"); s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8000); s.add_argument("--reload", action="store_true")
    s.set_defaults(f=cmd_serve)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
