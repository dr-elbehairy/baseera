"""The five ingestion pipelines. Each declares its row schema (what a valid source row looks like) and how it lands."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd
from pydantic import BaseModel, field_validator

from ....core.catalog import ASSET_TYPES, MODE_CODES, SYMPTOM_CODES, category_of, kind_of
from ....core.models import Asset, Cabinet, Observation, Report, WeatherDay, WorkOrder
from ..base import Pipeline, RowError, normalise_code, opt_dt, reporter_hash, to_dt
from ..match import AssetMatcher

STREET = {"main", "sec"}
CRIT = {"none", "mosque", "school", "crossing", "hospital"}
SYMPTOMS = SYMPTOM_CODES
REPORT_TYPES = {"dark", "flicker", "damage", "other"}


def _date(v) -> Optional[date]:
    if v is None or str(v).strip() == "":
        return None
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"bad date {v!r}")
    return ts.date()


# ----------------------------------------------------------------------------- cabinets
class CabinetRow(BaseModel):
    cabinet_code: str
    lon: float
    lat: float
    install_date: Optional[str] = None

    @field_validator("cabinet_code")
    @classmethod
    def _c(cls, v):
        v = normalise_code(v)
        if not v:
            raise ValueError("empty cabinet_code")
        return v


class CabinetPipeline(Pipeline):
    name = "cabinets"
    schema = CabinetRow

    def handle(self, row: CabinetRow, raw: dict) -> None:
        c = self.db.query(Cabinet).filter_by(cabinet_code=row.cabinet_code).first() or Cabinet(cabinet_code=row.cabinet_code)
        c.lon, c.lat, c.install_date, c.source = row.lon, row.lat, _date(row.install_date), self.source
        self.db.add(c)


# ----------------------------------------------------------------------------- assets
class AssetRow(BaseModel):
    asset_code: str
    asset_type: str
    kind: Optional[str] = None
    street_class: str = "sec"
    criticality: str = "none"
    lon: float
    lat: float
    install_date: Optional[str] = None
    cabinet_code: Optional[str] = None
    owner_entity: str = "municipality"

    @field_validator("asset_code")
    @classmethod
    def _code(cls, v):
        v = normalise_code(v)
        if not v:
            raise ValueError("empty asset_code")
        return v

    @field_validator("asset_type")
    @classmethod
    def _type(cls, v):
        v = str(v).strip().upper()
        if v not in ASSET_TYPES:
            raise ValueError(f"asset_type must be one of {sorted(ASSET_TYPES)}")
        return v

    @field_validator("street_class")
    @classmethod
    def _st(cls, v):
        v = str(v).strip().lower()
        if v not in STREET:
            raise ValueError("street_class must be main|sec")
        return v

    @field_validator("criticality")
    @classmethod
    def _cr(cls, v):
        v = (str(v).strip().lower() or "none")
        if v not in CRIT:
            raise ValueError(f"criticality must be one of {sorted(CRIT)}")
        return v

    @field_validator("lat")
    @classmethod
    def _lat(cls, v):
        if not (16.0 <= v <= 32.5):
            raise ValueError("lat outside Saudi Arabia")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v):
        if not (34.0 <= v <= 56.0):
            raise ValueError("lon outside Saudi Arabia")
        return v


class AssetPipeline(Pipeline):
    name = "assets"
    schema = AssetRow

    def handle(self, row: AssetRow, raw: dict) -> None:
        inst = _date(row.install_date)
        if inst and inst > date.today():
            raise RowError("install_date in the future")
        cab = None
        if row.cabinet_code:
            cab = self.db.query(Cabinet).filter_by(cabinet_code=normalise_code(row.cabinet_code)).first()
            if cab is None:
                raise RowError(f"unknown cabinet_code {row.cabinet_code!r} (load cabinets first)")
        a = self.db.query(Asset).filter_by(asset_code=row.asset_code).first() or Asset(asset_code=row.asset_code)
        a.asset_type, a.kind, a.street_class, a.criticality = row.asset_type, (row.kind or kind_of(row.asset_type)), row.street_class, row.criticality
        a.category = category_of(row.asset_type)
        a.lon, a.lat, a.install_date, a.owner_entity, a.source = row.lon, row.lat, inst, row.owner_entity, self.source
        a.cabinet_id = cab.cabinet_id if cab else None
        self.db.add(a)


# ----------------------------------------------------------------------------- reports
class ReportRow(BaseModel):
    external_ref: Optional[str] = None
    reported_at: str
    report_type: str = "dark"
    channel: str = "citizen"
    asset_code: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    closed_at: Optional[str] = None
    reporter: Optional[str] = None

    @field_validator("report_type")
    @classmethod
    def _rt(cls, v):
        v = str(v).strip().lower()
        if v not in REPORT_TYPES:
            raise ValueError(f"report_type must be one of {sorted(REPORT_TYPES)}")
        return v


class ReportPipeline(Pipeline):
    name = "reports"
    schema = ReportRow

    def __init__(self, db, source="municipal"):
        super().__init__(db, source)
        self.m = AssetMatcher(db)

    def handle(self, row: ReportRow, raw: dict) -> None:
        if row.external_ref and self.db.query(Report).filter_by(external_ref=row.external_ref).first():
            return  # idempotent re-run
        asset, method = self.m.resolve(row.asset_code, row.lon, row.lat)
        at = to_dt(row.reported_at)
        if at > datetime.utcnow() + pd.Timedelta(days=1):
            raise RowError("reported_at in the future")
        closed = opt_dt(row.closed_at)
        if closed and closed < at:
            raise RowError("closed_at before reported_at")
        self.db.add(Report(external_ref=row.external_ref or None, reported_at=at, report_type=row.report_type, channel=row.channel,
                           lon=row.lon, lat=row.lat, asset_id=asset.asset_id, match_method=method, closed_at=closed,
                           reporter_hash=reporter_hash(row.reporter), source=self.source))
        if row.report_type == "flicker":  # a citizen flicker report is itself a symptom observation
            self.db.add(Observation(asset_id=asset.asset_id, observed_at=at, symptom_code="flicker", severity=1, source="citizen"))


# ----------------------------------------------------------------------------- work orders
class WorkOrderRow(BaseModel):
    external_ref: Optional[str] = None
    asset_code: str
    kind: str
    opened_at: str
    closed_at: Optional[str] = None
    fault_code: Optional[str] = None
    cost_sar: Optional[float] = None
    report_ref: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def _k(cls, v):
        v = str(v).strip().lower()
        if v not in {"emergency", "planned"}:
            raise ValueError("kind must be emergency|planned")
        return v

    @field_validator("fault_code")
    @classmethod
    def _fc(cls, v):
        v = (str(v).strip().lower() if v is not None else "")
        if v and v not in MODE_CODES:
            raise ValueError(f"fault_code must be one of {sorted(MODE_CODES)} (or empty)")
        return v or None

    @field_validator("cost_sar")
    @classmethod
    def _cost(cls, v):
        if v is not None and v < 0:
            raise ValueError("cost_sar < 0")
        return v


class WorkOrderPipeline(Pipeline):
    name = "work_orders"
    schema = WorkOrderRow

    def __init__(self, db, source="municipal"):
        super().__init__(db, source)
        self.m = AssetMatcher(db)

    def handle(self, row: WorkOrderRow, raw: dict) -> None:
        if row.external_ref and self.db.query(WorkOrder).filter_by(external_ref=row.external_ref).first():
            return
        asset, _ = self.m.resolve(row.asset_code, None, None)
        opened, closed = to_dt(row.opened_at), opt_dt(row.closed_at)
        if closed and closed < opened:
            raise RowError("closed_at before opened_at")
        rep = self.db.query(Report).filter_by(external_ref=row.report_ref).first() if row.report_ref else None
        self.db.add(WorkOrder(external_ref=row.external_ref or None, asset_id=asset.asset_id, kind=row.kind, opened_at=opened, closed_at=closed,
                              fault_code=(row.fault_code or None), cost_sar=row.cost_sar, report_id=rep.report_id if rep else None, source=self.source))


# ----------------------------------------------------------------------------- observations (bulk import; the PWA posts via API)
class ObservationRow(BaseModel):
    asset_code: str
    observed_at: str
    symptom_code: str
    severity: int = 1
    source: str = "technician_qr"
    observer_id: Optional[str] = None
    note: Optional[str] = None
    client_ref: Optional[str] = None

    @field_validator("symptom_code")
    @classmethod
    def _sc(cls, v):
        v = str(v).strip().lower()
        if v not in SYMPTOMS:
            raise ValueError(f"symptom_code must be one of {sorted(SYMPTOMS)}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v):
        if not 1 <= int(v) <= 3:
            raise ValueError("severity must be 1..3")
        return int(v)


class ObservationPipeline(Pipeline):
    name = "observations"
    schema = ObservationRow

    def __init__(self, db, source="municipal"):
        super().__init__(db, source)
        self.m = AssetMatcher(db)

    def handle(self, row: ObservationRow, raw: dict) -> None:
        if row.client_ref and self.db.query(Observation).filter_by(client_ref=row.client_ref).first():
            return
        asset, _ = self.m.resolve(row.asset_code, None, None)
        self.db.add(Observation(asset_id=asset.asset_id, observed_at=to_dt(row.observed_at), symptom_code=row.symptom_code, severity=row.severity,
                                source=row.source, observer_id=row.observer_id or None, note=row.note or None, client_ref=row.client_ref or None))


# ----------------------------------------------------------------------------- weather
class WeatherRow(BaseModel):
    day: str
    tmax_c: float
    rain_mm: float = 0.0
    dust: int = 0
    sector: str = "default"

    @field_validator("tmax_c")
    @classmethod
    def _t(cls, v):
        if not -5 <= v <= 55:
            raise ValueError("tmax_c outside physical range")
        return v

    @field_validator("rain_mm")
    @classmethod
    def _r(cls, v):
        if v < 0:
            raise ValueError("rain_mm < 0")
        return v


class WeatherPipeline(Pipeline):
    name = "weather"
    schema = WeatherRow

    def handle(self, row: WeatherRow, raw: dict) -> None:
        d = _date(row.day)
        w = self.db.query(WeatherDay).filter_by(day=d, sector=row.sector).first() or WeatherDay(day=d, sector=row.sector)
        w.tmax_c, w.rain_mm, w.dust, w.source = row.tmax_c, row.rain_mm, int(row.dust), self.source
        self.db.add(w)


PIPELINES = {"cabinets": CabinetPipeline, "assets": AssetPipeline, "reports": ReportPipeline, "work_orders": WorkOrderPipeline,
             "observations": ObservationPipeline, "weather": WeatherPipeline}
ORDER = ["cabinets", "assets", "weather", "reports", "work_orders", "observations"]
