import { describe, expect, it, vi } from "vitest";
import type { JWT } from "next-auth/jwt";
import { syncIdentity } from "@/lib/sessionIdentity";

// Signing up signs in before the workspace exists; the backend then makes the
// user the owner. The cookie kept "analyst" until the next login.

const stale = { userId: "u1", role: "analyst", orgId: null, accessToken: "tok", refreshToken: "r" } as JWT;

describe("syncIdentity", () => {
  it("takes the role and organisation the backend reports now", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: { role: "owner", org_id: "o1" } }) });
    const out = await syncIdentity(stale, { apiBase: "http://api.test", fetchImpl });
    expect(fetchImpl).toHaveBeenCalledWith("http://api.test/api/v1/auth/me", { headers: { Authorization: "Bearer tok" } });
    expect(out).toMatchObject({ role: "owner", orgId: "o1", accessToken: "tok", refreshToken: "r" });
  });

  it("keeps the session as it was when the backend cannot be read", async () => {
    const down = vi.fn().mockRejectedValue(new Error("offline"));
    expect(await syncIdentity(stale, { apiBase: "x", fetchImpl: down })).toBe(stale);
    const refused = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    expect(await syncIdentity(stale, { apiBase: "x", fetchImpl: refused })).toBe(stale);
  });
});
