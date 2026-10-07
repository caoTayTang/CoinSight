# Deployment status and target

CI checks PostgreSQL-backed tests, validates Compose, and builds API, frontend, pipeline, Spark, and Airflow images. A push to `main` publishes versioned images to GHCR. The frontend image serves the real dashboard and proxies `/api` to FastAPI on the Compose network. The original Stitch mockup remains in `frontend/code.html` for reference and is not served. No production host or DNS record has been configured from this workspace.

A deployment needs a long-running Linux host for PostgreSQL, Kafka, Spark, Airflow, and the API. Put the API behind HTTPS at an API subdomain and keep PostgreSQL/Kafka internal. A Cloudflare Worker can serve the eventual frontend, but does not replace the long-running data services. The proposed `coinsight.kaiosthefox.dpdns.org` name is only a candidate until DNS and hosting are confirmed.

Before enabling production CD, provide the host/SSH target, the DNS zone, TLS/reverse-proxy setup, and secret storage for PostgreSQL and optional Bedrock credentials. Pin GHCR images to a commit SHA, run `migrate` before API/Airflow, then check `/ready`, `/v1/data-status`, `/v1/assets/BTC/live-summary`, and Airflow DAG status. Do not publish `postgres:5432`, Kafka, or the Airflow admin UI to the internet.

Local demo currently uses `http://localhost:8000/docs` for API contracts and `http://localhost:8081` for Airflow. `docker compose down` preserves named volumes; `down --volumes` deletes local database and checkpoints.
