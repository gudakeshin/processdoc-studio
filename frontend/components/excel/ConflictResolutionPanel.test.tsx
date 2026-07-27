// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The panel is driven by React Query hooks; mock the data layer so we can test
// its rendering / enable-disable logic without a live query client.
const h = vi.hoisted(() => ({
  conflicts: { data: [] as Record<string, unknown>[], isLoading: false },
  resolve: vi.fn(),
  reopen: vi.fn(),
}));

vi.mock("@/hooks/useModels", () => ({
  useModelConflicts: () => h.conflicts,
  useResolveModelConflict: () => ({ mutateAsync: h.resolve, isPending: false }),
  useReopenModelConflict: () => ({ mutateAsync: h.reopen, isPending: false }),
}));

import { ConflictResolutionPanel } from "./ConflictResolutionPanel";

function conflict(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    sheet: "Sheet1",
    cell_ref: "B2",
    type: "formula",
    severity: "high",
    status: "open",
    base: { value: 1 },
    local: { value: 2 },
    remote: { value: 3 },
    ...overrides,
  };
}

beforeEach(() => {
  h.conflicts = { data: [], isLoading: false };
  h.resolve.mockReset();
  h.resolve.mockResolvedValue(undefined);
  h.reopen.mockReset();
  h.reopen.mockResolvedValue(undefined);
});

describe("ConflictResolutionPanel", () => {
  it("shows an empty message when there are no conflicts", () => {
    render(<ConflictResolutionPanel projectId="p1" modelId="m1" />);
    expect(screen.getByText("No conflicts found.")).toBeInTheDocument();
  });

  it("resolves an open conflict by the chosen side and disables Reopen", () => {
    h.conflicts = { data: [conflict()], isLoading: false };
    render(<ConflictResolutionPanel projectId="p1" modelId="m1" />);

    // "Sheet1" also appears as a filter <option>, so assert on row-unique values.
    expect(screen.getByText("B2")).toBeInTheDocument();
    expect(screen.getByText("formula")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reopen" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Keep local" }));
    expect(h.resolve).toHaveBeenCalledWith({
      conflictId: "c1",
      chosen_side: "local",
      rationale: "manual resolve",
    });
  });

  it("disables the resolve actions once a conflict is resolved", () => {
    h.conflicts = { data: [conflict({ status: "resolved" })], isLoading: false };
    render(<ConflictResolutionPanel projectId="p1" modelId="m1" />);
    expect(screen.getByRole("button", { name: "Keep local" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reopen" })).toBeEnabled();
  });
});
