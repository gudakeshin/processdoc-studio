# Production topology (500-user scale)

Use this as a baseline when moving beyond single-process SQLite + `RUN_QUEUE_BACKEND=local`.

## Data and queue

- **Postgres:** Set `DATABASE_URL` (e.g. `postgresql+psycopg://user:pass@host:5432/processdoc`). Avoid the default SQLite file for multi-writer concurrency.
- **Connection pool:** Tune via environment (see [backend/app/core/config.py](../backend/app/core/config.py)):
  - `DATABASE_POOL_SIZE` — base pool per API process (default `5`).
  - `DATABASE_MAX_OVERFLOW` — extra connections under burst (default `10`).
  - `DATABASE_POOL_PRE_PING` — `true` to drop stale connections (default).
  - Rule of thumb: `(pool_size + max_overflow) × API worker processes` should stay **below** Postgres `max_connections` minus admin/overhead.
- **Redis:** Set `REDIS_URL` for shared parse/search cache and (when enabled) run queue and SSE fan-out.
- **Run queue:** For **multiple API replicas**, set `RUN_QUEUE_BACKEND=redis` and run **separate worker processes** (see comments in `backend/app/services/run_worker.py`). The API does not run Redis-backed execution workers in-process when `redis` is selected.
- **Cache consistency:** For multi-instance APIs, set `CACHE_ALLOW_MEMORY_FALLBACK=false` so a missing Redis fails fast instead of per-node in-memory caches diverging.

## Application processes

- **Uvicorn (single replica):** Example: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4` — each worker is a separate process; align DB pool × workers with Postgres limits.
- **Gunicorn + Uvicorn workers:** Common pattern for production: `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000` — tune `-w` with CPU, pool size, and expected concurrent requests.
- **Optional:** `uvicorn ... --limit-concurrency N` to cap in-flight requests per process (interacts with long-lived SSE/WebSocket connections).

## Reverse proxy (SSE and WebSocket)

Long-lived streams need **long proxy read timeouts**. Defaults (e.g. 60s) often **close SSE** while runs are still active.

**nginx (illustrative):**

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream processdoc_api {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    # REST + SSE (EventSource): disable buffering; long read timeout
    location /api/ {
        proxy_pass http://processdoc_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # WebSockets (adjust regex to match your routes, e.g. model or draw.io)
    location ~ ^/api/.*(ws|websocket) {
        proxy_pass http://processdoc_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }
}
```

Order `location` directives so **WebSocket** paths (or a dedicated prefix) match before a broad `/api/` block if both could apply. The important knobs are **`proxy_read_timeout`**, **`proxy_buffering off`** for SSE, and **Upgrade** headers for WebSocket.

## Docker Compose

Root [docker-compose.yml](../docker-compose.yml) only starts Postgres, Redis, and optional draw.io — **not** the API. Replace default `POSTGRES_PASSWORD` for non-local deployments and inject secrets via your orchestrator.

## Related docs

- [OPERATIONS.md](OPERATIONS.md) — concurrency definitions and soak/SLO gates.
- [load/README.md](load/README.md) — load and smoke scripts.
