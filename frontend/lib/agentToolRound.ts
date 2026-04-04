/**
 * Parse backend `agent_tool_round` payloads. The API sends a `trace` array
 * of { tool, is_error, output_chars, ... } per claude_tools.py — not `tool_name`.
 */

export type ParsedToolCallRow = {
  name: string;
  summary: string;
};

function briefTraceSummary(row: Record<string, unknown>): string {
  const err = row.is_error === true;
  const chars = typeof row.output_chars === "number" ? row.output_chars : null;
  const parts: string[] = [];
  if (err) parts.push("returned error");
  if (chars != null) parts.push(`${chars} chars output`);
  return parts.join(" · ");
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
    out.push({ name: tool, summary });
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
