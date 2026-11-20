/**
 * Pending approvals: the ledger's own proposals, put in front of the person.
 *
 * A bank movement that may close an invoice, and a record that looks already uploaded. The
 * page lists what the API returns, sends the person's choice, and says so when nothing waits or
 * when the list cannot be read. It never decides for them.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getProposedSettlements = vi.fn();
const getPossibleDuplicates = vi.fn();
const resolveSettlement = vi.fn();
const resolveDuplicate = vi.fn();

vi.mock("@/lib/api/ledger", () => ({
  getProposedSettlements: (...a: unknown[]) => getProposedSettlements(...a),
  getPossibleDuplicates: (...a: unknown[]) => getPossibleDuplicates(...a),
  resolveSettlement: (...a: unknown[]) => resolveSettlement(...a),
  resolveDuplicate: (...a: unknown[]) => resolveDuplicate(...a),
}));

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: true,
    focusMode: false,
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href, ...rest }, children),
}));

import OnayPage from "@/app/(dashboard)/onay/page";

const settlement = {
  id: "m1",
  amount_cents: 42_800_00,
  row: { id: "r1", transaction_date: "2026-11-12T00:00:00", amount_cents: 42_800_00, direction: "in", description: "Gelen havale 4410" },
  item: { counterparty: "Yıldız Tekstil", description: "Fatura A", amount_cents: 42_800_00, due_date: "2026-11-10" },
};
const duplicate = {
  id: "d1",
  transaction_date: "2026-11-02T00:00:00",
  amount_cents: 18_600_00,
  direction: "out",
  description: "Kira Kasım",
  matches: [{ id: "x", transaction_date: "2026-11-01", amount_cents: 18_600_00, direction: "out", description: "Kira Kasım (ekstre)" }],
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OnayPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const fn of [getProposedSettlements, getPossibleDuplicates, resolveSettlement, resolveDuplicate]) fn.mockReset();
  resolveSettlement.mockResolvedValue(undefined);
  resolveDuplicate.mockResolvedValue(undefined);
});

describe("Onay bekleyenler", () => {
  it("shows the movement beside the invoice it may close, with both amounts and the due date", async () => {
    getProposedSettlements.mockResolvedValue([settlement]);
    getPossibleDuplicates.mockResolvedValue([]);
    show();
    const card = within((await screen.findByText("Gelen havale 4410")).closest("li") as HTMLElement);
    expect(card.getByText("Yıldız Tekstil")).toBeInTheDocument();
    expect(card.getByText(/vade 2026-11-10/)).toBeInTheDocument();
    expect(card.getAllByText(/42\.800/).length).toBe(2);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Onay bekleyenler");
  });

  it("sends the person's choice and nothing else", async () => {
    getProposedSettlements.mockResolvedValue([settlement]);
    getPossibleDuplicates.mockResolvedValue([]);
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Evet, bu fatura" }));
    await waitFor(() => expect(resolveSettlement).toHaveBeenCalledWith("m1", "confirm"));
    await user.click(screen.getByRole("button", { name: "Hayır, ayrı para" }));
    await waitFor(() => expect(resolveSettlement).toHaveBeenCalledWith("m1", "reject"));
  });

  it("asks whether a record that looks uploaded is the same payment", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([duplicate]);
    const user = userEvent.setup();
    show();
    expect(await screen.findByText("Kira Kasım")).toBeInTheDocument();
    expect(screen.getByText(/Defterde zaten var: Kira Kasım \(ekstre\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Aynı ödeme" }));
    await waitFor(() => expect(resolveDuplicate).toHaveBeenCalledWith("d1", "exclude"));
  });

  it("says nothing waits only when both lists loaded and are empty", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    show();
    expect(await screen.findByText(/kararını bekleyen bir eşleşme/)).toBeInTheDocument();
  });

  it("does not claim an empty queue when the list failed to load", async () => {
    getProposedSettlements.mockRejectedValue(new Error("down"));
    getPossibleDuplicates.mockResolvedValue([]);
    show();
    expect(await screen.findByText("Onay bekleyenler okunamadı.")).toBeInTheDocument();
    expect(screen.queryByText(/kararını bekleyen bir eşleşme/)).toBeNull();
  });

  it("tells the person when their decision could not be saved", async () => {
    getProposedSettlements.mockResolvedValue([settlement]);
    getPossibleDuplicates.mockResolvedValue([]);
    resolveSettlement.mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Evet, bu fatura" }));
    expect(await screen.findByText("Kararın kaydedilemedi. Tekrar dene.")).toBeInTheDocument();
  });

  it("closes with the weekly loop, this being the third step", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    show();
    const loop = await screen.findByRole("contentinfo", { name: "Haftalık döngü" });
    expect(loop.querySelector("[aria-current='page']")?.textContent).toContain("DECIDE");
  });
});
