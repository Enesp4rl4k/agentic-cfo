import { isHrefAvailable } from "@/lib/legacy-dashboards";

/**
 * Which menu entries a company in focus mode sees (plan v10 §O0).
 *
 * A pilot company pilots one flow: connect its documents, read its ledger and
 * cash, act on it. Everything else stays in the product and is only hidden from
 * the menu; its URLs still open.
 */
export const FOCUS_HREFS: ReadonlySet<string> = new Set([
  "/baslangic",
  "/command-center",
  "/nakit-radari",
  "/bulten",
  "/baglan",
  "/upload",
  "/pnl",
  "/cashflow",
  "/settings/workspace",
  // The weekly loop closes with approval and the report (DESIGN.md: Observe, Orient, Decide, Act).
  "/onay",
  "/takvim",
  "/reports",
]);

export type SizeProfile = "micro" | "small" | "medium";

/** The finance screens of the menu's "finance" group that a focus-mode company does not already see. */
export const FINANCE_HREFS: readonly string[] = ["/forecast", "/budget", "/tax"];

/**
 * What a confirmed company-size profile does to the menu, in one place.
 *
 * - `focusDefault`: whether confirming the profile switches focus mode on (unless a person has ever
 *   chosen focus mode themselves; the server decides that, `size_profile` mirrors `FOCUS_DEFAULT` there).
 * - `focusHrefs`: the entries visible while focus mode is on. micro: the pilot flow; small: the flow plus
 *   the finance screens; medium: the pilot flow when someone chose focus mode, otherwise the menu is full.
 *
 * Only the menu changes. Every route stays reachable by URL and nothing is permission-gated by profile.
 */
export const PROFILE_NAV: Record<SizeProfile, { focusDefault: boolean; focusHrefs: ReadonlySet<string> }> = {
  micro: { focusDefault: true, focusHrefs: FOCUS_HREFS },
  small: { focusDefault: true, focusHrefs: new Set([...FOCUS_HREFS, ...FINANCE_HREFS]) },
  medium: { focusDefault: false, focusHrefs: FOCUS_HREFS },
};

export type NavOptions = { hasTrPack: boolean; focusMode: boolean; sizeProfile?: SizeProfile | null };

type NavItem = { href: string; trPack?: boolean };
type NavGroup<T extends NavItem> = { label: string; items: T[] };

function shown(item: NavItem, { hasTrPack, focusMode, sizeProfile }: NavOptions): boolean {
  if (item.trPack && !hasTrPack) return false;
  if (!isHrefAvailable(item.href)) return false;
  if (!focusMode) return true;
  return (sizeProfile ? PROFILE_NAV[sizeProfile].focusHrefs : FOCUS_HREFS).has(item.href);
}

/** The groups a company sees: the Turkey pack entries need the pack, and focus mode keeps only the flow its profile allows. */
export function visibleNavGroups<T extends NavItem, G extends NavGroup<T>>(
  groups: readonly G[],
  options: NavOptions,
): G[] {
  return groups
    .map((group) => ({ ...group, items: group.items.filter((item) => shown(item, options)) }))
    .filter((group) => group.items.length > 0);
}

/** What focus mode hides from the menu, each entry once: it is listed under "Daha fazla" and still opens. */
export function hiddenNavItems<G extends NavGroup<NavItem>>(groups: readonly G[], options: NavOptions): G["items"][number][] {
  const seen = new Set<string>();
  return groups.flatMap((group) => group.items).filter((item) => {
    // A legacy dashboard that is switched off is not "hidden": it does not exist, so it is not offered under "Daha fazla" either.
    if ((item.trPack && !options.hasTrPack) || !isHrefAvailable(item.href) || shown(item, options) || seen.has(item.href)) return false;
    seen.add(item.href);
    return true;
  });
}
