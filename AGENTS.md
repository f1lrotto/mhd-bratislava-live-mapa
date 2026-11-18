# MHD naživo

Live map of the Bratislava DPB fleet and the IDS BK regional buses. `backend/` is FastAPI (Python
3.13, uv): it polls DPB every 15 s and sweeps the IDS BK map every 30 s (`mhd/idsbk.py`), logs to
Parquet, plans trips (DPB only) and serves `frontend/dist`. `frontend/` is Svelte 5 + MapLibre.
`auth/` is the accounts server (Better Auth on Node 24, SQLite via `node:sqlite`): sign-in with an
email and a password, and the profile (favourite stations, lines and routes, and preferences such
as the UI language) in `auth/profile.js`. The profile panel is `/ucet` (the top bar's person
button). The backend starts it as a child process on 127.0.0.1
(`mhd/accounts.py`) and forwards `/api/auth/*` to it; the frontend's side is
`src/lib/profile.svelte.ts`.

## Checks

- Backend: `cd backend && uv run pytest -q`
- Frontend: `cd frontend && npm ci && npm run check && npm run build`
- Accounts: `cd auth && npm ci && npm test` (Node 24; the backend needs `auth/node_modules` and
  `node` to start it, or set `MHD_NO_ACCOUNTS=1`)

CI (`.github/workflows/ci.yml`) runs all three on every push to `main` and on pull requests.

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
- Accounts live on the same volume: `/data/accounts/auth.db` (SQLite) and `/data/accounts/secret`,
  generated on first start, which signs session cookies (a `BETTER_AUTH_SECRET` variable would
  override it; changing it signs everyone out). Losing the volume loses every account.
- Account emails (address verification, password reset; `auth/mail.js`) go through Resend when the
  service has `RESEND_API_KEY`, from `MAIL_FROM` (default `MHD naživo <ucet@mhd.filiphupka.com>`,
  so `mhd.filiphupka.com` must be a verified Resend domain: its DNS records go in Cloudflare).
  Without the key no email is sent and the app hides "forgotten password". In dev,
  `MHD_MAIL=log` logs the links instead and shows the email flows.
- The accounts server trusts only `mhd.filiphupka.com` and the service's Railway domain
  (`auth/server.js`, `allowedHosts`): they are where links in emails may lead. A dev server's host
  goes in `MHD_AUTH_HOSTS` (such as `localhost:5173`), never a wildcard.
- Passkeys belong to one host, `mhd.filiphupka.com` (they don't work on the Railway domain); a dev
  server sets its host in `MHD_PASSKEY_HOST`. Two-step sign-in (TOTP) secrets and backup codes are
  encrypted with the accounts secret, so changing it also breaks every user's two-step sign-in.
- Each deploy restarts the server with a few seconds of downtime (a volume can't be shared by two
  deployments). Railway's healthcheck on `/` gates it.
- DNS: `mhd` CNAME in the Cloudflare zone `filiphupka.com`, DNS only (not proxied), with a
  `_railway-verify.mhd` TXT record.
- Analytics and monitoring: PostHog EU, project `MHD` (355334) in the FilipHupka organization. The
  frontend (`src/lib/analytics.svelte.ts`) loads posthog-js on the production host only: cookieless
  until the visitor accepts the consent banner, nothing at all with GPC or Do Not Track. Keep the
  privacy page (`PrivacyPanel.svelte`, `/sukromie`) true to what is collected and stored.
  The server sends a `feed_heartbeat` event per source every 5 min (`mhd/heartbeat.py`, only when
  `RAILWAY_ENVIRONMENT_NAME=production`); PostHog alerts on them email when a feed goes stale.
- Railway settings live in Railway, not in the repo (`railway.json` config-as-code is deprecated).
  Change service settings, variables, volumes or DNS only when the user asks.

## Shipping

1. Commit the work in logical commits, rebase onto `origin/main`, and run the checks above.
2. Push to `main` (never force-push).
3. Follow CI for the pushed commit and fix failures your change caused.
4. With the Railway tools, find the deployment for the pushed commit in the project above and follow
   it to SUCCESS (WAITING while CI runs; SKIPPED if CI failed; FAILED or CRASHED needs its build or
   deploy logs). Then check `https://mhd.filiphupka.com/api/status`: `feed.down` is false,
   `feed.polledAt` is under a minute old and `vehicles` is above zero (at night, few vehicles run), and
   `https://mhd.filiphupka.com/api/auth/profile` answers 200 (the accounts server is up).
5. Report the commit, CI result, deployment status and the live check.
