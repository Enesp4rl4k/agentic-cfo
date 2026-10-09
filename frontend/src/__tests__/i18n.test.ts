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
});
