import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionList } from "@/components/decisions/DecisionList";
import type { DecisionEntry } from "@/lib/api/decisionRecords";
import { en } from "@/lib/i18n/messages/en";
import { tr } from "@/lib/i18n/messages/tr";

vi.mock("@/hooks/useI18n", () => ({ useI18n: () => ({ locale: "tr", t: tr }) }));

const base: DecisionEntry = {
  id: "d1", kind: "settlement_match", target_type: "open_item_match", target_id: "m1", outcome: "confirmed",
  decided_by: "u1", decided_via: "human", rule_id: null, decided_at: "2024-02-16T10:00:00Z", reason: null,
  evidence_refs: [{ type: "open_item", id: "abcdef123456" }], before: { amount_cents: 28500000 },
  after: { status: "confirmed" }, supersedes_id: null, superseded_by_id: null,
};

describe("decision log rows", () => {
  it("names the person, the kind and the outcome in the user's language", () => {
    render(<DecisionList entries={[base]} names={{ u1: "Ayşe Yılmaz" }} />);
    expect(screen.getByText("Ayşe Yılmaz")).toBeTruthy();
    expect(screen.getByText("Banka eşleşmesi")).toBeTruthy();
    expect(screen.getByText("Onaylandı")).toBeTruthy();
    expect(screen.getByText(/285[.,]000[.,]00/)).toBeTruthy(); // cents shown as money
  });

  it("shows a rule decision as the rule's, with the way back", () => {
    render(<DecisionList entries={[{ ...base, decided_via: "rule", decided_by: null, rule_id: "reconcile.invoice_number_exact" }]} />);
    expect(screen.getAllByText(/reconcile\.invoice_number_exact/).length).toBeGreaterThan(0);
    expect(screen.getByText(/bir kişi geri alabilir/)).toBeTruthy();
  });
});

describe("decision labels", () => {
  it("have the same kinds and outcomes in both languages", () => {
    expect(Object.keys(tr.decisionLog.kinds).sort()).toEqual(Object.keys(en.decisionLog.kinds).sort());
    expect(Object.keys(tr.decisionLog.outcomes).sort()).toEqual(Object.keys(en.decisionLog.outcomes).sort());
  });
});
