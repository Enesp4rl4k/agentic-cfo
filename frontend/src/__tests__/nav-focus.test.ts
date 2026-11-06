/**
 * Plan v10 §O0 — focus mode keeps the pilot flow in the menu and nothing else.
 * The menu entries are listed here by hand, from what the pilot flow needs.
 */
import { describe, it, expect } from "vitest";
import { FOCUS_HREFS, visibleNavGroups } from "@/lib/nav-focus";

const GROUPS = [
  {
    label: "General",
    items: [
      { href: "/baslangic" },
      { href: "/command-center" },
      { href: "/kurumsallasma" },
      { href: "/baglan" },
      { href: "/pnl" },
    ],
  },
  { label: "Finance", items: [{ href: "/cashflow" }, { href: "/budget" }, { href: "/tax" }] },
  { label: "C-Suite", items: [{ href: "/cto" }, { href: "/cmo" }, { href: "/coo" }, { href: "/chro" }, { href: "/ceo" }] },
  { label: "Portal", items: [{ href: "/smmm", trPack: true }, { href: "/settings/workspace" }] },
];

const hrefs = (groups: { items: { href: string }[] }[]) => groups.flatMap((g) => g.items.map((i) => i.href));

describe("visibleNavGroups", () => {
  it("shows every entry when focus mode is off", () => {
    const shown = visibleNavGroups(GROUPS, { hasTrPack: true, focusMode: false });
    expect(hrefs(shown)).toEqual(hrefs(GROUPS));
  });

  it("keeps the pilot flow and hides the rest in focus mode", () => {
    const shown = hrefs(visibleNavGroups(GROUPS, { hasTrPack: true, focusMode: true }));
    expect(shown).toEqual(["/baslangic", "/command-center", "/baglan", "/pnl", "/cashflow", "/settings/workspace"]);
  });

  it("leaves out the groups focus mode empties", () => {
    const labels = visibleNavGroups(GROUPS, { hasTrPack: true, focusMode: true }).map((g) => g.label);
    expect(labels).toEqual(["General", "Finance", "Portal"]);
  });

  it("still asks the Turkey pack for its own entries", () => {
    expect(hrefs(visibleNavGroups(GROUPS, { hasTrPack: false, focusMode: false }))).not.toContain("/smmm");
  });

  it("names no role screen in the focus list", () => {
    for (const href of ["/cto", "/cmo", "/coo", "/chro", "/ceo"]) expect(FOCUS_HREFS.has(href)).toBe(false);
  });
});
