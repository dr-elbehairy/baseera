"""Simulated municipal data source ("simulated" pipeline input).

Ports the PoC physics (02_النموذج_الأولي_بصيرة/_src/_build_prototype_data.py) but emits *raw source tables* — the same
shape a municipality would export — so the simulation flows through the same ingestion, feature, model, decision and
ledger code as real data. Nothing downstream knows it is simulated except the `source='simulated'` tag on every row.

Physics (reliability-centred): every predictable failure mode has a P–F interval; past point P the asset emits
symptoms most days until it fails at F. Whether a symptom is *captured* (becomes an observation row) depends on the
visibility scenario (vis_main / vis_sec), which is exactly what Baseera's QR + technician form changes in the field.

Tables written (CSV):
  assets, cabinets, weather, reports, work_orders, observations, truth (ground truth, tests only)
"""
from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.geo import xy_to_lonlat

PREDICTABLE = {"led_driver": "A", "lamp_eol": "A", "cabinet": "B", "cable_joint": "B", "solar_battery": "B", "collision": "C"}
COST_PLANNED = {"LED": 650, "HAL": 220, "SOL": 900, "CAB": 6500}
ROAD_W = {"main": 1.8, "sec": 1.0}
CRIT_W = {"none": 1.0, "mosque": 1.6, "school": 2.0, "crossing": 2.4, "hospital": 3.0}


@dataclass
class SimConfig:
    n_poles: int = 1200
    n_cabinets: int = 24
    days: int = 736                    # 2024-10-27 → 2026-11-01
    start: str = "2024-10-27"          # a Sunday
    seed: int = 2026
    vis_main: float = 0.70             # share of symptom episodes captured on main roads (Baseera "capture" scenario)
    vis_sec: float = 0.55
    code_share: float = 0.70           # share of reports that carry an asset code (the rest are matched spatially)
    emergency_multiplier: float = 2.0
    share_led: float = 0.65
    share_halogen: float = 0.30
    n_pumping: int = 40                # other categories (simplified simulation, sim/generic.py); 0 disables
    n_elevators: int = 30
    n_pavement: int = 200


