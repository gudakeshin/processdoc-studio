// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FinancialModelWizard } from "./FinancialModelWizard";

describe("FinancialModelWizard", () => {
  it("starts on the template step", () => {
    render(<FinancialModelWizard onComplete={vi.fn()} />);
    expect(screen.getByText("Select a Template")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("advances to the assumptions step after a template is chosen", () => {
    render(<FinancialModelWizard onComplete={vi.fn()} />);
    fireEvent.click(screen.getByText("Startup"));
    // Leaving the template step reveals the Back control of the next step.
    expect(screen.queryByText("Select a Template")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });
});
