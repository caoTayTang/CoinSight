.PHONY: setup up down test batch extract olap airflow stream live

# .env holds values for containers (host "postgres", paths under /data).
# Commands run on the host get localhost and repository paths instead.
-include .env
HOST_DATABASE_URL ?= postgresql://$(or $(POSTGRES_USER),crypto):$(or $(POSTGRES_PASSWORD),crypto)@localhost:5432/$(or $(POSTGRES_DB),crypto_dw)
HOST_ENV = DATABASE_URL=$(HOST_DATABASE_URL) RAW_DIR=../data/raw

setup:
	uv venv --python 3.12 --clear
	uv pip install -r pipeline/requirements.txt -r app/requirements.txt

up:
	docker compose up --build

down:
	docker compose --profile live --profile airflow down

test:
	DATABASE_URL=$(HOST_DATABASE_URL) .venv/bin/python -m pytest

batch:
	cd pipeline && $(HOST_ENV) ../.venv/bin/python batch_etl.py

extract:
	cd pipeline && $(HOST_ENV) ../.venv/bin/python extract_binance.py

airflow:
	docker compose --profile airflow up --build -d postgres airflow

olap:
	docker compose exec -T postgres psql -U $(or $(POSTGRES_USER),crypto) -d $(or $(POSTGRES_DB),crypto_dw) -v ON_ERROR_STOP=1 < postgres/queries/olap_examples.sql

stream:
	docker compose up --build kafka kafka-ui spark producer api

live:
	docker compose --profile live up --build kafka kafka-ui spark live-producer api
