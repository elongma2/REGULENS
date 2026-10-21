import { beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.hoisted(() => vi.fn());
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession } },
}));

import { apiFetch } from "./http";

describe("authenticated API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getSession.mockReset().mockResolvedValue({ data: { session: { access_token: "access-token" } } });
  });

  it("attaches the Supabase bearer token without exposing server secrets", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true } as Response);
    await apiFetch("/cases", { headers: { "Content-Type": "application/json" } });
    expect(fetchMock).toHaveBeenCalledWith("/api/cases", expect.objectContaining({
      headers: { Authorization: "Bearer access-token", "Content-Type": "application/json" },
    }));
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("SUPABASE_SERVICE_ROLE_KEY");
  });

  it("retries a transient read failure once", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ ok: true, status: 200 } as Response);

    const response = await apiFetch("/cases");

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry writes because they may already have been committed", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(apiFetch("/cases/case-1/review-notes", { method: "POST" })).rejects.toThrow("Failed to fetch");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
