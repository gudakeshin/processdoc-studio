/**
 * API origin for fetch/EventSource/WebSocket.
 *
 * In **development**, the default is **same-origin** (empty string): the browser only talks to the
 * Next dev server; `next.config.js` rewrites `/api/*` → FastAPI (`API_PROXY_TARGET`, default
 * http://127.0.0.1:8000). That avoids flaky browser→localhost:8000 failures and CORS.
 *
 * Set `NEXT_PUBLIC_API_URL` to a full URL to call the API directly (e.g. remote backend).
 * Set `NEXT_PUBLIC_API_DIRECT=true` to force direct `http://localhost:8000` from the browser when needed.
 */
export function getApiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  const direct = process.env.NEXT_PUBLIC_API_DIRECT === "1" || process.env.NEXT_PUBLIC_API_DIRECT === "true";

  if (raw === "same-origin" || raw === "relative") {
    return "";
  }

  if (raw) {
    const base = raw.replace(/\/$/, "");
    if (direct) return base;
    if (process.env.NODE_ENV === "development") {
      const lower = base.toLowerCase();
      if (lower === "http://localhost:8000" || lower === "http://127.0.0.1:8000") {
        return "";
      }
    }
    return base;
  }

  if (process.env.NODE_ENV === "development") {
    return "";
  }
  return "http://localhost:8000";
}

/** WebSocket target when HTTP uses same-origin `/api` proxy — browsers connect straight to FastAPI. */
export function getWsOriginForBrowser(): string {
  const w = process.env.NEXT_PUBLIC_API_WS_ORIGIN?.trim();
  if (w) {
    if (w.startsWith("ws://") || w.startsWith("wss://")) return w.replace(/\/$/, "");
    return w.replace(/^http:/, "ws:").replace(/^https:/, "wss:").replace(/\/$/, "");
  }
  return "ws://127.0.0.1:8000";
}
