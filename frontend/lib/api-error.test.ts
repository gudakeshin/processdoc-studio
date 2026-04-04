import { describe, expect, it } from "vitest";

import { extractApiErrorMessage } from "./api-error";

describe("extractApiErrorMessage", () => {
  it("reads string detail", () => {
    expect(extractApiErrorMessage({ detail: "nope" }, "fallback")).toBe("nope");
  });

  it("reads FastAPI validation array detail", () => {
    const payload = {
      detail: [{ type: "missing", loc: ["body", "name"], msg: "Field required" }],
    };
    expect(extractApiErrorMessage(payload, "fallback")).toContain("Field required");
  });
});
