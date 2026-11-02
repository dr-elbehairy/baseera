"""The simulated source: generate raw tables and push them through the *same* pipelines as municipal exports."""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...sim.generate import SimConfig, generate, write
from .pipelines.core import ORDER, PIPELINES


def seed_simulated(db: Session, cfg: SimConfig | None = None, outdir: str | None = None) -> dict:
    cfg = cfg or SimConfig()
    outdir = outdir or os.path.join(get_settings().data_dir, "sim")
    tables = generate(cfg)
    paths = write(tables, outdir)
    summary = {"meta": tables["meta"].iloc[0].to_dict(), "runs": {}}
    for name in ORDER:
        run = PIPELINES[name](db, source="simulated").run_csv(paths[name])
        summary["runs"][name] = {"in": run.n_in, "ok": run.n_ok, "quarantined": run.n_quarantined}
    return summary
