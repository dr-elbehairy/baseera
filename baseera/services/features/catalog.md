# Feature catalog — `feat_asset_week.x`

Every feature is computed **as of the week start W** from rows dated strictly before W (except the forecast, which is a
forecast available at W). Sources: `ops_asset`, `ops_cabinet`, `ledger_failure_event`, `ops_observation`, `ops_weather_day`.

| feature | definition | source | why it matters |
|---|---|---|---|
| age_y | (W − install_date) / 365.25 | asset | wear-out modes (LED driver, lamp EOL) |
| category_code | asset | lighting 0 · pumping 1 · elevators 2 · pavement 3 (core/catalog.py) | asset register |
| type_code | LED=0 HAL=1 SOL=2 CAB=3 | asset | different failure physics per type |
| main_road | 1 if street_class = main | asset | exposure, vandalism, reporting speed |
| is_cabinet (1 for network nodes: cabinets and pump-station panels) | 1 if kind = cabinet | asset | network asset; failure darkens all members |
| crit_w | consequence weight of the site (crossing 2.4, hospital 3.0 …) | asset | used in the decision engine too |
| cabinet_age_y | age of the feeding cabinet | cabinet | upstream stress |
| days_since_last_fail | days since the last failure reported before W (999 = none) | failure_event | repeat failures cluster |
| fails_365d | failures reported in the 365 days before W | failure_event | chronic assets |
| cabinet_fails_365d | failures on all assets fed by the same cabinet | failure_event | circuit health |
| symptoms_14d / symptoms_30d | recorded observations in the last 14 / 30 days | observation | the P–F warning |
| max_sev_30d | maximum severity recorded in 30 days | observation | severity escalates toward F |
| circuit_partial_trips_14d | partial_trip observations on the whole circuit in 14 days | observation | cabinet failure precursor |
| tmax_14d | mean daily max temperature, last 14 days | weather | Arrhenius ageing of drivers |
| tmax_fcst_7d | 7-day temperature forecast at W | weather forecast | heat-wave weeks |
| rain_7d / rain_30d | rainfall totals | weather | cable-joint moisture |
| dust_30d | dust days in 30 days | weather | solar battery, cooling |
| heat_load_120d | Σ max(tmax − 38, 0) over 120 days | weather | cumulative thermal stress |

Label `label_h` = 1 if a failure (first signal) occurred in [W, W + H) with H = `horizon_days` (14). NULL until W + H ≤ as_of.

Rules: adding a feature requires (1) a row here, (2) a leakage test in `tests/test_pipeline.py`, (3) a new model version through the gates.
