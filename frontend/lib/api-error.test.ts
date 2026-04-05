import { describe, expect, it } from "vitest";

import { extractApiErrorMessage, humanizePlainUpstreamError, parseResponseBodyLoose } from "./api-error";

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

  it("humanizes fallback when body is empty object", () => {
    const out = extractApiErrorMessage({}, "Internal Server Error");
    expect(out).toContain("uvicorn");
  });
});

describe("humanizePlainUpstreamError", () => {
  it("expands generic Internal Server Error", () => {
    const out = humanizePlainUpstreamError("Internal Server Error");
    expect(out).toContain("uvicorn");
    expect(out).toContain("API_PROXY_TARGET");
  });

  it("leaves app-specific messages unchanged", () => {
    expect(humanizePlainUpstreamError("Invalid credentials")).toBe("Invalid credentials");
  });
});

describe("parseResponseBodyLoose", () => {
  it("parses JSON bodies", async () => {
    const res = new Response(JSON.stringify({ ok: true }), { status: 200 });
    const { data, rawText } = await parseResponseBodyLoose(res);
    expect(data).toEqual({ ok: true });
    expect(rawText).toContain("ok");
  });

  it("returns null data and raw text for plain-text errors", async () => {
    const res = new Response("Internal Server Error", { status: 500 });
    const { data, rawText } = await parseResponseBodyLoose(res);
    expect(data).toBeNull();
    expect(rawText).toBe("Internal Server Error");
  });
});
