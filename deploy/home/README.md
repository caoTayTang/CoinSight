# Home-server deployment entry point

The deployment procedure is maintained in [docs/home_server.md](../../docs/home_server.md). Read it for setup, model transfer, backfill, tunnel, startup, verification and rollback.

For Google/GitHub login, follow [docs/auth_setup.md](../../docs/auth_setup.md). Do not duplicate provider credentials or callback settings in this directory.

Files here implement that procedure:

| File | Purpose |
| --- | --- |
| `deploy.sh` | Pull-based deployment of CI-passing main, or the current checkout with `--force` |
| `compose.restart.yml` | Core service restart/resource settings |
| `compose.agents.yml` | Forecast/anomaly/ledger home-server networking |
| `compose.warehouse.yml` | Trade/SRE home-server networking |
| `compose.tunnel.yml` | Separate Cloudflare connector |

Commands run on the destination server. `--force` builds the current checkout and applies migrations; it does not merge a PR.
