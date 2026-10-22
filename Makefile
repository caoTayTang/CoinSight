.PHONY: setup up down test batch extract extract-daily dss-demo dss-train dss-predict olap airflow live eda eda-backfill hourly-backfill hourly-train hourly-tune
.PHONY: hourly-future-init hourly-future-status hourly-future-schedule hourly-cross-asset-plan hourly-cross-asset-status hourly-cross-asset-schedule

# .env holds values for containers (host "postgres", paths under /data).
# Commands run on the host get localhost and repository paths instead.
-include .env
HOST_DATABASE_URL ?= postgresql://$(or $(POSTGRES_USER),crypto):$(or $(POSTGRES_PASSWORD),crypto)@localhost:5432/$(or $(POSTGRES_DB),crypto_dw)
HOST_ENV = DATABASE_URL=$(HOST_DATABASE_URL) RAW_DIR=data/raw

setup:
	uv venv --python 3.12 --clear
	uv pip install -r pipeline/requirements.txt -r app/requirements.txt

up:
	docker compose up --build

down:
	docker compose --profile batch --profile airflow down

test:
	DATABASE_URL=$(HOST_DATABASE_URL) .venv/bin/python -m pytest --ignore=tests/agents

batch:
	$(HOST_ENV) .venv/bin/python -m pipeline.batch.warehouse_loader

extract:
	$(HOST_ENV) .venv/bin/python -m pipeline.batch.ingest_binance_history

# DAY=YYYY-MM-DD, the last fully closed UTC day.
extract-daily:
	$(HOST_ENV) .venv/bin/python -m pipeline.batch.ingest_binance_history --day $(DAY)

dss-demo:
	uv run --python 3.12 --with-requirements pipeline/requirements.txt python -m scripts.demo_direction_model

dss-train:
	$(HOST_ENV) DSS_MODEL_PATH=data/models/direction.joblib .venv/bin/python -m pipeline.decision.direction_model train

dss-predict:
	$(HOST_ENV) DSS_MODEL_PATH=data/models/direction.joblib .venv/bin/python -m pipeline.decision.direction_model predict

airflow:
	docker compose --profile airflow up --build -d postgres migrate airflow

olap:
	docker compose exec -T postgres psql -U $(or $(POSTGRES_USER),crypto) -d $(or $(POSTGRES_DB),crypto_dw) -v ON_ERROR_STOP=1 < postgres/queries/olap_examples.sql

live:
	docker compose up --build kafka kafka-ui spark live-producer api frontend

# Explicit data mutation; downloads and loads only the small daily EDA scope.
eda-backfill:
	DATABASE_URL=$(HOST_DATABASE_URL) uv run --python 3.12 --with-requirements pipeline/requirements.txt python -m scripts.backfill_eda

# Explicit BTC-only hourly history; keep daily EDA and classifier separate.
hourly-backfill:
	DATABASE_URL=$(HOST_DATABASE_URL) uv run --python 3.12 --with-requirements pipeline/requirements.txt python -m scripts.backfill_eda --symbols BTC --interval 1h --start 2020-01

hourly-train:
	DATABASE_URL=$(HOST_DATABASE_URL) uv run --python 3.12 --with-requirements scripts/requirements-hourly.txt python -m scripts.train_hourly

# RUN=data/models/hourly/<uuid>; never scores the 2026 test partition.
hourly-tune:
	@test -n "$(RUN)" || (echo 'Usage: make hourly-tune RUN=data/models/hourly/<uuid>'; exit 1)
	uv run --python 3.12 --with-requirements scripts/requirements-hourly.txt python -m scripts.tune_hourly --base-run $(RUN)

# Frozen local prospective collection; install dependencies once before init.
FUTURE_PYTHON ?= data/models/hourly-runtime/venv/bin/python

hourly-future-init:
	@test -n "$(RUN)" || (echo 'Usage: make hourly-future-init RUN=<selected run>'; exit 1)
	$(FUTURE_PYTHON) -m scripts.hourly_future init --source "$(RUN)"

