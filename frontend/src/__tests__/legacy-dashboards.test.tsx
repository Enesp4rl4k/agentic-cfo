/**
 * Legacy dashboards (lib/legacy-dashboards): placeholder / non-ledger screens that are not part of the
 * pilot product. With NEXT_PUBLIC_LEGACY_DASHBOARDS off (the default) they are gone from the sidebar in
 * every mode, from the command palette, from the links of other pages, and their URL answers "not found"
 * before any of their code runs. With it on, everything is as before.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { availableCommands } from "@/components/ui/command-palette";
import { getMessages } from "@/lib/i18n";
import { LEGACY_DASHBOARD_HREFS, isHrefAvailable, isLegacyHref, legacyDashboardsEnabled } from "@/lib/legacy-dashboards";
import { hiddenNavItems, visibleNavGroups } from "@/lib/nav-focus";
import { NAV_GROUPS } from "@/lib/nav-items";

const here = path.dirname(fileURLToPath(import.meta.url));
const dashboardDir = path.join(here, "..", "app", "(dashboard)");
type LayoutModule = { default: (props: { children: React.ReactNode }) => React.ReactElement };
// One entry per legacy route: a route in LEGACY_DASHBOARD_HREFS without a layout here (and on disk) fails below.
const layouts: Record<string, () => Promise<LayoutModule>> = {
  "/cto": () => import("@/app/(dashboard)/cto/layout"),
  "/cmo": () => import("@/app/(dashboard)/cmo/layout"),
  "/coo": () => import("@/app/(dashboard)/coo/layout"),
  "/chro": () => import("@/app/(dashboard)/chro/layout"),
  "/compliance": () => import("@/app/(dashboard)/compliance/layout"),
  "/audit": () => import("@/app/(dashboard)/audit/layout"),
  "/analytics/cohort": () => import("@/app/(dashboard)/analytics/cohort/layout"),
};

const OPTIONS = [
  { hasTrPack: true, focusMode: false },
  { hasTrPack: true, focusMode: true },
  { hasTrPack: true, focusMode: true, sizeProfile: "small" as const },
  { hasTrPack: true, focusMode: true, sizeProfile: "medium" as const },
];
const hrefsOf = (groups: { items: { href: string }[] }[]) => groups.flatMap((g) => g.items.map((i) => i.href));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("the flag", () => {
  it("is off unless it is exactly \"true\"", () => {
    expect(legacyDashboardsEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_LEGACY_DASHBOARDS", "1");
    expect(legacyDashboardsEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_LEGACY_DASHBOARDS", "true");
    expect(legacyDashboardsEnabled()).toBe(true);
  });

  it("recognises a legacy path with its query, hash and sub-paths, and nothing else", () => {
    expect(isLegacyHref("/cto")).toBe(true);
    expect(isLegacyHref("/cto?job=abc")).toBe(true);
    expect(isLegacyHref("/analytics/cohort/")).toBe(true);
    expect(isLegacyHref("/analytics/monte-carlo")).toBe(false);
    expect(isLegacyHref("/ceo")).toBe(false);
    expect(isLegacyHref("/cfo")).toBe(false);
    expect(isLegacyHref("/ctoo")).toBe(false);
    expect(isLegacyHref("/")).toBe(false);
  });

  it("makes a legacy link unavailable while off and every other link always available", () => {
    expect(isHrefAvailable("/chro?job=1")).toBe(false);
    expect(isHrefAvailable("/pnl")).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_LEGACY_DASHBOARDS", "true");
    expect(isHrefAvailable("/chro?job=1")).toBe(true);
  });

  it("lists only screens that exist and are in the menu today", () => {
    const menu = new Set(hrefsOf(NAV_GROUPS));
    for (const href of LEGACY_DASHBOARD_HREFS) {
      expect(fs.existsSync(path.join(dashboardDir, ...href.split("/").filter(Boolean), "page.tsx")), href).toBe(true);
      expect(menu.has(href), href).toBe(true);
    }
  });
});

describe("sidebar", () => {
  it("drops every legacy entry in every mode while off, and never offers them under 'more'", () => {
    for (const options of OPTIONS) {
      const shown = hrefsOf(visibleNavGroups(NAV_GROUPS, options));
      const more = hiddenNavItems(NAV_GROUPS, options).map((i) => i.href);
      for (const href of LEGACY_DASHBOARD_HREFS) {
        expect(shown, `${href} shown, ${JSON.stringify(options)}`).not.toContain(href);
        expect(more, `${href} in more, ${JSON.stringify(options)}`).not.toContain(href);
      }
    }
  });

  it("keeps the real screens while off (ceo carries the autonomous-action approvals, cfo the job dashboard)", () => {
    const shown = hrefsOf(visibleNavGroups(NAV_GROUPS, OPTIONS[0]));
    for (const href of ["/ceo", "/cfo", "/risk", "/pnl", "/nakit-radari", "/onay"]) expect(shown).toContain(href);
  });

  it("shows them again, outside focus mode, when on", () => {
    vi.stubEnv("NEXT_PUBLIC_LEGACY_DASHBOARDS", "true");
    const shown = hrefsOf(visibleNavGroups(NAV_GROUPS, OPTIONS[0]));
    for (const href of LEGACY_DASHBOARD_HREFS) expect(shown).toContain(href);
    // in focus mode they wait under "more", as before
    const more = hiddenNavItems(NAV_GROUPS, OPTIONS[1]).map((i) => i.href);
    for (const href of LEGACY_DASHBOARD_HREFS) expect(more).toContain(href);
  });
});

describe("command palette", () => {
  const legacyCommandIds = ["cto", "cmo", "coo", "chro"];

  it("offers none of the legacy dashboards while off", () => {
    const commands = availableCommands();
    const ids = commands.map((c) => c.id);
    for (const id of legacyCommandIds) expect(ids).not.toContain(id);
    for (const c of commands) expect(c.href ? isLegacyHref(c.href) : false, c.id).toBe(false);
    for (const id of ["ceo", "risk", "pnl", "upload", "settings"]) expect(ids).toContain(id);
  });

  it("offers them again when on", () => {
    vi.stubEnv("NEXT_PUBLIC_LEGACY_DASHBOARDS", "true");
    const ids = availableCommands().map((c) => c.id);
    for (const id of legacyCommandIds) expect(ids).toContain(id);
  });
});

describe("direct URL", () => {
  const load = async (href: string) => (await layouts[href]()).default;

  it("has a gate layout on every legacy route, and only on those", () => {
    expect(Object.keys(layouts).sort()).toEqual([...LEGACY_DASHBOARD_HREFS].sort());
    for (const href of LEGACY_DASHBOARD_HREFS) {
      expect(Object.keys(layouts), href).toContain(href);
      const source = fs.readFileSync(path.join(dashboardDir, ...href.split("/").filter(Boolean), "layout.tsx"), "utf-8");
      expect(source, href).toContain("LegacyGate");
    }
  });

  it("answers not found while off, and the page below it is never rendered", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {}); // React logs the render error it rethrows
    const page = vi.fn(() => <p>placeholder numbers</p>);
    const Page = page;
    for (const href of LEGACY_DASHBOARD_HREFS) {
      const Layout = await load(href);
      let thrown: unknown;
      try {
        render(<Layout><Page /></Layout>);
      } catch (error) {
        thrown = error;
      }
      expect((thrown as { digest?: string } | undefined)?.digest, href).toMatch(/NOT_FOUND|404/);
    }
    expect(page).not.toHaveBeenCalled();
  });

  it("renders the page when on", async () => {
    vi.stubEnv("NEXT_PUBLIC_LEGACY_DASHBOARDS", "true");
    for (const href of LEGACY_DASHBOARD_HREFS) {
      const Layout = await load(href);
      expect(render(<Layout><p>the page</p></Layout>).container.textContent, href).toContain("the page");
    }
  });

  it("has a Turkish and an English 'not available' screen", () => {
    expect(getMessages("tr").notFound.title).toBe("Bu sayfa kullanılamıyor");
    expect(getMessages("en").notFound.title).toBeTruthy();
  });
});
