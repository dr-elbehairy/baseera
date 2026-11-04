"""Simulated condition-monitoring streams (layer 1 of the vision): for every non-lighting asset a daily aggregate per
channel with a baseline, noise, weather coupling and a drift that starts inside the P–F window of the mode it reveals.
Lighting gets a smart-meter driver-current channel. Emits the raw `telemetry` table the pipeline ingests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.catalog import CHANNELS, EVIDENCE, category_of

BASE = {"vibration_mms": (4.5, 0.25, 14.0), "motor_temp_c": (58.0, 1.2, 92.0), "flow_ratio": (96.0, 1.0, 62.0), "insulation_mohm": (250.0, 6.0, 40.0),
        "drive_current_a": (15.5, 0.3, 22.0), "door_cycle_s": (4.2, 0.1, 7.5), "trips_per_day": (0.2, 0.3, 4.0), "leveling_mm": (3.0, 0.4, 14.0),
        "crack_mm": (2.0, 0.2, 28.0), "settlement_mm": (1.0, 0.2, 25.0), "driver_current_a": (0.42, 0.01, 0.30), "lamp_hours": (0, 0, 0)}
# which channels reveal which mode (inverse of EVIDENCE restricted to channels)
MODE_CH = {}
for ch, modes in EVIDENCE.items():
    if ch in CHANNELS:
        for m in modes: MODE_CH.setdefault(m, []).append(ch)


def generate(assets: pd.DataFrame, truth: pd.DataFrame, dates: pd.DatetimeIndex, weather: pd.DataFrame, rng: np.random.Generator,
             sample_every: dict | None = None) -> pd.DataFrame:
    """assets: asset_code, asset_type; truth: asset_code, failed_on, failure_mode. Returns daily telemetry rows."""
    sample_every = sample_every or {"pavement": 10}      # vehicle cameras pass every ~10 days; sensors daily
    D = len(dates); tmax = weather.tmax_c.values; rain = weather.rain_mm.values
    out = []
    fails_by = {c: g for c, g in truth.groupby("asset_code")} if len(truth) else {}
    for a in assets.itertuples(index=False):
        cat = category_of(a.asset_type)
        chans = [c for c, v in CHANNELS.items() if v[0] == cat and c != "lamp_hours"]
        if cat == "lighting" and a.asset_type == "CAB":
            continue
        if cat == "lighting" and rng.uniform() > 0.35:   # only ~35% of poles are on a smart meter
            continue
        step = sample_every.get(cat, 1)
        f = fails_by.get(a.asset_code)
        fail_days = [((pd.Timestamp(r.failed_on) - dates[0]).days, r.failure_mode) for r in f.itertuples()] if f is not None else []
        for ch in chans:
            b, sd, fail_level = BASE[ch]; direction = CHANNELS[ch][3]
            base = b * rng.uniform(0.9, 1.1); level = np.full(D, base) + rng.normal(0, sd, D)
            if ch in ("motor_temp_c", "drive_current_a"): level += 0.25 * (tmax - 35)
            if ch == "flow_ratio": level -= 3.0 * (rain > 3)
            # drift towards the failure level over the P–F window before each failure this channel reveals
            for fd, mode in fail_days:
                if ch not in MODE_CH.get(mode, []): continue
                pf = int(rng.integers(12, 40)); start = max(0, fd - pf)
                t = np.arange(start, min(fd, D)); frac = ((t - start) / max(pf, 1)) ** 1.6
                level[start:min(fd, D)] = base + (fail_level - base) * frac + rng.normal(0, sd * 1.5, len(t))
                level[min(fd, D):min(fd + 3, D)] = base    # repaired → back to baseline
            days = range(0, D, step)
            out += [dict(asset_code=a.asset_code, day=dates[d].date(), channel=ch, value=round(float(level[d]), 3), n_samples=(1440 if step == 1 else 1),
                         source=CHANNELS[ch][4]) for d in days]
    return pd.DataFrame(out)


def dependencies(assets: pd.DataFrame) -> pd.DataFrame:
    """Infer graph edges from the register: cabinet feeds its poles; a pump-station panel feeds the pumps/valves nearest to it."""
    rows = []
    poles = assets[assets.asset_type.isin(["LED", "HAL", "SOL"]) & assets.cabinet_code.astype(str).ne("")]
    for r in poles.itertuples(index=False):
        rows.append(dict(parent_code=r.cabinet_code, child_code=r.asset_code, kind="feeds", weight=1.0))
    panels = assets[assets.asset_type == "PNL"]; pumps = assets[assets.asset_type.isin(["PMP", "VLV"])]
    if len(panels) and len(pumps):
        P = panels[["lon", "lat"]].values; Q = pumps[["lon", "lat"]].values
        near = np.argmin(((Q[:, None, :] - P[None, :, :]) ** 2).sum(-1), axis=1)
        for i, r in enumerate(pumps.itertuples(index=False)):
            rows.append(dict(parent_code=panels.iloc[near[i]].asset_code, child_code=r.asset_code, kind="feeds", weight=1.0))
    return pd.DataFrame(rows, columns=["parent_code", "child_code", "kind", "weight"])
