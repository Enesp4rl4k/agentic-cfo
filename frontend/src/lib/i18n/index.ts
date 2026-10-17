import { STORAGE_PREFIX } from "@/lib/branding";
import { en, type MessageTree } from "./messages/en";
import { tr } from "./messages/tr";

export type AppLocale = "en" | "tr";

/**
 * Cookie name mirroring the localStorage locale cache — written client-side
 * whenever the org locale resolves, read by the server root layout so the
 * very first HTML of the next request already ships in the right language.
 */
export const LOCALE_COOKIE_KEY = `${STORAGE_PREFIX}_locale`;

const DICTS: Record<AppLocale, MessageTree> = { en, tr };

export function resolveAppLocale(orgLocale?: string | null): AppLocale {
  if (!orgLocale) return "en";
  const lower = orgLocale.toLowerCase();
  if (lower.startsWith("tr")) return "tr";
  return "en";
}

export function getMessages(locale: AppLocale = "en"): MessageTree {
  return DICTS[locale] ?? en;
}

/**
 * Locale to paint with before `/org/me` resolves.
 *
 * The org row stays the source of truth, but waiting for it makes every
 * dashboard paint its role header in English and flip to Turkish a beat later —
 * wrong language in the position users read first. The last resolved locale
 * wins when we have one; a first visit borrows the browser language; "en" is
 * the final fallback.
 */
export function detectInitialLocale(
  cached?: string | null,
  languages: readonly string[] = [],
): AppLocale {
  if (cached) return resolveAppLocale(cached);
  if (languages.some((lang) => lang?.toLowerCase().startsWith("tr"))) return "tr";
  return "en";
}

export type { MessageTree };
