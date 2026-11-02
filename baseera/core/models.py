"""Operational, feature and ledger schema (one database, three logical schemas by table prefix).

ops_*      facts from the field and from source systems — append-mostly, audited
feat_*     weekly as-of snapshots; never updated after being written
ledger_*   derived measurements (PFR@L, emergency share, dark days); computed, never edited
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.utcnow()


# ----------------------------------------------------------------------------- ops
class Cabinet(Base):
    __tablename__ = "ops_cabinet"
    cabinet_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    cabinet_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    lon: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    install_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), default="municipal")


class Asset(Base):
    __tablename__ = "ops_asset"
    asset_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    asset_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(16))          # LED | HAL | SOL | CAB
    kind: Mapped[str] = mapped_column(String(16), default="pole")  # pole | cabinet (| pump | lift later)
    street_class: Mapped[str] = mapped_column(String(16), default="sec")  # main | sec
    criticality: Mapped[str] = mapped_column(String(16), default="none")  # none|mosque|school|crossing|hospital
    lon: Mapped[float] = mapped_column(Float, index=True)
    lat: Mapped[float] = mapped_column(Float, index=True)
    install_date: Mapped[date | None] = mapped_column(Date)
    cabinet_id: Mapped[str | None] = mapped_column(ForeignKey("ops_cabinet.cabinet_id"))
    owner_entity: Mapped[str] = mapped_column(String(64), default="municipality")
    source: Mapped[str] = mapped_column(String(32), default="municipal")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    cabinet = relationship("Cabinet")


class Report(Base):
    """Citizen or patrol report (Balady / 940). Reporter identity is hashed at ingestion — never stored."""
    __tablename__ = "ops_report"
    report_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    report_type: Mapped[str] = mapped_column(String(32))        # dark | flicker | damage | other
    channel: Mapped[str] = mapped_column(String(32), default="citizen")  # citizen | patrol
    lon: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    match_method: Mapped[str | None] = mapped_column(String(16))  # code | spatial | none
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reporter_hash: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="municipal")


class WorkOrder(Base):
    __tablename__ = "ops_work_order"
    wo_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))               # emergency | planned
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    fault_code: Mapped[str | None] = mapped_column(String(32))  # contractor's fault classification (maps to failure mode)
    cost_sar: Mapped[float | None] = mapped_column(Float)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("ops_report.report_id"))
    source: Mapped[str] = mapped_column(String(32), default="municipal")


class Observation(Base):
    """A degradation symptom recorded on a specific asset (technician QR form, patrol, or citizen 'flicker')."""
    __tablename__ = "ops_observation"
    obs_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    symptom_code: Mapped[str] = mapped_column(String(32))  # flicker|cycling|dim|partial_trip|intermittent|noise|heat|rust|tilt|other
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1..3
    source: Mapped[str] = mapped_column(String(32), default="technician_qr")  # technician_qr|patrol|citizen|simulated
    observer_id: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    photo_ref: Mapped[str | None] = mapped_column(String(128))
    client_ref: Mapped[str | None] = mapped_column(String(64), unique=True)  # idempotency key for offline sync


class WeatherDay(Base):
    __tablename__ = "ops_weather_day"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    sector: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    tmax_c: Mapped[float] = mapped_column(Float)
    rain_mm: Mapped[float] = mapped_column(Float, default=0.0)
    dust: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="ncm")


class Quarantine(Base):
    __tablename__ = "ops_quarantine"
    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(32), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(String(64))


class IngestRun(Base):
    __tablename__ = "ops_ingest_run"
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    pipeline: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    n_in: Mapped[int] = mapped_column(Integer, default=0)
    n_ok: Mapped[int] = mapped_column(Integer, default=0)
    n_quarantined: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict | None] = mapped_column(JSON)


# ----------------------------------------------------------------------------- model & decision
class ModelVersion(Base):
    __tablename__ = "ops_model_version"
    model_version_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    trained_from: Mapped[date] = mapped_column(Date)
    trained_to: Mapped[date] = mapped_column(Date)
    features: Mapped[list] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    gates: Mapped[dict] = mapped_column(JSON)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    artifact_path: Mapped[str] = mapped_column(String(256))
    approved_by: Mapped[str | None] = mapped_column(String(64))


class Prediction(Base):
    __tablename__ = "ops_prediction"
    __table_args__ = (UniqueConstraint("asset_id", "week_start", "model_version_id", name="uq_pred"),
                      Index("ix_pred_week", "week_start"))
    pred_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("ops_model_version.model_version_id"))
    p_fail: Mapped[float] = mapped_column(Float)
    risk_sar: Mapped[float] = mapped_column(Float)
    priority: Mapped[float] = mapped_column(Float)
    explanation: Mapped[dict | None] = mapped_column(JSON)
    run_tag: Mapped[str] = mapped_column(String(16), default="live")  # live | backtest


class WeeklyList(Base):
    __tablename__ = "ops_weekly_list"
    __table_args__ = (UniqueConstraint("week_start", "run_tag", name="uq_list_week"),)
    list_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("ops_model_version.model_version_id"))
    capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | approved | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    run_tag: Mapped[str] = mapped_column(String(16), default="live")
    items = relationship("ListItem", back_populates="weekly_list", cascade="all, delete-orphan")


class ListItem(Base):
    __tablename__ = "ops_list_item"
    item_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(ForeignKey("ops_weekly_list.list_id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))     # inspect | service | replace
    p_fail: Mapped[float] = mapped_column(Float)
    risk_sar: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)           # one-line explanation shown to the supervisor
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed|approved|overridden|done|skipped
    override_reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    weekly_list = relationship("WeeklyList", back_populates="items")


class Outcome(Base):
    __tablename__ = "ops_outcome"
    outcome_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(ForeignKey("ops_list_item.item_id"), unique=True)
    visited_at: Mapped[datetime] = mapped_column(DateTime)
    finding: Mapped[str] = mapped_column(String(32))     # confirmed_degradation|no_issue|already_failed|inaccessible
    action_taken: Mapped[str] = mapped_column(String(32))
    cost_sar: Mapped[float | None] = mapped_column(Float)
    technician_id: Mapped[str | None] = mapped_column(String(32))
    client_ref: Mapped[str | None] = mapped_column(String(64), unique=True)


# ----------------------------------------------------------------------------- features
class AssetWeek(Base):
    """One row per asset per week start, computed strictly from data known before week_start."""
    __tablename__ = "feat_asset_week"
    __table_args__ = (UniqueConstraint("asset_id", "week_start", name="uq_feat"), Index("ix_feat_week", "week_start"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    x: Mapped[dict] = mapped_column(JSON)               # feature vector (name → value), see services/features/catalog.md
    label_h: Mapped[int | None] = mapped_column(Integer)  # 1 if a failure occurred within H days after week_start; NULL if unknown yet
    built_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ----------------------------------------------------------------------------- ledger
class FailureEvent(Base):
    """A confirmed failure, derived from an emergency work order (or a dark report without one)."""
    __tablename__ = "ledger_failure_event"
    __table_args__ = (UniqueConstraint("wo_id", "run_tag", name="uq_fail_wo_tag"),)
    fail_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ops_asset.asset_id"), index=True)
    failed_on: Mapped[date] = mapped_column(Date, index=True)   # first signal date (report or WO open)
    failure_mode: Mapped[str | None] = mapped_column(String(32))
    wo_id: Mapped[str | None] = mapped_column(ForeignKey("ops_work_order.wo_id"))
    report_id: Mapped[str | None] = mapped_column(ForeignKey("ops_report.report_id"))
    days_dark: Mapped[int | None] = mapped_column(Integer)
    lead_days: Mapped[int | None] = mapped_column(Integer)      # days between the earliest qualifying list and the failure; NULL = no warning
    had_warning_at_L: Mapped[bool | None] = mapped_column(Boolean)
    run_tag: Mapped[str] = mapped_column(String(16), default="live")


class LedgerMonth(Base):
    __tablename__ = "ledger_month"
    __table_args__ = (UniqueConstraint("month", "run_tag", "zone", name="uq_ledger"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String(7), index=True)   # YYYY-MM
    zone: Mapped[str] = mapped_column(String(32), default="all")  # all | treatment | control
    n_failures: Mapped[int] = mapped_column(Integer)
    pfr: Mapped[dict] = mapped_column(JSON)                      # {"2": .., "7": .., "14": .., "own": ..}
    pfr_age_rule: Mapped[dict | None] = mapped_column(JSON)
    emergency_share: Mapped[float | None] = mapped_column(Float)
    dark_days: Mapped[int | None] = mapped_column(Integer)
    symptom_capture_rate: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    run_tag: Mapped[str] = mapped_column(String(16), default="live")


# ----------------------------------------------------------------------------- identity & audit
class User(Base):
    __tablename__ = "sec_user"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))  # supervisor | technician | manager | admin
    display_name: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "sec_audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)


# ----------------------------------------------------------------------------- platform (settings overrides, background jobs)
class Setting(Base):
    """Field-calibrated parameter overrides. The .env value is the default; a row here wins. Every change is audited."""
    __tablename__ = "sys_setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)           # {"v": <value>}
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    updated_by: Mapped[str | None] = mapped_column(String(64))


class Job(Base):
    """A background operation (recompute, training, backtest, simulation seed) with live progress for the UI."""
    __tablename__ = "sys_job"
    job_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued | running | done | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    step: Mapped[str | None] = mapped_column(String(256))
    log: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
