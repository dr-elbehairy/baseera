"""Runtime configuration. Every tunable the field will calibrate lives here, never in code paths.

Values are read from the environment (or a .env file). See .env.example for the documented defaults.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .catalog import default_costs, default_leads


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BASEERA_", extra="ignore")

    # --- platform
    database_url: str = "sqlite:///./data/baseera.db"
    data_dir: str = "./data"
    model_dir: str = "./data/models"
    jwt_secret: str = "change-me-in-production"
    jwt_minutes: int = 15
    refresh_days: int = 7
    env: str = "dev"  # dev | staging | production
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:8000"])
    auto_demo: bool = False                   # on an empty database, seed the tagged simulation at startup (cloud demo)
    auto_demo_as_of: str = "2026-10-25"

    # --- domain parameters (calibrated from survey / mentor; see docs/adr/ADR-004)
    horizon_days: int = 14                    # model target: failure within H days
    lead_days: List[int] = Field(default_factory=lambda: [2, 7, 14])   # L values reported in the ledger
    lead_default: int = 7                     # L used when the failure mode is unknown
    lead_by_mode: dict = Field(default_factory=default_leads)   # per failure mode, all categories (core/catalog.py)
    crew_jobs_per_week: int = 30              # planned interventions the sector crew absorbs weekly
    alert_probability: float = 0.10           # an asset enters the list only above this calibrated probability
    emergency_multiplier: float = 2.0         # emergency repair cost / planned repair cost
    consequence_sar_per_unit: float = 400.0   # social/safety cost of one dark pole-equivalent (secondary street)
    intervention_efficacy: float = 0.85       # share of predictable failures averted when serviced in time
    match_radius_m: float = 25.0              # spatial matching radius for reports without an asset code
    cost_planned: dict = Field(default_factory=default_costs)   # per asset type, all categories (core/catalog.py)
    critical_min_action: str = "inspect"      # critical assets never drop below a scheduled inspection
    # --- v0.4 consequences (SAR), prognosis, optimiser, constraints
    cof_safety_sar: float = 300.0             # base safety consequence per critical-weighted unit
    cof_environment_sar: float = 150.0
    cof_reputation_sar: float = 80.0
    dependency_service_sar: float = 120.0     # service interruption per dependent asset-week
    conformal_coverage: float = 0.90          # target coverage of the failure window
    weekly_budget_sar: float = 60000.0        # planned-maintenance budget per week (Pareto sweeps around it)
    crews: int = 3                            # routes per week
    rideby_radius_m: float = 250.0            # a low-value job within this distance of a route is grouped at near-zero travel cost
    rideby_cost_share: float = 0.6            # share of planned cost that remains when grouped (travel/setup saved)
    heat_ban_months: List[int] = Field(default_factory=lambda: [6, 7, 8, 9])
    heat_ban_hours: str = "12:00–15:00"
    ramadan_window: List[str] = Field(default_factory=lambda: ["2027-02-07", "2027-03-08"])
    hajj_freeze_window: List[str] = Field(default_factory=lambda: ["2027-05-10", "2027-05-25"])
    flood_season_months: List[int] = Field(default_factory=lambda: [11, 12, 1, 2, 3, 4])
    flood_readiness_boost: float = 1.3        # pumping risk multiplier during flood season
    anthropic_api_key: str = ""               # optional: generative assistant; templated answers otherwise
    anthropic_model: str = "claude-sonnet-5-5"

    # --- model gates (a new version is promoted only if all pass)
    gate_min_auc: float = 0.80
    gate_min_pfr_gain_over_age: float = 0.10  # PFR@L(model) − PFR@L(age rule) on validation
    gate_max_single_group_share: float = 0.90   # permutation importance of one feature *group* (symptoms, weather …) over all groups

    # --- demo users (dev only; production uses SSO/OIDC)
    demo_password: str = "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
