import assert from "node:assert/strict";
import { describe, it } from "vitest";

import {
  extractRunTodoRowsFromEventData,
  mergeRunEventEnvelope,
  runTodosFromEvents,
} from "@/lib/runTodosFromEvents";

describe("runTodosFromEvents", () => {
  it("reads todos from strict run-events-v1 envelope on run_todo_snapshot line", () => {
    const envelope = {
      schema_version: "run-events-v1",
      event_type: "run_todo_snapshot",
      payload: {
        todos: [
          { id: "context", label: "Assemble", status: "done" },
          { id: "plan", label: "Plan", status: "pending" },
        ],
      },
    };
    const lines = [`run_todo_snapshot: ${JSON.stringify(envelope)}`];
    const rows = runTodosFromEvents(lines);
    assert.equal(rows.length, 2);
    assert.equal(rows[0]?.id, "context");
    assert.equal(rows[1]?.id, "plan");
  });

  it("supports legacy flat todos on root", () => {
    const flat = {
      todos: [{ id: "qa", label: "QA", status: "pending" }],
    };
    const rows = runTodosFromEvents([`run_todo_snapshot: ${JSON.stringify(flat)}`]);
    assert.equal(rows.length, 1);
    assert.equal(rows[0]?.id, "qa");
  });

  it("parses todo.checklist_created tasks array under payload", () => {
    const envelope = {
      payload: {
        tasks: [
          { id: "out:docx", label: "DOCX", status: "pending" },
        ],
      },
    };
    const rows = runTodosFromEvents([`todo.checklist_created: ${JSON.stringify(envelope)}`]);
    assert.equal(rows.length, 1);
    assert.equal(rows[0]?.id, "out:docx");
  });

  it("mergeRunEventEnvelope flattens nested payload", () => {
    const merged = mergeRunEventEnvelope({
      schema_version: "x",
      payload: { status: "execution_started", foo: 1 },
    });
    assert.equal(merged.status, "execution_started");
    assert.equal(merged.foo, 1);
  });

  it("extractRunTodoRowsFromEventData returns empty for invalid rows", () => {
    assert.equal(
      extractRunTodoRowsFromEventData({
        payload: { todos: [{ id: "x", label: "y" } as { id: string; label: string }] },
      }).length,
      0,
    );
  });
});
