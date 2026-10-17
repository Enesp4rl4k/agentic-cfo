import { describe, expect, it } from "vitest";
import { detectInitialLocale, getMessages, resolveAppLocale } from "@/lib/i18n";

describe("resolveAppLocale", () => {
  it("maps tr-* org locales to Turkish and everything else to English", () => {
    expect(resolveAppLocale("tr-TR")).toBe("tr");
    expect(resolveAppLocale("TR")).toBe("tr");
    expect(resolveAppLocale("en-US")).toBe("en");
    expect(resolveAppLocale(null)).toBe("en");
    expect(resolveAppLocale(undefined)).toBe("en");
  });
});

describe("detectInitialLocale", () => {
  it("trusts the cached locale from the last resolved org", () => {
    expect(detectInitialLocale("tr", ["en-US"])).toBe("tr");
    expect(detectInitialLocale("en", ["tr-TR"])).toBe("en");
    expect(detectInitialLocale("tr-TR")).toBe("tr");
  });

  it("falls back to the browser language when there is no cache", () => {
    expect(detectInitialLocale(null, ["tr-TR", "en-US"])).toBe("tr");
    expect(detectInitialLocale(null, ["de-DE", "en-US"])).toBe("en");
    expect(detectInitialLocale(undefined, [])).toBe("en");
  });
});

