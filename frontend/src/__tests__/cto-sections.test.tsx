/**
 * CTO bölüm başlıkları — the section title must come from the message tree:
 * Turkish orgs see Turkish, English orgs see English. A hardcoded string in a
 * SectionCard breaks that contract for one of the two locales.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

const orgState = vi.hoisted(() => ({ locale: "tr-TR" }));

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Test Org", locale: orgState.locale, base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: orgState.locale.startsWith("tr"),
    baseCurrency: "TRY",
    locale: orgState.locale,
  }),
}));

import {
  InfraSection,
  TechDebtSection,
  IncidentSection,
  VelocitySection,
} from "@/components/cto/CTOSections";
import type {
  InfraData,
  TechDebtData,
  IncidentData,
  VelocityData,
} from "@/components/cto/types";

const infra: InfraData = {
  total_cost_cents: 120_000,
  waste_estimate_cents: 8_000,
  mom_change_pct: 4.2,
  top_cost_drivers: [],
  by_environment: {},
  alerts: [],
  narrative: "",
};

const techDebt: TechDebtData = {
  total_commits: 120,
  active_contributors: 7,
  churn_rate: 0.12,
  debt_score: 5.4,
  hotspot_files: [],
  refactor_priorities: [],
  narrative: "",
};

const incidents: IncidentData = {
  total_incidents: 3,
  by_severity: {},
  mttr_hours: 2.5,
  mttd_hours: 1.1,
  sla_breach_count: 1,
  sla_breach_pct: 12,
  recurring_services: [],
  trend: "down",
  alerts: [],
  narrative: "",
};

const velocity: VelocityData = {
  sprints_analyzed: 6,
  avg_velocity: 34,
  velocity_trend: "up",
  predictability_score: 0.8,
  carryover_ratio: 0.1,
  bottlenecks: [],
  sprint_series: [],
  narrative: "",
};

function renderSections() {
  render(
    <>
      <InfraSection data={infra} />
      <TechDebtSection data={techDebt} />
      <IncidentSection data={incidents} />
      <VelocitySection data={velocity} />
    </>
  );
}

describe("CTO bölüm başlıkları", () => {
  afterEach(() => {
    orgState.locale = "tr-TR";
  });

  it("TR org'da Türkçe başlık gösterir", () => {
    orgState.locale = "tr-TR";
    renderSections();
    expect(screen.getByRole("button", { name: /Altyapı Maliyeti/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Teknik Borç/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Olay ve Güvenilirlik/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mühendislik Temposu/ })).toBeInTheDocument();
  });

  it("EN org'da İngilizce başlık gösterir", () => {
    orgState.locale = "en-US";
    renderSections();
    expect(screen.getByRole("button", { name: /Infrastructure Cost/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Technical Debt/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Incident & Reliability/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Engineering Velocity/ })).toBeInTheDocument();
  });
});
