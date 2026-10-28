.PHONY: setup up down test batch extract extract-daily catch-up-daily dss-demo dss-train dss-predict olap airflow live eda eda-backfill hourly-backfill hourly-train hourly-tune
.PHONY: hourly-future-init hourly-future-status hourly-future-schedule hourly-cross-asset-plan hourly-cross-asset-status hourly-cross-asset-schedule
.PHONY: forecast-audit forecast-backfill forecast-dataset forecast-train forecast-auto forecast-resume forecast-seal forecast-backtest forecast-policy-backtest forecast-bundle forecast-support
.PHONY: anomaly-train anomaly-train-all anomaly-activate

# .env holds values for containers (host "postgres", paths under /data).
# Commands run on the host get localhost and repository paths instead.
-include .env
HOST_DATABASE_URL ?= postgresql://$(or $(POSTGRES_USER),crypto):$(or $(POSTGRES_PASSWORD),crypto)@localhost:5432/$(or $(POSTGRES_DB),crypto_dw)
HOST_ENV = DATABASE_URL=$(HOST_DATABASE_URL) RAW_DIR=data/raw
CUDA_DETERMINISM_ENV = CUBLAS_WORKSPACE_CONFIG=:4096:8

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

# Repair only missing trailing completed UTC days for each configured coin.
# Optional: THROUGH=YYYY-MM-DD (defaults to yesterday UTC).
catch-up-daily:
	$(HOST_ENV) .venv/bin/python -m pipeline.batch.catch_up_daily $(if $(THROUGH),--through $(THROUGH),)

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

# Experimental daily/hourly forecasting workflow.
forecast-audit:
	$(HOST_ENV) .venv/bin/python -m pipeline.decision.cli audit-data --symbols $(or $(SYMBOLS),BTC,ETH,SOL)

forecast-backfill:
	$(HOST_ENV) .venv/bin/python -m pipeline.decision.cli backfill --symbols $(or $(SYMBOLS),BTC) --start $(or $(START),2020-01)

forecast-dataset:
	$(HOST_ENV) FORECAST_SNAPSHOT_DIR=data/forecasting/snapshots .venv/bin/python -m pipeline.decision.cli build-dataset --symbol $(or $(SYMBOL),BTC) $(if $(CUTOFF),--cutoff $(CUTOFF),)

forecast-train:
	$(HOST_ENV) $(CUDA_DETERMINISM_ENV) FORECAST_SNAPSHOT_DIR=data/forecasting/snapshots FORECAST_RUN_DIR=data/forecasting/runs .venv/bin/python -m pipeline.decision.cli train --symbol $(or $(SYMBOL),BTC) --model $(or $(MODEL),xgboost) --snapshot-id $(SNAPSHOT_ID) --seed $(or $(SEED),42)

# Automatic experiment: train -> validation -> seal -> one-time test -> plots/report.
forecast-auto:
	$(HOST_ENV) $(CUDA_DETERMINISM_ENV) FORECAST_SNAPSHOT_DIR=data/forecasting/snapshots FORECAST_RUN_DIR=data/forecasting/runs .venv/bin/python -m pipeline.decision.train $(SNAPSHOT_ID) --model $(or $(MODEL),gru) --seed $(or $(SEED),42) $(if $(SYMBOL),--symbol $(SYMBOL),) $(if $(DEVICE),--device $(DEVICE),)

forecast-resume:
	$(HOST_ENV) $(CUDA_DETERMINISM_ENV) FORECAST_SNAPSHOT_DIR=data/forecasting/snapshots FORECAST_RUN_DIR=data/forecasting/runs .venv/bin/python -m pipeline.decision.cli resume --run-id $(RUN_ID)

forecast-seal:
	FORECAST_RUN_DIR=data/forecasting/runs .venv/bin/python -m pipeline.decision.cli seal --run-id $(RUN_ID)

forecast-backtest:
	$(HOST_ENV) FORECAST_SNAPSHOT_DIR=data/forecasting/snapshots FORECAST_RUN_DIR=data/forecasting/runs .venv/bin/python -m pipeline.decision.cli backtest --run-id $(RUN_ID)

