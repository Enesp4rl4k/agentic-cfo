import type { MessageTree } from "./messages/en";

/** Label groups under `t.codes` that map a backend code to words. */
export type CodeGroup = Exclude<keyof MessageTree["codes"], "unknown">;

/**
 * The words for a backend code (`awaiting_review`, `other_expense`, `smmm`...).
 *
 * A code the frontend has no label for is shown as "Bilinmeyen durum: <code>"
 * (or its English twin) — visibly unmapped, never a bare raw key and never blank.
 * Backend payloads are not changed to fit: add the code to `codes.<group>` in
 * both message files instead.
 */
export function codeLabel(t: MessageTree, group: CodeGroup, code: string | null | undefined): string {
  const raw = (code ?? "").trim();
  if (!raw) return t.codes.unknown.replace("{code}", "—");
  const map = t.codes[group] as Record<string, string>;
  return map[raw] ?? map[raw.toLowerCase()] ?? t.codes.unknown.replace("{code}", raw);
}

/** Same fallback as `codeLabel`, for a label map that lives in a feature's own section. */
export function mapLabel(t: MessageTree, map: Record<string, string>, code: string | null | undefined): string {
  const raw = (code ?? "").trim();
  if (!raw) return t.codes.unknown.replace("{code}", "—");
  return map[raw] ?? map[raw.toLowerCase()] ?? t.codes.unknown.replace("{code}", raw);
}
