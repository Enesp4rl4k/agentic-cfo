/**
 * Shared wire-normalization primitives.
 *
 * The role dashboards (`ceo-result`, `cto-result`, `coo-result`, `cmo-result`,
 * `chro-result`, `audit-result`) each used to carry their own private copies of
 * these tiny guards. They were byte-identical, so keeping six copies only
 * invited drift (fix a coercion in one role and forget the other five). They
 * live here once.
 *
 * Deliberately *not* shared: `str` and `numScores`. Those have per-role
 * contracts — most roles return `""` / `{}` on a miss while CHRO returns
 * `null` — so each role keeps a local helper that encodes its own fallback.
 */

/** True for a plain object (not null, not an array). */
export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Coerce a wire value to a finite number, or null. */
export function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

/** `num`, defaulting to 0. */
export function num0(v: unknown): number {
  return num(v) ?? 0;
}

/** A non-empty string, or null. */
export function strOrNull(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

/** An array filtered down to its plain-object members. */
export function records(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter(isRecord) : [];
}
