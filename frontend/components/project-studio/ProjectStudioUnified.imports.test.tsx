// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const modules = [
  ["DocumentUploader", () => import("@/components/documents/DocumentUploader")],
  ["EmptyState", () => import("@/components/ui/EmptyState")],
  ["ZonePanelErrorBoundary", () => import("@/components/ErrorBoundary")],
  ["ToolActivityFeed", () => import("@/components/run-studio/ToolActivityFeed")],
  ["ApprovalBanner", () => import("@/components/run-studio/ApprovalBanner")],
  ["ZoneAInstruction", () => import("@/components/run-studio/ZoneAInstruction")],
  ["ZoneCLiveMonitor", () => import("@/components/run-studio/ZoneCLiveMonitor")],
  ["RunHealthPanel", () => import("@/components/run-studio/RunHealthPanel")],
  ["ActivityTodoList", () => import("@/components/activity/ActivityTodoList")],
  ["WikiQuickAccess", () => import("@/components/wiki/WikiQuickAccess")],
  ["Button", () => import("@/components/ui/Button")],
  ["ProjectStudioUnified", () => import("@/components/project-studio/ProjectStudioUnified")],
] as const;

describe("ProjectStudioUnified dependency exports", () => {
  for (const [name, loader] of modules) {
    it(`${name} is defined`, async () => {
      const mod = await loader();
      const key = name as keyof typeof mod;
      expect(mod[key]).toBeDefined();
      expect(typeof mod[key]).toBe("function");
    });
  }
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/projects/p_test",
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: "tok",
    ready: true,
    logout: vi.fn(),
    api: vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 })),
  }),
}));

beforeEach(() => {
  class MockEventSource {
    close = vi.fn();
    addEventListener = vi.fn();
    removeEventListener = vi.fn();
  }
  vi.stubGlobal("EventSource", MockEventSource);
});

describe("ProjectStudioUnified render", () => {
  it("mounts without invalid element type", async () => {
    const { ProjectStudioUnified } = await import("@/components/project-studio/ProjectStudioUnified");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    expect(() =>
      render(
        <QueryClientProvider client={qc}>
          <ProjectStudioUnified pid="p_test" initialRunId="run_abc" />
        </QueryClientProvider>
      )
    ).not.toThrow();
  });
});
