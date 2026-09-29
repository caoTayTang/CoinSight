.PHONY: setup up down test batch extract stream live

setup:
	uv venv --python 3.12 --clear
	uv pip install -r pipeline/requirements.txt -r app/requirements.txt

up:
	docker compose up --build

down:
	docker compose --profile live down

test:
	.venv/bin/python -m pytest

batch:
	cd pipeline && ../.venv/bin/python batch_etl.py

extract:
	cd pipeline && ../.venv/bin/python extract_binance.py

stream:
	docker compose up --build kafka kafka-ui spark producer api

live:
	docker compose --profile live up --build kafka kafka-ui spark live-producer api
