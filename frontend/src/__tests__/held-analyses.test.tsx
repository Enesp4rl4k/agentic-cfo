/**
 * Held analyses: finished runs that wait for a person. Found by the pilot-flow browser test (3b, 3d):
 * no screen could approve one, and the setup page read "no balance column" into a file that was fine.
 * The approvals screen lists them with why they were held, approves or rejects (a writer's action),
 * and counts every kind of decision waiting in one place.
 */
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSession } from "next-auth/react";
import { ledgerSpies, planChangeSpies, renderWithQuery } from "./dashboard-mocks";

const { held, cfo, rows, agents, packet } = vi.hoisted(() => ({
  held: { listHeldAnalyses: vi.fn(), rejectAnalysis: vi.fn() },
  cfo: { approveJob: vi.fn() },
  rows: { listHeldRows: vi.fn() },
  agents: { getReviewQueue: vi.fn(), approveHeldJob: vi.fn(), rejectHeldJob: vi.fn() },
  packet: { getDecisionPacket: vi.fn() },
}));
vi.mock("@/lib/api/heldAnalyses", () => held);
vi.mock("@/lib/api/cfo", () => cfo);
vi.mock("@/lib/api/heldRows", () => rows);
vi.mock("@/lib/api/agentReview", () => agents);
vi.mock("@/lib/api/decisionPacket", () => packet);
vi.mock("@/lib/api/ledger", async () => (await import("./dashboard-mocks")).ledgerModule);
vi.mock("@/lib/api/planChanges", async () => (await import("./dashboard-mocks")).planChangesModule);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

import OnayPage from "@/app/(dashboard)/onay/page";
import { HeldAnalysesSection } from "@/components/held-analyses/HeldAnalysesSection";
import { reasonText } from "@/components/held-analyses/HeldReasons";
import { getMessages } from "@/lib/i18n";

const copy = getMessages("tr").heldAnalysis;

const analysis = (over: Record<string, unknown> = {}) => ({
  id: "job-1",
  filename: "banka-ekstresi.csv",
  min_confidence: 0.83,
  reasons: [{ code: "weakest_step", step: "forecast", detail: "baz runway=1 ay", confidence: 0.83 }],
  proves_balance: true,
  created_at: null,
  ...over,
});

