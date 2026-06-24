// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// branding-context imports useAuth from "./auth-context" — mock that exact specifier.
const mockApi = vi.fn();
vi.mock("./auth-context", () => ({
  useAuth: () => ({ api: mockApi, ready: true }),
}));

import { BrandingProvider, brandingToCssVars, useBranding, type Branding } from "./branding-context";

const SAMPLE: Branding = {
  level: "project_custom",
  primary_color: "#990011",
  palette: {
    primary: "#990011",
    complementary: "#0072B1",
    accent_light: "#FCF6F5",
    accent_dark: "#7A0010",
    neutral_light: "#AAAAAA",
    neutral_dark: "#1A1A1A",
    text_primary: "#1A1A1A",
    text_inverse: "#FFFFFF",
  },
  font_family: "Georgia",
  font_size_base: 12,
  logo_url: null,
  company_name: "Acme Corp",
  custom_footer_text: null,
  deck_theme: "",
};

function withClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function ShowCompany() {
  const b = useBranding();
  return <span data-testid="company">{b?.company_name ?? "none"}</span>;
}

describe("brandingToCssVars", () => {
  it("returns no overrides for null branding", () => {
    expect(brandingToCssVars(null)).toEqual({});
  });

  it("maps the resolved primary onto the existing brand-green tokens", () => {
    const vars = brandingToCssVars(SAMPLE) as Record<string, string>;
    expect(vars["--deloitte-green"]).toBe("#990011");
    expect(vars["--accent-green"]).toBe("#990011");
    expect(vars["--brand-primary"]).toBe("#990011");
    expect(vars["--brand-font-family"]).toBe("Georgia");
  });

  it("leaves the blue/complementary accents unbound to avoid unexpected shifts", () => {
    const vars = brandingToCssVars(SAMPLE) as Record<string, string>;
    expect(vars["--deloitte-blue"]).toBeUndefined();
    expect(vars["--accent-blue"]).toBeUndefined();
  });
});

describe("BrandingProvider", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  it("fetches the project's branding and injects it as scoped CSS vars", async () => {
    mockApi.mockResolvedValue(
      new Response(JSON.stringify(SAMPLE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    withClient(
      <BrandingProvider projectId="p1">
        <div data-testid="child" />
        <ShowCompany />
      </BrandingProvider>
    );

    await waitFor(() => expect(screen.getByTestId("company")).toHaveTextContent("Acme Corp"));
    expect(mockApi).toHaveBeenCalledWith("/api/projects/p1/branding");
    const wrapper = screen.getByTestId("child").parentElement as HTMLElement;
    expect(wrapper.style.getPropertyValue("--deloitte-green")).toBe("#990011");
    expect(wrapper.style.getPropertyValue("--accent-green")).toBe("#990011");
  });

  it("falls back to no overrides when the request fails", async () => {
    mockApi.mockResolvedValue(new Response("nope", { status: 500 }));

    withClient(
      <BrandingProvider projectId="p1">
        <div data-testid="child" />
        <ShowCompany />
      </BrandingProvider>
    );

    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(screen.getByTestId("company")).toHaveTextContent("none");
    const wrapper = screen.getByTestId("child").parentElement as HTMLElement;
    expect(wrapper.style.getPropertyValue("--deloitte-green")).toBe("");
  });
});
