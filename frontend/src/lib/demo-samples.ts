/**
 * IS_DEMO wire fixtures — the prefill-less degradation path (DEMO_PLAN §D2).
 *
 * Risk and CEO are the two dashboards with no input form to fall back on: on
 * an empty organisation they showed an honest but bare empty state. In demo
 * mode these fixtures take over — only while no live result exists, only
 * behind `NEXT_PUBLIC_DEMO_MODE=true` — and they go through the SAME
 * normalizers the live endpoints use (`normalizeRiskCascadeReport`,
 * `normalizeCEOResult`), never a pre-built view: a renamed backend key breaks
 * `demo-samples.test.ts` instead of rendering "undefined" on screen.
 *
 * Honesty: a page rendering a fixture shows the "Örnek veri" badge
 * (t.csvInput.sampleData); the sample disappears the moment a real result or
 * decision brief arrives. Sample data is never presented as a live analysis.
 * The numbers are one coherent Örnek A.Ş. story and every KRI status is
 * consistent with that KRI's own thresholds.
 */

/** The demo flag, read at call time so tests can stub it per case. */
export function isDemoMode(): boolean {
  return process.env.NEXT_PUBLIC_DEMO_MODE === "true";
}

// ── Risk cascade report (wire shape of GET /risk-cascade/*) ──────────────────

const KRI_DSO = {
  name: "DSO",
  category: "financial",
  current_value: 52,
  unit: "gün",
  threshold_amber: 45,
  threshold_red: 60,
  higher_is_worse: true,
  status: "amber",
  trend: "deteriorating",
  trajectory_months: 3,
  source: "CFO raporu",
  evidence: "tahsilat tablosu",
  cascade_trigger: "nakit",
  cascade_params: { days: 60 },
};

const KRI_RUNWAY = {
  name: "Nakit koşu bandı",
  category: "financial",
  current_value: 2.6,
  unit: "ay",
  threshold_amber: 6,
  threshold_red: 3,
  higher_is_worse: false,
  status: "red",
  trend: "deteriorating",
  trajectory_months: 3,
  source: "CFO raporu",
  evidence: "13 haftalık nakit planı",
  cascade_trigger: null,
  cascade_params: {},
};

const KRI_INCIDENT = {
  name: "Açık olay oranı",
  category: "ops",
  current_value: 5.4,
  unit: "%",
  threshold_amber: 5,
  threshold_red: 8,
  higher_is_worse: true,
  status: "amber",
  trend: "stable",
  trajectory_months: 3,
  source: "KRI dosyası",
  evidence: "operasyon KRI satırı",
  cascade_trigger: null,
  cascade_params: {},
};

const KRI_SUPPLIER = {
  name: "Tedarikçi konsantrasyonu",
  category: "financial",
  current_value: 38,
  unit: "%",
  threshold_amber: 40,
  threshold_red: 60,
  higher_is_worse: true,
  status: "green",
  trend: "stable",
  trajectory_months: 3,
  source: "KRI dosyası",
  evidence: "satın alma raporu",
  cascade_trigger: null,
  cascade_params: {},
};

const KRI_CLOUD = {
  name: "Bulut gideri sapması",
  category: "tech",
  current_value: 7,
  unit: "%",
  threshold_amber: 10,
  threshold_red: 20,
  higher_is_worse: true,
  status: "green",
  trend: "improving",
  trajectory_months: 3,
  source: "CFO raporu",
  evidence: "faturalı bulut gideri",
  cascade_trigger: null,
  cascade_params: {},
};

const SAMPLE_CASCADE_RESULT = {
  scenarios: [{ name: "baz", overall_risk_score: 62 }],
  executive_summary:
    "DSO 52 günle 45 gün amber eşiğini aştı; 60 güne yaklaşan tahsilat gecikmesi nakit akışını domine ediyor.",
  immediate_actions: [
    "60 gün üstü bakiyeleri haftalık tahsilat ritmine al",
    "Kritik müşteriler için otomatik hatırlatma akışı kur",
  ],
};

export const SAMPLE_RISK_WIRE: Record<string, unknown> = {
  kri_posture: {
    kri_score: 6,
    posture: "elevated",
    posture_tr: "Yükselmiş",
    // Derived check: red 1 (runway), amber 2 (DSO, incident), green 2.
    counts: { red: 1, amber: 2, green: 2, total: 5 },
    all_kris: [KRI_DSO, KRI_RUNWAY, KRI_INCIDENT, KRI_SUPPLIER, KRI_CLOUD],
    red_kris: [KRI_RUNWAY],
    amber_kris: [KRI_DSO, KRI_INCIDENT],
    upcoming_red: [],
    cascade_ready: [KRI_DSO],
    by_category: {
      financial: [KRI_DSO, KRI_RUNWAY, KRI_SUPPLIER],
      ops: [KRI_INCIDENT],
      tech: [KRI_CLOUD],
    },
    sources: ["CFO raporu", "KRI dosyası"],
  },
  cascade_links: [
    {
      kri_name: "DSO",
      kri_category: "financial",
      kri_status: "amber",
      kri_value: 52,
      kri_unit: "gün",
      trigger_type: "threshold",
      trigger_params: { days: 60 },
      cascade_result: SAMPLE_CASCADE_RESULT,
      cascade_error: null,
    },
  ],
  total_cascades: 1,
  critical_count: 1,
  cascade_summary:
    "Nakit koşu bandı kırmızıda: DSO eşiği aşılırsa zincirleme risk treasury ve finance domenlerini etkiler.",
  domains_at_risk: ["treasury", "finance"],
  top_cascade: {
    kri_name: "DSO",
    trigger_type: "threshold",
    cascade_result: SAMPLE_CASCADE_RESULT,
  },
};

