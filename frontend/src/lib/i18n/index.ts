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

/**
 * The product's audience is Turkish SMEs and their accountants, so Turkish is
 * the default whenever nothing says otherwise. An explicit choice of English
 * (an org stored as "en-*" or a cached "en") is respected.
 */
export const DEFAULT_APP_LOCALE: AppLocale = "tr";

export function resolveAppLocale(orgLocale?: string | null): AppLocale {
  if (!orgLocale) return DEFAULT_APP_LOCALE;
  const lower = orgLocale.toLowerCase();
  if (lower.startsWith("en")) return "en";
  return "tr";
}

export function getMessages(locale: AppLocale = DEFAULT_APP_LOCALE): MessageTree {
  return DICTS[locale] ?? en;
}

/**
 * Locale to paint with before `/org/me` resolves.
 *
 * The org row stays the source of truth, but waiting for it makes every
 * dashboard paint its role header in English and flip to Turkish a beat later —
 * wrong language in the position users read first. The last resolved locale
 * wins when we have one; otherwise Turkish — a first visit does not borrow the
 * browser language, since an English-configured browser is not a request for an
 * English finance product.
 */
export function detectInitialLocale(
  cached?: string | null,
  languages: readonly string[] = [],
): AppLocale {
  if (cached) return resolveAppLocale(cached);
  void languages; // kept in the signature for callers; the default is Turkish
  return DEFAULT_APP_LOCALE;
}

export type { MessageTree };
