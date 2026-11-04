# Architecture decision records

| # | decision | alternatives rejected | why |
|---|---|---|---|
| ADR-001 | One relational store (PostgreSQL; SQLite locally) for ops, features and ledger; lon/lat floats + haversine instead of PostGIS in v0.1 | feature store, NoSQL, PostGIS from day one | hundreds of thousands of asset-weeks fit Postgres; one tool; the metric is SQL-expressible; 25 m matching needs no GIS engine |
| ADR-002 | Python everywhere (FastAPI + scikit-learn + pandas) | Spark, polyglot services | same language as the PoC; weekly scoring of 300k assets does not need distribution |
| ADR-003 | Gradient boosting + isotonic calibration | neural nets, survival models | tabular, rare events, explainability required; PoC numbers show sufficiency |
| ADR-004 | Decision engine = one declared rule with .env parameters | integer programming, RL | supervisor trust; capacity is a single constraint; parameters are what the field calibrates |
| ADR-005 | Technician app as PWA (BarcodeDetector + manual fallback + localStorage queue) | native apps | no store, offline, enough for QR + a 20-second form |
| ADR-006 | Read-only integration with municipal systems | write-back to CMMS | enables the shadow pilot without contract or IT changes |
| ADR-007 | Simulation is a tagged *source*, not embedded demo data | hard-coded demo numbers | swapping to real exports touches nothing downstream; the tag prevents confusion in front of the jury |
| ADR-008 | Docker Compose first, same images to Kubernetes later | Kubernetes now | time to 18 Nov |
| ADR-009 | Vanilla JS apps served by the API in v0.1; Next.js migration path kept open | Next.js now | zero build step for the hackathon; the API is the contract, the UI is replaceable |
| ADR-010 | Live PFR@L counts only approved/done lists; backtest counts proposed lists | count every proposed list | a list nobody acted on is not a warning; the backtest has no supervisor |
| ADR-011 | Field parameters are rows in `sys_setting` applied over `.env` defaults, audited per change | env-only | the field calibrates from a screen, not from a file; every change has a name on it |
| ADR-012 | Long operations run as in-process background jobs recorded in `sys_job` (one at a time) | Celery/RQ | one container, no broker, progress visible; swap for a queue when more than one worker is needed |
| ADR-013 | Uploads always go through a dry-run preview before commit; rejected rows are quarantined with the reason and can be fixed and retried | silent partial loads | the operator sees what will happen before it happens |
| ADR-014 | Light, Arabic-first design system with a single primary colour; risk is the only use of amber/red | hackathon palette | an operational tool for a municipality, not a pitch deck |
| ADR-015 | One platform for the four asset families of the challenge via a single catalogue (`core/catalog.py`); lighting is the calibrated pilot, the others ship with a simplified, clearly simpler simulation | lighting-only prototype | the registered idea covers urban assets, not lamps; the catalogue makes the category a data row, not a code branch |
| ADR-016 | Failure windows by conformalised quantile regression on days-to-failure (target coverage a parameter); shown only where a signal or alert exists; coverage re-measured per backtest | point RUL estimates | a number without a guarantee is not a schedule input (the vision's second innovation) |
| ADR-017 | Consequences are five SAR terms with the dependency graph inside the service term; every term a calibratable parameter and the breakdown stored per prediction | single consequence weight | the pump-vs-pole example only works if consequences are explicit and auditable |
| ADR-018 | Selection by MILP (HiGHS via scipy) under capacity and budget with critical assets forced; greedy fallback; backtest keeps the capacity-only rule so PFR@L stays comparable | greedy only / OR-Tools | exact small problems, no extra dependency; the backtest measures prediction, not budget policy |
| ADR-019 | Routes by k-means + nearest neighbour with ride-along grouping within a radius at a reduced cost share | full VRP | the hackathon needs the grouping effect visible, not an optimal tour |
| ADR-020 | The assistant is template-first from stored facts; an LLM (optional key) only rephrases those facts | free-form LLM | explanations must be auditable and never invent numbers |

Changing the decision rule or the PFR@L definition requires a new ADR.
