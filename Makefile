PY ?= python
AS_OF ?= $(shell date +%Y-%m-%d)

.PHONY: help install up down migrate seed-sim features train plan ledger backtest demo serve test lint clean

help:            ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
install:         ## install into the current Python
	$(PY) -m pip install -r requirements.txt && $(PY) -m pip install -e .
up:              ## start the full stack (PostgreSQL + API) with Docker Compose
	docker compose up -d --build
down:            ## stop the stack
	docker compose down
migrate:         ## create schema + demo users
	$(PY) -m baseera.cli migrate
seed-sim:        ## load the simulated source through the ingestion pipelines
	$(PY) -m baseera.cli seed-sim
features:        ## derive failures + build weekly as-of features
	$(PY) -m baseera.cli build-features --as-of $(AS_OF)
train:           ## train + gate + promote
	$(PY) -m baseera.cli train --as-of $(AS_OF)
plan:            ## score the current week and build the weekly list
	$(PY) -m baseera.cli plan --as-of $(AS_OF)
ledger:          ## compute the monthly ledger (PFR@L, emergency share, dark days)
	$(PY) -m baseera.cli ledger
backtest:        ## temporal backtest on the last year (writes data/backtest.json)
	$(PY) -m baseera.cli backtest --split $(shell date -v-365d +%Y-%m-%d 2>/dev/null || date -d '-365 days' +%Y-%m-%d) --end $(AS_OF)
demo:            ## everything on the simulation in one go (≈ 2–4 min)
	$(PY) -m baseera.cli demo --as-of 2026-10-25
serve:           ## run the API + web apps on :8000
	$(PY) -m baseera.cli serve --reload
test:            ## run the test suite
	$(PY) -m pytest
lint:            ## byte-compile everything (no extra tooling required)
	$(PY) -m compileall -q baseera tests
clean:           ## remove local data (database, models, sim CSVs)
	rm -rf data/baseera.db* data/models data/sim data/test data/backtest.json
