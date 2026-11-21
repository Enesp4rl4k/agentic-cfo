/**
 * The payment calendar: a scenario over the radar, never a write.
 *
 * The arithmetic is checked on numbers (a delayed payable lifts the weeks it skipped, a brought-forward
 * one lowers them, receivables are never touched, nothing moves nothing changes). The page is checked
 * as a person meets it: buttons shift a payment by a week, the lowest cash follows, reset restores the
 * base, and without a proven balance it says so instead of drawing a route.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSession } from "next-auth/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { openingCashFixture, planChangeSpies } from "./dashboard-mocks";
import { clampWeek, payables, runScenario } from "@/components/calendar/scenario";
import type { CashRadar } from "@/lib/api/ledger";

const getCashRadar = vi.fn();
vi.mock("@/lib/api/ledger", () => ({ getCashRadar: (...a: unknown[]) => getCashRadar(...a) }));

vi.mock("@/lib/api/planChanges", async () => (await import("./dashboard-mocks")).planChangesModule);
const { listPlanChanges, decidePlanChange, withdrawPlanChange, proposePlanChange } = planChangeSpies;

vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);

import TakvimPage from "@/app/(dashboard)/takvim/page";

const item = (id: string, name: string, amount: number) => ({
  id, counterparty: name, description: null, amount_cents: amount * 100, due_date: null,
  expected_date: "2026-12-01", delay_days: 0, is_overdue: false,
  basis: "known", basis_reason: "document_due_date", basis_inputs: {}, instrument: "invoice", rules_verified: null,
});

/** Four weeks: start 100k; week 2 pays 150k (the dip), week 3 collects 80k. */
function radar(over: Partial<CashRadar> = {}): CashRadar {
  const w = (n: number, close: number, extra: Record<string, unknown> = {}) => ({
    week: n, start_date: `2026-12-0${n}`, end_date: `2026-12-0${n + 1}`,
    inflow_cents: 0, outflow_cents: 0, net_cents: 0, end_balance_cents: close * 100,
    receivables: [], payables: [], ...extra,
  });
  return {
    anchor_date: "2026-12-01", starting_cash_cents: 100_000 * 100, starting_cash_as_of: "2026-12-01",
    weeks: [
      w(1, 100_000),
      w(2, -50_000, { payables: [item("p1", "Ana Tedarikçi", 150_000)], outflow_cents: 150_000 * 100 }),
      w(3, 30_000, { receivables: [item("r1", "Sadık Müşteri", 80_000)], inflow_cents: 80_000 * 100 }),
      w(4, 30_000),
    ],
    shortfall: null, overdue_receivables: [], overdue_payables_cents: 0, undated_receivables_cents: 0,
    undated_payables_cents: 0, beyond_horizon_cents: 0, other_currency_items: 0, not_included: [],
    ...over,
  } as CashRadar;
}

describe("scenario arithmetic", () => {
  it("lists only payables as movable", () => {
    expect(payables(radar()).map((p) => p.id)).toEqual(["p1"]);
  });

  it("changes nothing when nothing moves", () => {
    const r = runScenario(radar(), {});
    expect(r?.scenario).toEqual(r?.base);
  });

  it("lifts the weeks a delayed payable skipped, and only those", () => {
    const r = runScenario(radar(), { p1: 4 })!;
    // paid in week 4 instead of 2: weeks 2 and 3 keep 150k more, week 4 on is as before
    expect(r.scenario).toEqual([100_000_00, 100_000_00, 180_000_00, 30_000_00].map((v) => v));
    expect(r.lowScenario).toBe(30_000_00);
    expect(r.lowBase).toBe(-50_000_00);
  });

  it("lowers the weeks of a payable brought forward", () => {
    const r = runScenario(radar(), { p1: 1 })!;
    expect(r.scenario[0]).toBe(-50_000_00);
    expect(r.scenario[1]).toBe(-50_000_00);
    expect(r.scenario[2]).toBe(30_000_00);
  });

  it("returns nothing without a proven balance, and clamps a week to the horizon", () => {
    expect(runScenario(radar({ starting_cash_cents: null }), {})).toBeNull();
    expect(clampWeek(0, 13)).toBe(1);
    expect(clampWeek(20, 13)).toBe(13);
  });
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TakvimPage />
    </QueryClientProvider>,
  );
}

// Braces: a function returned from beforeEach is run as its teardown.
beforeEach(() => {
  getCashRadar.mockReset();
  listPlanChanges.mockReset();
  listPlanChanges.mockResolvedValue({ changes: [], canDecide: false });
  proposePlanChange.mockReset();
  decidePlanChange.mockReset();
});