function actAs(role: string) {
  vi.mocked(useSession).mockReturnValue({
    data: { user: { id: "u1", email: "a@b.c", role, orgId: "org1" }, accessToken: "tok" },
    status: "authenticated",
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  actAs("owner");
  held.listHeldAnalyses.mockResolvedValue([]);
  held.rejectAnalysis.mockResolvedValue(undefined);
  cfo.approveJob.mockResolvedValue(undefined);
  rows.listHeldRows.mockResolvedValue([]);
  agents.getReviewQueue.mockResolvedValue([]);
  packet.getDecisionPacket.mockRejectedValue(new Error("no packet"));
  ledgerSpies.getProposedSettlements.mockResolvedValue([]);
  ledgerSpies.getPossibleDuplicates.mockResolvedValue([]);
  planChangeSpies.listPlanChanges.mockResolvedValue({ changes: [], canDecide: false });
});

describe("reasons in words", () => {
  const r = copy.reasons;
  it("says the number and the threshold of a low confidence", () => {
    expect(reasonText(r, { code: "confidence_low", min_confidence: 0.62, threshold: 0.8 })).toBe(
      "Güven puanı %62; %80 altındaki sonuçlar onayla kullanılır.",
    );
  });
  it("names the weakest step with its own words, and does not invent a percentage it was not given", () => {
    expect(reasonText(r, { code: "weakest_step", step: "forecast", detail: "baz runway=1 ay", confidence: 0.83 })).toBe(
      "En zayıf halka: forecast (%83). baz runway=1 ay",
    );
    expect(reasonText(r, { code: "weakest_step", step: "forecast", detail: "x", confidence: null })).toBe("En zayıf halka: forecast. x");
  });
  it("says every row waits, with the run's own summary", () => {
    expect(reasonText(r, { code: "rows_waiting", count: 6, all_rows: true, summary: "6 kaydın para birimi bilinmiyor." })).toBe(
      "Dosyadaki 6 satırın hepsi bir kişinin kararını bekliyor. 6 kaydın para birimi bilinmiyor.",
    );
    expect(reasonText(r, { code: "rows_waiting", count: 2, all_rows: false, summary: "" })).toBe(
      "2 satır bir kişinin kararını bekliyor (toplamlara dahil değil).",
    );
  });
  it("says no reason was recorded rather than guessing one", () => {
    expect(reasonText(r, { code: "unspecified" })).toBe(r.unspecified);
    expect(reasonText(r, { code: "something_new" })).toBe(r.unspecified);
  });
});

describe("HeldAnalysesSection", () => {
  it("renders nothing when no analysis waits", async () => {
    const { container } = renderWithQuery(<HeldAnalysesSection />);
    await waitFor(() => expect(held.listHeldAnalyses).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("lists each held analysis with why it was held and what approving gives", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    renderWithQuery(<HeldAnalysesSection />);
    expect(await screen.findByText("Onayınızı bekleyen 1 analiz")).toBeInTheDocument();
    expect(screen.getByText("banka-ekstresi.csv")).toBeInTheDocument();
    expect(screen.getByText("En zayıf halka: forecast (%83). baz runway=1 ay")).toBeInTheDocument();
    expect(screen.getByText(copy.balanceProven)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.viewResults })).toHaveAttribute("href", "/pnl?job=job-1");
  });

  it("approves only after the confirmation is accepted, and the answer is recorded by the server", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.approve }));
    expect(await screen.findByText(copy.confirmTitle)).toBeInTheDocument();
    expect(cfo.approveJob).not.toHaveBeenCalled();
    held.listHeldAnalyses.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: copy.confirmApprove }));
    await waitFor(() => expect(cfo.approveJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText(copy.approved)).toBeInTheDocument();
  });

  it("rejects with the reason the person gives", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.reject }));
    await user.type(await screen.findByLabelText(copy.rejectReason), "yanlış dönem");
    held.listHeldAnalyses.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: copy.confirmReject }));
    await waitFor(() => expect(held.rejectAnalysis).toHaveBeenCalledWith("job-1", "yanlış dönem"));
    expect(await screen.findByText(copy.rejected)).toBeInTheDocument();
  });

  it("says so when the server refuses the decision", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    cfo.approveJob.mockRejectedValue(new Error("403"));
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.approve }));
    await user.click(await screen.findByRole("button", { name: copy.confirmApprove }));
    expect(await screen.findByText(copy.actionFailed)).toBeInTheDocument();
  });

  it("shows a viewer the buttons inert, with the reason, and never sends an approval", async () => {
    actAs("viewer");
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    const approve = await screen.findByRole("button", { name: copy.approve });
    expect(approve).toHaveAttribute("aria-disabled", "true");
    await user.click(approve);
    expect(screen.queryByText(copy.confirmTitle)).toBeNull();
    expect(cfo.approveJob).not.toHaveBeenCalled();
  });
});

