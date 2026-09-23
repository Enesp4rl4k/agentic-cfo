/**
 * Karar Paketi paneli — imza anında dört soru tek ekranda:
 * ne oldu · seçenekler ve sonuçları · veri ne taze · geçmişte ne oldu.
 *
 * Panel "optional furniture": paket yüklenemezse hiçbir şey çizmez, altındaki
 * onay akışını asla engellemez.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";

const { packet, dec } = vi.hoisted(() => ({
  packet: { getDecisionPacket: vi.fn() },
  dec: { listDecisions: vi.fn(), createDecision: vi.fn(), measureOutcome: vi.fn() },
}));
vi.mock("@/lib/api/decisionPacket", () => packet);
vi.mock("@/lib/api/decisions", () => dec);

import { DecisionPacketPanel } from "@/components/ui/decision-packet-panel";

const full = {
  job_id: "job-1",
  status: "awaiting_review",
  awaiting_review: true,
  generated_at: "2026-09-23T10:00:00+00:00",
  gate: {
    held_for_review: true,
    min_confidence: 0.6,
    reason: "Analiz güven eşiğinin altında sonuç üretti — insan onayı bekleniyor.",
  },
  situation: {
    revenue_12m: 1_200_000_000,
    net_margin: 0.2,
    net_change_12m: 50_000_000,
    top_opex_category: "salary",
    top_opex_amount: 400_000_000,
    runway_months: 9.5,
    forecast_12m_net: 300_000_000,
    anomaly_count: 1,
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
      assumptions: ["Gelir ve gider eğilimleri değişmez (baz senaryo)"],
      recommendation: null,
      engine: "forecast",
      scenarios: [],
    },
    {
      id: "preset_1",
      label: "2 Kişi İşe Alma",
      description: "İşe alım.",
      baseline: false,
      base_net_impact: -24_000_000,
      breakeven_months: 6,
      cashflow_risk: "medium",
      runway_after: null,
      assumptions: ["Ortalama brüt maaş"],
      recommendation: "Değerlendirin",
      engine: "counterfactual",
      scenarios: [],
    },
  ],
  freshness: [
    {
      source: "analysis_file",
      label: "Analiz dosyası",
      as_of: "2026-09-23T09:00:00+00:00",
      age_days: 0,
      state: "fresh",
      detail: "m.csv",
    },
    {
      source: "connector:github",
      label: "Bağlantı: github",
      as_of: null,
      age_days: null,
      state: "never",
      detail: null,
    },
    {
      source: "erp:parasut",
      label: "ERP: parasut",
      as_of: "2026-07-01T00:00:00+00:00",
      age_days: 84,
      state: "stale",
      detail: "success",
    },
  ],
  precedent: {
    decisions: [
      {
        id: "d1",
        topic: "Fiyat artışı",
        final_decision: "Kademeli zam uygulansın",
        resolution_status: "uygulandi",
        confidence_score: 0.8,
        created_at: "2026-05-01T10:00:00+00:00",
      },
    ],
    pending_actions: 2,
  },
  calibration: {
    status: "ok",
    pairs: 4,
    mae_kurus: 12_500_000,
    smape_pct: 8.4,
    coverage_pct: 75,
    bias_kurus: -3_000_000,
  },
  evidence: "",
};

describe("Karar Paketi paneli", () => {
  beforeEach(() => {
    packet.getDecisionPacket.mockReset();
    // Recorder prefill: no decision recorded yet in these tests.
    dec.listDecisions.mockReset().mockResolvedValue([]);
    dec.createDecision.mockReset();
    dec.measureOutcome.mockReset();
  });

  it("answers the four questions on one screen", async () => {
    packet.getDecisionPacket.mockResolvedValue(full);
    render(<DecisionPacketPanel jobId="job-1" />);
    expect(packet.getDecisionPacket).toHaveBeenCalledWith("job-1");

    expect(await screen.findByText("Karar Paketi")).toBeInTheDocument();

    // 0. Neden insan kontrolünde?
    expect(screen.getByText(/güven eşiğinin altında/)).toBeInTheDocument();

    // 1. Ne oldu?
    expect(screen.getByText("9.5 ay")).toBeInTheDocument();
    expect(screen.getByText(/salary ·/)).toBeInTheDocument();

    // 2. Seçenekler + sonuçları (baseline referans, preset sonuçlu).
    //    Recorder'ın <select> de aynı seçenek adlarını taşıdığı için
    //    seçenek tablosuna scope edilir.
    const optionsSection = within(screen.getByLabelText("Seçenekler"));
    expect(optionsSection.getByText("Hiçbir şey yapma")).toBeInTheDocument();
    expect(screen.getByText("referans")).toBeInTheDocument();
    expect(screen.getByText("0 ₺ (referans)")).toBeInTheDocument();
    expect(optionsSection.getByText("2 Kişi İşe Alma")).toBeInTheDocument();
    expect(screen.getByText(/240\.000/)).toBeInTheDocument(); // −240.000 ₺
    expect(screen.getByText("6 ay")).toBeInTheDocument(); // break-even

    // 3. Veri ne taze? — fresh / never / stale çipleri
    expect(screen.getByText("Veri ne taze?")).toBeInTheDocument();
    expect(screen.getByText("bugün")).toBeInTheDocument();
    expect(screen.getByText("hiç senkron yok")).toBeInTheDocument();
    expect(screen.getByText("84 gün önce")).toBeInTheDocument();

    // + Güven satırı — kalibrasyon (P3): üçten çok kapanmış pencere → ok
    expect(screen.getByText("Tahminler tuttu mu?")).toBeInTheDocument();
    expect(screen.getByText(/ortalama hata/)).toBeInTheDocument();
    expect(screen.getByText(/sMAPE/)).toBeInTheDocument();

    // 4. Geçmişte ne oldu? — emsal + açık aksiyon
    expect(screen.getByText("Fiyat artışı")).toBeInTheDocument();
    expect(screen.getByText("Kademeli zam uygulansın")).toBeInTheDocument();
    expect(screen.getByText("2 açık aksiyon")).toBeInTheDocument();
  });

  it("renders nothing when the packet cannot be loaded", async () => {
    packet.getDecisionPacket.mockRejectedValue(new Error("backend kapalı"));
    const { container } = render(<DecisionPacketPanel jobId="job-1" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByText("Karar Paketi")).not.toBeInTheDocument();
  });
});
