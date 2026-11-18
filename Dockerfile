# One image: the Svelte frontend, built in the first stage, served by the FastAPI backend, which
# also polls DPB and runs the nightly jobs and the accounts server (auth/, Node). Logs, the static
# build and the accounts database live in MHD_DATA_DIR, a persistent volume.

FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Better Auth needs Node; it uses Node's built-in SQLite, so there are no native modules.
FROM node:24-slim AS accounts
WORKDIR /app/auth
COPY auth/package.json auth/package-lock.json ./
RUN npm ci --omit=dev
COPY auth/server.js auth/profile.js auth/mail.js ./

FROM python:3.13-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# The final image gets the venv only, without uv or its download cache.
FROM python:3.13-slim
WORKDIR /app/backend
COPY --from=backend /app/backend/.venv ./.venv
COPY backend/mhd ./mhd
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY --from=accounts /usr/local/bin/node /usr/local/bin/node
COPY --from=accounts /app/auth /app/auth

ENV PATH=/app/backend/.venv/bin:$PATH PYTHONUNBUFFERED=1 MHD_DATA_DIR=/data
EXPOSE 8000
# A single worker: the poller lives in the process and DPB must see one client.
CMD ["sh", "-c", "exec uvicorn mhd.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
