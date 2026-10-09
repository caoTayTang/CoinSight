.PHONY: setup up down test batch extract extract-daily dss-demo dss-train dss-predict olap airflow stream live

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
	docker compose --profile batch --profile replay --profile airflow down

test:
	DATABASE_URL=$(HOST_DATABASE_URL) .venv/bin/python -m pytest

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

stream:
	STREAM_KAFKA_TOPIC=crypto-prices-replay STREAM_MODE=replay STREAM_CHECKPOINT_PATH=/checkpoints/kaggle-replay-v1 docker compose --profile replay up --build kafka kafka-ui spark producer api frontend

live:
	docker compose up --build kafka kafka-ui spark live-producer api frontend
