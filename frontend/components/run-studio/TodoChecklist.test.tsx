// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TodoChecklistState } from "@/hooks/useTodoChecklistState";
import { TodoChecklist } from "./TodoChecklist";

function checklist(): TodoChecklistState {
  const tasks = [
    { id: "out:docx", title: "Draft DOCX", status: "completed" as const, phase: "act" as const },
    { id: "out:pptx", title: "Draft deck", status: "in_progress" as const, phase: "act" as const },
  ];
  return {
    tasks,
    phases: [
      { phase: "observe", tasks: [], completed: 0, total: 0 },
      { phase: "plan", tasks: [], completed: 0, total: 0 },
      { phase: "act", tasks, completed: 1, total: 2 },
      { phase: "report", tasks: [], completed: 0, total: 0 },
    ],
    progress: { total: 2, completed: 1, inProgress: 1, blocked: 0, percentComplete: 50 },
  };
}

describe("TodoChecklist", () => {
  it("renders overall progress and expands phase tasks by default", () => {
    render(<TodoChecklist checklist={checklist()} />);
    expect(screen.getByText("1/2 (50%)")).toBeInTheDocument();
    expect(screen.getByText("Draft DOCX")).toBeInTheDocument();
    expect(screen.getByText("Draft deck")).toBeInTheDocument();
  });

  it("collapses a phase when its header is toggled", () => {
    render(<TodoChecklist checklist={checklist()} />);
    fireEvent.click(screen.getByRole("button", { name: /act/i }));
    expect(screen.queryByText("Draft DOCX")).not.toBeInTheDocument();
  });
});
