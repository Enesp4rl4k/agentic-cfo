/**
 * Plan v10 §O0 — focus mode keeps the pilot flow in the menu and nothing else.
 * The menu entries are listed here by hand, from what the pilot flow needs.
 */
import { describe, it, expect } from "vitest";
import { FINANCE_HREFS, FOCUS_HREFS, PROFILE_NAV, hiddenNavItems, visibleNavGroups, type SizeProfile } from "@/lib/nav-focus";
import { NAV_GROUPS } from "@/lib/nav-items";

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

  it("keeps the Monday briefing in the focus list", () => {
    expect(FOCUS_HREFS.has("/bulten")).toBe(true);
  });

  it("names no role screen in the focus list", () => {
    for (const href of ["/cto", "/cmo", "/coo", "/chro", "/ceo"]) expect(FOCUS_HREFS.has(href)).toBe(false);
  });
});

const PROFILES: SizeProfile[] = ["micro", "small", "medium"];
const FULL = { hasTrPack: true, focusMode: false } as const;
const menu = (opts: { focusMode: boolean; sizeProfile?: SizeProfile | null }) =>
  new Set(hrefs(visibleNavGroups(NAV_GROUPS, { hasTrPack: true, ...opts })));

describe("PROFILE_NAV: the menu by company-size profile", () => {
  it("states each profile once, with the focus default the server mirrors", () => {
    expect(PROFILES.map((p) => [p, PROFILE_NAV[p].focusDefault])).toEqual([["micro", true], ["small", true], ["medium", false]]);
  });

  it("every entry it names is a real menu entry", () => {
    const real = new Set(NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href)));
    for (const p of PROFILES) for (const href of PROFILE_NAV[p].focusHrefs) expect(real.has(href)).toBe(true);
    const finance = NAV_GROUPS.find((g) => g.label === "finance")?.items.map((i) => i.href) ?? [];
    for (const href of FINANCE_HREFS) expect(finance).toContain(href);
  });

  it("micro keeps the pilot flow, small adds the finance screens, medium keeps the pilot flow only when focus is chosen", () => {
    expect(menu({ focusMode: true, sizeProfile: "micro" })).toEqual(new Set(FOCUS_HREFS));
    expect(menu({ focusMode: true, sizeProfile: "small" })).toEqual(new Set([...FOCUS_HREFS, ...FINANCE_HREFS]));
    expect(menu({ focusMode: true, sizeProfile: "medium" })).toEqual(new Set(FOCUS_HREFS));
  });

  it("without focus mode every profile shows the full menu, and no profile shows less than none", () => {
    const all = menu({ focusMode: false });
    for (const p of PROFILES) expect(menu({ focusMode: false, sizeProfile: p })).toEqual(all);
    expect(menu({ focusMode: true })).toEqual(new Set(FOCUS_HREFS));
  });

  it("lists what focus mode hides, each once, so every screen stays one click away", () => {
    const hidden = hiddenNavItems(NAV_GROUPS, { ...FULL, focusMode: true, sizeProfile: "micro" }).map((i) => i.href);
    expect(new Set(hidden).size).toBe(hidden.length);
    expect(hidden).toContain("/ceo");
    expect(hidden).toContain("/forecast");
    expect(hiddenNavItems(NAV_GROUPS, { ...FULL, focusMode: true, sizeProfile: "small" }).map((i) => i.href)).not.toContain("/forecast");
    expect(hiddenNavItems(NAV_GROUPS, FULL)).toEqual([]);
    const shownAndHidden = new Set([...menu({ focusMode: true, sizeProfile: "micro" }), ...hidden]);
    expect(shownAndHidden).toEqual(menu({ focusMode: false }));
  });
});