# Causal policy replay. START is inclusive and END is exclusive; omitting both
# uses the pinned model snapshot's held-out test split.
# Usage: make forecast-policy-backtest SYMBOL=BTC INITIAL_CASH=10000
forecast-policy-backtest:
	$(HOST_ENV) DAILY_FORECAST_BUNDLE_ROOT=data/models/daily-forecast .venv/bin/python -m pipeline.decision.cli policy-backtest \
		--symbol $(or $(SYMBOL),BTC) \
		--initial-cash $(or $(INITIAL_CASH),10000) \
		--policy-version $(or $(POLICY_VERSION),daily_quantile_v1) \
		--performance-days $(or $(PERFORMANCE_DAYS),30) \
		--market-days $(or $(MARKET_DAYS),30) \
		--trend-hours $(or $(TREND_HOURS),168) \
		$(if $(START),--start $(START),) \
		$(if $(END),--end $(END),) \
		$(if $(DEVICE),--device $(DEVICE),) \
		$(if $(OUTPUT_DIRECTORY),--output-directory $(OUTPUT_DIRECTORY),) \
		$(if $(ALLOW_OUTSIDE_TEST),--allow-outside-test,)

# Pin one finalized/test-consumed run as an immutable daily serving bundle.
# Usage: make forecast-bundle RUN_DIR=data/forecasting/runs/BTC/gru/<run-id> VERSION=2026-10-23-v1
forecast-bundle:
	@test -n "$(RUN_DIR)" || (echo 'Usage: make forecast-bundle RUN_DIR=<tested run directory> VERSION=<version>'; exit 1)
	@test -n "$(VERSION)" || (echo 'Usage: make forecast-bundle RUN_DIR=<tested run directory> VERSION=<version>'; exit 1)
	.venv/bin/python -m pipeline.decision.serving.cli build-bundle --run-directory "$(RUN_DIR)" --version "$(VERSION)" --activate

# Audit -> targeted repair only if needed -> daily inference + diagnostics.
# Usage: make forecast-support SYMBOL=BTC PERFORMANCE_DAYS=30 MARKET_DAYS=30 TREND_HOURS=168
forecast-support:
	$(HOST_ENV) DAILY_FORECAST_BUNDLE_ROOT=data/models/daily-forecast .venv/bin/python -m pipeline.decision.serving.cli report \
		--symbol $(or $(SYMBOL),BTC) \
		--performance-days $(or $(PERFORMANCE_DAYS),30) \
		--market-days $(or $(MARKET_DAYS),30) \
		--trend-hours $(or $(TREND_HOURS),168) $(if $(CUTOFF),--cutoff $(CUTOFF),)

# Temporal Isolation Forest training. END is exclusive and must be frozen
# before reviewing test results; VERSION is immutable within each asset/frequency.
anomaly-train:
	@test -n "$(END)" || (echo 'Usage: make anomaly-train SYMBOL=BTC FREQUENCY=1h END=2026-10-27 VERSION=2026-10-27-v1'; exit 1)
	@test -n "$(VERSION)" || (echo 'VERSION is required'; exit 1)
	$(HOST_ENV) .venv/bin/python -m pipeline.decision.anomaly.cli \
		--symbol $(or $(SYMBOL),BTC) --frequency $(or $(FREQUENCY),1h) \
		--end $(END) --version $(VERSION) $(if $(ACTIVATE),--activate,)

anomaly-train-all:
	@test -n "$(END)" || (echo 'Usage: make anomaly-train-all END=2026-10-27 VERSION=2026-10-27-v1 ACTIVATE=1'; exit 1)
	@test -n "$(VERSION)" || (echo 'VERSION is required'; exit 1)
	@for symbol in BTC ETH; do \
		for frequency in 1h 1d; do \
			$(MAKE) anomaly-train SYMBOL=$$symbol FREQUENCY=$$frequency END=$(END) VERSION=$(VERSION) ACTIVATE=$(ACTIVATE) || exit $$?; \
		done; \
	done

anomaly-activate:
	@test -n "$(VERSION)" || (echo 'Usage: make anomaly-activate SYMBOL=BTC FREQUENCY=1h VERSION=2026-10-27-v1'; exit 1)
	.venv/bin/python -m pipeline.decision.anomaly.cli \
		--symbol $(or $(SYMBOL),BTC) --frequency $(or $(FREQUENCY),1h) \
		--version $(VERSION) --activate-existing
