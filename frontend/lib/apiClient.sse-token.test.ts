import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchSseToken } from "./apiClient";

describe("fetchSseToken", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs JSON with Authorization and returns payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ sse_token: "tok", expires_in: 90 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const out = await fetchSseToken("https://api.example", "access-xyz", "run-1");

    expect(out.sse_token).toBe("tok");
    expect(out.expires_in).toBe(90);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example/api/auth/sse-token");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      Authorization: "Bearer access-xyz",
      "Content-Type": "application/json",
    });
    expect(init.body).toBe(JSON.stringify({ run_id: "run-1" }));
  });

  it("throws on non-OK response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401 }),
    );
    await expect(fetchSseToken("http://localhost", "t")).rejects.toThrow("sse-token failed: 401");
  });
});
