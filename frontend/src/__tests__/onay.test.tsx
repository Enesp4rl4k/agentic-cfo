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
import { ledgerSpies, planChangeSpies, renderWithQuery, settlementFixture as settlement } from "./dashboard-mocks";

vi.mock("@/lib/api/ledger", async () => (await import("./dashboard-mocks")).ledgerModule);
const { getProposedSettlements, getPossibleDuplicates, resolveSettlement, resolveDuplicate } = ledgerSpies;

vi.mock("@/lib/api/planChanges", async () => (await import("./dashboard-mocks")).planChangesModule);
const { listPlanChanges, decidePlanChange, withdrawPlanChange, proposePlanChange } = planChangeSpies;

vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

// The other kinds of decision the screen counts: nothing waits in them here.
vi.mock("@/lib/api/heldAnalyses", () => ({ listHeldAnalyses: async () => [], rejectAnalysis: vi.fn() }));
vi.mock("@/lib/api/heldRows", () => ({ listHeldRows: async () => [] }));
vi.mock("@/lib/api/agentReview", () => ({ getReviewQueue: async () => [], approveHeldJob: vi.fn(), rejectHeldJob: vi.fn() }));

import OnayPage from "@/app/(dashboard)/onay/page";

const duplicate = {
  id: "d1",
  transaction_date: "2026-11-02T00:00:00",
  amount_cents: 18_600_00,
  direction: "out",
  description: "Kira Kasım",
  matches: [{ id: "x", transaction_date: "2026-11-01", amount_cents: 18_600_00, direction: "out", description: "Kira Kasım (ekstre)" }],
};

const show = () => renderWithQuery(<OnayPage />);

beforeEach(() => {
  for (const fn of [getProposedSettlements, getPossibleDuplicates, resolveSettlement, resolveDuplicate]) fn.mockReset();
  listPlanChanges.mockReset();
  listPlanChanges.mockResolvedValue({ changes: [], canDecide: false });
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
    expect(await screen.findByText(/kararını bekleyen bir analiz, kayıt, eşleşme/)).toBeInTheDocument();
  });

  it("does not claim an empty queue when the list failed to load", async () => {
    getProposedSettlements.mockRejectedValue(new Error("down"));
    getPossibleDuplicates.mockResolvedValue([]);
    show();
    expect(await screen.findByText("Onay bekleyenler okunamadı.")).toBeInTheDocument();
    expect(screen.queryByText(/kararını bekleyen bir analiz, kayıt, eşleşme/)).toBeNull();
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

describe("Onay bekleyenler: payment plan change proposals", () => {
  const proposal = {
    id: "c1", open_item_id: "p1", counterparty: "Ana Tedarikçi", description: null, amount_cents: 120_000_00,
    from_date: "2026-12-01", to_date: "2026-12-29", status: "pending", requested_by: "1",
    requested_at: "2026-11-20T10:00:00Z", request_note: "tedarikçi anlaştı", decided_by: null, decided_at: null, decision_note: null,
  };

  it("lets an owner or admin approve or reject, with an optional reason", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    listPlanChanges.mockResolvedValue({ changes: [proposal], canDecide: true });
    decidePlanChange.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    expect(await screen.findByText(/2026-12-01 → 2026-12-29/)).toBeInTheDocument();
    expect(screen.getByText(/tedarikçi anlaştı/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Gerekçe (isteğe bağlı)"), "kredi vadesi");
    await user.click(screen.getByRole("button", { name: "Reddet" }));
    await waitFor(() => expect(decidePlanChange).toHaveBeenCalledWith("c1", "reject", "kredi vadesi"));
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(decidePlanChange).toHaveBeenCalledWith("c1", "approve", "kredi vadesi"));
  });

  it("asks the only decider to confirm that proposer and approver are the same person, and sends the server's sentence", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    listPlanChanges.mockResolvedValue({
      changes: [{ ...proposal, self_decision: "acknowledge" }], canDecide: true, selfDecisionAck: "Öneren ve onaylayan aynı kişi: ben.",
    });
    decidePlanChange.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
    await user.click(await screen.findByRole("button", { name: "Öneren ve onaylayan aynı kişi: onaylıyorum" }));
    await waitFor(() =>
      expect(decidePlanChange).toHaveBeenCalledWith("c1", "approve", undefined, "Öneren ve onaylayan aynı kişi: ben."));
  });

  it("does not offer approval of one's own proposal when another decider must decide, and says why", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    listPlanChanges.mockResolvedValue({
      changes: [{ ...proposal, self_decision: "blocked", self_decision_message: "Bu tutar eşiğin üstünde." }],
      canDecide: true, selfDecisionAck: "x",
    });
    show();
    expect(await screen.findByText(/başka bir sahibi ya da yöneticisi onaylamalı/)).toBeInTheDocument();
    expect(screen.getByText("Bu tutar eşiğin üstünde.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Öneren ve onaylayan aynı kişi: onaylıyorum" })).toBeNull();
    expect(screen.getByRole("button", { name: "Geri çek" })).toBeInTheDocument();
    // and it is not in the one-tap queue either: it is not theirs to decide
    expect(screen.queryByRole("button", { name: "Tek dokunuşla karar ver" })).toBeNull();
  });

  it("says so when the proposer changed the approval threshold themselves", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    listPlanChanges.mockResolvedValue({
      changes: [{ ...proposal, threshold_changed_by_proposer: true }], canDecide: true, selfDecisionAck: "x",
    });
    show();
    expect(await screen.findByText(/eşiğini yakın zamanda kendisi değiştirdi/)).toBeInTheDocument();
  });

  it("shows anyone else that the decision belongs to an owner or admin, and lets the proposer withdraw", async () => {
    getProposedSettlements.mockResolvedValue([]);
    getPossibleDuplicates.mockResolvedValue([]);
    listPlanChanges.mockResolvedValue({ changes: [proposal], canDecide: false });
    withdrawPlanChange.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    expect(await screen.findByText(/sahip ya da yönetici onaylayabilir/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Geri çek" }));
    await waitFor(() => expect(withdrawPlanChange).toHaveBeenCalledWith("c1"));
  });
});
