/**
 * The cash curve and the week detail of the branded Nakit Radarı.
 *
 * The geometry is pure and checked as numbers: zero is always inside the
 * domain, the lowest week is the deepest point, a curve that never goes under
 * zero draws no tinted zone. The page side is checked as a person meets it: a
 * week opens its items, the picture says where the lowest point is, the weekly
 * loop is a strip of links with the current step marked.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { buildCurve, CURVE_HEIGHT, niceStep, polyline } from "@/components/radar/curve";

const getCashRadar = vi.fn();

vi.mock("@/lib/api/ledger", () => ({
  getCashRadar: (...args: unknown[]) => getCashRadar(...args),
  getMondayBriefing: vi.fn().mockResolvedValue(null),
  respondToBriefing: vi.fn(),
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

import NakitRadariPage from "@/app/(dashboard)/nakit-radari/page";

const item = (id: string, counterparty: string, amount: number, over: Record<string, unknown> = {}) => ({
  id,
  counterparty,
  description: null,
  amount_cents: amount * 100,
  due_date: null,
  expected_date: "2026-12-16",
  delay_days: 0,
  is_overdue: false,
  ...over,
});

const week = (n: number, close: number, over: Record<string, unknown> = {}) => ({
  week: n,
  start_date: `2026-12-${String(n).padStart(2, "0")}`,
  end_date: `2026-12-${String(n + 6).padStart(2, "0")}`,
  inflow_cents: 0,
  outflow_cents: 0,
  net_cents: 0,
  end_balance_cents: close * 100,
  receivables: [],
  payables: [],
  ...over,
});

const radar = (weeks: ReturnType<typeof week>[], over: Record<string, unknown> = {}) => ({
  anchor_date: "2026-12-01",
  starting_cash_cents: 100_000 * 100,
  starting_cash_as_of: "2026-12-01",
  weeks,
  shortfall: null,
  overdue_receivables: [],
  overdue_payables_cents: 0,
  undated_receivables_cents: 0,
  undated_payables_cents: 0,
  beyond_horizon_cents: 0,
  other_currency_items: 0,
  not_included: [],
  ...over,
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NakitRadariPage />
    </QueryClientProvider>,
  );
}

describe("curve geometry", () => {
  it("steps in 1-2-5 and survives an empty range", () => {
    expect(niceStep(300)).toBe(100);
    expect(niceStep(7)).toBe(5);
    expect(niceStep(0)).toBe(1);
  });

  it("always keeps zero inside the domain, even when every week is positive", () => {
    const g = buildCurve([500, 600, 700]);
    expect(g.zeroY).toBeGreaterThan(0);
    expect(g.zeroY).toBeLessThanOrEqual(CURVE_HEIGHT);
    expect(g.negativeHeight).toBe(0);
    expect(g.ticks.some((t) => t.value === 0)).toBe(true);
  });

  it("puts the lowest week deepest and tints the part below zero", () => {
    const g = buildCurve([612, 498, 371, 240, 96, -42, -184, -150, -34]);
    expect(g.lowIndex).toBe(6);
    const ys = g.points.map((p) => p.y);
    expect(ys.indexOf(Math.max(...ys))).toBe(6);
    expect(g.negativeHeight).toBeGreaterThan(0);
    expect(g.points[5].y).toBeGreaterThan(g.zeroY);
    expect(g.points[4].y).toBeLessThan(g.zeroY);
  });

  it("stays finite for a flat zero route and for one week", () => {
    for (const values of [[0, 0, 0], [250]]) {
      const g = buildCurve(values);
      expect(g.points.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
    }
    expect(polyline(buildCurve([1, 2]).points).split(" ")).toHaveLength(2);
  });
});

describe("Nakit Radarı: the branded route", () => {
  const weeks = [
    week(1, 100_000),
    week(2, 40_000),
    week(3, -70_000, {
      payables: [item("p1", "Ana Tedarikçi AŞ", 120_000), item("p2", "Kira", 18_000)],
      receivables: [item("r1", "Sadık Müşteri", 30_000, { is_overdue: true })],
    }),
    week(4, -10_000),
  ];

  it("says in words where the lowest point is, since the picture is not read aloud", async () => {
    getCashRadar.mockResolvedValue(radar(weeks));
    show();
    const img = await screen.findByRole("img", { name: /3\. haftada/ });
    expect(img.getAttribute("aria-label")).toContain("70.000");
  });

  it("opens the gap week first and lists its items, biggest first, overdue marked", async () => {
    getCashRadar.mockResolvedValue(
      radar(weeks, {
        shortfall: {
          week: 3, week_start: "2026-12-03", week_end: "2026-12-09", shortfall_cents: 70_000 * 100,
          driver: "x", actions: [],
        },
      }),
    );
    show();
    const detail = await screen.findByRole("region", { name: "Bu haftayı ne oluşturuyor" });
    const names = within(detail).getAllByRole("listitem").map((li) => li.textContent);
    expect(names[0]).toContain("Ana Tedarikçi AŞ");
    expect(names[1]).toContain("Kira");
    expect(within(detail).getByText(/gecikmiş/)).toBeTruthy();
  });

  it("opens another week from the table, by keyboard-reachable button", async () => {
    getCashRadar.mockResolvedValue(radar(weeks));
    const user = userEvent.setup();
    show();
    await screen.findByRole("img", { name: /3\. haftada/ });
    await user.click(screen.getByRole("button", { name: "1. haftayı göster" }));
    expect(screen.getByRole("button", { name: "1. haftayı göster" })).toHaveAttribute("aria-pressed", "true");
    const detail = screen.getByRole("region", { name: "Bu haftayı ne oluşturuyor" });
    expect(within(detail).getByText("Bu hafta için kayıtlı hareket yok.")).toBeTruthy();
  });

  it("claims no gap in its words when no balance was proven", async () => {
    // Movement without a proven balance: the radar is not empty, it just has no starting cash.
    const moving = weeks.map((w) => ({ ...w, outflow_cents: 1_00, net_cents: -1_00 }));
    getCashRadar.mockResolvedValue(radar(moving, { starting_cash_cents: null, starting_cash_as_of: null }));
    show();
    expect(await screen.findByText("En düşük birikmiş hareket")).toBeTruthy();
    expect(screen.queryByText("En düşük kasa")).toBeNull();
    expect(screen.getAllByText("Haftalık birikmiş hareket").length).toBeGreaterThan(0);
  });

  it("ends with the weekly loop: four steps, this one marked, the rest links", async () => {
    getCashRadar.mockResolvedValue(radar(weeks));
    show();
    const loop = await screen.findByRole("contentinfo", { name: "Haftalık döngü" });
    const links = within(loop).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/baglan", "/smmm-onay", "/reports"]);
    expect(loop.querySelector("[aria-current='page']")?.textContent).toContain("ORIENT");
  });
});
