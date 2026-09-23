/**
 * Karar Defteri — karar → beklenti → ölçülen sonuç döngüsünün arayüzü:
 *
 *  1. defter paneli listenir, açık kayıt "Sonucu ölç" sunar,
 *  2. ölçüm kapandıktan sonra buton gider, varyans görünür,
 *  3. paketteki "Kararı deftere yaz" akışı kaydeder ve ölçümü çağırır,
 *  4. kayıtlı bir iş için form yerine mevcut kayıt gösterilir.
 *
 * Backend deterministic (no LLM); para kuruş, UI lira gösterir.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { dec, packet } = vi.hoisted(() => ({
  dec: { listDecisions: vi.fn(), createDecision: vi.fn(), measureOutcome: vi.fn() },
  packet: { getDecisionPacket: vi.fn() },
}));
vi.mock("@/lib/api/decisions", () => dec);
vi.mock("@/lib/api/decisionPacket", () => packet);

import { DecisionLogPanel } from "@/components/ui/decision-log-panel";
import { DecisionPacketPanel } from "@/components/ui/decision-packet-panel";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const expected = {
  revenue_12m: 1_200_000_000,
  net_change_12m: 50_000_000,
  runway_months: 9.5,
  forecast_12m_net: 300_000_000,
  option_id: "preset_1",
  option_label: "2 Kişi İşe Alma",
  option_net_impact: -240_000_000,
  option_runway_after: 8.2,
  generated_at: "2026-09-20T10:00:00+00:00",
};

const openRec = {
  id: "dec-1",
  job_id: "job-1",
  org_id: "org-1",
  topic: "Bütçe kesintisi",
  chosen_option_id: "preset_1",
  chosen_option_label: "2 Kişi İşe Alma",
  rationale: "Nakit ömrü kısalıyor",
  expected,
  status: "open" as const,
  actual: null,
  variance: null,
  outcome_note: null,
  measured_at: null,
  created_by: "u1",
  created_at: "2026-09-20T10:00:00+00:00",
  updated_at: "2026-09-20T10:00:00+00:00",
};

const closedRec = {
  ...openRec,
  id: "dec-2",
  topic: "Stok devrini hızlandır",
  chosen_option_id: "preset_2",
  chosen_option_label: "Stok azaltma",
  status: "closed" as const,
  actual: {
    realized_net_kurus: 30_000_000,
    income_kurus: 50_000_000,
    expense_kurus: 20_000_000,
    transactions_since: 2,
    runway_months_latest: 11,
    data_job_id: "job-2",
    decided_at: "2026-09-21T10:00:00+00:00",
    as_of: "2026-09-23T10:00:00+00:00",
  },
  variance: { realized_net_kurus: 30_000_000, runway_delta: 1.5 },
  outcome_note: null,
  measured_at: "2026-09-23T10:00:00+00:00",
  updated_at: "2026-09-23T10:00:00+00:00",
};

const packetFull = {
  job_id: "job-1",
  status: "awaiting_review",
  awaiting_review: true,
  generated_at: "2026-09-23T10:00:00+00:00",
  gate: { held_for_review: true, min_confidence: 0.6, reason: null },
  situation: {
    revenue_12m: 1_200_000_000,
    net_margin: 0.2,
    net_change_12m: 50_000_000,
    top_opex_category: "salary",
    top_opex_amount: 400_000_000,
    runway_months: 9.5,
    forecast_12m_net: 300_000_000,
    anomaly_count: 0,
    min_confidence: 0.6,
  },
  options: [
    {
      id: "baseline",
      label: "Hiçbir şey yapma",
      description: "Mevcut planla devam.",
      baseline: true,
      base_net_impact: 0,
      breakeven_months: null,
      cashflow_risk: null,
      runway_after: 9.5,
      assumptions: [],
      recommendation: null,
      engine: "forecast",
      scenarios: [],
    },
    {
      id: "preset_1",
      label: "2 Kişi İşe Alma",
      description: "İşe alım.",
      baseline: false,
      base_net_impact: -240_000_000,
      breakeven_months: 8,
      cashflow_risk: "orta",
      runway_after: 8.2,
      assumptions: [],
      recommendation: "Düşün",
      engine: "forecast",
      scenarios: [],
    },
  ],
  freshness: [],
  precedent: { decisions: [], pending_actions: 0 },
  calibration: { status: "yeterli veri yok", pairs: 1 },
  evidence: "",
};

beforeEach(() => {
  dec.listDecisions.mockReset();
  dec.createDecision.mockReset();
  dec.measureOutcome.mockReset();
  packet.getDecisionPacket.mockReset();
});

// ── Defter paneli ─────────────────────────────────────────────────────────────

describe("DecisionLogPanel", () => {
  it("lists the ledger: an open decision offers measurement, a closed one shows the variance", async () => {
    dec.listDecisions.mockResolvedValue([openRec, closedRec]);
    render(<DecisionLogPanel />);

    expect(await screen.findByText("Karar Defteri")).toBeInTheDocument();
    expect(screen.getByText("Bütçe kesintisi")).toBeInTheDocument();
    expect(screen.getByText(/Stok azaltma/)).toBeInTheDocument();

    // 2 kayıt: 1 açık, 1 ölçüldü → rozetler tutarlı.
    expect(screen.getByText("1 açık")).toBeInTheDocument();
    expect(screen.getByText("1 ölçüldü")).toBeInTheDocument();

    // Açık → buton; ölçüldü → varyans (net ₺300.000, pist +1.5 ay).
    expect(screen.getByRole("button", { name: "Sonucu ölç" })).toBeInTheDocument();
    expect(screen.getAllByText(/ölçüldü/).length).toBeGreaterThan(0);
    expect(screen.getByText(/300\.000/)).toBeInTheDocument();
    expect(screen.getByText("+1.5 ay")).toBeInTheDocument();
  });

  it("measuring an open decision closes it and swaps the button for the variance", async () => {
    dec.listDecisions.mockResolvedValue([openRec]);
    dec.measureOutcome.mockResolvedValue({
      ...openRec,
      status: "closed",
      measured_at: "2026-09-24T09:00:00+00:00",
      variance: { realized_net_kurus: -12_500_000, runway_delta: -0.5 },
      actual: { ...closedRec.actual!, realized_net_kurus: -12_500_000 },
    });
    render(<DecisionLogPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Sonucu ölç" }));
    await waitFor(() =>
      expect(dec.measureOutcome).toHaveBeenCalledWith("dec-1")
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Sonucu ölç" })
      ).not.toBeInTheDocument()
    );
    expect(screen.getByText(/125\.000/)).toBeInTheDocument();
    expect(screen.getByText("-0.5 ay")).toBeInTheDocument();
  });

  it("renders the empty state when the ledger is empty", async () => {
    dec.listDecisions.mockResolvedValue([]);
    render(<DecisionLogPanel />);
    expect(await screen.findByText(/Kayıtlı karar yok/)).toBeInTheDocument();
  });
});

// ── Paket içi kayıt akışı ─────────────────────────────────────────────────────

describe("DecisionPacketPanel — kararı deftere yaz", () => {
  it("records a decision against the packet and then measures it", async () => {
    packet.getDecisionPacket.mockResolvedValue(packetFull);
    dec.listDecisions.mockResolvedValue([]);
    dec.createDecision.mockResolvedValue(openRec);
    dec.measureOutcome.mockResolvedValue({
      ...openRec,
      status: "closed",
      measured_at: "2026-09-24T09:00:00+00:00",
      variance: { realized_net_kurus: 30_000_000, runway_delta: 1.5 },
      actual: closedRec.actual,
    });
    render(<DecisionPacketPanel jobId="job-1" />);

    const select = await screen.findByLabelText("Karar seçeneği");
    fireEvent.change(select, { target: { value: "preset_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Kararı deftere yaz" }));

    await waitFor(() =>
      expect(dec.createDecision).toHaveBeenCalledWith(
        expect.objectContaining({ jobId: "job-1", optionId: "preset_1" })
      )
    );

    // Kayıt sonrası form yerini defter kaydına bırakır.
    const measureBtn = await screen.findByRole("button", {
      name: "Sonucu ölç",
    });
    expect(
      screen.queryByRole("button", { name: "Kararı deftere yaz" })
    ).not.toBeInTheDocument();

    fireEvent.click(measureBtn);
    await waitFor(() =>
      expect(dec.measureOutcome).toHaveBeenCalledWith("dec-1")
    );
    expect(await screen.findByText(/\+1.5 ay/)).toBeInTheDocument();
  });

  it("prefills with the job's existing decision instead of showing a fresh form", async () => {
    packet.getDecisionPacket.mockResolvedValue(packetFull);
    dec.listDecisions.mockResolvedValue([openRec]);
    render(<DecisionPacketPanel jobId="job-1" />);

    expect(await screen.findByText("Bütçe kesintisi")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sonucu ölç" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Kararı deftere yaz" })
    ).not.toBeInTheDocument();
    expect(dec.createDecision).not.toHaveBeenCalled();
  });
});
