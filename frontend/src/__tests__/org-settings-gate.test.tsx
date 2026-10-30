/**
 * Public pages must not ask for `/org/me`.
 *
 * A locale-aware component on the login page (GuestDemoButton) made an
 * unauthenticated `/org/me` call → 401 → apiClient signs out and redirects to
 * the login page → which asked again: an endless reload loop. The org is only
 * fetched with an authenticated session.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSession } from "next-auth/react";

const { client } = vi.hoisted(() => ({ client: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));

import { useOrgSettings } from "@/hooks/useOrgSettings";

function Probe() {
  const { org, loading } = useOrgSettings();
  return <p>{loading ? "loading" : org?.name ?? "no-org"}</p>;
}

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

const AUTHED = vi.mocked(useSession).getMockImplementation() ?? (() => ({
  data: { accessToken: "tok" }, status: "authenticated",
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.mocked(useSession).mockImplementation(AUTHED as typeof useSession);
});

describe("useOrgSettings session gate", () => {
  it("never calls /org/me without a session", async () => {
    // Every render (not just the first) sees no session.
    vi.mocked(useSession).mockReturnValue({
      data: null, status: "unauthenticated", update: vi.fn(),
    } as unknown as ReturnType<typeof useSession>);

    wrap(<Probe />);

    expect(await screen.findByText("no-org")).toBeTruthy();
    expect(client.get).not.toHaveBeenCalled();
  });

  it("fetches the org once a session exists", async () => {
    client.get.mockResolvedValue({ data: { data: { org_id: "o1", name: "Örnek A.Ş." } } });

    wrap(<Probe />);

    await waitFor(() => expect(screen.getByText("Örnek A.Ş.")).toBeTruthy());
    expect(client.get).toHaveBeenCalledWith("/org/me");
  });
});
