/**
 * Contract checks for unified studio post-confirm flow (no React runtime).
 * See plan: unified studio — chat handoff + approve + queue ops docs.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const _dir = dirname(fileURLToPath(import.meta.url));

describe("unified studio post-confirm", () => {
  it("useRunStudio refetches conversation when rid becomes non-empty", () => {
    const src = readFileSync(join(_dir, "../hooks/useRunStudio.tsx"), "utf8");
    expect(src).toContain("When a run is selected");
    expect(src).toContain("!rid) return");
    expect(src).toContain("void refreshChatFromServer()");
    expect(src).toMatch(/\[token, pid, rid, refreshChatFromServer\]/);
  });

  it("ProjectStudioUnified shows ApprovalBanner driven by useRunStudio's approve flow", () => {
    const studioSrc = readFileSync(join(_dir, "../components/project-studio/ProjectStudioUnified.tsx"), "utf8");
    expect(studioSrc).toContain("<ApprovalBanner state={studio.approvalBannerState}");
    const hookSrc = readFileSync(join(_dir, "../hooks/useRunStudio.tsx"), "utf8");
    expect(hookSrc).toContain("/approve");
    expect(hookSrc).toContain("onApprove: approvePlan");
  });

  it(".env.example documents redis queue worker / embedded consumer", () => {
    const repoRoot = join(_dir, "../..");
    const ex = readFileSync(join(repoRoot, ".env.example"), "utf8");
    expect(ex).toContain("RUN_QUEUE_EMBED_REDIS_CONSUMER");
    expect(ex).toContain("run_execution_worker");
    expect(ex).toContain("execution_enqueued");
  });
});
