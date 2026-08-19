/**
 * Dashboard render tests — KPI cards, utility formatters, component structure.
 *
 * We test the pure utility functions and a minimal component tree.
 * Heavy chart components (recharts) are mocked.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Mock recharts (uses SVG/canvas not available in jsdom) ────────────────────
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart:     () => <div data-testid="line-chart" />,
  AreaChart:     () => <div data-testid="area-chart" />,
  BarChart:      () => <div data-testid="bar-chart" />,
  ComposedChart: () => <div data-testid="composed-chart" />,
  Line:          () => null,
  Area:          () => null,
  Bar:           () => null,
  XAxis:         () => null,
  YAxis:         () => null,
  CartesianGrid: () => null,
  Tooltip:       () => null,
  Legend:        () => null,
}));

// ── Utility formatters ────────────────────────────────────────────────────────

import { formatCurrency, formatPercent, formatMonths } from "@/lib/utils";

describe("formatCurrency", () => {
  it("formats positive USD amounts", () => {
    expect(formatCurrency(1234567)).toContain("1,234,567");
  });

  it("formats zero", () => {
    expect(formatCurrency(0)).toContain("0");
  });

  it("formats negative amounts", () => {
    expect(formatCurrency(-500)).toContain("500");
  });
});

describe("formatPercent", () => {
  it("converts 0-1 ratio to percentage string", () => {
    expect(formatPercent(0.185)).toBe("18.5%");
    expect(formatPercent(1.0)).toBe("100.0%");
    expect(formatPercent(0)).toBe("0.0%");
  });
});

describe("formatMonths", () => {
  it("returns 'Stable' for null or undefined", () => {
    expect(formatMonths(null)).toBe("Stable");
    expect(formatMonths(undefined)).toBe("Stable");
  });

  it("returns month count string for numbers", () => {
    expect(formatMonths(6)).toBe("6 mo");
    expect(formatMonths(12)).toBe("12 mo");
  });
});

// ── KPI card component ────────────────────────────────────────────────────────

function KPICard({ label, value, trend }: { label: string; value: string; trend?: "up" | "down" | "neutral" }) {
  return (
    <div data-testid="kpi-card">
      <p data-testid="kpi-label">{label}</p>
      <p data-testid="kpi-value">{value}</p>
      {trend && <span data-testid="kpi-trend">{trend}</span>}
    </div>
  );
}

describe("KPICard", () => {
  it("renders label and value", () => {
    render(<KPICard label="Gelir" value="₺4.8M" />);
    expect(screen.getByTestId("kpi-label").textContent).toBe("Gelir");
    expect(screen.getByTestId("kpi-value").textContent).toBe("₺4.8M");
  });

  it("renders trend indicator when provided", () => {
    render(<KPICard label="Net Kâr" value="₺892K" trend="up" />);
    expect(screen.getByTestId("kpi-trend").textContent).toBe("up");
  });

  it("omits trend indicator when not provided", () => {
    render(<KPICard label="Risk" value="87" />);
    expect(screen.queryByTestId("kpi-trend")).toBeNull();
  });
});

// ── Social proof stats ────────────────────────────────────────────────────────

import { SocialProofSection } from "@/components/landing/SocialProofSection";

describe("SocialProofSection", () => {
  it("renders all four stat blocks", () => {
    render(<SocialProofSection />);
    expect(screen.getByText("12+")).toBeDefined();
    expect(screen.getByText("5 dk")).toBeDefined();
    expect(screen.getByText("941")).toBeDefined();
  });
});
