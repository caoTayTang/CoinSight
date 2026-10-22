# Linux home server

Run from the repository root. Keep credentials in the ignored `.env` file.
Set `AIRFLOW_UID` to the host user ID and `COINSIGHT_OBSERVABILITY_NETWORK`
to the core Compose network name (here `crypto-dw-dss_crypto-network`).

The home overrides connect agents directly to container services. This works
on Linux while published admin ports remain bound to `127.0.0.1`.
The API reaches the Desk gateway at `warehouse-mcp:8000`; the agents use
`postgres:5432`, `prediction-agent:8000`, and other Docker service names.
Airflow is limited to two concurrent tasks, one API worker, and one DAG parser
to leave memory available for Kafka, Spark, and the agents.

Manual deployment of the checked-out branch:

```bash
bash deploy/home/deploy.sh --force
```

Do not schedule the non-force command while testing a feature branch: it tracks
`origin/main`. Cloudflare Access must be configured before publishing the app.
Local web: http://127.0.0.1:3000. API: http://127.0.0.1:8000/health.

For databases from the original scaffold, back up PostgreSQL and apply the
ordered `postgres/init/*.sql` files before migrations. Existing volumes do not
rerun Docker's initialization scripts automatically. Normal restarts preserve
warehouse data, Kafka data, Spark checkpoints, and the home Spark Ivy cache.

## Historical data

Build the batch image first so an old local image is not reused. Mount a separate
writable archive directory; the normal `/data` mount is intentionally read-only.

```bash
docker compose --profile batch build pipeline
docker compose --profile batch run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data/raw:/backfill:rw" \
  pipeline python -m scripts.backfill_eda --symbols BTC,ETH,SOL \
  --interval 1h --start 2020-01 --raw-dir /backfill
docker compose --profile batch run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data/raw:/backfill:rw" \
  pipeline python -m scripts.backfill_eda \
  --interval 1d --start 2024-01 --raw-dir /backfill
```

## Check the server

```bash
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8000/v1/assets/BTC/live-summary
curl -fsS http://127.0.0.1:8020/health
docker compose logs --tail 20 live-producer spark
```

The live summary should report `ready`, recent candles, and a small
`freshness_seconds` value. Allow 15 minutes to fill its initial window.
Kafka UI: http://127.0.0.1:8080. Airflow: http://127.0.0.1:8081.
These URLs are local to the server, not directly reachable from the MacBook.

## Daily jobs

After the initial backfill and Airflow startup:

```bash
docker compose --profile airflow exec airflow airflow dags unpause coinsight_warehouse_daily
docker compose --profile airflow exec airflow airflow dags unpause coinsight_direction_daily
```

Warehouse updates run at 06:00 UTC; daily predictions at 07:30 UTC, with model
evaluation on Mondays. The daily direction model is separate from the supplied
hourly forecast bundle. A rejected evaluation leaves daily predictions unavailable
until a model passes the baseline quality gate; do not bypass that gate.

## Cloudflare tunnel

Configure the hostname's Access email allowlist before routing DNS. Set
`CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` in `.env`, then recreate the API.
The Linux connector runs separately from the core stack:

```bash
docker compose --env-file .env -p coinsight-tunnel -f deploy/home/compose.tunnel.yml up -d
docker compose --env-file .env -p coinsight-tunnel -f deploy/home/compose.tunnel.yml logs --tail 20
```

Host files: `~/.cloudflared/config.yml` and mode-600 `~/.cloudflared/coinsight.json`.
The config uses the tunnel UUID, credentials at `/etc/cloudflared/credentials.json`,
loopback metrics, the app hostname routed to `http://127.0.0.1:3000`, and a final
`http_status:404` rule. `AIRFLOW_UID` must match the credential owner. Never commit
credentials. The broader Cloudflare login certificate is not mounted.

On the Mac, open https://coinsight.kaiosthefox.dpdns.org and sign in with an allowed email.
The connector restarts with Docker. Admin services stay private. Unauthenticated
public requests must redirect to Access; no router port forwarding is needed.
