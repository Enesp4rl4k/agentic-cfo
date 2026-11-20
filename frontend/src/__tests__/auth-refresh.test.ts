import { describe, expect, it, vi } from "vitest";
import type { JWT } from "next-auth/jwt";
import { REFRESH_FAILED, REFRESH_MARGIN_MS, freshToken, tokenExpiry } from "@/lib/authRefresh";

// The backend's access token lives 30 minutes, the session 7 days, and nothing
// called /auth/refresh: half an hour after signing in, the next request was a
// 401 and a trip to the login page.

const API = "http://api.test";

function jwtExpiringAt(ms: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "HS256" })}.${b64({ sub: "u1", exp: Math.floor(ms / 1000) })}.sig`;
}

function token(expiresAt: number, over: Partial<JWT> = {}): JWT {
  return {
    userId: "u1", role: "analyst", orgId: "o1",
    accessToken: jwtExpiringAt(expiresAt), refreshToken: "refresh-1", ...over,
  } as JWT;
}

const NOW = 1_800_000_000_000;

describe("freshToken", () => {
  it("reads a JWT's expiry", () => {
    expect(tokenExpiry(jwtExpiringAt(NOW))).toBe(NOW);
    expect(tokenExpiry("not-a-jwt")).toBeNull();
  });

  it("leaves a token with time to spare alone", async () => {
    const fetchImpl = vi.fn();
    const t = token(NOW + 10 * 60_000);
    expect(await freshToken(t, { apiBase: API, now: NOW, fetchImpl })).toBe(t);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("trades the refresh token shortly before expiry", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: { access_token: "new-access" } }) });
    const out = await freshToken(token(NOW + REFRESH_MARGIN_MS - 1), { apiBase: API, now: NOW, fetchImpl });
    expect(fetchImpl).toHaveBeenCalledWith(`${API}/api/v1/auth/refresh`, expect.objectContaining({
      method: "POST", body: JSON.stringify({ refresh_token: "refresh-1" }),
    }));
    expect(out.accessToken).toBe("new-access");
    expect(out.refreshToken).toBe("refresh-1");
    expect(out.error).toBeUndefined();
  });

  it("marks the session when the backend refuses the refresh token", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    const out = await freshToken(token(NOW - 1), { apiBase: API, now: NOW, fetchImpl });
    expect(out.error).toBe(REFRESH_FAILED);
  });

  it("marks the session when the backend cannot be reached", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("down"));
    const out = await freshToken(token(NOW - 1), { apiBase: API, now: NOW, fetchImpl });
    expect(out.error).toBe(REFRESH_FAILED);
  });

  it("marks the session when there is no refresh token to trade", async () => {
    const fetchImpl = vi.fn();
    const out = await freshToken(token(NOW - 1, { refreshToken: "" }), { apiBase: API, now: NOW, fetchImpl });
    expect(out.error).toBe(REFRESH_FAILED);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
