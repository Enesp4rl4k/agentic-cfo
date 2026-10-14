import { describe, expect, it } from "vitest";
import { normalizeCOOResult } from "@/lib/coo-result";

/**
 * The wire shape the COO pipeline emits — the sample-CSV column set the
 * documented PH examples produce (process/resource/sla agents).
 */
const RAW = {
  job_id: "job-coo-1",
  processes: [
    { process_name: "Order Processing", cycle_time: 5, throughput: 20, wip: 45, constraint_type: "resource", toc_recommendation: "Add capacity at the constraint.", impact_score: 92 },
    { process_name: "Payment Verification", cycle_time: 3, throughput: 30, wip: 25, constraint_type: "policy", toc_recommendation: "Auto-approve low-risk payments.", impact_score: 78 },
  ],
  sla: {
    tickets: [
      { ticket_id: "T001", title: "Sistem Entegrasyonu", assigned_to: "Ali", created_date: "2026-06-20", due_date: "2026-07-25", hours_remaining: 48, risk_score: 0.91, risk_level: "kritik", priority: "critical", status: "in_progress" },
      { ticket_id: "T002", title: "Rapor Talebi", assigned_to: "Ayşe", created_date: "2026-07-01", due_date: "2026-07-30", hours_remaining: 120, risk_score: 0.35, risk_level: "düşük", priority: "low", status: "open" },
    ],
    breach_rate: 0.12,
    trend: [{ date: "2026-06", breach_pct: 18 }, { date: "2026-07", breach_pct: 12 }],
  },
  error: null,
};

describe("normalizeCOOResult", () => {
  it("maps the wire payload onto the dashboard view", () => {
    const v = normalizeCOOResult(RAW);
    expect(v).not.toBeNull();
    expect(v!.processes).toHaveLength(2);
    expect(v!.processes![0].impact_score).toBe(92);
    expect(v!.sla!.tickets[0].risk_score).toBe(0.91);
    expect(v!.sla!.breach_rate).toBe(0.12);
    expect(v!.sla!.trend).toHaveLength(2);
    expect(v!.error).toBeNull();
  });

  it("keeps category values as they arrive — no fabricated vocabulary", () => {
    const v = normalizeCOOResult({
      processes: [{ process_name: "X", constraint_type: "beyin", impact_score: 10 }],
    });
    expect(v!.processes![0].constraint_type).toBe("beyin");
  });

  it("turns empty sections into null instead of empty scaffolding", () => {
    expect(normalizeCOOResult({ processes: [], sla: { tickets: [] } })).toBeNull();
    const v = normalizeCOOResult(RAW);
    const empty = normalizeCOOResult({ processes: [{ cycle_time: 3 }] });
    expect(empty).toBeNull(); // no process_name → no rows → nothing honest to show
    expect(v!.processes).not.toBeNull();
  });

  it("drops unusable rows and never leaks NaN", () => {
    const v = normalizeCOOResult({
      processes: [{ process_name: "A", impact_score: NaN }, "junk", { impact_score: 5 }],
      sla: { tickets: [{ title: "id'siz" }, { ticket_id: "T9", hours_remaining: "birçok" }], breach_rate: "x" },
    });
    expect(v!.processes).toHaveLength(1);
    expect(v!.processes![0].impact_score).toBe(0);
    expect(v!.sla!.tickets).toHaveLength(1);
    expect(v!.sla!.tickets[0].hours_remaining).toBe(0);
    expect(v!.sla!.breach_rate).toBe(0);
  });

  it("returns null for non-objects and keeps the error field", () => {
    expect(normalizeCOOResult(undefined)).toBeNull();
    expect(normalizeCOOResult("boom")).toBeNull();
    expect(normalizeCOOResult({})).toBeNull();
    const v = normalizeCOOResult({ error: "CSV okunamadı" });
    expect(v!.error).toBe("CSV okunamadı");
    expect(v!.processes).toBeNull();
  });
});
