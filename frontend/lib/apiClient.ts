import { extractApiErrorMessage, parseResponseBodyLoose } from "./api-error";

/**
 * Central fetch: timeout + limited retries for idempotent (GET/HEAD) requests.
 */

const DEFAULT_TIMEOUT_MS = 90_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Explicit reasons avoid Chrome/undici's noisy "signal is aborted without reason" on bare abort(). */
function abortTimeout(ms: number): DOMException {
  return new DOMException(`Request timed out after ${ms}ms`, "TimeoutError");
}

export async function apiFetch(input: string | URL, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const idempotent = method === "GET" || method === "HEAD";
  const maxAttempts = idempotent ? 3 : 1;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const parent = init.signal;
    if (parent?.aborted) {
      const r = parent.reason;
      if (r instanceof Error) throw r;
      if (r !== undefined && r !== null && r !== "") {
        throw new DOMException(String(r), "AbortError");
      }
      throw new DOMException("Request was cancelled", "AbortError");
    }

    const controller = new AbortController();
    let timeoutId: ReturnType<typeof globalThis.setTimeout> | undefined;
    if (parent) {
      parent.addEventListener(
        "abort",
        () => {
          const r = parent.reason;
          if (r instanceof Error) {
            controller.abort(r);
            return;
          }
          controller.abort(
            r !== undefined && r !== null && r !== ""
              ? new DOMException(String(r), "AbortError")
              : new DOMException("Parent request was cancelled", "AbortError"),
          );
        },
        { once: true },
      );
    }
    try {
      timeoutId = globalThis.setTimeout(() => controller.abort(abortTimeout(DEFAULT_TIMEOUT_MS)), DEFAULT_TIMEOUT_MS);
      const res = await fetch(input, { ...init, signal: controller.signal });
      if (idempotent && res.status >= 500 && attempt < maxAttempts - 1) {
        await sleep(300 * (attempt + 1));
        continue;
      }
      return res;
    } catch (err) {
      if (idempotent && attempt < maxAttempts - 1) {
        await sleep(300 * (attempt + 1));
        continue;
      }
      throw err;
    } finally {
      if (timeoutId !== undefined) globalThis.clearTimeout(timeoutId);
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
  const { data: parsed, rawText } = await parseResponseBodyLoose(res);
  if (!res.ok) {
    const hint = rawText ? ` — ${rawText.slice(0, 200)}` : "";
    throw new Error(`sse-token failed: ${res.status}${hint}`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(rawText ? rawText.slice(0, 200) : "sse-token: invalid response body");
  }
  const obj = parsed as Record<string, unknown>;
  if (typeof obj.sse_token !== "string") {
    throw new Error(extractApiErrorMessage(obj, rawText.slice(0, 200)));
  }
  return {
    sse_token: obj.sse_token,
    expires_in: typeof obj.expires_in === "number" ? obj.expires_in : Number(obj.expires_in) || 0,
  };
}
