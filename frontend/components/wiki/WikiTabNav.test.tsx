// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WikiTabNav } from "./WikiTabNav";

const TABS = [
  { key: "browse", label: "Browse" },
  { key: "search", label: "Search", count: 12 },
];

describe("WikiTabNav", () => {
  it("renders a tab per entry and shows the count when present", () => {
    render(<WikiTabNav tabs={TABS} activeTab="browse" onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Browse/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Search/ })).toBeInTheDocument();
    expect(screen.getByText("(12)")).toBeInTheDocument();
  });

  it("invokes onChange with the tab key when clicked", () => {
    const onChange = vi.fn();
    render(<WikiTabNav tabs={TABS} activeTab="browse" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Search/ }));
    expect(onChange).toHaveBeenCalledWith("search");
  });
});
