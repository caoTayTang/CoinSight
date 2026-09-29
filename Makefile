.PHONY: setup up down test batch extract olap airflow stream live

setup:
	uv venv --python 3.12 --clear
	uv pip install -r pipeline/requirements.txt -r app/requirements.txt

up:
	docker compose up --build

down:
	docker compose --profile live --profile airflow down

test:
	.venv/bin/python -m pytest

batch:
	cd pipeline && ../.venv/bin/python batch_etl.py

extract:
	cd pipeline && ../.venv/bin/python extract_binance.py

airflow:
	docker compose --profile airflow up --build -d postgres airflow

olap:
	docker compose exec -T postgres psql -U crypto -d crypto_dw -v ON_ERROR_STOP=1 < docs/olap_queries.sql

stream:
	docker compose up --build kafka kafka-ui spark producer api

live:
	docker compose --profile live up --build kafka kafka-ui spark live-producer api
