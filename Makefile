.PHONY: setup up down test batch stream stream-logs live live-logs

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
	cd pipeline && python batch_etl.py

stream:
	docker compose up --build -d kafka kafka-ui spark producer api
	docker compose ps

stream-logs:
	docker compose logs --follow producer spark

live:
	docker compose --profile live up --build -d kafka kafka-ui spark live-producer api
	docker compose --profile live ps

live-logs:
	docker compose --profile live logs --follow live-producer spark
