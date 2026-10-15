/**
 * U7 / DEVELOPMENT_PLAN 1.3 — the shared provenance badge.
 *
 * DESIGN.md: "distinguish real, estimated and benchmark data close to the
 * metric". One component carries that split for every metric card; the
 * classifier mirrors backend app/platform/provenance.py (SYNTHETIC_SOURCES)
 * so the UI and the auto-chain agree on what counts as measured. Anything
 * the wire does not describe renders nothing — a wrong calm "Gerçek" badge
 * is worse than no badge.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

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

import { getMessages } from "@/lib/i18n";
import {
  classifyDataSource,
  ProvenanceBadge,
} from "@/components/ui/provenance-badge";

const tr = getMessages("tr");

afterEach(() => {
  vi.clearAllMocks();
});

describe("classifyDataSource (wire → honesty class)", () => {
  it("maps measured and deterministic sources to real", () => {
    expect(classifyDataSource("real")).toBe("real");
    expect(classifyDataSource("manual")).toBe("real");
    expect(classifyDataSource("rule_based")).toBe("real");
  });

  it("maps extrapolations to estimated", () => {
    expect(classifyDataSource("estimated")).toBe("estimated");
    expect(classifyDataSource("derived")).toBe("estimated");
  });

  it("maps sector assumptions to benchmark", () => {
    expect(classifyDataSource("benchmark")).toBe("benchmark");
  });

  it("refuses to classify unknown or missing values", () => {
    expect(classifyDataSource("tcmb_api")).toBeNull();
    expect(classifyDataSource("")).toBeNull();
    expect(classifyDataSource(null)).toBeNull();
    expect(classifyDataSource(undefined)).toBeNull();
  });

  it("is case-insensitive on the wire value", () => {
    expect(classifyDataSource("Estimated")).toBe("estimated");
  });
});

describe("ProvenanceBadge", () => {
  it("renders the real label with a reachable explanation", () => {
    render(<ProvenanceBadge dataSource="real" basis="connected or pasted domain data" />);
    const chip = screen.getByText(tr.provenance.real);
    expect(chip.getAttribute("title")).toContain(tr.provenance.realHint);
    expect(chip.getAttribute("title")).toContain("connected or pasted domain data");
  });

  it("renders estimated as the amber tahmin class", () => {
    render(<ProvenanceBadge dataSource="estimated" />);
    const chip = screen.getByText(tr.provenance.estimated);
    expect(chip.getAttribute("title")).toBe(tr.provenance.estimatedHint);
  });

  it("renders benchmark", () => {
    render(<ProvenanceBadge dataSource="benchmark" />);
    expect(screen.getByText(tr.provenance.benchmark)).toBeInTheDocument();
  });

  it("renders nothing when the wire carries no recognisable source", () => {
    const { container } = render(<ProvenanceBadge dataSource="something_new" />);
    expect(container.innerHTML).toBe("");
  });
});
