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

Changing the decision rule or the PFR@L definition requires a new ADR.
