import assert from "node:assert/strict";
import { describe, it } from "vitest";

import type { ParsedRunEvent } from "@/lib/runEvents";
import { reasoningTraceFromParsedEvents } from "@/lib/reasoningTraceFromEvents";

describe("reasoningTraceFromParsedEvents", () => {
  it("merges coordinator_plan and agent_tool_round in event order", () => {
    const events: ParsedRunEvent[] = [
      { eventType: "thinking.start", payload: { phase: "observe" } },
      {
        eventType: "coordinator_plan",
        payload: { thinking_excerpt: "alpha", rationale: "because" },
      },
      {
        eventType: "agent_tool_round",
        payload: {
          agent: "docx",
          round: 1,
          trace: [{ tool: "retrieve_context" }, { tool: "qa_validator" }],
        },
      },
    ];
    const trace = reasoningTraceFromParsedEvents(events);
    assert.equal(trace[0]?.kind, "thinking");
    assert.equal(trace[1]?.kind, "coordinator");
    assert.ok(String(trace[1]?.text).includes("alpha"));
    assert.equal(trace[2]?.kind, "coordinator");
    assert.equal(trace[3]?.kind, "tools");
    assert.ok(String(trace[3]?.text).includes("retrieve_context"));
  });
});
