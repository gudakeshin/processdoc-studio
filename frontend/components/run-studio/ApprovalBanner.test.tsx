// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApprovalBanner } from "./ApprovalBanner";

describe("ApprovalBanner", () => {
  it("renders nothing when state is null", () => {
    const { container } = render(<ApprovalBanner state={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders hitl_gate with reason and Approve action", () => {
    render(
      <ApprovalBanner
        state={{ type: "hitl_gate", reason: "Teammate requested sign-off", onApprove: vi.fn() }}
      />
    );
    expect(screen.getByText("Approval required")).toBeInTheDocument();
    expect(screen.getByText("Teammate requested sign-off")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("renders review_ready busy state with disabled button", () => {
    render(
      <ApprovalBanner state={{ type: "review_ready", busy: true, onApprove: vi.fn() }} />
    );
    expect(screen.getByText("Outputs ready — final review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
  });

  it("renders plan_blocked with stage detail and re-run preflight action", () => {
    render(
      <ApprovalBanner
        state={{
          type: "plan_blocked",
          blockedStage: "guardrail",
          blockedCode: "GR-7",
          blockedReason: "budget exceeded",
          onResimulate: vi.fn(),
        }}
      />
    );
    expect(screen.getByText("Plan blocked by automated governance checks")).toBeInTheDocument();
    expect(screen.getByText(/Stage: guardrail/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-run preflight" })).toBeEnabled();
  });
});
