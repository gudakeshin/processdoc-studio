/**
 * Builds the same markdown body as backend `build_visual_qa_chat_message_body`
 * so Visual QA appears in the instruction chat even before/without DB persistence.
 */

export type VisualQaReportLike = {
  status?: string;
  summary?: string;
  findings?: unknown;
};

export function buildVisualQaChatMarkdown(report: VisualQaReportLike, runId: string): string {
  const st = String(report.status ?? "").toLowerCase() || "unknown";
  const summary = String(report.summary ?? "").trim();
  const rawFindings = report.findings;
  const findings: string[] = [];
  if (Array.isArray(rawFindings)) {
    for (const x of rawFindings.slice(0, 20)) {
      const t = String(x).trim();
      if (t) findings.push(t);
    }
  }

  const lines: string[] = [`## Visual QA — run \`${runId}\``, "", `**Status:** \`${st}\``, ""];

  if (summary) {
    lines.push(summary, "");
  }
  if (findings.length > 0) {
    lines.push("### Findings", "");
    for (const f of findings) lines.push(`- ${f}`);
  } else if (st === "fail" || st === "warn") {
    lines.push("_No structured findings were returned; see the full report artifact if needed._", "");
  } else if (st === "pass" || st === "skip") {
    lines.push("_No layout or image issues were flagged for this run._", "");
  }

  return lines.join("\n").trim();
}

export function chatIncludesVisualQaForRun(
  messages: Array<{ role: string; content: string; metadata?: { kind?: string; run_id?: string } }>,
  runId: string
): boolean {
  return messages.some((m) => {
    if (m.role !== "assistant" || m.metadata?.kind !== "visual_qa_report") return false;
    if (m.metadata?.run_id === runId) return true;
    return m.content.includes(`\`${runId}\``) || m.content.includes(runId);
  });
}
