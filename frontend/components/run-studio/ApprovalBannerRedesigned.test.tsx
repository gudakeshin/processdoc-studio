// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApprovalBannerRedesigned } from "./ApprovalBannerRedesigned";

describe("ApprovalBannerRedesigned", () => {
  it("renders nothing when state is null", () => {
    const { container } = render(<ApprovalBannerRedesigned state={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders hitl_gate as a live status region with Approve action", () => {
    render(
      <ApprovalBannerRedesigned
        state={{ type: "hitl_gate", reason: "Mid-run approval needed", onApprove: vi.fn() }}
      />
    );
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "assertive");
    expect(screen.getByText("Approval required")).toBeInTheDocument();
    expect(screen.getByText("Mid-run approval needed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("renders review_ready busy state with spinner label and disabled button", () => {
    render(
      <ApprovalBannerRedesigned state={{ type: "review_ready", busy: true, onApprove: vi.fn() }} />
    );
    expect(screen.getByText("Outputs ready for review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
  });

  it("renders plan_blocked with re-run action disabled when no handler", () => {
    render(
      <ApprovalBannerRedesigned
        state={{ type: "plan_blocked", blockedStage: "preflight", blockedReason: "policy" }}
      />
    );
    expect(screen.getByText("Governance check failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-run preflight checks" })).toBeDisabled();
  });
});
