/**
 * G16 / plan v11 A0.6: the menu carries i18n keys, not copy, and every key has a
 * label in both languages. A label written straight into the menu cannot compile
 * (labelKey is typed), and a key missing from a locale fails here.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { NAV_GROUPS } from "@/lib/nav-items";
import { getMessages } from "@/lib/i18n";

const here = path.dirname(fileURLToPath(import.meta.url));

describe("menu labels", () => {
  for (const locale of ["tr", "en"] as const) {
    it(`every group and item has a ${locale} label`, () => {
      const menu = getMessages(locale).menu;
      for (const group of NAV_GROUPS) {
        expect(menu.groups[group.label], group.label).toBeTruthy();
        for (const item of group.items) expect(menu.items[item.labelKey], item.href).toBeTruthy();
      }
    });
  }

  it("speaks Turkish to a Turkish company", () => {
    const tr = getMessages("tr").menu;
    expect(tr.items.upload).toBe("Yükle");
    expect(tr.items.cashflow).toBe("Nakit Akışı");
    expect(tr.items.commandCenter).toBe("Komuta Merkezi");
  });

  it("leaves no label written into the layout", () => {
    const layout = fs.readFileSync(path.join(here, "..", "app", "(dashboard)", "layout.tsx"), "utf-8");
    // Line endings differ between checkouts: compare trimmed lines, not raw text.
    const lines = layout.split(/\r?\n/).map((line) => line.trim());
    expect(lines, "bare Dashboard text in the breadcrumb").not.toContain("Dashboard");
    for (const copy of ["\"Cash Flow\"", "\"Upload\"", "\"Command Center\"", "label: \"Completed\""]) {
      expect(layout.includes(copy), copy).toBe(false);
    }
  });
});