describe("Ödeme takvimi: how each payment is known", () => {
  const withP = (p: Record<string, unknown>, opening?: Record<string, unknown>) =>
    radar({
      opening_cash: { ...openingCashFixture, ...opening },
      weeks: radar().weeks.map((w) => (w.week === 2 ? { ...w, payables: [{ ...item("p1", "Ana Tedarikçi", 150_000), ...p }] } : w)),
    } as Partial<CashRadar>);

  it("marks an estimated and an assumed payment with the radar's own tags, and a documented one with none", async () => {
    getCashRadar.mockResolvedValue(withP({ basis: "estimated", basis_reason: "recurring_median", basis_inputs: { months_observed: 4, median_cents: 15_000_000, day_of_month: 5 } }));
    show();
    expect(await screen.findByRole("button", { name: /Neden tahmini: Son 4 ayda/ })).toHaveTextContent("tahmini");
  });

  it("marks an assumed payment as a varsayım", async () => {
    getCashRadar.mockResolvedValue(withP({ basis: "assumed", basis_reason: "overdue_payable_placed_in_week_1", basis_inputs: { due_date: "2026-11-10" } }));
    show();
    expect(await screen.findByRole("button", { name: /Neden tahmini/ })).toHaveTextContent("varsayım");
  });

  it("shows no tag on a documented payment", async () => {
    getCashRadar.mockResolvedValue(withP({}));
    show();
    await screen.findByText("Ana Tedarikçi");
    expect(screen.queryByText("tahmini")).toBeNull();
    expect(screen.queryByText("varsayım")).toBeNull();
    expect(screen.queryByText("onaylanan plana göre")).toBeNull();
  });

  it("says an approved plan change is by the plan, not a confirmed bank date", async () => {
    getCashRadar.mockResolvedValue(withP({ basis: "assumed", basis_reason: "payment_plan_change_taken_as_date", basis_inputs: { planned_date: "2026-12-15", document_due_date: "2026-12-01" } }));
    show();
    expect(await screen.findByText("onaylanan plana göre")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Onaylanan ödeme planı değişikliği/ })).toHaveTextContent("varsayım");
  });

  it("states the balance's statement date, and warns when it is stale", async () => {
    getCashRadar.mockResolvedValue(withP({}, { as_of: "2026-11-12", age_days: 20, stale: true }));
    show();
    expect(await screen.findByText("Bu bakiye 20 gün önceki ekstreye dayanıyor")).toBeInTheDocument();
    expect(screen.getByText("12 Kasım ekstresine göre kasa")).toBeInTheDocument();
  });

  it("does not warn about a fresh balance", async () => {
    getCashRadar.mockResolvedValue(withP({}));
    show();
    await screen.findByText("Ana Tedarikçi");
    expect(screen.queryByText(/gün önceki ekstreye dayanıyor/)).toBeNull();
  });
});

describe("Ödeme takvimi", () => {
  it("shifts a payment by a week and the lowest cash follows", async () => {
    getCashRadar.mockResolvedValue(radar());
    const user = userEvent.setup();
    show();
    const lowest = await screen.findByText("Senaryoda en düşük kasa");
    await user.click(screen.getByRole("button", { name: "Ana Tedarikçi: 1 hafta ötele" }));
    await user.click(screen.getByRole("button", { name: "Ana Tedarikçi: 1 hafta ötele" }));
    // delayed two weeks to week 4: the lowest point is no longer negative
    expect((lowest.closest("div") as HTMLElement).textContent).toMatch(/30\.000/);
    expect(screen.getByText("1 ödeme taşındı")).toBeInTheDocument();
  });

  it("restores the base forecast on reset", async () => {
    getCashRadar.mockResolvedValue(radar());
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Ana Tedarikçi: 1 hafta ötele" }));
    await user.click(screen.getByRole("button", { name: "Senaryoyu sıfırla" }));
    expect(screen.queryByText("1 ödeme taşındı")).toBeNull();
    const base = screen.getByText("Asıl tahminde en düşük kasa").closest("div") as HTMLElement;
    const scenario = screen.getByText("Senaryoda en düşük kasa").closest("div") as HTMLElement;
    expect(within(scenario).getByText(/50\.000/)).toBeInTheDocument();
    expect(within(base).getByText(/50\.000/)).toBeInTheDocument();
  });

  it("keeps the edges: no earlier than week 1, no later than the last", async () => {
    getCashRadar.mockResolvedValue(radar());
    show();
    const earlier = await screen.findByRole("button", { name: "Ana Tedarikçi: 1 hafta öne al" });
    expect(earlier).not.toBeDisabled(); // it stands in week 2
  });

  it("says a proven balance is needed, and draws no route without one", async () => {
    getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    show();
    expect(await screen.findByText(/kanıtlanmış bir banka bakiyesi gerekir/)).toBeInTheDocument();
    expect(screen.queryByText("Senaryoda en düşük kasa")).toBeNull();
  });

  it("calls the radar only to read it", async () => {
    getCashRadar.mockResolvedValue(radar());
    show();
    await screen.findByText("Senaryoda en düşük kasa");
    expect(getCashRadar).toHaveBeenCalledTimes(1);
  });

  it("closes with the weekly loop, this being the second step", async () => {
    getCashRadar.mockResolvedValue(radar());
    show();
    const loop = await screen.findByRole("contentinfo", { name: "Haftalık döngü" });
    expect(loop.querySelector("[aria-current='page']")?.textContent).toContain("ORIENT");
  });
});

