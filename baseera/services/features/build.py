"""Weekly as-of feature builder.

For every asset and every week start W, the row contains only what was knowable before W:
  * failures reported before W (history), observations recorded before W (symptoms), weather up to W,
  * plus the 7-day temperature *forecast* that exists at W (from the forecast feed; in simulation, actual + noise).
The label (failure within H days after W) is filled only when W + H <= as_of, otherwise NULL.
See catalog.md for the definition and source of every feature.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...core.catalog import CATEGORY_CODE, TYPE_CODE, is_node
from ...core.config import get_settings
from ...core.models import Asset, AssetWeek, Cabinet, FailureEvent, Observation, WeatherDay

FEATURES = ["age_y", "type_code", "category_code", "main_road", "is_cabinet", "crit_w", "cabinet_age_y",
            "days_since_last_fail", "fails_365d", "cabinet_fails_365d",
            "symptoms_14d", "symptoms_30d", "max_sev_30d", "circuit_partial_trips_14d",
            "tmax_14d", "tmax_fcst_7d", "rain_7d", "rain_30d", "dust_30d", "heat_load_120d"]
CRIT_W = {"none": 1.0, "mosque": 1.6, "school": 2.0, "crossing": 2.4, "hospital": 3.0}


def week_starts_between(start: date, end: date) -> list[date]:
    """Sundays in [start, end]."""
    d = start + timedelta(days=(6 - start.weekday()) % 7)  # Monday=0 … Sunday=6
    out = []
    while d <= end:
        out.append(d); d += timedelta(days=7)
    return out


def load_frames(db: Session, run_tag: str = "live") -> dict[str, pd.DataFrame]:
    A = pd.DataFrame([dict(asset_id=a.asset_id, asset_code=a.asset_code, asset_type=a.asset_type, category=a.category, kind=a.kind, street_class=a.street_class,
                           criticality=a.criticality, install_date=a.install_date, cabinet_id=a.cabinet_id, lon=a.lon, lat=a.lat)
                      for a in db.query(Asset).filter(Asset.active.is_(True)).all()])
    C = pd.DataFrame([dict(cabinet_id=c.cabinet_id, cab_install=c.install_date) for c in db.query(Cabinet).all()])
    F = pd.DataFrame([dict(asset_id=f.asset_id, failed_on=f.failed_on, mode=f.failure_mode)
                      for f in db.query(FailureEvent).filter(FailureEvent.run_tag == run_tag).all()], columns=["asset_id", "failed_on", "mode"])
    O = pd.DataFrame([dict(asset_id=o.asset_id, day=o.observed_at.date(), symptom=o.symptom_code, sev=o.severity)
                      for o in db.query(Observation).all()], columns=["asset_id", "day", "symptom", "sev"])
    W = pd.DataFrame([dict(day=w.day, tmax=w.tmax_c, rain=w.rain_mm, dust=w.dust) for w in db.query(WeatherDay).all()],
                     columns=["day", "tmax", "rain", "dust"]).sort_values("day")
    if len(A) and len(C):
        A = A.merge(C, on="cabinet_id", how="left")
    else:
        A["cab_install"] = None
    return dict(assets=A, failures=F, observations=O, weather=W)


def build_features(db: Session, as_of: date, weeks: list[date] | None = None, horizon: int | None = None,
                   run_tag: str = "live", replace: bool = True) -> int:
    """Build feat_asset_week rows for the given week starts (default: all Sundays with data, up to as_of)."""
    s = get_settings(); H = horizon or s.horizon_days
    fr = load_frames(db, run_tag)
    A, F, O, Wx = fr["assets"], fr["failures"], fr["observations"], fr["weather"]
    if A.empty:
        return 0
    if weeks is None:
        first = (Wx.day.min() if len(Wx) else as_of - timedelta(days=365)) + timedelta(days=7)
        weeks = week_starts_between(first, as_of)
    if replace and weeks:
        db.execute(delete(AssetWeek).where(AssetWeek.week_start.in_(weeks)))
        db.flush()

    # index helpers
    n = len(A); idx = {a: i for i, a in enumerate(A.asset_id)}
    cab_of = A.cabinet_id.fillna("").values
    cab_members: dict[str, np.ndarray] = {c: np.where(cab_of == c)[0] for c in set(cab_of) if c}
    inst = pd.to_datetime(A.install_date); cinst = pd.to_datetime(A.cab_install)
    F = F.copy(); F["failed_on"] = pd.to_datetime(F.failed_on)
    O = O.copy(); O["day"] = pd.to_datetime(O.day)
    Wx = Wx.copy(); Wx["day"] = pd.to_datetime(Wx.day); Wx = Wx.set_index("day")
    fc_rng = np.random.default_rng(11)  # forecast error in simulation; replaced by the forecast feed in production

    rows = []
    for w in weeks:
        W = pd.Timestamp(w)
        hist_fail = F[F.failed_on < W]
        last = hist_fail.groupby("asset_id").failed_on.max()
        f365 = hist_fail[hist_fail.failed_on >= W - pd.Timedelta(days=365)].groupby("asset_id").size()
        o14 = O[(O.day < W) & (O.day >= W - pd.Timedelta(days=14))]
        o30 = O[(O.day < W) & (O.day >= W - pd.Timedelta(days=30))]
        s14 = o14.groupby("asset_id").size(); s30 = o30.groupby("asset_id").size(); mx30 = o30.groupby("asset_id").sev.max()
        trips = o14[o14.symptom == "partial_trip"].groupby("asset_id").size()
        trip_arr = np.zeros(n); fails_arr = np.zeros(n)
        for a, v in trips.items():
            if a in idx: trip_arr[idx[a]] = v
        for a, v in f365.items():
            if a in idx: fails_arr[idx[a]] = v
        circuit = np.zeros(n); cab_f = np.zeros(n)
        for c, members in cab_members.items():
            circuit[members] = trip_arr[members].sum(); cab_f[members] = fails_arr[members].sum()
        wx14 = Wx[(Wx.index < W) & (Wx.index >= W - pd.Timedelta(days=14))]
        wx7 = Wx[(Wx.index < W) & (Wx.index >= W - pd.Timedelta(days=7))]
        wx30 = Wx[(Wx.index < W) & (Wx.index >= W - pd.Timedelta(days=30))]
        wx120 = Wx[(Wx.index < W) & (Wx.index >= W - pd.Timedelta(days=120))]
        fc = Wx[(Wx.index >= W) & (Wx.index < W + pd.Timedelta(days=7))]
        tmax14 = float(wx14.tmax.mean()) if len(wx14) else 35.0
        tfc = (float(fc.tmax.mean()) + float(fc_rng.normal(0, 0.8))) if len(fc) else tmax14
        rain7 = float(wx7.rain.sum()); rain30 = float(wx30.rain.sum()); dust30 = float(wx30.dust.sum())
        heat = float(np.clip(wx120.tmax - 38, 0, None).sum()) if len(wx120) else 0.0
        age = ((W - inst).dt.days / 365.25).fillna(10.0).values
        cage = ((W - cinst).dt.days / 365.25).fillna(10.0).values
        dsl = np.full(n, 999.0)
        for a, d in last.items():
            if a in idx: dsl[idx[a]] = min(999.0, (W - d).days)
        label = None
        if w + timedelta(days=H) <= as_of:
            nxt = F[(F.failed_on >= W) & (F.failed_on < W + pd.Timedelta(days=H))].asset_id.unique()
            label = np.zeros(n, int)
            for a in nxt:
                if a in idx: label[idx[a]] = 1
        for i in range(n):
            a = A.asset_id.iloc[i]
            x = dict(age_y=round(float(age[i]), 2), type_code=TYPE_CODE[A.asset_type.iloc[i]], category_code=CATEGORY_CODE.get(A.category.iloc[i], 0),
                     main_road=int(A.street_class.iloc[i] == "main"), is_cabinet=int(is_node(A.asset_type.iloc[i])), crit_w=CRIT_W.get(A.criticality.iloc[i], 1.0), cabinet_age_y=round(float(cage[i]), 2),
                     days_since_last_fail=float(dsl[i]), fails_365d=float(fails_arr[i]), cabinet_fails_365d=float(cab_f[i]),
                     symptoms_14d=float(s14.get(a, 0)), symptoms_30d=float(s30.get(a, 0)), max_sev_30d=float(mx30.get(a, 0)),
                     circuit_partial_trips_14d=float(circuit[i]), tmax_14d=round(tmax14, 2), tmax_fcst_7d=round(tfc, 2),
                     rain_7d=round(rain7, 1), rain_30d=round(rain30, 1), dust_30d=dust30, heat_load_120d=round(heat, 1))
            rows.append(dict(asset_id=a, week_start=w, x=x, label_h=(int(label[i]) if label is not None else None)))
        if len(rows) >= 20000:
            db.bulk_insert_mappings(AssetWeek, rows); rows = []
    if rows:
        db.bulk_insert_mappings(AssetWeek, rows)
    db.commit()
    return len(weeks) * n


def frame(db: Session, weeks: list[date] | None = None, labelled_only: bool = False) -> pd.DataFrame:
    q = db.query(AssetWeek)
    if weeks is not None:
        q = q.filter(AssetWeek.week_start.in_(weeks))
    if labelled_only:
        q = q.filter(AssetWeek.label_h.isnot(None))
    recs = [dict(asset_id=r.asset_id, week_start=r.week_start, label=r.label_h, **r.x) for r in q.all()]
    df = pd.DataFrame(recs, columns=["asset_id", "week_start", "label"] + FEATURES)
    return df