describe("getMessages", () => {
  it("returns role dashboard headers in both locales", () => {
    expect(getMessages("tr").roleDashboards.ceo.title).toBe("CEO karar panosu");
    expect(getMessages("en").roleDashboards.ceo.title).toBe("CEO decision board");
    expect(getMessages("tr").billing.title).not.toBe(getMessages("en").billing.title);
  });

  it("localizes role section headings in both locales", () => {
    const tr = getMessages("tr");
    const en = getMessages("en");

    expect(tr.roleDashboards.cto.sections.infrastructureCost).toBe("Altyapı Maliyeti");
    expect(en.roleDashboards.cto.sections.infrastructureCost).toBe("Infrastructure Cost");
    expect(tr.roleDashboards.cmo.sections.campaignPerformance).toBe("Kampanya Performansı");
    expect(tr.roleDashboards.chro.sections.hrHealthSummary).toBe("İK Sağlık Özeti");
    expect(tr.roleDashboards.cfo.sections.pnlSummary).toBe("P&L Özeti");
    expect(en.roleDashboards.cfo.sections.pnlSummary).toBe("P&L summary");
    expect(tr.roleDashboards.cfo.title).toBe("CFO Görünümü");
    expect(en.roleDashboards.cfo.title).toBe("CFO overview");
    expect(tr.roleDashboards.coo.sections.bottlenecks).toBe(
      "Süreç Darboğazları (Verimlilik vs Döngü Zamanı)",
    );
    expect(en.roleDashboards.coo.sections.bottlenecks).toBe(
      "Process Bottlenecks (Throughput vs Cycle Time)",
    );
    expect(tr.roleDashboards.ceo.sections.crossDomainRiskTimeline).not.toBe(
      en.roleDashboards.ceo.sections.crossDomainRiskTimeline,
    );
  });

  /** Every key of one locale's tree must exist in the other, with a string leaf. */
  function collectLeafPaths(node: unknown, prefix = ""): string[] {
    if (typeof node === "string") return [prefix];
    if (node === null || typeof node !== "object") return [prefix];
    return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
      collectLeafPaths(v, prefix ? `${prefix}.${k}` : k),
    );
  }

  it("keeps the tr and en message trees structurally identical", () => {
    const trLeaves = collectLeafPaths(getMessages("tr")).sort();
    const enLeaves = collectLeafPaths(getMessages("en")).sort();

    expect(trLeaves).toEqual(enLeaves);
    expect(trLeaves.length).toBeGreaterThan(100);
  });

  it("localizes the Group A feature pages (pnl, cashflow, baglan, upload, chat)", () => {
    const tr = getMessages("tr");
    const en = getMessages("en");

    expect(tr.pnl.title).toBe("Gelir Tablosu (P&L)");
    expect(en.pnl.title).toBe("P&L statement");
    expect(tr.cashflow.title).toBe("Nakit Akışı Tablosu");
    expect(en.cashflow.title).toBe("Cash flow statement");
    expect(tr.baglan.title).toBe("Verilerimi Bağla");
    expect(en.baglan.title).toBe("Connect my data");
    expect(tr.upload.mapping.heading).toBe("Kolon Eşleştirme");
    expect(en.upload.mapping.heading).toBe("Column mapping");
    expect(tr.chat.title).toBe("CFO Asistanı");
    expect(en.chat.title).toBe("CFO Assistant");

    // opex keys from the backend must resolve in both locales
    for (const key of ["salary", "rent", "utilities", "marketing", "technology", "other_expense"]) {
      expect(tr.pnl.opex.labels[key]).toBeTruthy();
      expect(en.pnl.opex.labels[key]).toBeTruthy();
    }

    // suggestion questions drive real buttons — never empty
    expect(tr.chat.suggestions.q.cashOutlook).not.toBe(en.chat.suggestions.q.cashOutlook);
    expect(tr.chat.footer).toContain("Enter");
  });

  it("localizes the Group B feature pages (budget, tax, trends, comparison, forecast, sensitivity)", () => {
    const tr = getMessages("tr");
    const en = getMessages("en");

    expect(tr.budget.title).toBe("Bütçe Karşılaştırması");
    expect(en.budget.title).toBe("Budget comparison");
    expect(tr.tax.title).toBe("Vergi Analizi");
    expect(en.tax.title).toBe("Tax analysis");
    expect(tr.trends.title).toBe("Dönem Analizi & Trendler");
    expect(en.trends.title).toBe("Period analysis & trends");
    expect(tr.comparison.title).toBe("Dönem Karşılaştırması");
    expect(en.comparison.title).toBe("Period comparison");
    expect(tr.forecast.title).toBe("12 Aylık Tahmin");
    expect(en.forecast.title).toBe("12-month forecast");
    expect(tr.sensitivity.title).toBe("What-If Analizi");
    expect(en.sensitivity.title).toBe("What-if analysis");

    // comparison metric labels cover every PeriodMetrics key
    for (const key of [
      "revenue",
      "gross_profit",
      "gross_margin",
      "ebitda",
      "ebitda_margin",
      "net_income",
      "net_margin",
      "opex",
      "cash_flow",
    ]) {
      expect(tr.comparison.metrics.labels[key as keyof typeof tr.comparison.metrics.labels]).toBeTruthy();
      expect(en.comparison.metrics.labels[key as keyof typeof en.comparison.metrics.labels]).toBeTruthy();
    }

    // percent position differs between locales: TR "%20" prefix vs EN "20%" suffix
    expect(tr.sensitivity.heatmap.marginTooltip).toContain("%{val}");
    expect(en.sensitivity.heatmap.marginTooltip).toContain("{val}%");

    // forecast scenario names exist in both locales
    expect(tr.forecast.fan.optimistic).toBe("İyimser");
    expect(en.forecast.fan.optimistic).toBe("Optimistic");
    expect(tr.forecast.table.colRunway).toBe("Raf Ömrü");
    expect(en.forecast.table.colRunway).toBe("Runway");
  });

  it("localizes the Group C feature pages (integrations, intelligence, anomalies, reports, templates, notifications)", () => {
    const tr = getMessages("tr");
    const en = getMessages("en");

    expect(tr.integrations.title).toBe("Entegrasyonlar");
    expect(en.integrations.title).toBe("Integrations");
    expect(tr.intelligence.title).toBe("Proaktif KRI Dashboard");
    expect(en.intelligence.title).toBe("Proactive KRI dashboard");
    expect(tr.anomalies.title).toBe("Anomali Tespiti");
    expect(en.anomalies.title).toBe("Anomaly Detection");
    expect(tr.reports.title).toBe("Raporlar");
    expect(en.reports.title).toBe("Reports");
    expect(tr.templates.title).toBe("CSV Şablonları");
    expect(en.templates.title).toBe("CSV templates");
    expect(tr.notifications.title).toBe("Bildirimler");
    expect(en.notifications.title).toBe("Notifications");

    // ERP provider labels are replaced by tree values in both locales
    for (const key of ["parasut", "logo_tiger", "mikro", "netsis"] as const) {
      expect(tr.integrations.providers[key].label).toBeTruthy();
      expect(en.integrations.providers[key].label).toBeTruthy();
    }

    // anomaly severity + type filters must exist in both locales
    for (const key of ["all", "critical", "high", "medium", "low"] as const) {
      expect(tr.anomalies.filters[key]).toBeTruthy();
      expect(en.anomalies.filters[key]).toBeTruthy();
    }
    for (const key of [
      "duplicate_payment",
      "unusual_amount",
      "unusual_vendor",
      "vendor_concentration",
      "negative_cashflow_streak",
      "expense_spike",
      "missing_revenue",
      "round_number",
      "late_payment",
      "fx_concentration",
    ] as const) {
      expect(tr.anomalies.types[key]).toBeTruthy();
      expect(en.anomalies.types[key]).toBeTruthy();
    }

    // report type labels carry both label and description
    for (const key of ["full", "pnl", "cashflow", "forecast"] as const) {
      expect(tr.reports.types[key].label).toBeTruthy();
      expect(en.reports.types[key].description).toBeTruthy();
    }

    // relative-time helpers differ per locale and never render empty
    expect(tr.integrations.ago.mins).toContain("{count}");
    expect(en.integrations.ago.mins).toContain("{count}");
    expect(tr.integrations.ago.justNow).toBe("Az önce");
    expect(en.integrations.ago.justNow).toBe("Just now");
    expect(tr.notifications.ago.days).not.toBe(en.notifications.ago.days);

    // percent position differs: TR "%{pct}" prefix vs EN "{pct}%" suffix
    expect(tr.anomalies.confidence).toContain("%{pct}");
    expect(en.anomalies.confidence).toContain("{pct}%");
  });

  it("localizes the Group D feature pages (smmm, smmm-onay, audit, risk, cascade, simulation, iliskili-taraf, tr-vertical)", () => {
    const tr = getMessages("tr");
    const en = getMessages("en");

    expect(tr.smmm.title).toBeTruthy();
    expect(en.smmm.title).toBeTruthy();
    expect(tr.smmm.title).not.toBe(en.smmm.title);
    expect(tr.smmmOnay.title).toBeTruthy();
    expect(en.smmmOnay.title).toBeTruthy();
    expect(tr.audit.title).toBeTruthy();
    expect(en.audit.title).toBeTruthy();
    expect(tr.risk.title).toBeTruthy();
    expect(en.risk.title).toBeTruthy();
    expect(tr.simulation.title).toBeTruthy();
    expect(en.simulation.title).toBeTruthy();
    expect(tr.iliskiliTaraf.title).toBeTruthy();
    expect(en.iliskiliTaraf.title).toBeTruthy();
    expect(tr.trVertical.title).toBeTruthy();
    expect(en.trVertical.title).toBeTruthy();

    // workflow stages are real labels rendered as badges — never empty, differ per locale
    for (const key of ["veri_yok", "basarisiz", "onay_bekliyor", "analiz_edildi", "muhurlendi"] as const) {
      expect(tr.smmm.stage[key]).toBeTruthy();
      expect(en.smmm.stage[key]).toBeTruthy();
    }
    expect(tr.smmm.stage.onay_bekliyor).toBe("Onay bekliyor");
    expect(en.smmm.stage.onay_bekliyor).not.toBe(tr.smmm.stage.onay_bekliyor);

    // cascade sub-group lives under risk
    expect(tr.risk.cascade.title).toBeTruthy();
    expect(en.risk.cascade.title).toBeTruthy();

    // likelihood/impact axis labels for the risk matrix
    for (const key of ["rare", "unlikely", "possible", "likely", "almostCertain"] as const) {
      expect(tr.risk.matrix.likelihood[key]).toBeTruthy();
      expect(en.risk.matrix.likelihood[key]).toBeTruthy();
    }

    // relationship groups drive filter chips on iliskili-taraf
    for (const key of ["ortak", "yonetici", "aile", "istirak", "anaOrtaklik", "kilitPersonel", "diger"] as const) {
      expect(tr.iliskiliTaraf.relationships[key]).toBeTruthy();
      expect(en.iliskiliTaraf.relationships[key]).toBeTruthy();
    }
  });
});
