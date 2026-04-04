/**
 * Central fetch: timeout + limited retries for idempotent (GET/HEAD) requests.
 */

const DEFAULT_TIMEOUT_MS = 25_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function apiFetch(input: string | URL, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const idempotent = method === "GET" || method === "HEAD";
  const maxAttempts = idempotent ? 3 : 1;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeoutId = globalThis.setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
    const parent = init.signal;
    if (parent) {
      if (parent.aborted) controller.abort();
      else parent.addEventListener("abort", () => controller.abort(), { once: true });
    }
    try {
      const res = await fetch(input, { ...init, signal: controller.signal });
      globalThis.clearTimeout(timeoutId);
      if (idempotent && res.status >= 500 && attempt < maxAttempts - 1) {
        await sleep(300 * (attempt + 1));
        continue;
      }
      return res;
    } catch (err) {
      globalThis.clearTimeout(timeoutId);
      if (idempotent && attempt < maxAttempts - 1) {
        await sleep(300 * (attempt + 1));
        continue;
      }
      throw err;
    }
  }
  throw new Error("apiFetch: exhausted retries");
}

export type PermissionStageResult = {
  stage: string;
  allowed: boolean;
  code: string;
  reason: string;
  metadata: Record<string, unknown>;
};

export type PermissionSimulationResult = {
  project_id: string;
  allowed: boolean;
  stages: PermissionStageResult[];
};

/** Exchange access JWT for a short-lived SSE-only token (reduces long-lived JWT in query strings). */
export async function fetchSseToken(
  apiBase: string,
  accessToken: string,
  runId?: string | null,
): Promise<{ sse_token: string; expires_in: number }> {
  const res = await apiFetch(`${apiBase.replace(/\/$/, "")}/api/auth/sse-token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ run_id: runId ?? null }),
  });
  if (!res.ok) {
    throw new Error(`sse-token failed: ${res.status}`);
  }
  return res.json() as Promise<{ sse_token: string; expires_in: number }>;
}
