// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TodoTask } from "@/hooks/useTodoChecklistState";
import { TodoItem } from "./TodoItem";

function task(overrides: Partial<TodoTask> = {}): TodoTask {
  return { id: "t1", title: "Assemble context", status: "queued", phase: "observe", ...overrides };
}

describe("TodoItem", () => {
  it("labels the row with its title and status, and shows Skip for in-flight work", () => {
    render(<TodoItem task={task({ status: "in_progress" })} />);
    expect(screen.getByRole("listitem")).toHaveAttribute(
      "aria-label",
      "Assemble context — in progress"
    );
    expect(screen.getByRole("button", { name: "Skip task: Assemble context" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
  });

  it("surfaces Retry only on failure and forwards the action", () => {
    const onAction = vi.fn();
    render(<TodoItem task={task({ status: "failed" })} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry task: Assemble context" }));
    expect(onAction).toHaveBeenCalledWith("t1", "retry");
  });

  it("surfaces Approve only when blocked and hides actions once completed", () => {
    const onAction = vi.fn();
    const { rerender } = render(<TodoItem task={task({ status: "blocked" })} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve task: Assemble context" }));
    expect(onAction).toHaveBeenCalledWith("t1", "approve");

    rerender(<TodoItem task={task({ status: "completed" })} onAction={onAction} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
