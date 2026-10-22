# Running CoinSight on a home server

This sets up the full system on an always-on machine at home and publishes it at
`https://coinsight.kaiosthefox.dpdns.org` behind Cloudflare Access: warehouse, Kafka, Spark streaming, live Binance
data, the daily Airflow batch, the agents, the prediction ledger and automatic deploys from `main`.

It is written for a coding agent running on that machine, with the few dashboard steps marked **[you]**.
Run commands from the repository root unless stated otherwise.

## What you end up with

```text
Binance WS ─► live-producer ─► Kafka ─► Spark ─► Postgres ◄─ Airflow (daily archives)
                                                   │
          forecast · anomaly · ledger agents ──────┤
          Trade / SRE agents + gateway ────────────┤
                                                   ▼
                    API ◄─ web (nginx :3000) ◄─ cloudflared ◄─ Cloudflare Access ◄─ you
```

Only the web app goes through the tunnel; it proxies `/api` to the API. `/docs` on the same hostname is the public
docs site, served by a Cloudflare Worker (`frontend/wrangler.toml`), so it stays up when this machine is off. Postgres, Kafka UI, Airflow and
Jaeger stay on `127.0.0.1`. Deploys are pull-based: the server polls `main` and deploys commits whose CI
passed. The repository is public, so no GitHub runner is ever given access to this machine.

## 0. Requirements

- 8 GB RAM or more (the stack uses about 4 GB; Kafka and Spark are the largest), 20 GB free disk.
- Docker Engine or Docker Desktop with Compose v2, `git`, `gh` (logged in), `uv`, Node 22, `cloudflared`.
- The machine must not sleep. macOS: `sudo pmset -a sleep 0 disablesleep 1` (and keep it on power).
  Linux laptop: set `HandleLidSwitch=ignore` in `/etc/systemd/logind.conf`, then `sudo systemctl restart systemd-logind`.

```bash
docker compose version && git --version && jq --version && uv --version && node --version && cloudflared --version
```

## 1. Bring over what git doesn't have **[you, on the dev Mac]**

Model files and secrets are not in the repository. On the dev Mac:

```bash
cd ~/BK/HK261/DW/CoinSight
tar czf ~/coinsight-models.tgz data/models/agent-serving-bundle/v1 data/models/warehouse-anomaly/v1   # ~10 MB
```

Copy `~/coinsight-models.tgz` and the `.env` file to the server by AirDrop, USB or `scp`. **Don't** send
`.env` through chat, email or git: it holds the Groq, OpenRouter and Bedrock keys.

## 2. Check out and configure

```bash
git clone git@github.com:caoTayTang/CoinSight.git ~/coinsight && cd ~/coinsight
tar xzf ~/coinsight-models.tgz            # creates data/models/...
cp ~/.env.from-mac .env                   # wherever you copied it
mkdir -p data/raw data/models
```

Edit `.env`:

| Variable | Value |
|---|---|
| `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK` | Keep from the Mac |
| `WAREHOUSE_AGENT_TOKEN` | New random value: `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `AIRFLOW_UID` | Output of `id -u` |
| `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD` | Leave empty until step 5 |
| `POSTGRES_PASSWORD` | Optional: change from the default (Postgres only listens on 127.0.0.1) |

## 3. Start everything

```bash
deploy/home/deploy.sh --force
```

This builds and starts, in order: the core stack (Postgres + migrations, Kafka, Kafka UI, Spark, live producer,
API, web, Jaeger), Airflow, the forecast/anomaly/ledger agents, then the Trade/SRE agents and gateway, and
waits for the health checks. The first build takes 10 to 20 minutes.

```bash
docker ps --format '{{.Names}}\t{{.Status}}'      # every container Up, agents (healthy)
curl -s http://127.0.0.1:8000/health              # {"status":"ok"}
```

## 4. Load history and turn on the batch

The live producer fills one-minute candles from now on. History comes from Binance's daily and monthly
archives:

```bash
# Hourly candles from 2020 for the three assets the agents cover (downloads archives into data/raw).
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with-requirements pipeline/requirements.txt \
  python -m scripts.backfill_eda --symbols BTC,ETH,SOL --interval 1h --start 2020-01
