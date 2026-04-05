import { getApiBase } from "./api";

/**
 * Read a fetch Response body once. If the body is not JSON (e.g. plain-text
 * "Internal Server Error" from a proxy or ASGI), returns data: null and rawText for messaging.
 */
export async function parseResponseBodyLoose(res: Response): Promise<{ data: unknown; rawText: string }> {
  const rawText = await res.text();
  const t = rawText.trim();
  if (!t) return { data: null, rawText: "" };
  try {
    return { data: JSON.parse(t), rawText };
  } catch {
    return { data: null, rawText: t.length > 1200 ? `${t.slice(0, 1200)}…` : t };
  }
}

type ApiErrorShape = {
  detail?: string | { message?: string; [k: string]: unknown };
  message?: string;
  error?: string;
};

/** Plain-text bodies from Next rewrites or proxies when the upstream API is down. */
export function humanizePlainUpstreamError(message: string): string {
  const t = message.trim();
  if (/^internal server error$/i.test(t)) {
    return (
      "Could not reach the API (the FastAPI backend is probably not running). " +
      "With same-origin /api in dev, start it from the repo: `cd backend && python -m uvicorn app.main:app --reload` " +
      "(default http://127.0.0.1:8000). In `frontend`, `API_PROXY_TARGET` must point at that URL."
    );
  }
  if (/^bad gateway$/i.test(t)) {
    return "Bad gateway: the Next.js dev server could not reach the API. Start the backend on port 8000.";
  }
  if (/^gateway timeout$/i.test(t) || /^504$/i.test(t)) {
    return "Gateway timeout: the API took too long to respond or is unreachable.";
  }
  if (/^service unavailable$/i.test(t)) {
    return "Service unavailable: the API may be down or still starting.";
  }
  return message;
}

export function extractApiErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return humanizePlainUpstreamError(fallback);
  const data = payload as ApiErrorShape;
  if (typeof data.detail === "string" && data.detail.trim()) return humanizePlainUpstreamError(data.detail);
  if (Array.isArray(data.detail)) {
    const parts = data.detail
      .map((x) => {
        if (x && typeof x === "object" && "msg" in x && typeof (x as { msg: unknown }).msg === "string") {
          return (x as { msg: string }).msg;
        }
        return String(x);
      })
      .filter(Boolean);
    if (parts.length) return humanizePlainUpstreamError(parts.join("; "));
  }
  if (data.detail && typeof data.detail === "object" && typeof data.detail.message === "string" && data.detail.message.trim()) {
    return humanizePlainUpstreamError(data.detail.message);
  }
  if (typeof data.message === "string" && data.message.trim()) return humanizePlainUpstreamError(data.message);
  if (typeof data.error === "string" && data.error.trim()) return humanizePlainUpstreamError(data.error);
  return humanizePlainUpstreamError(fallback);
}

export type ErrorGateKind = "plan" | "visual_qa" | "guardrail" | "network" | "other";

export function classifyErrorGate(message: string | null | undefined): {
  kind: ErrorGateKind;
  label: string;
  hint: string;
} {
  const text = String(message || "").toLowerCase();
  if (!text) {
    return { kind: "other", label: "Unknown", hint: "Open logs and retry the action." };
  }
  // Match backend plan/confirm errors only — do not use the substring "conversation" alone (it appears in "Conversation send failed").
  if (
    text.includes("plan changed") ||
    text.includes("awaiting plan edits") ||
    text.includes("no assistant plan is available") ||
    text.includes("plan still has open questions") ||
    text.includes("conversation_id does not match") ||
    text.includes("no conversation found for confirmed plan") ||
    text.includes("run creation requires latest confirmed plan") ||
    text.includes("paused plan_ready") ||
    (text.includes("plan_hash") && text.includes("confirm"))
  ) {
    return {
      kind: "plan",
      label: "Plan gate",
      hint: "Resolve open questions in chat, confirm the latest plan when ready, then retry.",
    };
  }
  if (text.includes("visual qa") || text.includes("visual_qa")) {
    return {
      kind: "visual_qa",
      label: "Visual QA gate",
      hint: "Review/fix output quality and rerun before final approval.",
    };
  }
  if (text.includes("guardrail")) {
    return {
      kind: "guardrail",
      label: "Guardrail gate",
      hint: "Address policy/compliance findings, then re-run.",
    };
  }
  if (
    text.includes("failed to fetch") ||
    text.includes("network") ||
    text.includes("timeout") ||
    text.includes("sse unavailable")
  ) {
    const base = getApiBase() || "(same-origin /api via Next.js)";
    return {
      kind: "network",
      label: "Network",
      hint: `Cannot reach the API at ${base}. Start the backend (uvicorn on port 8000). With NEXT_PUBLIC_API_URL=same-origin, ensure the proxy target is running (see frontend/.env.local and API_PROXY_TARGET). Otherwise set NEXT_PUBLIC_API_URL to the real API URL and restart next dev; development mode allows common localhost/LAN Origins via CORS.`,
    };
  }
  return {
    kind: "other",
    label: "Runtime",
    hint: "Check run status and server logs, then retry.",
  };
}
