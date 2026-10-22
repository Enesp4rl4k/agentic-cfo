/**
 * D1 — guest demo entry (DEMO_PLAN §D1).
 *
 * The conversion path for a visitor who wants to try the product before
 * buying: POST /demo/guest → NextAuth credentials shortcut → land on
 * /upload (where QuickDemoBanner starts the sample analysis). Failures
 * must render an honest retry state, never a silent dead click.
 *
 * Mocks: next/navigation + next-auth/react (setup.ts), fetch (per-test).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { Session } from "next-auth";
import { getSession, signIn } from "next-auth/react";

const { push, refresh } = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh, replace: vi.fn() }),
  useSearchParams: () => ({ get: vi.fn().mockReturnValue(null) }),
  usePathname: () => "/",
}));

import { GuestDemoButton } from "@/components/demo/GuestDemoButton";

function okGuestResponse() {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => ({
      data: {
        access_token: "guest-access",
        refresh_token: "guest-refresh",
        user: { user_id: "u1", email: "demo-x@demo.local", role: "owner" },
      },
      error: null,
    }),
  });
}

describe("Demo — guest entry (D1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // clearAllMocks keeps implementations — re-pin the happy default so a
    // per-test override (e.g. the session-missing race) cannot leak forward.
    vi.mocked(getSession).mockResolvedValue({ accessToken: "tok" } as Session);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("mints a guest session and signs it in through the credentials shortcut", async () => {
    const fetchMock = okGuestResponse();
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(signIn).mockResolvedValue({ ok: true, error: null, status: 200, url: "/" });

    render(<GuestDemoButton>Demoyu Dene</GuestDemoButton>);
    fireEvent.click(screen.getByRole("button", { name: "Demoyu Dene" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/demo/guest"),
        expect.objectContaining({ method: "POST" })
      );
    });
    await waitFor(() => {
      expect(signIn).toHaveBeenCalledWith("credentials", {
        access_token: "guest-access",
        refresh_token: "guest-refresh",
        redirect: false,
      });
    });
    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/upload");
    });
  });

  it("shows an honest retry state when the backend refuses (demo_mode off)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Demo modu kapalı." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<GuestDemoButton>Demoyu Dene</GuestDemoButton>);
    fireEvent.click(screen.getByRole("button", { name: "Demoyu Dene" }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Başlatılamadı — tekrar deneyin" })
      ).toBeDefined();
    });
    expect(signIn).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("does not sign in when the response carries no access token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ data: {}, error: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<GuestDemoButton>Demoyu Dene</GuestDemoButton>);
    fireEvent.click(screen.getByRole("button", { name: "Demoyu Dene" }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Başlatılamadı — tekrar deneyin" })
      ).toBeDefined();
    });
    expect(signIn).not.toHaveBeenCalled();
  });

  it("does not navigate when signIn 'succeeds' but no session was established", async () => {
    // The csrf race: a late duplicate /api/auth/session response overwrites the
    // csrf cookie mid-flow → callback answers 200 with an error-less URL and no
    // session cookie. Trusting result.error alone navigates to /upload, where
    // the middleware bounces the visitor to the login page.
    const fetchMock = okGuestResponse();
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(signIn).mockResolvedValue({
      ok: true,
      error: null,
      status: 200,
      url: "/api/auth/signin?csrf=true",
    });
    // Both attempts see no session → the retry must not save it either.
    vi.mocked(getSession).mockResolvedValue(null);

    render(<GuestDemoButton>Demoyu Dene</GuestDemoButton>);
    fireEvent.click(screen.getByRole("button", { name: "Demoyu Dene" }));

    await waitFor(
      () => {
        expect(
          screen.getByRole("button", { name: "Başlatılamadı — tekrar deneyin" })
        ).toBeDefined();
      },
      { timeout: 4000 }
    );
    expect(signIn).toHaveBeenCalledTimes(2);
    expect(push).not.toHaveBeenCalled();
  });

  it("rides out the csrf race with one re-attempt and lands on /upload", async () => {
    const fetchMock = okGuestResponse();
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(signIn).mockResolvedValue({
      ok: true,
      error: null,
      status: 200,
      url: "/api/auth/signin?csrf=true",
    });
    vi.mocked(getSession)
      .mockResolvedValueOnce(null)
      .mockResolvedValue({ accessToken: "guest-access" } as Session);

    render(<GuestDemoButton>Demoyu Dene</GuestDemoButton>);
    fireEvent.click(screen.getByRole("button", { name: "Demoyu Dene" }));

    await waitFor(
      () => {
        expect(push).toHaveBeenCalledWith("/upload");
      },
      { timeout: 4000 }
    );
    expect(signIn).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledTimes(1); // the guest org is minted once
  });
});
