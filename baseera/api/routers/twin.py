"""Digital-twin view of one asset: telemetry channels with baselines and anomalies, SESI and equivalent age, diagnosis,
failure window, consequence breakdown."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.catalog import CHANNELS, MODES, TYPES, channels_for
from ...core.db import get_db
from ...core.models import Asset, Dependency, Prediction, TelemetryDay, User, WeeklyList
from ...core.security import require
from ...services.ingest.base import normalise_code
from ...services.model.prognosis import diagnose
from ...services.twin.sesi import asset_summary

router = APIRouter(prefix="/twin", tags=["twin"])


@router.get("/assets/{ref}")
def twin(ref: str, days: int = 120, db: Session = Depends(get_db), u: User = Depends(require())):
    a = db.get(Asset, ref) or db.query(Asset).filter_by(asset_code=normalise_code(ref)).first()
    if not a:
        raise HTTPException(404, "asset not found")
    wk = db.query(func.max(WeeklyList.week_start)).filter(WeeklyList.run_tag == "live").scalar() or date.today()
    since = wk - timedelta(days=days)
    rows = db.query(TelemetryDay).filter(TelemetryDay.asset_id == a.asset_id, TelemetryDay.day >= since, TelemetryDay.day <= wk).order_by(TelemetryDay.day).all()
    chans = {}
    for r in rows:
        chans.setdefault(r.channel, []).append(dict(day=str(r.day), v=r.value))
    base_rows = db.query(TelemetryDay).filter(TelemetryDay.asset_id == a.asset_id).order_by(TelemetryDay.day).limit(60 * 6).all()
    base = {}
    for r in base_rows:
        base.setdefault(r.channel, []).append(r.value)
    channels = []
    for ch in channels_for(a.category):
        if ch not in chans: continue
        b = base.get(ch, [])[:60]; mu = sum(b) / len(b) if b else None
        sd = (sum((x - mu) ** 2 for x in b) / max(1, len(b) - 1)) ** 0.5 if b and mu is not None else None
        last = chans[ch][-7:]; lv = sum(x["v"] for x in last) / len(last)
        z = ((lv - mu) / (sd or abs(mu) * 0.05 + 1e-6)) * CHANNELS[ch][3] if mu is not None else None
        channels.append(dict(channel=ch, ar=CHANNELS[ch][1], unit=CHANNELS[ch][2], source=CHANNELS[ch][4], baseline=(round(mu, 2) if mu is not None else None),
                             last=round(lv, 2), z=(round(z, 1) if z is not None else None), anomalous=bool(z is not None and z > 2), series=chans[ch]))
    p = db.query(Prediction).filter_by(asset_id=a.asset_id, week_start=wk, run_tag="live").first()
    kids = db.query(Dependency).filter_by(parent_asset_id=a.asset_id).count(); parent = db.query(Dependency).filter_by(child_asset_id=a.asset_id).first()
    parent_code = db.get(Asset, parent.parent_asset_id).asset_code if parent else None
    return dict(asset_id=a.asset_id, code=a.asset_code, type=a.asset_type, type_ar=TYPES[a.asset_type][1], category=a.category, week_start=str(wk),
                channels=channels, sesi=asset_summary(db, a.category, a.install_date, wk), diagnosis=diagnose(db, a.asset_id, a.asset_type, a.category, wk),
                prediction=(dict(p=round(p.p_fail, 3), risk_sar=round(p.risk_sar), tier=p.tier, mode=p.mode_pred, mode_ar=(MODES[p.mode_pred][1] if p.mode_pred in MODES else None),
                                 window=([p.window_lo, p.window_hi] if p.window_lo is not None else None), cof=p.cof, explanation=p.explanation) if p else None),
                graph=dict(dependents=kids, parent=parent_code))
