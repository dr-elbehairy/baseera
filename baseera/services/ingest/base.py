"""Ingestion framework: read rows → validate (pydantic) → match asset → upsert, or quarantine with a written reason.

Rule: nothing enters the operational schema without a matched asset (except assets, cabinets and weather themselves).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Iterable

import pandas as pd
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import IngestRun, Quarantine


class RowError(Exception):
    pass


def normalise_code(code: Any) -> str:
    """Contractor exports vary: ' lp-10001 ', 'LP10001', 'LP_10001' → 'LP-10001'."""
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return ""
    s = str(code).strip().upper().replace("_", "-").replace(" ", "")
    m = re.match(r"^([A-Z]{2})-?0*(\d+)$", s)
    if m:
        prefix, num = m.groups()
        return f"{prefix}-{int(num):02d}" if prefix == "CB" else f"{prefix}-{int(num)}"
    return s


def reporter_hash(value: Any) -> str | None:
    """PDPL: identity of the reporter never reaches the database — only a salted hash for de-duplication."""
    if value is None or str(value).strip() == "" or (isinstance(value, float) and pd.isna(value)):
        return None
    salt = get_settings().jwt_secret
    return hashlib.sha256(f"{salt}:{str(value).strip()}".encode()).hexdigest()


def to_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        raise RowError(f"bad datetime: {v!r}")
    return ts.to_pydatetime()


def opt_dt(v: Any) -> datetime | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return None
    return to_dt(v)


class Pipeline:
    name: str = "base"
    schema: type[BaseModel]

    def __init__(self, db: Session, source: str = "municipal"):
        self.db = db
        self.source = source
        self.s = get_settings()

    # -- to implement
    def handle(self, row: BaseModel, raw: dict) -> None:
        raise NotImplementedError

    # -- framework
    def run(self, rows: Iterable[dict]) -> IngestRun:
        run = IngestRun(pipeline=self.name)
        self.db.add(run); self.db.flush()
        for raw in rows:
            raw = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in dict(raw).items()}
            run.n_in += 1
            try:
                row = self.schema(**raw)
                self.handle(row, raw)
                run.n_ok += 1
            except (ValidationError, RowError, ValueError) as e:
                self.db.add(Quarantine(pipeline=self.name, raw_payload=_jsonable(raw), reason=str(e)[:2000]))
                run.n_quarantined += 1
            if run.n_in % 2000 == 0:
                self.db.flush()
        run.finished_at = datetime.utcnow()
        self.db.commit()
        return run

    def run_csv(self, path: str) -> IngestRun:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        return self.run(df.to_dict("records"))

    def run_one(self, raw: dict) -> tuple[bool, str | None]:
        """Single record from a form: (ok, reason). Quarantined like any other row when it fails."""
        run = self.run([raw])
        if run.n_ok == 1:
            return True, None
        q = self.db.query(Quarantine).filter_by(pipeline=self.name).order_by(Quarantine.row_id.desc()).first()
        return False, (q.reason if q else "rejected")


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (datetime, pd.Timestamp)):
            out[k] = v.isoformat()
        elif hasattr(v, "item"):
            out[k] = v.item()
        else:
            out[k] = v
    return out
