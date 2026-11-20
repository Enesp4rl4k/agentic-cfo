/**
 * One-tap approvals: the same decisions as /onay, one card at a time, for a phone.
 *
 * A tap sends the choice and the next card opens only once the server accepted it; a refusal keeps
 * the card. "Not sure" leaves a decision for the desk and the end screen says how many. A plan change
 * is a card only for someone who may decide it. `?tek=1` (the link a notification carries) opens it.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

const listPlanChanges = vi.fn();
const decidePlanChange = vi.fn();
vi.mock("@/lib/api/planChanges", () => ({
  listPlanChanges: (...a: unknown[]) => listPlanChanges(...a),
  decidePlanChange: (...a: unknown[]) => decidePlanChange(...a),
  withdrawPlanChange: vi.fn(),
}));

let tekParam: string | null = null;
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: (k: string) => (k === "tek" ? tekParam : null) }),
  usePathname: () => "/onay",
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
const duplicate = { id: "d1", transaction_date: "2026-11-02T00:00:00", amount_cents: 18_600_00, direction: "out", description: "Kira Kasım" };
const proposal = {
  id: "c1", open_item_id: "p1", counterparty: "Ana Tedarikçi", description: null, amount_cents: 120_000_00,
  from_date: "2026-12-01", to_date: "2026-12-29", status: "pending", requested_by: "9",
  requested_at: "2026-11-20T10:00:00Z", request_note: null, decided_by: null, decided_at: null, decision_note: null,
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OnayPage />
    </QueryClientProvider>,
  );
}

// Braces: a function returned from beforeEach is run as its teardown.
beforeEach(() => {
  tekParam = null;
  for (const fn of [getProposedSettlements, getPossibleDuplicates, resolveSettlement, resolveDuplicate, listPlanChanges, decidePlanChange]) {
    fn.mockReset();
  }
  getProposedSettlements.mockResolvedValue([settlement]);
  getPossibleDuplicates.mockResolvedValue([duplicate]);
  listPlanChanges.mockResolvedValue({ changes: [], canDecide: false });
  resolveSettlement.mockResolvedValue(undefined);
  resolveDuplicate.mockResolvedValue(undefined);
  decidePlanChange.mockResolvedValue({});
});

describe("Onay: one tap at a time", () => {
  it("opens the queue from the list and walks the cards in order", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Tek dokunuşla karar ver" }));
    expect(screen.getByText("KARAR 1 / 2")).toBeInTheDocument();
    expect(screen.getByText(/Gelen havale 4410 → Yıldız Tekstil/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Evet, bu fatura" }));
    await waitFor(() => expect(resolveSettlement).toHaveBeenCalledWith("m1", "confirm"));
    expect(await screen.findByText("KARAR 2 / 2")).toBeInTheDocument();
    expect(screen.getByText("Kira Kasım")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Aynı ödeme" }));
    await waitFor(() => expect(resolveDuplicate).toHaveBeenCalledWith("d1", "exclude"));
    expect(await screen.findByText("Bütün kararlar verildi")).toBeInTheDocument();
  });

  it("keeps the card when the server refuses, and says so", async () => {
    resolveSettlement.mockRejectedValue(new Error("no"));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Tek dokunuşla karar ver" }));
    await user.click(screen.getByRole("button", { name: "Evet, bu fatura" }));
    expect(await screen.findByText("Kararın kaydedilemedi. Tekrar dene.")).toBeInTheDocument();
    expect(screen.getByText("KARAR 1 / 2")).toBeInTheDocument();
  });

  it("leaves a decision for the desk and counts it at the end", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Tek dokunuşla karar ver" }));
    await user.click(screen.getByRole("button", { name: "Emin değilim, masada bakarım" }));
    await user.click(screen.getByRole("button", { name: "Emin değilim, masada bakarım" }));
    expect(await screen.findByText("2 karar masaya kaldı")).toBeInTheDocument();
    expect(resolveSettlement).not.toHaveBeenCalled();
    expect(resolveDuplicate).not.toHaveBeenCalled();
  });

  it("offers a plan change only to someone who may decide it", async () => {
    listPlanChanges.mockResolvedValue({ changes: [proposal], canDecide: true });
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Tek dokunuşla karar ver" }));
    expect(screen.getByText("2026-12-01 → 2026-12-29")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(decidePlanChange).toHaveBeenCalledWith("c1", "approve"));
  });

  it("does not put a plan change in the queue for someone who may not decide it", async () => {
    listPlanChanges.mockResolvedValue({ changes: [proposal], canDecide: false });
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    show();
    await screen.findByText(/sahip ya da yönetici onaylayabilir/);
    expect(screen.queryByRole("button", { name: "Tek dokunuşla karar ver" })).toBeNull();
  });

  it("opens straight into the queue from a notification link", async () => {
    tekParam = "1";
    show();
    expect(await screen.findByText("KARAR 1 / 2")).toBeInTheDocument();
  });
});
