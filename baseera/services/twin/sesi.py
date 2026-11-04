"""Saudi Environmental Stress Index (SESI) — the twin's environmental ageing model.

For every calendar day and sector, five components in 0..1 are computed from the weather feed and the calendar:
  heat      Arrhenius acceleration of electronics/insulation: 2^((Tmax − 30)/10), scaled so 50 °C ≈ 1
  dust      dust-storm flag (cooling paths, bearings, optics)
  humidity  coastal humidity/salinity proxy (sector parameter; Riyadh ≈ 0.1)
  season    load cycles: Ramadan, Hajj, event seasons (elevators, facilities)
  rain      rain events (pumps, cable joints, pavements)
The category index is a weighted sum (catalog.SESI_W) and the ageing factor turns one calendar day into `ageing`
equivalent days consumed (1.0 = nominal). Equivalent age of an asset = Σ ageing over its life.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from ...core.catalog import CATEGORIES, SESI_W
from ...core.config import get_settings
from ...core.models import SesiDay, WeatherDay

HUMIDITY_BY_SECTOR = {"default": 0.10, "riyadh": 0.10, "jeddah": 0.75, "dammam": 0.70, "yanbu": 0.70, "makkah": 0.45}


def _in(win, d: date) -> bool:
    try:
        a, b = (date.fromisoformat(x) for x in win); return a <= d <= b
    except Exception:
        return False


def _season(d: date, s) -> float:
    if _in(s.hajj_freeze_window, d):
        return 1.0
    if _in(s.ramadan_window, d):
        return 0.7
    return 0.3 if d.month in (10, 11, 12, 1, 2) else 0.1


def components(tmax_c: float, dust: int, rain_mm: float, d: date, sector: str = "default") -> dict:
    s = get_settings()
    heat = min(1.0, max(0.0, (2 ** ((tmax_c - 30.0) / 10.0) - 1) / 3.0))
    return dict(heat=round(heat, 3), dust=float(bool(dust)), humidity=HUMIDITY_BY_SECTOR.get(sector, 0.1), season=_season(d, s), rain=min(1.0, rain_mm / 15.0))


def index_for(category: str, c: dict) -> float:
    w = SESI_W[category]
    return round(w[0] * c["heat"] + w[1] * c["dust"] + w[2] * c["humidity"] + w[3] * c["season"] + w[4] * c["rain"], 4)


def ageing_for(category: str, idx: float) -> float:
    return round(0.85 + 1.35 * idx, 4)


def compute(db: Session, days: list[date] | None = None, sector: str = "default") -> int:
    q = db.query(WeatherDay).filter(WeatherDay.sector == sector)
    if days:
        q = q.filter(WeatherDay.day.in_(days))
    existing = {r.day: r for r in db.query(SesiDay).filter_by(sector=sector).all()}
    n = 0
    for w in q.all():
        c = components(w.tmax_c, w.dust, w.rain_mm, w.day, sector)
        idx = {cat: index_for(cat, c) for cat in CATEGORIES}
        row = existing.get(w.day) or SesiDay(day=w.day, sector=sector)
        row.heat, row.dust, row.humidity, row.season, row.rain = c["heat"], c["dust"], c["humidity"], c["season"], c["rain"]
        row.sesi = idx; row.ageing = {cat: ageing_for(cat, v) for cat, v in idx.items()}
        db.add(row); n += 1
    db.commit()
    return n


def frame(db: Session, sector: str = "default") -> pd.DataFrame:
    rows = db.query(SesiDay).filter_by(sector=sector).order_by(SesiDay.day).all()
    return pd.DataFrame([dict(day=r.day, heat=r.heat, dust=r.dust, humidity=r.humidity, season=r.season, rain=r.rain,
                              **{f"sesi_{k}": v for k, v in r.sesi.items()}, **{f"age_{k}": v for k, v in r.ageing.items()}) for r in rows])


def asset_summary(db: Session, category: str, install: date | None, as_of: date, sector: str = "default") -> dict:
    F = frame(db, sector)
    if F.empty:
        return dict(components={}, index=None, calendar_age_y=None, equivalent_age_y=None, ageing_factor=None, series=[])
    last = F[F.day <= as_of].tail(30)
    comp = {k: round(float(last[k].mean()), 2) for k in ("heat", "dust", "humidity", "season", "rain")} if len(last) else {}
    idx = round(float(last[f"sesi_{category}"].mean()), 3) if len(last) else None
    cal = ((as_of - install).days / 365.25) if install else None
    life = F[(F.day > (install or F.day.min())) & (F.day <= as_of)]
    factor = float(life[f"age_{category}"].mean()) if len(life) else 1.0
    eq = cal * factor if cal is not None else None
    series = F[F.day <= as_of].tail(120)
    return dict(components=comp, index=idx, calendar_age_y=(round(cal, 2) if cal is not None else None), equivalent_age_y=(round(eq, 2) if eq is not None else None),
                ageing_factor=round(factor, 2), series=[dict(day=str(d), v=float(v)) for d, v in zip(series.day, series[f"sesi_{category}"])])
