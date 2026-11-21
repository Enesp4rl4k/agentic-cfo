/**
 * Consolidated Radar View (Plan v12 Faz 4) Vitest Test
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConsolidatedRadarView } from "@/components/consolidation/ConsolidatedRadarView";
import { tr } from "@/lib/i18n/messages/tr";
import type { ConsolidatedCashRadar } from "@/lib/api/consolidation";

const mockRadar: ConsolidatedCashRadar = {
  group_name: "Holding Grubu",
  participating_org_ids: ["org-1", "org-2"],
  total_starting_cash_cents: 50000000,
  total_eliminated_cents: 25000000,
  insights: ["2 şirket konsolide edildi; ₺250.000 grup içi alacak/borç elendi."],
  eliminations: [
    {
      item_id: "el-1",
      org_id: "org-1",
      org_name: "Holding Enerji A.Ş.",
      direction: "receivable",
      counterparty: "Holding Lojistik Ltd. Şti.",
      amount_cents: 25000000,
      due_date: "2026-03-20",
      week: 3,
      eliminated_reason: "Grup içi alacak eliminasyonu",
    },
  ],
  weeks: [
    {
      week: 1,
      start_date: "2026-03-01",
      end_date: "2026-03-07",
      gross_inflow_cents: 10000000,
      gross_outflow_cents: 5000000,
      eliminated_inflow_cents: 0,
      eliminated_outflow_cents: 0,
      net_inflow_cents: 10000000,
      net_outflow_cents: 5000000,
      consolidated_balance_cents: 55000000,
    },
    {
      week: 3,
      start_date: "2026-03-15",
      end_date: "2026-03-21",
      gross_inflow_cents: 35000000,
      gross_outflow_cents: 30000000,
      eliminated_inflow_cents: 25000000,
      eliminated_outflow_cents: 25000000,
      net_inflow_cents: 10000000,
      net_outflow_cents: 5000000,
      consolidated_balance_cents: 60000000,
    },
  ],
};

describe("ConsolidatedRadarView", () => {
  it("renders metrics, insights, and 13-week table", () => {
    render(
      <ConsolidatedRadarView
        radar={mockRadar}
        copy={tr.cashRadar}
        fmt={(v) => `₺${v.toLocaleString("tr-TR")}`}
      />
    );

    expect(screen.getByText("Konsolide Grup Nakit Radarı")).toBeDefined();
    expect(screen.getByText("2 şirket konsolide edildi; ₺250.000 grup içi alacak/borç elendi.")).toBeDefined();

    // Eliminasyon butonu ve açılımı
    const elimBtn = screen.getByText("Elenen Grup İçi Kalemler (1)");
    fireEvent.click(elimBtn);

    expect(screen.getByText("Holding Enerji A.Ş.")).toBeDefined();
    expect(screen.getByText("Holding Lojistik Ltd. Şti.")).toBeDefined();
    expect(screen.getByText("Grup içi alacak eliminasyonu")).toBeDefined();
  });
});
