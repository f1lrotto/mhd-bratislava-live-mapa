# MHD naživo

Live map of the Bratislava DPB fleet and the IDS BK regional buses. `backend/` is FastAPI (Python
3.13, uv): it polls DPB every 15 s and sweeps the IDS BK map every 30 s (`mhd/idsbk.py`), logs to
Parquet, plans trips (DPB only) and serves `frontend/dist`. `frontend/` is Svelte 5 + MapLibre.

## Checks

- Backend: `cd backend && uv run pytest -q`
- Frontend: `cd frontend && npm ci && npm run check && npm run build`

CI (`.github/workflows/ci.yml`) runs both on every push to `main` and on pull requests.

## Deployment

Production is https://mhd.filiphupka.com: Railway project `mhd-nazivo`
(436464ae-e0c1-4724-a880-c1d8ba2c11c3), environment `production`
(be92e6dd-84cc-4c26-8f54-a43c178daa3b), service `web` (b263837a-c91a-478d-b9dd-8fb79e85f8a4).

- Railway builds the root `Dockerfile` on every push to `main` and deploys it once CI passes
  ("Wait for CI"). There is no registry and no deploy command: pushing to `main` is the deploy.
  A failed CI run marks the deployment SKIPPED and production keeps the previous version.
- The service runs one replica in `us-east4`. Not Amsterdam: DPB drops connections from Railway's
  `europe-west4` IPs. Keep one replica and one uvicorn worker: DPB must see a single poller.
- A volume is mounted at `/data` (`MHD_DATA_DIR`) with the logs, history and static build. The
  server runs the static build at startup (a no-op unless a feed changed; on an empty volume it
  builds everything) and the nightly build and retention at 03:30 local time (`mhd/nightly.py`), so
  nothing else is scheduled.
- Each deploy restarts the server with a few seconds of downtime (a volume can't be shared by two
  deployments). Railway's healthcheck on `/` gates it.
- DNS: `mhd` CNAME in the Cloudflare zone `filiphupka.com`, DNS only (not proxied), with a
  `_railway-verify.mhd` TXT record.
- Railway settings live in Railway, not in the repo (`railway.json` config-as-code is deprecated).
  Change service settings, variables, volumes or DNS only when the user asks.

## Shipping

1. Commit the work in logical commits, rebase onto `origin/main`, and run both checks above.
2. Push to `main` (never force-push).
3. Follow CI for the pushed commit and fix failures your change caused.
4. With the Railway tools, find the deployment for the pushed commit in the project above and follow
   it to SUCCESS (WAITING while CI runs; SKIPPED if CI failed; FAILED or CRASHED needs its build or
   deploy logs). Then check `https://mhd.filiphupka.com/api/status`: `feed.down` is false,
   `feed.polledAt` is under a minute old and `vehicles` is above zero (at night, few vehicles run).
5. Report the commit, CI result, deployment status and the live check.
