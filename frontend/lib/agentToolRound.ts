/**
 * Parse backend `agent_tool_round` payloads. The API sends a `trace` array
 * of { tool, is_error, output_chars, ... } per claude_tools.py — not `tool_name`.
 */

export type WebCapturePreview = {
  kind: "web_capture";
  url?: string;
  title?: string;
  snippet?: string;
  ok?: boolean;
  truncated?: boolean;
  error?: string;
};

export type ToolCallPreview = WebCapturePreview;

export type ParsedToolCallRow = {
  name: string;
  summary: string;
  preview?: ToolCallPreview;
};

function briefTraceSummary(row: Record<string, unknown>): string {
  const err = row.is_error === true;
  const chars = typeof row.output_chars === "number" ? row.output_chars : null;
  const parts: string[] = [];
  if (err) parts.push("returned error");
  if (chars != null) parts.push(`${chars} chars output`);
  return parts.join(" · ");
}

function extractPreview(row: Record<string, unknown>): ToolCallPreview | undefined {
  const raw = row.preview;
  if (!raw || typeof raw !== "object") return undefined;
  const r = raw as Record<string, unknown>;
  const kind = typeof r.kind === "string" ? r.kind : "";
  if (kind === "web_capture") {
    return {
      kind: "web_capture",
      url: typeof r.url === "string" ? r.url : undefined,
      title: typeof r.title === "string" ? r.title : undefined,
      snippet: typeof r.snippet === "string" ? r.snippet : undefined,
      ok: typeof r.ok === "boolean" ? r.ok : undefined,
      truncated: typeof r.truncated === "boolean" ? r.truncated : undefined,
      error: typeof r.error === "string" ? r.error : undefined,
    };
  }
  return undefined;
}

/**
 * Expands one agent_tool_round payload into display rows (one per tool_use in the round).
 */
export function toolCallsFromAgentRoundPayload(
  p: Record<string, unknown> | null | undefined
): ParsedToolCallRow[] {
  if (!p) return [];

  if (typeof p.tool_name === "string" && p.tool_name.trim()) {
    return [
      {
        name: p.tool_name.trim(),
        summary:
          typeof p.result_summary === "string" && p.result_summary.trim()
            ? p.result_summary.trim()
            : "",
      },
    ];
  }

  const out: ParsedToolCallRow[] = [];
  const trace = Array.isArray(p.trace) ? p.trace : [];
  for (const row of trace) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const tool = typeof r.tool === "string" ? r.tool.trim() : "";
    if (!tool) continue;
    const summary = briefTraceSummary(r);
    const preview = extractPreview(r);
    out.push({ name: tool, summary, preview });
  }

  if (out.length === 0 && Array.isArray(p.tool_calls)) {
    for (const row of p.tool_calls) {
      if (typeof row === "string" && row.trim()) {
        out.push({ name: row.trim(), summary: "" });
      } else if (row && typeof row === "object") {
        const r = row as Record<string, unknown>;
        const n =
          typeof r.name === "string"
            ? r.name
            : typeof r.tool === "string"
              ? r.tool
              : "";
        if (n.trim()) out.push({ name: n.trim(), summary: "" });
      }
    }
  }

  return out;
}
