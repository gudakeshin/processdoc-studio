import { describe, expect, it } from "vitest";

import { showGuidedDecisionsSection } from "./instructionChatCowork";

describe("instructionChatCowork", () => {
  it("hides guided decisions when showGuidedDecisions is false", () => {
    expect(showGuidedDecisionsSection(false, 3)).toBe(false);
  });

  it("hides when no prompts", () => {
    expect(showGuidedDecisionsSection(true, 0)).toBe(false);
  });

  it("shows when enabled and prompts exist", () => {
    expect(showGuidedDecisionsSection(true, 2)).toBe(true);
  });
});
