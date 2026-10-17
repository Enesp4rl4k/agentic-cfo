/**
 * IS_DEMO sample fixtures — wire fidelity + honesty gates (DEMO_PLAN §D2).
 *
 * Two things must hold for the prefill-less degradation path:
 *
 * 1. Wire fidelity: each fixture goes through the SAME normalizer the live
 *    endpoints use, and must yield a populated view with no "undefined"/"NaN"
 *    anywhere — a renamed backend key fails here instead of on screen.
 * 2. Honesty: the pages show a sample ONLY behind NEXT_PUBLIC_DEMO_MODE and
 *    always with the "Örnek veri" badge; without the flag the page keeps its
 *    honest empty state, and the live "Analizi Çalıştır" path stays reachable
 *    next to the sample.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks: only what the pages touch on mount ─────────────────────────────────

// OutlookChart draws with recharts (SVG/canvas not available in jsdom).
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
  LineChart: () => React.createElement("div", null, null),
  AreaChart: () => React.createElement("div", null, null),
  BarChart: () => React.createElement("div", null, null),
  ComposedChart: () => React.createElement("div", null, null),
  Line: () => null,
  Area: () => null,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));

// The page resolves the org locale through useI18n — pin the tr-TR org copy,
// exactly like baslangic.test.tsx.
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Örnek A.Ş.", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: true,
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
}));

// Context hydration on mount: an org with no CEO result — the sample path.
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: { data: null } }),
    post: vi.fn().mockResolvedValue({ data: null }),
  },
}));

// Brief + history fetch on mount: nothing to overwrite the sample with.
vi.mock("@/lib/api/semantic", () => ({
  getDecisionBrief: vi.fn().mockResolvedValue({ brief: null }),
  getSemanticHistory: vi.fn().mockResolvedValue([]),
  rebuildSemantic: vi.fn(),
  approveDecisionBrief: vi.fn(),
  metricSimulationHref: (mid: string) => `/simulasyon/${mid}`,
}));

// The brief panel links metric chips; jsdom needs a plain anchor.
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href }, children),
}));

// ActionCenter polls pending actions on mount.
vi.mock("@/lib/api/actions", () => ({
  getPendingActions: vi.fn().mockResolvedValue([]),
  approveAction: vi.fn(),
  rejectAction: vi.fn(),
}));

// DomainDataSources lists agent jobs on mount — out of scope for these gates.
vi.mock("@/components/ceo/DomainDataSources", () => ({
  DomainDataSources: () => null,
}));

import { normalizeRiskCascadeReport } from "@/lib/risk-report";
import { normalizeCEOResult } from "@/lib/ceo-result";
import { SAMPLE_RISK_WIRE, SAMPLE_CEO_WIRE } from "@/lib/demo-samples";
import { getMessages } from "@/lib/i18n";
import RiskPage from "@/app/(dashboard)/risk/page";
import CeoPage from "@/app/(dashboard)/ceo/page";

const tr = getMessages("tr");

const wrap = (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
};

afterEach(() => {
  vi.unstubAllEnvs();
});

// ── Wire fidelity: fixtures through the live normalizers ─────────────────────

describe("demo sample wire fixtures", () => {
  it("the risk fixture passes the live normalizer with consistent counts", () => {
    const view = normalizeRiskCascadeReport(SAMPLE_RISK_WIRE);
    expect(view?.kri_posture?.posture).toBe("elevated");
    expect(view?.kri_posture?.counts).toEqual({ red: 1, amber: 2, green: 2, total: 5 });
    expect(view?.cascade_links).toHaveLength(1);
    expect(view?.total_cascades).toBe(1);
    expect(JSON.stringify(view)).not.toMatch(/undefined|NaN/);
  });

  it("the CEO fixture passes the live normalizer with a renderable brief", () => {
    const view = normalizeCEOResult(SAMPLE_CEO_WIRE);
    expect(view?.decision_brief?.headline).toContain("Nakit disiplini");
    expect(view?.cross_risks).toHaveLength(2);
    expect(view?.board_deck).toHaveLength(3);
    expect(view?.okr_status?.company_score).toBe(74);
    expect(JSON.stringify(view)).not.toMatch(/undefined|NaN/);
  });
});

// ── Honesty: the sample is labelled and demo-gated ───────────────────────────

describe("risk page sample", () => {
  it("shows the labelled sample in demo mode, live run still reachable", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    wrap(<RiskPage />);
    expect(screen.getByText(tr.csvInput.sampleData)).toBeInTheDocument();
    expect(screen.getAllByText("Nakit koşu bandı").length).toBeGreaterThan(0);
    expect(screen.getByText(tr.risk.run)).toBeInTheDocument();
    expect(screen.queryByText(tr.risk.empty.heading)).toBeNull();
  });

  it("keeps the honest empty state without the demo flag", () => {
    wrap(<RiskPage />);
    expect(screen.queryByText(tr.csvInput.sampleData)).toBeNull();
    expect(screen.getByText(tr.risk.empty.heading)).toBeInTheDocument();
  });
});

describe("CEO page sample", () => {
  it("shows the labelled sample brief in demo mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    wrap(<CeoPage />);
    expect(
      await screen.findByText(tr.csvInput.sampleData),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Nakit disiplinini korurken kârlılık iyileştirilmeli"),
    ).toBeInTheDocument();
    expect(screen.queryByText(tr.roleDashboards.ceo.body.emptyState)).toBeNull();
  });

  it("keeps the honest empty state without the demo flag", async () => {
    wrap(<CeoPage />);
    expect(await screen.findByText(tr.roleDashboards.ceo.body.emptyState)).toBeInTheDocument();
    expect(screen.queryByText(tr.csvInput.sampleData)).toBeNull();
  });
});

// ── U6 / 1.6: the main button must not fire a doomed 400 ──────────────────────
// Same render harness as above: store has no active CFO job, which is exactly
// the state where POST /ceo/analyze can only answer "Provide at least one
// input". The button is disabled and the page says what to do instead.

describe("CEO no-input guard", () => {
  it("disables the main button and explains until a CFO job exists", async () => {
    wrap(<CeoPage />);
    expect(
      await screen.findByText(tr.roleDashboards.ceo.body.noCfoInputHint),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: tr.roleDashboards.ceo.body.runAnalysis }),
    ).toBeDisabled();
  });
});
