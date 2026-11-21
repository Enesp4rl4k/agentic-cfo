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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { planChangeSpies } from "./dashboard-mocks";
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