/** Move Ana Tedarikçi's payment a week later, then press the page's send button (its name differs by role). */
async function moveAndSend(user: ReturnType<typeof userEvent.setup>, sendLabel: string) {
  await user.click(await screen.findByRole("button", { name: "Ana Tedarikçi: 1 hafta ötele" }));
  await user.click(await screen.findByRole("button", { name: `Ana Tedarikçi: ${sendLabel}` }));
}

describe("Ödeme takvimi: from scenario to a proposal", () => {
  it("sends a moved payment for approval with the date a whole number of weeks later", async () => {
    getCashRadar.mockResolvedValue(radar());
    proposePlanChange.mockResolvedValue({ id: "c1" });
    const user = userEvent.setup();
    show();
    await moveAndSend(user, "Onaya gönder");
    // the radar expects the payment on 2026-12-01; one week later
    expect(proposePlanChange).toHaveBeenCalledWith("p1", "2026-12-08");
    expect(decidePlanChange).not.toHaveBeenCalled();
    expect(await screen.findByText(/onaya gönderildi/)).toBeInTheDocument();
  });

  it("changes the plan at once for someone who may decide", async () => {
    getCashRadar.mockResolvedValue(radar());
    listPlanChanges.mockResolvedValue({ changes: [], canDecide: true });
    proposePlanChange.mockResolvedValue({ id: "c1" });
    decidePlanChange.mockResolvedValue({ id: "c1" });
    const user = userEvent.setup();
    show();
    await moveAndSend(user, "Planı değiştir");
    expect(decidePlanChange).toHaveBeenCalledWith("c1", "approve");
    expect(await screen.findByText("Ödeme planı değişti.")).toBeInTheDocument();
  });

  it("shows the server's own sentence when it refuses", async () => {
    getCashRadar.mockResolvedValue(radar());
    proposePlanChange.mockRejectedValue({ detail: "Bu ödeme için karar bekleyen bir öneri zaten var." });
    const user = userEvent.setup();
    show();
    await moveAndSend(user, "Onaya gönder");
    expect(await screen.findByText("Bu ödeme için karar bekleyen bir öneri zaten var.")).toBeInTheDocument();
  });
});

describe("Ödeme takvimi: the accountant advises, the company proposes", () => {
  // Moving a payment is the company's commercial decision (docs/payment-plan-approval.md): the API refuses
  // smmm (PROPOSER_ROLES), so the screen does not offer her a button that can only answer 403.
  const asRole = (role: string) =>
    vi.mocked(useSession).mockReturnValue({
      data: { user: { id: "1", email: "m@x.com", role, orgId: "o1" }, accessToken: "tok" },
      status: "authenticated",
    } as unknown as ReturnType<typeof useSession>);

  it("lets the accountant try dates, but the send button is inert and says why", async () => {
    asRole("smmm");
    getCashRadar.mockResolvedValue(radar());
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Ana Tedarikçi: 1 hafta ötele" }));
    const send = await screen.findByRole("button", { name: "Ana Tedarikçi: Onaya gönder" });
    expect(send).toHaveAttribute("aria-disabled", "true");
    expect(send).toHaveAttribute("title", expect.stringMatching(/mali müşavir tavsiye eder/));
    await user.click(send);
    expect(proposePlanChange).not.toHaveBeenCalled();
    expect(screen.getAllByText(/ticari kararıdır/).length).toBeGreaterThan(0);
  });

  it.each(["owner", "admin", "cfo", "analyst"])("offers a %s the send button", async (role) => {
    asRole(role);
    getCashRadar.mockResolvedValue(radar());
    proposePlanChange.mockResolvedValue({ id: "c1" });
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Ana Tedarikçi: 1 hafta ötele" }));
    const send = await screen.findByRole("button", { name: "Ana Tedarikçi: Onaya gönder" });
    expect(send).not.toHaveAttribute("aria-disabled");
    await user.click(send);
    expect(proposePlanChange).toHaveBeenCalledTimes(1);
  });
});
