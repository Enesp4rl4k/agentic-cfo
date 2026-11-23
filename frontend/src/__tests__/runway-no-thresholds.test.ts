/**
 * The frontend decides no runway class: a runway figure is never compared with a threshold of the component's own.
 * The class comes from the server (`level`, `attention`, `watch`, `cash_gone`). Display-only comparisons are listed
 * here with their reason.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
// A runway-ish identifier compared with a bare number (other than the 0/1 of a sign or "under a month" display).
const RULE = /\b[\w.?]*(?:runway|pist)[\w.?]*\s*(<=?|>=?)\s*(\d+(?:\.\d+)?)/gi;
const ALLOWED = new Set(["0", "1"]);   // "runway_delta > 0" (a sign) and "< 1" (the 'under a month' wording)

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (name === "__tests__" || name === "generated" || name === "node_modules") return [];
    return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(name) ? [p] : [];
  });
}

describe("runway thresholds", () => {
  it("has no runway comparison with a class-like number in the frontend", () => {
    const hits: string[] = [];
    for (const file of files(SRC)) {
      readFileSync(file, "utf-8").split("\n").forEach((line, i) => {
        for (const m of line.matchAll(RULE)) if (!ALLOWED.has(m[2])) hits.push(`${file.replace(SRC, "src")}:${i + 1} ${m[0]}`);
      });
    }
    expect(hits).toEqual([]);
  });

  it("catches the pattern it forbids", () => {
    expect([..."if (runwayMonths < 6) {".matchAll(RULE)].length).toBe(1);
    expect([..."r.variance.runway_delta >= 0".matchAll(RULE)].filter((m) => !ALLOWED.has(m[2])).length).toBe(0);
  });
});