# Daily candles for the dashboard and the daily model.
make eda-backfill
```

Then let Airflow keep it current. Open `http://127.0.0.1:8081` or use the CLI:

```bash
docker compose exec airflow airflow dags unpause coinsight_warehouse_daily
docker compose exec airflow airflow dags unpause coinsight_direction_daily
docker compose exec airflow airflow dags trigger coinsight_warehouse_daily     # first run now
```

Check coverage: `make olap`, or ask the agent "check BTC coverage for the last 168 hours" once step 5 is done.

## 5. Publish through Cloudflare

**Order matters: create the Access application first, so the hostname is never public without a login.**

1. **[you]** Zero Trust dashboard → Access → Applications → Add → Self-hosted.
   Domain `coinsight.kaiosthefox.dpdns.org`. Policy: Allow, Include → Emails → your address (and anyone you invite).
   Login method: One-time PIN (and GitHub/Google if you like).
   Then a second Self-hosted application for the public docs: domain `coinsight.kaiosthefox.dpdns.org`, path `docs`,
   policy action **Bypass**, Include → Everyone. The more specific path wins, so `/docs` needs no login.
2. **[you]** In the application's settings copy the **Application Audience (AUD) tag**. Your team domain is under
   Settings → Custom pages (`<team>.cloudflareaccess.com`). Put both in `.env`:
   `CF_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com`, `CF_ACCESS_AUD=<tag>`, then `deploy/home/deploy.sh --force`.
   From now on the API rejects requests without a valid Access token, and each email gets its own history and
   memory.
3. Create the tunnel and route it:

   ```bash
   cloudflared tunnel login                         # browser: pick the kaiosthefox.dpdns.org zone
   cloudflared tunnel create coinsight              # prints the tunnel ID, writes ~/.cloudflared/<ID>.json
   cp deploy/cloudflared/config.example.yml ~/.cloudflared/config.yml   # fill in <TUNNEL_ID> and <user>
   cloudflared tunnel route dns coinsight coinsight.kaiosthefox.dpdns.org
   cloudflared tunnel run coinsight                 # foreground test; Ctrl-C when it works
   ```

4. Run it as a service: Linux `sudo cloudflared service install`; macOS `sudo cloudflared service install`
   (installs a launchd daemon using `~/.cloudflared/config.yml`).
5. Open `https://coinsight.kaiosthefox.dpdns.org`: Access login, then the dashboard with your email in the Desk bar.
6. Deploy the docs on `/docs`: `npm --prefix frontend run deploy:docs`. The Worker route needs the hostname's DNS record
   from step 3. If the hostname is still a Worker custom domain, remove it first (Workers → `coinsight-docs` → Domains).

Don't add tunnel routes for Airflow, Kafka UI or Jaeger. If you need them remotely, give each its own hostname
behind its own Access application.

## 6. Continuous deployment

**Docs site:** pushes to `main` that touch docs deploy through `.github/workflows/deploy-docs.yml`.
**[you]** Create a Cloudflare API token (My Profile → API Tokens → Custom: Account › Workers Scripts › Edit,
Zone › Workers Routes › Edit, zone `kaiosthefox.dpdns.org`), then:

```bash
gh secret set CLOUDFLARE_API_TOKEN          # paste the token
gh secret set CLOUDFLARE_ACCOUNT_ID          # the Account ID shown by `npx wrangler whoami`
```

**The app:** poll every 5 minutes. A commit on `main` is deployed only after all its CI checks succeed.

```bash
# Linux or macOS cron (crontab -e); PATH must include docker, git, curl and jq.
*/5 * * * * cd $HOME/coinsight && PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin deploy/home/deploy.sh >> data/deploy.log 2>&1
```

