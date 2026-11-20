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
]);

type NavItem = { href: string; trPack?: boolean };
type NavGroup<T extends NavItem> = { label: string; items: T[] };

/** The groups a company sees: the Turkey pack entries need the pack, and focus mode keeps only the flow. */
export function visibleNavGroups<T extends NavItem, G extends NavGroup<T>>(
  groups: readonly G[],
  { hasTrPack, focusMode }: { hasTrPack: boolean; focusMode: boolean },
): G[] {
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) => (!item.trPack || hasTrPack) && (!focusMode || FOCUS_HREFS.has(item.href)),
      ),
    }))
    .filter((group) => group.items.length > 0);
}
