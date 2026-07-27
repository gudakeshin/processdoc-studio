// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SystemBanner } from "./SystemBanner";

describe("SystemBanner", () => {
  it("renders an assertive alert for errors with title, detail, and action", () => {
    const onClick = vi.fn();
    render(
      <SystemBanner
        type="error"
        title="Plan blocked"
        detail="Budget exceeded"
        action={{ label: "Re-run preflight", onClick }}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
    expect(screen.getByText("Plan blocked")).toBeInTheDocument();
    expect(screen.getByText("Budget exceeded")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-run preflight" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("uses a polite alert for info and dismisses itself on dismiss", () => {
    const onDismiss = vi.fn();
    render(<SystemBanner type="info" title="Polling mode" onDismiss={onDismiss} />);
    expect(screen.getByRole("alert")).toHaveAttribute("aria-live", "polite");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss message" }));
    expect(onDismiss).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("hides the dismiss control when not dismissible", () => {
    render(<SystemBanner type="warn" title="Heads up" dismissible={false} />);
    expect(screen.queryByRole("button", { name: "Dismiss message" })).not.toBeInTheDocument();
  });
});
