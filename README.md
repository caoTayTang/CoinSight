# Crypto Data Warehouse DSS

Minimal scaffold for a cryptocurrency data warehouse and decision-support
system. Ownership follows the architecture, not separate `A/`, `B/`, or `C/`
folders.

## Team Split

```text
 B: BATCH ETL
 [Source] -> [Raw CSV/Parquet] -> [Batch transform] -> [PostgreSQL DW] -> [Forecast]
                                      ^
                         [Scheduler / quality gates]

 A: STREAMING ETL
 [Kaggle replay] --\
                    >-> [Kafka] -> [Spark Structured Streaming]
 [Binance API] ----/         ^              |
                             |              +-> [7-day live metrics]
                        [Kafka UI]                      |
                                                      v
                                                [PostgreSQL DW]

 C: DECISION SUPPORT
 [Forecast] -----\
                  >-> [FastAPI] <-> [Browser dashboard]
 [Live metrics] -/

 C also owns Docker Compose, service health, integration tests, and demo flow.
```

## Responsibilities

### A - Streaming ETL

- `pipeline/producer.py` replays historical OHLCV rows to Kafka in event-time
  order. BTC, ETH, and SOL are selected by default.
- `pipeline/live_producer.py` polls completed one-minute candles from Binance's
  public market-data API and publishes them in the same event format.
- `pipeline/stream_etl.py` validates and deduplicates events, calculates daily
  sliding seven-day metrics, and upserts them into `fact_live_metric`.
- Kafbat UI displays Kafka topics, partitions, offsets, and message contents.
- Kafka offsets and Spark checkpoints make the stream restartable.

### B - Batch ETL and Warehouse

- Own raw data, validation, batch loading, the warehouse, and forecasting.
- Current files: `data/sample.csv`, `pipeline/batch_etl.py`,
  `pipeline/config.py`, `pipeline/contracts.py`, `postgres/init/`.
- Current status: CSV loading and the warehouse exist; scheduling and forecasting
  remain to be implemented.

### C - DSS and Integration

- Expose batch and live results through the API.
- Maintain the lightweight HTML/CSS/JavaScript dashboard served by FastAPI.
- Maintain Docker Compose, service checks, integration tests, and demo flow.
- Current files: `app/api.py`, `app/static/`, `docker-compose.yml`,
  `tests/test_api.py`.

Each role may add files inside the relevant component as the implementation
grows.

## Current Project

```text
crypto-dw-dss/
|-- pipeline/          Batch loader, replay/live producers, and Spark stream job
|-- postgres/init/     Warehouse schema and seed data
|-- app/               FastAPI service and browser dashboard
|-- tests/             Contract, batch, and API tests
|-- data/sample.csv    Sample source data
|-- docker-compose.yml Services, volume, and Docker network
`-- Makefile           Common commands
```

Airflow, Parquet storage, and forecasting are not implemented.

## Streaming Dataset

The replay source is Kaggle's
[Cryptocurrency Prices (Top 200+) - Daily Updated](https://www.kaggle.com/datasets/isaaclopgu/cryptocurrency-historical-prices-top-100-2025),
version 105. It contains daily OHLCV data for 250 cryptocurrencies in
`Crypto_historical_data.csv` and is licensed CC BY-SA 4.0.

Place the CSV at:

```text
data/raw/Crypto_historical_data.csv
```

`data/raw/` is ignored by Git. Change `REPLAY_SYMBOLS` in `.env` to select
other assets, or set it to an empty value to replay all assets.

## Run

From the project directory, start everything in the background:

```bash
docker compose up --build -d
```

The first run takes longer because Docker downloads Kafka and Spark. Check the
services with:

```bash
docker compose ps --all
```

`postgres`, `kafka`, `kafka-ui`, `spark`, and `api` should be running. The
`pipeline` and `producer` containers should eventually show `Exited (0)`; this
means their one-time jobs completed successfully.

| Service | Address |
| --- | --- |
| Data dashboard | <http://localhost:8000> |
| Kafka UI | <http://localhost:8080> |
| API documentation | <http://localhost:8000/docs> |

The dashboard summarizes warehouse coverage, recent prices and volume, basic
descriptive statistics, and the latest Spark streaming metrics. It refreshes
every 30 seconds.

Kafka UI has no login in this local setup and can modify topics. Do not expose
port `8080` on a public or shared machine without adding authentication.

## See the Stream Working

Choose one source mode. For historical Kaggle replay:

```bash
make stream
```

For current BTC, ETH, and SOL data from Binance:

```bash
make live
```

The live producer requests the latest two one-minute candles and publishes the
most recent completed candle. It uses Binance's
[public market-data endpoint](https://developers.binance.com/en/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data),
so no API key is required. `volume` is the candle's USDT quote volume. Change
`LIVE_SYMBOLS` in `.env` to use other symbols that have a USDT pair.

Binance applies IP-based request limits. Each kline request has weight `2`; the
default three symbols polled every 20 seconds use only `18` weight per minute.
The producer honors Binance's `Retry-After` response when it receives HTTP `429`
or `418` and pauses before trying again.

Do not run `make stream` and `make live` together on a fresh checkpoint. A live
event advances Spark's event-time watermark, which can make old replay events
arrive too late. To switch modes and rebuild all local state:

```bash
docker compose --profile live down --volumes
make live
```

This deletes locally stored PostgreSQL data.

Open <http://localhost:8080>, then select:

```text
local -> Topics -> crypto-prices -> Messages
```

Click a message to inspect its JSON value. Important fields are:

- `symbol`: cryptocurrency ticker, such as `BTC`.
- `event_time`: original date from the historical dataset.
- `open_price`, `high_price`, `low_price`, `close_price`: candle prices.
- `volume`: quote trading volume for that candle.
- `event_id`: stable identifier Spark uses to remove duplicates.
- `source`: `kaggle-replay` or `binance-rest`.

The topic has three partitions. An offset is only the position of a message
inside its partition; it is not a price or timestamp.

Watch Spark consume events and store metric windows:

```bash
docker compose logs --follow spark
```

Look for `stored ... metric updates from batch ...`. Press `Ctrl+C` to stop
watching; the containers continue running.

Query the generated seven-day windows:

```bash
docker compose exec postgres psql -U crypto -d crypto_dw -c \
"select symbol, count(*) as windows, max(event_count) as max_events
 from fact_live_metric group by symbol order by symbol;"
```

`max_events` should reach `7` because each full metric window contains seven
daily price events.

Both streaming commands stay attached to service logs. Use `Ctrl+C` when
finished.

The first Spark startup downloads its Kafka connector. To replay from a
completely clean state, remove both the database and checkpoint
volumes before restarting:

```bash
docker compose --profile live down --volumes
make stream
```

## Tests

Install [uv](https://docs.astral.sh/uv/) once, then create the Python 3.12
environment and install dependencies:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
make setup
```

Activate the environment when running Python commands directly:

```bash
source .venv/bin/activate
```

Run the test suite:

```bash
make test
```

The tests check validation, CSV filtering and ordering, Binance candle
normalization, batch loading, and API health. A successful run currently reports
`11 passed`.

Stop the services without deleting stored data:

```bash
make down
```
