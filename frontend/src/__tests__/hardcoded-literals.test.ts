/**
 * No new hard-coded, user-visible text in JSX.
 *
 * A Turkish user must never meet a string that is not in the message files, so
 * JSX text, copy-bearing attributes (placeholder, title, aria-label, alt, label,
 * description...) and toast/dialog calls under src/app and src/components must
 * come from `useI18n()` (`t.*`). The scan is AST based (helpers/literal-scan.ts),
 * so comments, class names, routes and `data-testid`s never match; brand names,
 * Turkish tax acronyms, file formats, units and currency codes are allowlisted
 * there, each group with its reason.
 *
 * Ratchet, like the casing gate: `hardcoded-literals.baseline.json` pins today's
 * per-file counts of legacy literals. A file may only go down (and must then
 * lower its baseline); a file that is not listed must be clean. Regenerate after
 * a migration with:
 *   LITERALS_BASELINE_UPDATE=1 npx vitest run hardcoded-literals
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isUserCopy, scanAll, scanSource } from "./helpers/literal-scan";

const here = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.join(here, "..");
const BASELINE_FILE = path.join(here, "hardcoded-literals.baseline.json");

type Counts = Record<string, number>;

function countByFile(): Counts {
  const out: Counts = {};
  for (const f of scanAll(srcRoot)) out[f.file] = (out[f.file] ?? 0) + 1;
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b)));
}

describe("scanner", () => {
  it("flags JSX text, copy attributes and toast calls", () => {
    const src = `export function X() { toast("Saved"); return <div><p>Hello world</p><input placeholder="Search" aria-label="Close" data-testid="x" className="a b" /></div>; }`;
    const kinds = scanSource("x.tsx", src).map((f) => f.kind).sort();
    expect(kinds).toEqual(["attr", "attr", "call", "jsx-text"]);
  });

  it("lets brand names, acronyms, units and identifiers through", () => {
    for (const ok of ["SMMM", "KDV", "TL", "CSV", "Tiphys", "P25", "e-Fatura", "employee_id, department, level", "12 %", "—", "·"]) {
      expect(isUserCopy(ok), ok).toBe(false);
    }
    for (const bad of ["Save", "Kaydet", "Select category", "Genel analiz"]) {
      expect(isUserCopy(bad), bad).toBe(true);
    }
  });
});

describe("hard-coded user-visible literals", () => {
  const baseline: Counts = fs.existsSync(BASELINE_FILE) ? JSON.parse(fs.readFileSync(BASELINE_FILE, "utf-8")) : {};
  const current = countByFile();

  if (process.env.LITERALS_BASELINE_UPDATE) {
    it("rewrites the baseline", () => {
      fs.writeFileSync(BASELINE_FILE, JSON.stringify(current, null, 2) + "\n");
    });
    return;
  }

  it("has no new literal in a file that is not baselined, and none added to a baselined file", () => {
    const grew = Object.entries(current)
      .filter(([file, n]) => n > (baseline[file] ?? 0))
      .map(([file, n]) => `${file}: ${n} literal(s), baseline ${baseline[file] ?? 0}`);
    const detail = scanAll(srcRoot)
      .filter((f) => grew.some((g) => g.startsWith(`${f.file}:`)))
      .map((f) => `${f.file}:${f.line} [${f.kind}] ${f.text}`);
    expect(grew, `Move this text into src/lib/i18n/messages/{tr,en}.ts and read it through useI18n().\n${detail.join("\n")}`).toEqual([]);
  });

  it("asks for the baseline to be lowered when a file got cleaner", () => {
    const stale = Object.entries(baseline)
      .filter(([file, n]) => (current[file] ?? 0) < n)
      .map(([file, n]) => `${file}: baseline ${n}, now ${current[file] ?? 0}`);
    expect(stale, "Lower hardcoded-literals.baseline.json (LITERALS_BASELINE_UPDATE=1).").toEqual([]);
  });

  it("never baselines the pilot's own screens", () => {
    const never = ["components/demo/", "components/macro/"];
    expect(Object.keys(baseline).filter((f) => never.some((p) => f.startsWith(p)))).toEqual([]);
  });
});
