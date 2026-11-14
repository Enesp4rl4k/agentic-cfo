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
}));

vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

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
  getMondayBriefing.mockReset();
  respondToMondayBriefing.mockReset();
});

describe("Pazartesi bülteni", () => {
  it("shows the three sentences exactly as the server wrote them", async () => {
    getMondayBriefing.mockResolvedValue(briefing());
    show();
    expect(await screen.findByText(/20\.000,00 TL azalış/)).toBeTruthy();
    expect(screen.getByText(/Demir Çelik A\.Ş\., 40\.000,00 TL/)).toBeTruthy();
    expect(screen.getByText(/tahsilatı öne çekin/)).toBeTruthy();
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
    expect(await screen.findByText(/henüz bülten yok/i)).toBeTruthy();
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
    expect(respondToMondayBriefing).toHaveBeenCalledWith("done", "2025-02-01");
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
    await waitFor(() => expect(respondToMondayBriefing).toHaveBeenCalledWith("deferred", "2025-02-01"));
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

  it("says it could not load rather than showing an empty week", async () => {
    getMondayBriefing.mockRejectedValue(new Error("boom"));
    show();
    expect(await screen.findByText(/yüklenemedi/)).toBeTruthy();
  });
});