hourly-future-status:
	@test -n "$(STUDY)" || (echo 'Usage: make hourly-future-status STUDY=<study>'; exit 1)
	$(FUTURE_PYTHON) -m scripts.hourly_future status --study "$(STUDY)"

hourly-future-schedule:
	@test -n "$(STUDY)" || (echo 'Usage: make hourly-future-schedule STUDY=<study>'; exit 1)
	$(FUTURE_PYTHON) -m scripts.install_hourly_future_schedule --study "$(STUDY)"

hourly-cross-asset-plan:
	@test -n "$(RUN)" || (echo 'Usage: make hourly-cross-asset-plan RUN=<selected run>'; exit 1)
	$(FUTURE_PYTHON) -m scripts.hourly_cross_asset init --offline --source "$(RUN)"

hourly-cross-asset-status:
	@test -n "$(EXPERIMENT)" || (echo 'Usage: make hourly-cross-asset-status EXPERIMENT=<experiment>'; exit 1)
	$(FUTURE_PYTHON) -m scripts.hourly_cross_asset status --experiment "$(EXPERIMENT)"

hourly-cross-asset-schedule:
	@test -n "$(EXPERIMENT)" || (echo 'Usage: make hourly-cross-asset-schedule EXPERIMENT=<experiment>'; exit 1)
	$(FUTURE_PYTHON) -m scripts.install_hourly_cross_asset_schedule --experiment "$(EXPERIMENT)"

# Read-only EDA; no notebook outputs, implicit backfill or model training.
eda:
	DATABASE_URL=$(HOST_DATABASE_URL) uv run --python 3.12 --with-requirements scripts/requirements-eda.txt python -m scripts.run_eda

# Optional protocol services use an isolated dependency set (new MCP/A2A SDKs).
.PHONY: agents-up agents-down agents-test agents-smoke
AGENT_PYTHON ?= data/models/local-agent-runtime/venv/bin/python

agents-up:
	docker compose -p coinsight-agents -f compose.agents.yml up --build -d

agents-down:
	docker compose -p coinsight-agents -f compose.agents.yml down

agents-test:
	$(AGENT_PYTHON) -m pytest tests/agents -q

agents-smoke:
	$(AGENT_PYTHON) -m scripts.check_local_agents

# ---- Agent evaluation (docs/evaluation.md) -------------------------------------------------
.PHONY: eval-db eval-db-down eval eval-replay eval-test
EVAL_DSN ?= postgresql://eval:eval@127.0.0.1:15440/coinsight_eval
ROUTES ?= groq-gpt-oss-120b
SPLIT ?= train
EVAL_RUN = EVAL_DATABASE_URL=$(EVAL_DSN) uv run --python 3.12 --with-requirements warehouse_agents/requirements.txt python -m evals.run

# Disposable Postgres for fixtures; never the application warehouse.
eval-db:
	docker run -d --rm --name coinsight-eval-pg -e POSTGRES_USER=eval -e POSTGRES_PASSWORD=eval \
	  -e POSTGRES_DB=coinsight_eval -p 127.0.0.1:15440:5432 postgres:16
	until docker exec coinsight-eval-pg pg_isready -U eval -d coinsight_eval >/dev/null 2>&1; do sleep 1; done

eval-db-down:
	docker rm -f coinsight-eval-pg

eval:
	$(EVAL_RUN) --routes $(ROUTES) --split $(SPLIT) --pace 2 --out evals/reports/$(SPLIT)

# Deterministic: recorded model responses and tool results, no keys or network (runs in CI).
eval-replay:
	uv run --python 3.12 --with-requirements warehouse_agents/requirements.txt python -m evals.run \
	  --backend replay --routes groq-gpt-oss-120b --split ci --out evals/reports/ci --min-pass-rate 0.75

eval-test:
	uv run --python 3.12 --with pytest --with pytest-asyncio --with-requirements warehouse_agents/requirements.txt \
	  python -m pytest tests/evals tests/warehouse_agents -q