def generate(cfg: SimConfig = SimConfig()) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)
    P = cfg
    DATES = pd.date_range(P.start, periods=P.days, freq="D")
    D = len(DATES)

    # ---------------------------------------------------------------- weather
    doy = DATES.dayofyear.values
    tmax = 32.5 + 11.5 * np.sin(2 * np.pi * (doy - 110) / 365.25)
    ar = np.zeros(D)
    for i in range(1, D):
        ar[i] = 0.75 * ar[i - 1] + rng.normal(0, 1.1)
    tmax = tmax + ar
    for yr in sorted(set(DATES.year)):
        s = np.where((DATES.year == yr) & (DATES.month >= 6) & (DATES.month <= 8))[0]
        if len(s) > 10:
            for _ in range(rng.integers(2, 4)):
                st = rng.choice(s[:-8]); L = rng.integers(3, 7); tmax[st:st + L] += rng.uniform(3, 5)
    rain = np.zeros(D)
    for i in range(D):
        if DATES[i].month in (11, 12, 1, 2, 3, 4) and rng.uniform() < 0.035:
            rain[i] = rng.gamma(1.6, 6.0)
    dust = ((DATES.month.isin([3, 4, 5, 6])) & (rng.uniform(size=D) < 0.08)).astype(int)
    weather = pd.DataFrame(dict(day=DATES.date, tmax_c=np.round(tmax, 1), rain_mm=np.round(rain, 1), dust=dust))

    # ---------------------------------------------------------------- geometry & assets
    roads = []
    for y in (450, 1350): roads.append(("main", [[0, y], [2400, y]]))
    for x in (700, 1700): roads.append(("main", [[x, 0], [x, 1800]]))
    for y in (150, 750, 1050, 1650): roads.append(("sec", [[0, y], [2400, y]]))
    for x in (250, 1200, 2150): roads.append(("sec", [[x, 0], [x, 1800]]))
    seg = []
    for kind, ((x0, y0), (x1, y1)) in roads:
        n = int(np.hypot(x1 - x0, y1 - y0) // 32); horiz = (y0 == y1)
        for side in (-12, 12):
            for k in range(n):
                f = (k + 0.5) / n; xx = x0 + f * (x1 - x0); yy = y0 + f * (y1 - y0)
                seg.append((xx + (0 if horiz else side), yy + (side if horiz else 0), kind))
    idx = rng.choice(len(seg), P.n_poles, replace=False)
    px = np.array([seg[i][0] for i in idx], float); py = np.array([seg[i][1] for i in idx], float)
    road = np.array([seg[i][2] for i in idx], dtype=object)
    N = P.n_poles
    ptype = rng.choice(["LED", "HAL", "SOL"], N, p=[P.share_led, P.share_halogen, 1 - P.share_led - P.share_halogen])
    install = np.where(ptype == "LED", rng.uniform(2017, 2024.5, N), np.where(ptype == "HAL", rng.uniform(2006, 2016, N), rng.uniform(2020, 2025, N)))
    exposure = rng.uniform(0.85, 1.20, N)
    cab_x = np.tile(np.linspace(150, 2250, 6), 4)[:P.n_cabinets] + rng.normal(0, 60, P.n_cabinets)
    cab_y = np.repeat([300, 750, 1150, 1600], 6)[:P.n_cabinets] + rng.normal(0, 60, P.n_cabinets)
    cab = np.argmin((px[:, None] - cab_x[None]) ** 2 + (py[:, None] - cab_y[None]) ** 2, axis=1)
    cab_install = rng.uniform(2005, 2020, P.n_cabinets)
    crit = np.full(N, "none", dtype=object)
    for name, cnt, rad in (("crossing", 14, 60), ("school", 7, 110), ("mosque", 9, 80), ("hospital", 2, 160)):
        cx = rng.uniform(100, 2300, cnt); cy = rng.uniform(100, 1700, cnt)
        for a, b in zip(cx, cy):
            m = (np.hypot(px - a, py - b) < rad) & (crit == "none"); crit[m] = name

    def code(i: int) -> str:
        return f"LP-{10000 + i}" if i < N else f"CB-{i - N + 1:02d}"

    def ymd(yr_float: float) -> str:
        y = int(yr_float); return str(pd.Timestamp(year=y, month=1, day=1) + pd.Timedelta(days=int((yr_float - y) * 365)))[:10]

    assets = pd.DataFrame([dict(asset_code=code(i), asset_type=ptype[i], kind="pole", street_class=road[i], criticality=crit[i],
                                lon=xy_to_lonlat(px[i], py[i])[0], lat=xy_to_lonlat(px[i], py[i])[1], install_date=ymd(install[i]),
                                cabinet_code=f"CB-{cab[i] + 1:02d}", owner_entity="municipality") for i in range(N)] +
                          [dict(asset_code=code(N + c), asset_type="CAB", kind="cabinet", street_class="main", criticality="none",
                                lon=xy_to_lonlat(cab_x[c], cab_y[c])[0], lat=xy_to_lonlat(cab_x[c], cab_y[c])[1], install_date=ymd(cab_install[c]),
                                cabinet_code=f"CB-{c + 1:02d}", owner_entity="municipality") for c in range(P.n_cabinets)])
    cabinets = pd.DataFrame([dict(cabinet_code=f"CB-{c + 1:02d}", lon=xy_to_lonlat(cab_x[c], cab_y[c])[0], lat=xy_to_lonlat(cab_x[c], cab_y[c])[1],
                                  install_date=ymd(cab_install[c])) for c in range(P.n_cabinets)])

    # ---------------------------------------------------------------- degradation & failures (ground truth)
    LED_LIFE_Y = 12.0
    led_life = LED_LIFE_Y * rng.weibull(2.2, N)
    health = np.clip(1 - (2025.0 - install) / led_life, 0.02, 1.0)
    led_rate_i = 1 / (led_life * 365.25) / 1.45
    pf_led = rng.uniform(10, 40, N)
    lamp_life = lambda n: rng.weibull(3.0, n) * 2.8 * 365.25
    hal_burn = rng.uniform(0, 1.0, N) * lamp_life(N)
    hal_life = np.maximum(lamp_life(N), hal_burn + rng.uniform(1, 400, N))
    pf_hal = rng.uniform(7, 30, N)
    cab_health = rng.uniform(0.02, 1.0, P.n_cabinets)
    cab_rate0 = 1 / (3.5 * 365.25) / 1.45
    pf_cab = rng.uniform(5, 21, P.n_cabinets)
    cbl_wet = np.zeros(N)
    events, precursor = [], []
    out_until = np.full(N, -1); cab_out_until = np.full(P.n_cabinets, -1)
    for d in range(D):
        T = tmax[d]; arr = 2.0 ** ((T - 30.0) / 10.0)
        led = (ptype == "LED") & (out_until < d)
        rate = led_rate_i * arr * exposure
        health[led] -= rate[led] * rng.lognormal(0, 0.25, led.sum())
        remaining = health / np.maximum(rate, 1e-9)
        for i in np.where(led & (remaining < pf_led) & (rng.uniform(size=N) < 0.30))[0]: precursor.append((d, int(i), "flicker"))
        for i in np.where(led & (health <= 0))[0]:
            events.append((d, int(i), "led_driver")); health[i] = 1.0; out_until[i] = d + 3
            led_life[i] = LED_LIFE_Y * rng.weibull(2.2); led_rate_i[i] = 1 / (led_life[i] * 365.25) / 1.45
        hal = (ptype == "HAL") & (out_until < d)
        hal_burn[hal] += 1
        for i in np.where(hal & (hal_life - hal_burn < pf_hal) & (rng.uniform(size=N) < 0.30))[0]: precursor.append((d, int(i), "cycling"))
        for i in np.where(hal & (hal_burn >= hal_life))[0]:
            events.append((d, int(i), "lamp_eol")); hal_burn[i] = 0; hal_life[i] = lamp_life(1)[0]; out_until[i] = d + 2
        sol = (ptype == "SOL") & (out_until < d)
        for i in np.where(sol & (rng.uniform(size=N) < 0.00025 * (1 + dust[d] * 3)))[0]:
            events.append((d, int(i), "solar_battery")); out_until[i] = d + 4
            for k in range(1, int(rng.integers(1, 4))): precursor.append((max(0, d - k), int(i), "dim"))
        for c in range(P.n_cabinets):
            if cab_out_until[c] >= d: continue
            r_c = cab_rate0 * arr * (1 + (2025 - cab_install[c]) / 25)
            cab_health[c] -= r_c * rng.lognormal(0, 0.3)
            if cab_health[c] / r_c < pf_cab[c] and rng.uniform() < 0.35:
                members = np.where(cab == c)[0]
                for i in rng.choice(members, min(3, len(members)), replace=False): precursor.append((d, int(i), "partial_trip"))
            if cab_health[c] <= 0:
                events.append((d, N + c, "cabinet")); cab_health[c] = 1.0; cab_out_until[c] = d + 2
        if rain[d] > 3: cbl_wet[(rng.uniform(size=N) < 0.04)] += rain[d] / 30.0
        cbl_wet *= 0.995
        ci = (cbl_wet > 0.6) & (out_until < d)
        for i in np.where(ci & (rng.uniform(size=N) < 0.15))[0]: precursor.append((d, int(i), "intermittent"))
        for i in np.where(ci & (rng.uniform(size=N) < 0.02 * cbl_wet))[0]:
            events.append((d, int(i), "cable_joint")); cbl_wet[i] = 0; out_until[i] = d + 3
        f5 = (out_until < d) & (rng.uniform(size=N) < np.where(road == "main", 0.000035, 0.000012))
        for i in np.where(f5)[0]:
            events.append((d, int(i), "collision")); out_until[i] = d + 5

    EV = pd.DataFrame(events, columns=["d", "asset", "mode"])
    PR = pd.DataFrame(precursor, columns=["d", "asset", "kind"])

    # ---------------------------------------------------------------- what the municipality actually exports
    def report_delay(a: int) -> int:
        if a >= N: return int(rng.integers(0, 2))
        base = 1.2 if road[a] == "main" else 3.5
        return int(min(14, rng.gamma(1.5, base / 1.5)))

    reports, wos, truth = [], [], []
    for k, r in enumerate(EV.itertuples(index=False)):
        a = int(r.asset); rep_d = min(D - 1, r.d + report_delay(a)); out_days = int(rng.integers(2, 6))
        rep_at = DATES[rep_d] + pd.Timedelta(hours=int(rng.integers(6, 23)))
        with_code = rng.uniform() < cfg.code_share
        lon, lat = (assets.lon.iloc[a], assets.lat.iloc[a])
        if not with_code:  # citizen pin: jittered by up to ~10 m
            lon += rng.normal(0, 0.00005); lat += rng.normal(0, 0.00005)
        ext = f"R-{k + 1:06d}"
        reports.append(dict(external_ref=ext, reported_at=rep_at, report_type="dark", channel="citizen" if a < N else "patrol",
                            asset_code=code(a) if with_code else "", lon=round(lon, 7), lat=round(lat, 7),
                            closed_at=rep_at + pd.Timedelta(days=out_days), reporter=f"966500{k:06d}"))
        cost = COST_PLANNED["CAB" if a >= N else ptype[a]] * cfg.emergency_multiplier
        wos.append(dict(external_ref=f"WO-{k + 1:06d}", asset_code=code(a), kind="emergency", opened_at=rep_at + pd.Timedelta(hours=2),
                        closed_at=rep_at + pd.Timedelta(days=out_days), fault_code=r.mode, cost_sar=int(cost * rng.uniform(0.85, 1.2)),
                        report_ref=ext))
        truth.append(dict(asset_code=code(a), failed_on=DATES[r.d].date(), reported_on=DATES[rep_d].date(), failure_mode=r.mode,
                          cls=PREDICTABLE[r.mode]))
    vis = np.where(PR.asset.map(lambda a: a < N and road[a] == "main").values, cfg.vis_main, cfg.vis_sec)
    seen = PR[np.random.default_rng(7).uniform(size=len(PR)) < vis]
    src = rng.choice(["technician_qr", "patrol", "citizen"], len(seen), p=[0.6, 0.25, 0.15])
    observations = pd.DataFrame(dict(asset_code=[code(int(a)) for a in seen.asset], observed_at=[DATES[d] + pd.Timedelta(hours=20) for d in seen.d],
                                     symptom_code=seen.kind.values, severity=rng.integers(1, 4, len(seen)), source=src,
                                     observer_id=["tech-%02d" % rng.integers(1, 7) if s == "technician_qr" else "" for s in src]))
    reports_df, wos_df, truth_df = pd.DataFrame(reports), pd.DataFrame(wos), pd.DataFrame(truth)
    n_fail_other = 0; n_ep_other = 0
    for cat, n_cat, vis in (("pumping", cfg.n_pumping, 0.65), ("elevators", cfg.n_elevators, 0.70), ("pavement", cfg.n_pavement, 0.45)):
        if n_cat <= 0:
            continue
        from .generic import generate_category
        g = generate_category(cat, n_cat, DATES, weather, np.random.default_rng(cfg.seed + hash(cat) % 1000), vis, cfg.code_share, cfg.emergency_multiplier, 0)
        assets = pd.concat([assets, g["assets"]], ignore_index=True); reports_df = pd.concat([reports_df, g["reports"]], ignore_index=True)
        wos_df = pd.concat([wos_df, g["work_orders"]], ignore_index=True); observations = pd.concat([observations, g["observations"]], ignore_index=True)
        truth_df = pd.concat([truth_df, g["truth"]], ignore_index=True); n_fail_other += g["n_failures"]; n_ep_other += g["n_symptom_episodes"]
    from .telemetry import dependencies, generate as gen_tele
    telemetry = gen_tele(assets, truth_df, DATES, weather, np.random.default_rng(cfg.seed + 77))
    deps = dependencies(assets)
    return dict(assets=assets, cabinets=cabinets, dependencies=deps, weather=weather, reports=reports_df, work_orders=wos_df,
                observations=observations, telemetry=telemetry, truth=truth_df,
                meta=pd.DataFrame([dict(n_poles=N, n_cabinets=P.n_cabinets, n_other=cfg.n_pumping + cfg.n_elevators + cfg.n_pavement, days=D, start=P.start,
                                        seed=P.seed, vis_main=cfg.vis_main, vis_sec=cfg.vis_sec, n_failures=len(EV) + n_fail_other,
                                        n_symptom_episodes=len(PR) + n_ep_other, n_observations=len(observations))]))


def write(tables: dict[str, pd.DataFrame], outdir: str) -> dict[str, str]:
    os.makedirs(outdir, exist_ok=True)
    paths = {}
    for name, df in tables.items():
        p = os.path.join(outdir, f"{name}.csv"); df.to_csv(p, index=False); paths[name] = p
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate simulated municipal source tables")
    ap.add_argument("--out", default="data/sim"); ap.add_argument("--poles", type=int, default=1200); ap.add_argument("--cabinets", type=int, default=24)
    ap.add_argument("--days", type=int, default=736); ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--vis-main", type=float, default=0.70); ap.add_argument("--vis-sec", type=float, default=0.55)
    a = ap.parse_args(argv)
    t = generate(SimConfig(n_poles=a.poles, n_cabinets=a.cabinets, days=a.days, seed=a.seed, vis_main=a.vis_main, vis_sec=a.vis_sec))
    paths = write(t, a.out)
    m = t["meta"].iloc[0].to_dict()
    print(f"simulated: {m['n_poles']} poles, {m['n_cabinets']} cabinets, {m['days']} days → {m['n_failures']} failures, "
          f"{m['n_observations']}/{m['n_symptom_episodes']} symptom episodes captured; written to {a.out}")
    return paths


if __name__ == "__main__":
    main()
