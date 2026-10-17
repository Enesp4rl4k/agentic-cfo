/**
 * U2 / DEVELOPMENT_PLAN 1.5 — hydration loading indicator.
 *
 * While the stored analysis is being fetched from CompanyContext the dashboard
 * must say so ("Son analiz yükleniyor…") instead of flashing an empty state
 * (Redis-down contexts take up to their 2s bound), and the paste form must
 * open immediately — the hint never gates the form. CMO is the pinned page;
 * the same pattern (hydrating state + HydrationHint after the header) is on
 * CEO/CTO/COO/CHRO.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { client } = vi.hoisted(() => ({
  client: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Örnek A.Ş.", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: true,
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
}));
// DomainPanel refreshes domain status on mount — out of scope here.
vi.mock("@/components/domains/DomainPanel", () => ({ DomainPanel: () => null }));

import { getMessages } from "@/lib/i18n";
import CMODashboardPage from "@/app/(dashboard)/cmo/page";

const tr = getMessages("tr");

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("CMO hydration hint (U2 / 1.5)", () => {
  it("shows the hint while context is in flight, without gating the form", async () => {
    const d = deferred<{ data: { data: null } }>();
    client.get.mockReturnValueOnce(d.promise);
    wrap(<CMODashboardPage />);

    // The hint appears for the in-flight fetch…
    expect(await screen.findByRole("status")).toHaveTextContent(
      tr.empty.hydration,
    );
    // …and the paste form is NOT delayed by it.
    expect(
      screen.getByText(tr.roleDashboards.cmo.body.csvPasteHeading),
    ).toBeInTheDocument();

    d.resolve({ data: { data: null } });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("hint disappears once the fetch settles without a stored result", async () => {
    client.get.mockResolvedValueOnce({ data: { data: null } });
    wrap(<CMODashboardPage />);
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(
      screen.getByText(tr.roleDashboards.cmo.body.csvPasteHeading),
    ).toBeInTheDocument();
  });
});
