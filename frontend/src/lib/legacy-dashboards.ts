/**
 * Legacy dashboards: screens that are not part of the pilot product.
 *
 * Their content is placeholder or not drawn from the organisation's ledger
 * (a prefilled sample CSV, "Acme Corp", fixed cohorts, a sample audit), and a
 * pilot user must never meet a number that has no real source. They stay in the
 * repository for development behind ONE flag:
 *
 *   NEXT_PUBLIC_LEGACY_DASHBOARDS=true   (default: off)
 *
 * Off: the entry is gone from the sidebar in every mode, from the command
 * palette and from the links of other pages, and the direct URL answers with
 * the app's "not found" page (see LegacyGate) before any of its code runs.
 * On: everything behaves as it did before.
 *
 * The flag is read at call time, like `isDemoMode()`, so tests can stub it.
 * `NEXT_PUBLIC_*` is inlined by the build, so this is a build-time switch.
 */
export const LEGACY_DASHBOARD_HREFS: readonly string[] = [
  "/cto",
  "/cmo",
  "/coo",
  "/chro",
  "/compliance",
  "/audit",
  "/analytics/cohort",
];

export function legacyDashboardsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_LEGACY_DASHBOARDS === "true";
}

/** Whether an in-app path (query string and hash ignored) is one of the legacy dashboards. */
export function isLegacyHref(href: string): boolean {
  const path = href.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
  return LEGACY_DASHBOARD_HREFS.some((legacy) => path === legacy || path.startsWith(`${legacy}/`));
}

/** False for a legacy dashboard while the flag is off: the one question every menu, palette and link asks. */
export function isHrefAvailable(href: string): boolean {
  return legacyDashboardsEnabled() || !isLegacyHref(href);
}
