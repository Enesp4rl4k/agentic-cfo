/**
 * Pazartesi bülteni: what the owner reads on Monday and how they answer it.
 *
 * The API is mocked with the shape backend/app/services/monday_briefing.py returns.
 * This checks the page's side of the contract: the three sentences are shown as the
 * server wrote them (the page computes nothing), a company with nothing known gets no
 * invented calm, and an answer goes to the server and is confirmed only once it is saved.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getMondayBriefing = vi.fn();
const respondToMondayBriefing = vi.fn();
vi.mock("@/lib/api/briefing", () => ({
  getMondayBriefing: (...args: unknown[]) => getMondayBriefing(...args),
  respondToMondayBriefing: (...args: unknown[]) => respondToMondayBriefing(...args),
  // The release card (BriefingRelease) has its own test; here the briefing has no e-mail.
  getBriefingDeliveries: () => Promise.resolve([]),
  releaseMondayBriefing: vi.fn(),
}));
vi.mock("@/lib/api/orgs", async () => (await import("./dashboard-mocks")).orgsModule);

// The Monday screen also shows the route and the count of waiting decisions.
const getCashRadar = vi.fn();
const getProposedSettlements = vi.fn();
const getPossibleDuplicates = vi.fn();
const listPlanChanges = vi.fn();
vi.mock("@/lib/api/ledger", () => ({
  getCashRadar: (...a: unknown[]) => getCashRadar(...a),
  getProposedSettlements: (...a: unknown[]) => getProposedSettlements(...a),
  getPossibleDuplicates: (...a: unknown[]) => getPossibleDuplicates(...a),
}));
vi.mock("@/lib/api/planChanges", () => ({
  listPlanChanges: (...a: unknown[]) => listPlanChanges(...a),
}));

vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

import { membershipSpies, membershipsFor } from "./dashboard-mocks";
import BultenPage from "@/app/(dashboard)/bulten/page";

const briefing = (over: Record<string, unknown> = {}) => ({
  briefing_id: "brief_org1_202505",
  org_id: "org1",
  week_start: "2025-02-01",
  week_end: "2025-02-07",
  starting_cash_cents: 100_000_00,
  net_change_cents: -20_000_00,
  end_balance_cents: 80_000_00,
  approaching_title: "Demir Çelik A.Ş.",
  approaching_amount_cents: 40_000_00,
  approaching_date: "2025-02-04",
  action_type: "collect",
  action_title: "Örnek Müşteri Ltd.'den tahsilatı öne çek",
  action_detail: "Vadesi 5 Şubat.",
  action_amount_cents: 20_000_00,
  sentence_radar: "Bu hafta net nakit pozisyonunuzda 20.000,00 TL azalış var; tahmini hafta sonu bakiyesi 80.000,00 TL.",
  sentence_obligation: "En yakın ödeme: Demir Çelik A.Ş., 40.000,00 TL, 4 Şubat.",
  sentence_action: "Önce şunu yapın: Örnek Müşteri Ltd.'den tahsilatı öne çekin.",
  full_text: "",
  verified: true,
  fallback_used: false,
  balance_known: true,
  has_data: true,
  balance_as_of: "2025-01-30",
  balance_age_days: 2,
  balance_stale: false,
  runway_status: "computed",
  runway_months: 4,
  runway_level: "warning",
  runway_basis: "known",
  runway_line: "Uyarı: Nakit pisti yaklaşık 4,0 ay (31 Mart 2026 ekstresindeki kasa ₺120.000,00).",
  fingerprint: "fp-seen",
  ...over,
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BultenPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  membershipSpies.getMemberships.mockResolvedValue(membershipsFor("owner"));
  getMondayBriefing.mockReset();
  respondToMondayBriefing.mockReset();
  getCashRadar.mockReset();
  getCashRadar.mockResolvedValue({ weeks: [], starting_cash_cents: null });
  getProposedSettlements.mockReset();
  getProposedSettlements.mockResolvedValue([]);
  getPossibleDuplicates.mockReset();
  getPossibleDuplicates.mockResolvedValue([]);
  listPlanChanges.mockReset();
  listPlanChanges.mockResolvedValue({ changes: [], canDecide: false });
});

describe("Pazartesi bülteni", () => {
  it("shows the three sentences exactly as the server wrote them", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    show();
    expect(await screen.findByText(/20\.000,00 TL azalış/)).toBeTruthy();
    expect(screen.getByText(/Demir Çelik A\.Ş\., 40\.000,00 TL/)).toBeTruthy();
    expect(screen.getByText(/tahsilatı öne çekin/)).toBeTruthy();
  });

  it("labels the balance with its statement's day and warns when it is old", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    const fresh = show();
    expect(await screen.findByText("30 Ocak ekstresine göre kasa")).toBeTruthy();
    expect(screen.queryByText(/gün önceki ekstreye dayanıyor/)).toBeNull();
    fresh.unmount();

    getMondayBriefing.mockResolvedValue(briefing({ balance_as_of: "2024-12-23", balance_age_days: 40, balance_stale: true }));
    show();
    expect(await screen.findByText("23 Aralık ekstresine göre kasa")).toBeTruthy();
    expect(screen.getByText("Bu bakiye 40 gün önceki ekstreye dayanıyor")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Yeni ekstre yükle" }).getAttribute("href")).toBe("/baglan");
  });

  it("names the week the briefing covers", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    show();
    expect(await screen.findByText(/2025-02-01/)).toBeTruthy();
    expect(screen.getByText(/2025-02-07/)).toBeTruthy();
  });

  it("says so when the sentence text was replaced by the deterministic template", async () => {
    getMondayBriefing.mockResolvedValue(briefing({ fallback_used: true }));
    show();
    expect(await screen.findByText(/şablon/i)).toBeTruthy();
  });

  it("offers no answer and invents no calm when nothing is known about the company", async () => {
    getMondayBriefing.mockResolvedValue(briefing({ has_data: false }));
    show();
    expect(await screen.findByText(/henüz seyir defteri yok/i)).toBeTruthy();
    expect(screen.queryByText(/20\.000,00 TL azalış/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Yaptım" })).toBeNull();
    expect(screen.getByRole("link", { name: /Verilerimi bağla/ })).toBeTruthy();
  });

  it("sends the answer with the briefing it answers and confirms once saved", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    respondToMondayBriefing.mockResolvedValue({
      decision_id: "d1",
      status: "closed",
      chosen_option_label: "Yaptım",
      briefing_id: "brief_org1_202505",
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Yaptım" }));
    await waitFor(() => expect(respondToMondayBriefing).toHaveBeenCalledTimes(1));
    expect(respondToMondayBriefing).toHaveBeenCalledWith("done", "2025-02-01", "fp-seen");
    // "Yaptım" is the owner's statement: saved as that, not as a proven payment.
    expect(await screen.findByText(/Yaptığını bildirdin/)).toBeTruthy();
    expect(screen.getByText(/banka ekstresi satırı gösterene kadar/)).toBeTruthy();
  });

  it("confirms a deferred answer plainly", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    respondToMondayBriefing.mockResolvedValue({
      decision_id: "d1", status: "open", chosen_option_label: "Ertele", briefing_id: "brief_org1_202505",
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Ertele" }));
    expect(await screen.findByText(/Yanıtınız kaydedildi/)).toBeTruthy();
  });

  it("maps the three buttons to the three answers the server knows", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    respondToMondayBriefing.mockResolvedValue({
      decision_id: "d1",
      status: "open",
      chosen_option_label: "Ertele",
      briefing_id: "brief_org1_202505",
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Ertele" }));
    await waitFor(() => expect(respondToMondayBriefing).toHaveBeenCalledWith("deferred", "2025-02-01", "fp-seen"));
  });

  it("does not claim the answer was saved when the server refused it", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    // The API client rejects with an Error carrying the server's `detail` and the status.
    respondToMondayBriefing.mockRejectedValue(
      Object.assign(new Error("Bu bülten için kayıt açılamıyor: şirketin tamamlanmış bir analizi yok."), {
        status: 409,
      }),
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Gerek yok" }));
    expect(await screen.findByText(/tamamlanmış bir analizi yok/)).toBeTruthy();
    expect(screen.queryByText(/Yanıtınız kaydedildi/)).toBeNull();
  });

  it("reloads the briefing when it changed after the owner read it", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    respondToMondayBriefing.mockRejectedValue(
      Object.assign(new Error("Bülten siz gördükten sonra değişti (yeni veri geldi)."), { status: 409 }),
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Yaptım" }));
    expect(await screen.findByText(/gördükten sonra değişti/)).toBeTruthy();
    expect(screen.queryByText(/Yanıtınız kaydedildi/)).toBeNull();
    await waitFor(() => expect(getMondayBriefing).toHaveBeenCalledTimes(2));
  });

  it("says it could not load rather than showing an empty week", async () => {
    getMondayBriefing.mockRejectedValue(new Error("boom"));
    show();
    expect(await screen.findByText(/yüklenemedi/)).toBeTruthy();
  });

  it("makes the radar sentence the headline and shows the briefing's own figures", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    show();
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.textContent).toMatch(/20\.000,00 TL azalış/);
    expect(screen.getByText("30 Ocak ekstresine göre kasa")).toBeTruthy();
    expect(screen.getByText("Hafta sonu kasa")).toBeTruthy();
    expect(screen.getByText("En yakın ödeme")).toBeTruthy();
  });

  it("shows no balance figure when the balance is not known", async () => {
    getMondayBriefing.mockResolvedValue(briefing({ balance_known: false, starting_cash_cents: null }));
    show();
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("30 Ocak ekstresine göre kasa")).toBeNull();
    expect(screen.queryByText("Hafta sonu kasa")).toBeNull();
    expect(screen.getByText("Bu hafta net değişim")).toBeTruthy();
  });

  it("counts the decisions waiting across the lists the approvals page shows", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    getProposedSettlements.mockResolvedValue([{ id: "s1" }]);
    getPossibleDuplicates.mockResolvedValue([{ id: "d1" }]);
    listPlanChanges.mockResolvedValue({ changes: [{ id: "c1" }], canDecide: true });
    show();
    expect(await screen.findByText(/3 kalem senin kararını bekliyor/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Onay bekleyenleri incele" }).getAttribute("href")).toBe("/onay");
  });

  it("does not claim nothing waits when a list could not be read", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    getPossibleDuplicates.mockRejectedValue(new Error("down"));
    show();
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(getPossibleDuplicates).toHaveBeenCalled());
    expect(screen.queryByText(/seni bekleyen bir karar yok/)).toBeNull();
  });

  it("ends with the weekly loop, every step a link from Monday", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    show();
    const loop = await screen.findByRole("contentinfo", { name: "Haftalık döngü" });
    expect(loop.querySelectorAll("a")).toHaveLength(4);
    expect(loop.querySelector("[aria-current='page']")).toBeNull();
  });

  it("says a measured runway with its months, beside the week's answer", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    show();
    expect(await screen.findByTestId("runway-text")).toHaveProperty("textContent", expect.stringContaining("yaklaşık 4,0 ay"));
    expect(screen.getByTestId("runway-value").textContent).toBe("4 ay");
    expect(screen.queryByTestId("runway-assumed")).toBeNull();
  });

  it("puts a critical runway above everything else", async () => {
    getMondayBriefing.mockResolvedValue(
      briefing({ runway_level: "critical", runway_months: 1.7, runway_line: "KRİTİK: Nakit pisti yaklaşık 1,7 ay." }),
    );
    show();
    const card = await screen.findByRole("alert");
    expect(card.textContent).toContain("KRİTİK: Nakit pisti yaklaşık 1,7 ay.");
    const heading = screen.getByRole("heading", { level: 1 });
    // The runway card precedes the week's first sentence in the page.
    expect(card.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("badges an assumed basis where the number is", async () => {
    getMondayBriefing.mockResolvedValue(briefing({ runway_basis: "assumed" }));
    show();
    expect(await screen.findByTestId("runway-assumed")).toBeTruthy();
  });

  it("says unknown, with no figure, when the balance is not known", async () => {
    getMondayBriefing.mockResolvedValue(
      briefing({
        runway_status: "no_balance",
        runway_months: null,
        runway_level: null,
        runway_basis: null,
        runway_line: "Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı.",
      }),
    );
    show();
    expect(await screen.findByText("Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı.")).toBeTruthy();
    expect(screen.getByTestId("runway-value").textContent).toBe("Bilinmiyor");
  });
});
