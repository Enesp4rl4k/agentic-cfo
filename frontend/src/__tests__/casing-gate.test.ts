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
const componentsDir = path.join(here, "..", "components");

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

function pageFiles(): Array<{ where: string; file: string }> {
  if (!fs.existsSync(dashboardDir)) return [];
  return fs
    .readdirSync(dashboardDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => ({ where: `${d.name}/page.tsx`, file: path.join(dashboardDir, d.name, "page.tsx") }))
    .filter((p) => fs.existsSync(p.file));
}

// V2: components carry copy too (stress card, product tour, demo banners) —
// every .tsx under components/** is scanned with the same rules.
function componentFiles(): Array<{ where: string; file: string }> {
  if (!fs.existsSync(componentsDir)) return [];
  return (fs.readdirSync(componentsDir, { recursive: true }) as string[])
    .filter((rel) => rel.endsWith(".tsx"))
    .map((rel) => ({
      where: `components/${rel.split(path.sep).join("/")}`,
      file: path.join(componentsDir, rel),
    }));
}

function scannedFiles(): Array<{ where: string; file: string }> {
  return [...pageFiles(), ...componentFiles()];
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
  for (const { where, file } of scannedFiles()) {
    let inTemplate = false;
    const lines = fs.readFileSync(file, "utf-8").split(/\r?\n/);
    lines.forEach((raw, i) => {
      const ticks = countBackticks(raw);
      const wasInTemplate = inTemplate;
      if (ticks % 2 === 1) inTemplate = !inTemplate;
      if (wasInTemplate) return; // sample-data content — data, not copy
      if (isCommentLine(raw)) return;
      if (TR.test(raw) && !trOnlyInsideRegex(raw)) {
        findings.push({ where, line: i + 1, text: raw.trim().slice(0, 120) });
      }
    });
  }
  return findings;
}

function scanCasing(): Finding[] {
  const findings: Finding[] = [];
  for (const { where, file } of scannedFiles()) {
    const lines = fs.readFileSync(file, "utf-8").split(/\r?\n/);
    lines.forEach((raw, i) => {
      if (isCommentLine(raw)) return;
      if (UI_COPY.test(raw) && BAD_I.test(raw)) {
        findings.push({ where, line: i + 1, text: raw.trim().slice(0, 120) });
      }
    });
  }
  return findings;
}

function format(list: Finding[]): string {
  return list.map((f) => `${f.where}:${f.line}: ${f.text}`).join("\n");
}

// ── Component ratchet (V2) ─────────────────────────────────────────────────────
// Widening the scan to components/** surfaced ~800 legacy lines in ~50 files —
// a migration, not a one-commit fix. Like the mypy allowlist, the baseline pins
// today's per-file counts: a file may only go down (and must then lower its
// baseline), a file not listed must be clean, and demo/macro are never listed.
// Regenerate after a migration with: CASING_BASELINE_UPDATE=1 npx vitest run casing-gate
const BASELINE_FILE = path.join(here, "casing-gate.baseline.json");
const NEVER_BASELINED = ["components/demo/", "components/macro/"];

type Counts = Record<string, number>;
interface Baseline { embedded: Counts; casing: Counts }

function countByFile(list: Finding[]): Counts {
  const out: Counts = {};
  for (const f of list) {
    if (!f.where.startsWith("components/")) continue;
    out[f.where] = (out[f.where] ?? 0) + 1;
  }
  return out;
}

function sortedCounts(c: Counts): Counts {
  return Object.fromEntries(Object.entries(c).sort(([a], [b]) => a.localeCompare(b)));
}

function loadBaseline(): Baseline {
  if (process.env.CASING_BASELINE_UPDATE === "1") {
    const fresh: Baseline = {
      embedded: sortedCounts(countByFile(scanEmbeddedTr())),
      casing: sortedCounts(countByFile(scanCasing())),
    };
    fs.writeFileSync(BASELINE_FILE, JSON.stringify(fresh, null, 2) + "\n", "utf-8");
    return fresh;
  }
  return JSON.parse(fs.readFileSync(BASELINE_FILE, "utf-8")) as Baseline;
}

function ratchetViolations(actual: Counts, allowed: Counts): string[] {
  const problems: string[] = [];
  for (const [file, n] of Object.entries(actual)) {
    const cap = allowed[file] ?? 0;
    if (n > cap) problems.push(`${file}: ${n} > baseline ${cap} (move the new copy to i18n)`);
  }
  for (const [file, cap] of Object.entries(allowed)) {
    const n = actual[file] ?? 0;
    if (n < cap) problems.push(`${file}: ${n} < baseline ${cap} (lower the baseline — the ratchet only tightens)`);
  }
  return problems;
}

describe("U4 grep kapısı (gömülü TR + İ-casing)", () => {
  it("dashboard pages carry no embedded Turkish copy outside i18n messages", () => {
    const offenders = scanEmbeddedTr().filter((f) => !f.where.startsWith("components/"));
    expect(offenders, `gömülü TR metin (i18n'e taşınmalı):\n${format(offenders)}`).toEqual([]);
  });

  it("dashboard pages contain no wrong-cased I+vowel in copy strings", () => {
    const offenders = scanCasing().filter((f) => !f.where.startsWith("components/"));
    expect(offenders, `hatalı İ-casing (I+sesli harf):\n${format(offenders)}`).toEqual([]);
  });

  it("components only ever lose embedded Turkish copy (ratchet)", () => {
    const baseline = loadBaseline();
    const problems = ratchetViolations(countByFile(scanEmbeddedTr()), baseline.embedded);
    expect(problems, `gömülü TR ratchet:\n${problems.join("\n")}`).toEqual([]);
  });

  it("components only ever lose wrong-cased I+vowel (ratchet)", () => {
    const baseline = loadBaseline();
    const problems = ratchetViolations(countByFile(scanCasing()), baseline.casing);
    expect(problems, `İ-casing ratchet:\n${problems.join("\n")}`).toEqual([]);
  });

  it("demo and macro components are never baselined — they must be clean", () => {
    const baseline = loadBaseline();
    const listed = [...Object.keys(baseline.embedded), ...Object.keys(baseline.casing)]
      .filter((file) => NEVER_BASELINED.some((dir) => file.startsWith(dir)));
    expect(listed).toEqual([]);
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
