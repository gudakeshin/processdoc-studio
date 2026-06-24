// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScoreGauge } from "./ScoreGauge";

describe("ScoreGauge", () => {
  it("renders the score as a clamped percentage on the progressbar", () => {
    render(<ScoreGauge score={0.82} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "82");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(screen.getByText("QA score: 82%")).toBeInTheDocument();
  });

  it("clamps out-of-range scores into 0..100", () => {
    const { rerender } = render(<ScoreGauge score={1.5} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    rerender(<ScoreGauge score={-0.3} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});
