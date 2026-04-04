import { getApiBase } from "./api";

type ApiErrorShape = {
  detail?: string | { message?: string; [k: string]: unknown };
  message?: string;
  error?: string;
};

export function extractApiErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const data = payload as ApiErrorShape;
  if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
  if (Array.isArray(data.detail)) {
    const parts = data.detail
      .map((x) => {
        if (x && typeof x === "object" && "msg" in x && typeof (x as { msg: unknown }).msg === "string") {
          return (x as { msg: string }).msg;
        }
        return String(x);
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (data.detail && typeof data.detail === "object" && typeof data.detail.message === "string" && data.detail.message.trim()) {
    return data.detail.message;
  }
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  if (typeof data.error === "string" && data.error.trim()) return data.error;
  return fallback;
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
