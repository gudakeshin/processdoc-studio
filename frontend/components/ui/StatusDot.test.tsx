// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusDot } from "./StatusDot";

describe("StatusDot", () => {
  it("derives a default screen-reader label from the status", () => {
    const { rerender } = render(<StatusDot status="ok" />);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Status: OK");
    rerender(<StatusDot status="warn" />);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Status: Warning");
    rerender(<StatusDot status="error" />);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Status: Error");
  });

  it("honors an explicit label and describedBy", () => {
    render(<StatusDot status="error" label="Run failed" describedBy="detail-1" />);
    const dot = screen.getByRole("img");
    expect(dot).toHaveAttribute("aria-label", "Run failed");
    expect(dot).toHaveAttribute("aria-describedby", "detail-1");
  });
});
