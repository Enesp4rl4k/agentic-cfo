/**
 * U4 / 1.2 grep kapısı — embedded TR metin + İ-casing.
 *
 * Embedded copy: any non-comment line carrying Turkish-specific characters is
 * flagged, with two data exemptions (data is not copy — it is not translated):
 *   1. lines inside multi-line backtick templates (sample CSV blocks: audit
 *      findings/controls/coverage, coo/chro/templates sample rows);
 *   2. lines whose TR characters live inside a /…/ regex literal (chat intent
 *      matchers, coo status filter — they match TR data, they are not shown).
 * This subsumes scripts/_scan_ui_strings.py's copy-pattern heuristic, which
 * missed bare-JSX paragraphs (analytics info banner, pipeline status badges)
 * that a manual wide sweep caught and moved into i18n messages on 2026-10-14.
 *
 * İ-casing: tr.ts is the Turkish copy home, so ASCII "I" followed by a
 * lowercase vowel there is wrong-cased İ ("Iade" → "İade"). Copy strings in
 * pages get the same check; acronyms (I + consonant / uppercase) don't match.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dashboardDir = path.join(here, "..", "app", "(dashboard)");

// Turkish-specific characters (same class as the Python migration scan).
const TR = /[çÇğĞıİöÖşŞüÜ]/;
// Quoted string containing a space, or bare JSX text — copy-looking context.
const UI_COPY = /["'`][^"'`\n]* [^"'`\n]*["'`]|>[^<>{}\n]{3,}</;
// ASCII I + lowercase vowel — never valid Turkish casing.
const BAD_I = /I[aeiou]/;
// TR characters confined to a /…/ regex segment → matcher code, not copy.
function trOnlyInsideRegex(line: string): boolean {
  const withoutRegex = line.replace(/\/[^/\n]*\//g, "");
  return !TR.test(withoutRegex);
}

function pageFiles(): Array<{ name: string; file: string }> {
  if (!fs.existsSync(dashboardDir)) return [];
  return fs
    .readdirSync(dashboardDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => ({ name: d.name, file: path.join(dashboardDir, d.name, "page.tsx") }))
    .filter((p) => fs.existsSync(p.file));
}

function isCommentLine(line: string): boolean {
  const s = line.trim();
  return s.startsWith("//") || s.startsWith("*") || s.startsWith("/*") || s.startsWith("{/*");
}

function countBackticks(line: string): number {
  return (line.match(/(?<!\\)`/g) ?? []).length;
}

interface Finding {
  where: string;
  line: number;
  text: string;
}

function scanEmbeddedTr(): Finding[] {
  const findings: Finding[] = [];
  for (const { name, file } of pageFiles()) {
    let inTemplate = false;
    const lines = fs.readFileSync(file, "utf-8").split(/\r?\n/);
    lines.forEach((raw, i) => {
      const ticks = countBackticks(raw);
      const wasInTemplate = inTemplate;
      if (ticks % 2 === 1) inTemplate = !inTemplate;
      if (wasInTemplate) return; // sample-data content — data, not copy
      if (isCommentLine(raw)) return;
      if (TR.test(raw) && !trOnlyInsideRegex(raw)) {
        findings.push({ where: `${name}/page.tsx`, line: i + 1, text: raw.trim().slice(0, 120) });
      }
    });
  }
  return findings;
}

function scanCasing(): Finding[] {
  const findings: Finding[] = [];
  for (const { name, file } of pageFiles()) {
    const lines = fs.readFileSync(file, "utf-8").split(/\r?\n/);
    lines.forEach((raw, i) => {
      if (isCommentLine(raw)) return;
      if (UI_COPY.test(raw) && BAD_I.test(raw)) {
        findings.push({ where: `${name}/page.tsx`, line: i + 1, text: raw.trim().slice(0, 120) });
      }
    });
  }
  return findings;
}

function format(list: Finding[]): string {
  return list.map((f) => `${f.where}:${f.line}: ${f.text}`).join("\n");
}

describe("U4 grep kapısı (gömülü TR + İ-casing)", () => {
  it("dashboard pages carry no embedded Turkish copy outside i18n messages", () => {
    const offenders = scanEmbeddedTr();
    expect(offenders, `gömülü TR metin (i18n'e taşınmalı):\n${format(offenders)}`).toEqual([]);
  });

  it("dashboard pages contain no wrong-cased I+vowel in copy strings", () => {
    const offenders = scanCasing();
    expect(offenders, `hatalı İ-casing (I+sesli harf):\n${format(offenders)}`).toEqual([]);
  });

  it("tr.ts has no wrong-cased I+vowel (Iade → İade)", () => {
    const trFile = path.join(here, "..", "lib", "i18n", "messages", "tr.ts");
    const offenders = fs
      .readFileSync(trFile, "utf-8")
      .split(/\r?\n/)
      .map((line, i) => ({ line, i }))
      .filter(({ line }) => BAD_I.test(line) && !isCommentLine(line))
      .map(({ line, i }) => `${i + 1}: ${line.trim().slice(0, 120)}`);
    expect(offenders, `tr.ts hatalı İ-casing:\n${offenders.join("\n")}`).toEqual([]);
  });
});