Merge a PR → CI runs on GitHub → within 5 minutes of CI passing the server fast-forwards and rebuilds.
`tail -f data/deploy.log` shows each decision (`skip … CI pending`, `deploying …`, `deployed …`).

**Rollback:** revert the commit on `main` (it deploys like any other), or on the server
`git checkout <good-sha> && deploy/home/deploy.sh --force`, then `git checkout main` once `main` is fixed.

## 6b. Sign-in with Supabase instead of Cloudflare Access

With Supabase the dashboard and docs are public, anyone can try a few free-model questions, and people sign in
with Google or GitHub for more and for Claude Haiku. The API trusts only Google and GitHub sign-ins, because
owners are decided by email and an unverified email sign-up could claim an owner's address.

1. **Supabase → Authentication → URL Configuration:** Site URL `https://coinsight.kaiosthefox.dpdns.org`;
   Redirect URLs `https://coinsight.kaiosthefox.dpdns.org/**` and, for development, `http://localhost:5173/**`.
2. **GitHub:** Settings → Developer settings → OAuth Apps → New. Homepage URL as above; Authorization callback
   URL `https://<project-ref>.supabase.co/auth/v1/callback`. Paste the client ID and a new client secret into
   Supabase → Authentication → Sign In / Providers → GitHub.
3. **Google:** Google Cloud console → APIs & Services → OAuth consent screen (External, app name CoinSight),
   then Credentials → Create OAuth client ID → Web application. Authorized redirect URI: the same Supabase
   callback URL. Paste the client ID and secret into Supabase → Providers → Google.
4. **Server `.env`:** `SUPABASE_URL=https://<project-ref>.supabase.co` and `SUPABASE_PUBLISHABLE_KEY=sb_publishable_…`
   (both public), then `deploy/home/deploy.sh --force`. The client secrets stay in Supabase; the server never
   holds them.
5. **Check, then open the app:** in a private window, sign in with each provider and see your email in the top
   bar. Then remove the Access application for `coinsight.kaiosthefox.dpdns.org` (Zero Trust → Access →
   Applications). Keep the one for `ssh.` and the `docs` bypass. While both exist, Access still works: its
   signed-in users keep their history, because both key users by the same email hash.

Without a sign-in, a visitor is keyed by a hash of their IP (the /64 network for IPv6) and gets
`AGENT_ANON_DAILY_LIMIT` free-model questions a day, with `AGENT_ANON_GLOBAL_DAILY_LIMIT` across all anonymous
visitors. They have no history list and no long-term memory, since an IP can be shared.

## 7. Verify

| Check | Expect |
|---|---|
| `/drift` in the Desk | anomaly and forecast drift, ledger count growing |
| "check service health" | API, forecast, traces, Airflow, Kafka, Postgres ok; stream fresh (< 5 min) |
| `select count(*) from ml.prediction_ledger` | +1 per hour; scored rows appear an hour later |
| Desk → History / Memory | your threads and notes only |
| Signed out, `curl https://coinsight.kaiosthefox.dpdns.org/api/v1/me` | redirected to the Access login |
| Signed out, `curl -I https://coinsight.kaiosthefox.dpdns.org/docs/` | 200, no login |
| `tail data/deploy.log` | a `deployed` line for the current `main` |

## Operations

- Logs: `docker compose logs --tail 100 <service>`; agents: `docker compose -f warehouse_agents/compose.yml logs`.
- Restart a part without redeploying: `docker compose restart live-producer`.
- Disk: Kafka retention and `data/raw` archives grow slowly; `docker system prune` removes old images after deploys.
- Power loss: every long-running container has `restart: unless-stopped` here (`deploy/home/compose.restart.yml`), so the stack returns when Docker starts. Make Docker start at login/boot, and check `cloudflared` and cron after a reboot.
