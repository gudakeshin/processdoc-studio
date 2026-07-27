// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the title and omits the description when not provided", () => {
    render(<EmptyState title="No runs yet" />);
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
    expect(screen.queryByText("Start one to see activity.")).not.toBeInTheDocument();
  });

  it("renders the description and action children when provided", () => {
    render(
      <EmptyState title="No runs yet" description="Start one to see activity.">
        <button type="button">New run</button>
      </EmptyState>
    );
    expect(screen.getByText("Start one to see activity.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New run" })).toBeInTheDocument();
  });
});
