.PHONY: up down test batch stream

up:
	docker compose up --build

down:
	docker compose down

test:
	pytest

batch:
	cd pipeline && python batch_etl.py

stream:
	docker compose up --build kafka kafka-ui spark producer