describe("the approvals screen is the one place for everything waiting", () => {
  it("counts each kind and links to where it is answered", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    rows.listHeldRows.mockResolvedValue([{ id: "r1" }, { id: "r2" }, { id: "r3" }]);
    agents.getReviewQueue.mockResolvedValue([{ id: "a1", agent_type: "cfo", created_at: "", gate: null }]);
    renderWithQuery(<OnayPage />);
    const nav = await screen.findByRole("navigation", { name: "5 karar sizi bekliyor" });
    const link = (name: RegExp) => within(nav).getByRole("link", { name });
    await waitFor(() => expect(link(/İncelenecek kayıtlar/)).toHaveTextContent("3"));
    expect(link(/Analizler/)).toHaveAttribute("href", "#analizler");
    expect(link(/İncelenecek kayıtlar/)).toHaveAttribute("href", "/bekleyen-kayitlar");
    expect(link(/Rol sonuçları/)).toHaveAttribute("href", "#rol-sonuclari");
    // The held analysis is on this screen, with its approve button; the rows link to their own screen.
    expect(await screen.findByRole("button", { name: copy.approve })).toBeInTheDocument();
    expect(screen.getByText("İncelemenizi bekleyen 3 kayıt")).toBeInTheDocument();
  });

  it("says nothing waits only when every kind has answered and is empty", async () => {
    renderWithQuery(<OnayPage />);
    expect(await screen.findByText(getMessages("tr").onay.empty)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /karar sizi bekliyor/ })).toBeNull();
  });

  it("does not say nothing waits while a kind is still loading", async () => {
    held.listHeldAnalyses.mockReturnValue(new Promise(() => undefined));
    renderWithQuery(<OnayPage />);
    await waitFor(() => expect(ledgerSpies.getProposedSettlements).toHaveBeenCalled());
    expect(screen.queryByText(getMessages("tr").onay.empty)).toBeNull();
  });
});

describe("honesty and stale cards", () => {
  const rejectedWith = (status: number) => Object.assign(new Error("x"), { status });

  it("tells the approver the closing balance covers rows still waiting, with their count when known", async () => {
    held.listHeldAnalyses.mockResolvedValue([
      analysis({ reasons: [{ code: "rows_waiting", count: 4, all_rows: false, summary: "" }] }),
    ]);
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.approve }));
    expect(await screen.findByText(copy.confirmBalanceNoteRows.replace("{count}", "4"))).toBeInTheDocument();
  });

  it("uses the count-free wording when the payload gives no held-row count", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.approve }));
    expect(await screen.findByText(copy.confirmBalanceNote)).toBeInTheDocument();
  });

  it("refetches the list when a decision fails, and drops a card decided elsewhere (409)", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    cfo.approveJob.mockRejectedValue(rejectedWith(409));
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.approve }));
    const before = held.listHeldAnalyses.mock.calls.length;
    held.listHeldAnalyses.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: copy.confirmApprove }));
    expect(await screen.findByText(copy.alreadyDecided)).toBeInTheDocument();
    expect(held.listHeldAnalyses.mock.calls.length).toBeGreaterThan(before);
    expect(screen.queryByText("banka-ekstresi.csv")).toBeNull();
    expect(screen.queryByText(copy.actionFailed)).toBeNull();
  });

  it("keeps the error when the item is still waiting after the refetch", async () => {
    held.listHeldAnalyses.mockResolvedValue([analysis()]);
    cfo.approveJob.mockRejectedValue(rejectedWith(409));
    const user = userEvent.setup();
    renderWithQuery(<HeldAnalysesSection />);
    await user.click(await screen.findByRole("button", { name: copy.approve }));
    await user.click(await screen.findByRole("button", { name: copy.confirmApprove }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.alreadyDecided);
    expect(screen.getByText("banka-ekstresi.csv")).toBeInTheDocument();
  });
});

describe("useApproveJob refreshes everything an approval changes", () => {
  it("invalidates the held list, the waiting counts, the radar and the company view", async () => {
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const { renderHook, act } = await import("@testing-library/react");
    const { useApproveJob } = await import("@/hooks/useCFO");
    const { WAITING_KEYS } = await import("@/hooks/useWaitingCounts");
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useApproveJob(), { wrapper });
    await act(async () => { await result.current.mutateAsync("job-1"); });
    const keys = spy.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey: unknown }).queryKey));
    for (const key of [...Object.values(WAITING_KEYS), ["cash-radar"], ["ledger-summary"], ["dashboard", "job-1"], ["jobs"]]) {
      expect(keys).toContain(JSON.stringify(key));
    }
  });
});