// ── CEO orchestrator result (wire shape of context.last_ceo_result) ──────────

export const SAMPLE_CEO_WIRE: Record<string, unknown> = {
  job_id: "ornek-ceo",
  board_deck: [
    {
      slide_number: 1,
      title: "Yönetici özeti",
      content:
        "Nakit disiplini korundu; tahsilat süresi ve bulut gideri optimizasyonu ilk iki öncelik.",
      metrics: { net_income_cents: 124000000 },
    },
    {
      slide_number: 2,
      title: "Finansal görünüm",
      content: "Nakit koşu bandı 2,6 aya indi, DSO 52 güne çıktı.",
      metrics: { revenue_cents: 482000000 },
    },
    {
      slide_number: 3,
      title: "Öncelikler",
      content: "Tahsilat disiplini ve bulut gideri optimizasyonu.",
    },
  ],
  okr_status: {
    company_score: 74,
    objectives: [
      {
        objective_id: "okr-1",
        name: "Nakit dönüşümü",
        weight: 0.5,
        score: 68,
        momentum: "down",
        key_results: [
          { name: "DSO'yu 45 güne indir", progress: 40 },
          { name: "13 haftalık planı koru", progress: 75 },
        ],
      },
      {
        objective_id: "okr-2",
        name: "Kârlılık",
        weight: 0.5,
        score: 80,
        momentum: "up",
        key_results: [{ name: "Brüt marjı güçlendir", progress: 70 }],
      },
    ],
  },
  outlook: {
    base_case: [100, 102, 104, 103, 106, 108],
    optimistic: [100, 104, 108, 111, 115, 118],
    pessimistic: [100, 99, 97, 95, 94, 92],
  },
  financial_summary: { revenue_cents: 482000000, net_margin: 0.18 },
  cross_risks: [
    {
      risk_id: "R-1",
      title: "Nakit daralması tech yol haritasını kilitleyebilir",
      severity: "high",
      domains: ["finance", "tech"],
      recommended_action: "13. hafta planını dondur",
    },
    {
      risk_id: "R-2",
      title: "Tek müşteri bağımlılığı gelir çeşitliliğini zayıflatıyor",
      severity: "medium",
      domains: ["sales"],
      recommended_action: "İkinci müşteri segmentini hedefle",
    },
  ],
  swot: {
    strengths: ["Nakit disiplini", "Uçtan uca finans görünürlüğü"],
    weaknesses: ["Tek müşteri bağımlılığı", "Uzun tahsilat süresi"],
    opportunities: ["Bulut gideri optimizasyonu", "Fiyatlandırma iyileştirmesi"],
    threats: ["Kur oynaklığı", "Rekabetçi fiyat baskısı"],
    strategic_priorities: ["Nakit dönüşümünü hızlandır", "Kârlılığı koru"],
  },
  strategic_priorities: [
    {
      title: "Tahsilat disiplinini standartlaştır",
      rationale:
        "DSO 52 günden 45 güne inerse nakit koşu bandı yaklaşık 3 ay uzar.",
      horizon: "0-3 ay",
      owner: "CFO",
      metric: "DSO",
      target_date: "2027-01-31",
    },
    {
      title: "Bulut giderlerini optimize et",
      rationale:
        "Sapma %7'den %3'e düşerse yıllık kârlılığa doğrudan katkı sağlar.",
      horizon: "3-6 ay",
      owner: "CTO",
      metric: "Bulut gideri sapması",
      target_date: "2027-03-31",
    },
  ],
  decision_brief: {
    period: "2026-Q3",
    currency: "TRY",
    locale: "tr-TR",
    headline: "Nakit disiplinini korurken kârlılık iyileştirilmeli",
    health_score: 68,
    findings: [
      {
        severity: "high",
        domain: "finance",
        statement:
          "DSO 52 gün ile amber eşiğin üzerinde; tahsilat gecikmesi nakit akışını domine ediyor.",
        metric_ids: ["dso"],
        confidence: 0.8,
      },
      {
        severity: "medium",
        domain: "tech",
        statement:
          "Bulut gideri sapması %7 ile yeşilde; yükseliş eğilimi izlenmeli.",
        metric_ids: [],
        confidence: 0.6,
      },
    ],
    options: [
      {
        title: "Tahsilat disiplinini sıkılaştır",
        impact_summary:
          "DSO 45 güne inerse nakit koşu bandı yaklaşık 3 ay uzar.",
        linked_cf_action: "collections_sla",
      },
      {
        title: "Bulut giderlerini optimize et",
        impact_summary: "Sapma %3e düşerse kârlılığa ölçülebilir katkı.",
        linked_cf_action: null,
      },
    ],
    recommendation: {
      title: "Tahsilat disiplinini sıkılaştır",
      rationale: "En hızlı nakit etkisi düşük maliyetli aksiyon.",
      option_index: 0,
    },
    conflicts: [],
    awaiting_review: false,
    generated_at: "2026-10-01T09:00:00+00:00",
    schema_version: "1",
  },
};
