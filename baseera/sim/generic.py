"""Simplified simulation for the non-pilot categories (pumping stations, elevators, pavements).

Deliberately simpler than the lighting physics: each asset has a Weibull life per failure mode, a P–F window during
which category-specific symptoms are emitted most days, and a weather modifier (rain for pumps and pavements, heat for
elevator drives). Emits the same raw tables as the municipality would export. Tagged `simulated` downstream like
everything else; replaced by municipal exports through the same pipelines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.catalog import MODES, TYPES
from ..core.geo import xy_to_lonlat

# category → list of (type, share, modes[(mode, mean_life_y, pf_days_range, symptoms)])
SPEC = {
    "pumping": ("PS", [("PMP", 0.6, [("bearing_wear", 6.0, (14, 45), ["vibration", "noise"]), ("seal_leak", 5.0, (7, 30), ["leak"]), ("motor_winding", 10.0, (10, 40), ["overheating", "tripping"]), ("intake_blockage", 2.5, (3, 12), ["low_flow", "blockage"])]),
                      ("PNL", 0.2, [("panel_fault", 9.0, (10, 40), ["tripping", "heat"])]),
                      ("VLV", 0.2, [("seal_leak", 8.0, (7, 30), ["leak", "rust"])])]),
    "elevators": ("EL", [("ELV", 0.6, [("door_mechanism", 4.0, (7, 30), ["door_slow", "noise"]), ("drive_motor", 9.0, (14, 45), ["jerk", "heat"]), ("controller", 8.0, (10, 30), ["trip", "alarm"]), ("rope_wear", 12.0, (21, 60), ["jerk", "leveling"]), ("sensor", 3.0, (3, 14), ["trip", "leveling"])]),
                       ("ESC", 0.25, [("drive_motor", 8.0, (14, 45), ["jerk", "noise"]), ("sensor", 3.0, (3, 14), ["trip"])]),
                       ("LFT", 0.15, [("door_mechanism", 4.0, (7, 30), ["door_slow"]), ("controller", 7.0, (10, 30), ["alarm"])])]),
    "pavement": ("PV", [("PAV", 0.75, [("subsidence", 30.0, (30, 120), ["settlement", "crack"]), ("tile_failure", 16.0, (14, 60), ["tile_loose", "crack"]), ("drainage", 20.0, (14, 45), ["pooling"]), ("impact", 25.0, (0, 2), ["edge_damage"])]),
                      ("RMP", 0.15, [("tile_failure", 18.0, (14, 60), ["tile_loose", "edge_damage"]), ("drainage", 20.0, (14, 45), ["pooling"])]),
                      ("CRS", 0.10, [("tile_failure", 14.0, (14, 60), ["tile_loose", "crack"]), ("impact", 20.0, (0, 2), ["edge_damage"])])]),
}
CRIT_CHOICES = {"pumping": (["none", "hospital", "crossing"], [0.6, 0.15, 0.25]), "elevators": (["crossing", "hospital", "none"], [0.6, 0.2, 0.2]),
                "pavement": (["none", "school", "mosque", "crossing"], [0.55, 0.15, 0.15, 0.15])}


def generate_category(category: str, n: int, dates: pd.DatetimeIndex, weather: pd.DataFrame, rng: np.random.Generator,
                      vis: float, code_share: float, emergency_multiplier: float, ref_offset: int) -> dict[str, pd.DataFrame]:
    prefix, types = SPEC[category]
    D = len(dates); rain = weather.rain_mm.values; tmax = weather.tmax_c.values
    tnames = [t for t, _, _ in types]; shares = np.array([s for _, s, _ in types]); shares /= shares.sum()
    ttype = rng.choice(tnames, n, p=shares)
    modes_of = {t: m for t, _, m in types}
    px = rng.uniform(50, 2350, n); py = rng.uniform(50, 1750, n)
    install = rng.uniform(2008, 2024, n)
    crit_c, crit_p = CRIT_CHOICES[category]
    crit = rng.choice(crit_c, n, p=crit_p)
    road = rng.choice(["main", "sec"], n, p=[0.5, 0.5])
    code = lambda i: f"{prefix}-{ref_offset + i + 1:05d}"
    assets = pd.DataFrame([dict(asset_code=code(i), asset_type=ttype[i], kind=TYPES[ttype[i]][2], street_class=road[i], criticality=crit[i],
                                lon=xy_to_lonlat(px[i], py[i])[0], lat=xy_to_lonlat(px[i], py[i])[1],
                                install_date=str(pd.Timestamp(year=int(install[i]), month=1, day=1) + pd.Timedelta(days=int((install[i] % 1) * 365)))[:10],
                                cabinet_code="", owner_entity="municipality") for i in range(n)])
    # per asset, per mode: remaining life in days (Weibull), re-drawn after each failure
    events, precursor = [], []
    state = {}
    for i in range(n):
        for mode, life_y, pf, syms in modes_of[ttype[i]]:
            age_d = (2024.8 - install[i]) * 365.25
            rem = life_y * 365.25 * rng.weibull(2.0) - age_d * rng.uniform(0.1, 0.5)
            state[(i, mode)] = [max(rem, rng.uniform(30, 700)), int(rng.integers(pf[0], pf[1] + 1)) if pf[1] > 0 else 0, syms]
    out_until = np.full(n, -1)
    for d in range(D):
        wet = 1.0 + (2.5 if rain[d] > 3 else 0.0) if category in ("pumping", "pavement") else 1.0
        hot = 1.0 + max(0.0, (tmax[d] - 38) / 10) if category == "elevators" else 1.0
        for (i, mode), st in state.items():
            if out_until[i] >= d:
                continue
            step = (wet if mode in ("drainage", "intake_blockage", "seal_leak", "subsidence") else 1.0) * (hot if mode == "drive_motor" else 1.0)
            st[0] -= step * rng.lognormal(0, 0.2)
            if 0 < st[0] <= st[1] and rng.uniform() < 0.25:
                precursor.append((d, i, rng.choice(st[2])))
            if st[0] <= 0:
                events.append((d, i, mode)); out_until[i] = d + int(rng.integers(2, 8))
                life_y = next(l for m, l, *_ in modes_of[ttype[i]] if m == mode)
                st[0] = life_y * 365.25 * rng.weibull(2.0)
    EV = pd.DataFrame(events, columns=["d", "asset", "mode"]); PR = pd.DataFrame(precursor, columns=["d", "asset", "kind"])
    reports, wos, truth = [], [], []
    for k, r in enumerate(EV.itertuples(index=False)):
        a = int(r.asset); rep_d = min(D - 1, r.d + int(min(10, rng.gamma(1.5, 1.5)))); out_days = int(rng.integers(2, 9))
        rep_at = dates[rep_d] + pd.Timedelta(hours=int(rng.integers(6, 23)))
        with_code = rng.uniform() < code_share
        lon, lat = assets.lon.iloc[a], assets.lat.iloc[a]
        if not with_code:
            lon += rng.normal(0, 0.00005); lat += rng.normal(0, 0.00005)
        ext = f"R-{prefix}-{ref_offset + k + 1:06d}"
        reports.append(dict(external_ref=ext, reported_at=rep_at, report_type="damage" if category == "pavement" else "dark", channel="citizen",
                            asset_code=code(a) if with_code else "", lon=round(lon, 7), lat=round(lat, 7), closed_at=rep_at + pd.Timedelta(days=out_days),
                            reporter=f"9665{ref_offset + k:07d}"))
        cost = TYPES[ttype[a]][4] * emergency_multiplier
        wos.append(dict(external_ref=f"WO-{prefix}-{ref_offset + k + 1:06d}", asset_code=code(a), kind="emergency", opened_at=rep_at + pd.Timedelta(hours=2),
                        closed_at=rep_at + pd.Timedelta(days=out_days), fault_code=r.mode, cost_sar=int(cost * rng.uniform(0.85, 1.2)), report_ref=ext))
        truth.append(dict(asset_code=code(a), failed_on=dates[r.d].date(), reported_on=dates[rep_d].date(), failure_mode=r.mode, cls=MODES[r.mode][2]))
    seen = PR[rng.uniform(size=len(PR)) < vis] if len(PR) else PR
    src = rng.choice(["technician_qr", "patrol", "citizen"], len(seen), p=[0.55, 0.3, 0.15]) if len(seen) else []
    observations = pd.DataFrame(dict(asset_code=[code(int(a)) for a in seen.asset], observed_at=[dates[d] + pd.Timedelta(hours=10) for d in seen.d],
                                     symptom_code=list(seen.kind.values), severity=rng.integers(1, 4, len(seen)), source=src,
                                     observer_id=["tech-%02d" % rng.integers(1, 7) if s == "technician_qr" else "" for s in src]))
    return dict(assets=assets, reports=pd.DataFrame(reports), work_orders=pd.DataFrame(wos), observations=observations, truth=pd.DataFrame(truth),
                n_failures=len(EV), n_symptom_episodes=len(PR))
