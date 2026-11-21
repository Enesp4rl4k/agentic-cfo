/**
 * The browser's role classes are the backend's, and the middleware uses them.
 *
 * The old middleware ranked viewer < analyst < editor < admin < owner, so `cfo`
 * and `smmm` (real backend roles) ranked -1 and were sent away from /upload,
 * /settings/* and /pilot, while `editor` (no such role) ranked above analyst.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { ROLE_CLASSES, ROUTE_RULES, hasRoleClass } from "@/lib/roles";

const ACCESS_PY = path.resolve(__dirname, "../../../backend/app/api/access.py");

/** `NAME = frozenset({"a", "b"})` in access.py, as a sorted list. */
function backendSet(name: string): string[] {
  const src = readFileSync(ACCESS_PY, "utf-8");
  const m = new RegExp(String.raw`^${name} = frozenset\(\{([^}]*)\}\)`, "m").exec(src);
  if (!m) throw new Error(`${name} not found in access.py`);
  return [...m[1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]).sort();
}

describe("role classes mirror the backend", () => {
  it.each([
    ["contributor", "CONTRIBUTOR_ROLES"],
    ["writer", "WRITER_ROLES"],
    ["decider", "DECIDER_ROLES"],
  ] as const)("%s = %s", (cls, name) => {
    expect([...ROLE_CLASSES[cls]].sort()).toEqual(backendSet(name));
  });

  it("contributor is writer plus analyst, nothing else", () => {
    expect([...ROLE_CLASSES.contributor].sort()).toEqual([...ROLE_CLASSES.writer, "analyst"].sort());
  });
});

describe("hasRoleClass", () => {
  it("lets cfo and smmm in where they belong, and keeps viewers out of everything", () => {
    for (const role of ["cfo", "smmm"]) {
      expect(hasRoleClass(role, "contributor")).toBe(true);
      expect(hasRoleClass(role, "writer")).toBe(true);
      expect(hasRoleClass(role, "decider")).toBe(false); // cfo is a writer, not a decider
    }
    for (const cls of Object.keys(ROLE_CLASSES) as Array<keyof typeof ROLE_CLASSES>) {
      expect(hasRoleClass("viewer", cls)).toBe(false);
      expect(hasRoleClass("editor", cls)).toBe(false); // not a backend role
      expect(hasRoleClass(undefined, cls)).toBe(false);
    }
  });

  it("an analyst may upload but not write or decide", () => {
    expect(hasRoleClass("analyst", "contributor")).toBe(true);
    expect(hasRoleClass("analyst", "writer")).toBe(false);
    expect(hasRoleClass("analyst", "decider")).toBe(false);
  });
});

describe("route rules", () => {
  const allowed = (pathname: string, role: string) => {
    const rule = ROUTE_RULES.find((r) => pathname.startsWith(r.prefix));
    return !rule || hasRoleClass(role, rule.cls);
  };

  it("sends cfo and smmm to /upload but not into workspace member management", () => {
    expect(allowed("/upload", "cfo")).toBe(true);
    expect(allowed("/upload", "smmm")).toBe(true);
    expect(allowed("/upload", "analyst")).toBe(true);
    expect(allowed("/upload", "viewer")).toBe(false);
    expect(allowed("/settings/workspace", "cfo")).toBe(false);
    expect(allowed("/settings/workspace", "admin")).toBe(true);
  });
});
