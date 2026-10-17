"use client";

import { useContext, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  detectInitialLocale,
  getMessages,
  LOCALE_COOKIE_KEY,
  resolveAppLocale,
  type AppLocale,
  type MessageTree,
} from "@/lib/i18n";
import { BootLocaleContext } from "@/lib/i18n/boot-locale";
import { useOrgSettings } from "@/hooks/useOrgSettings";

/** Layout effect on the client, inert during SSR (React warns if you don't). */
const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

function readCachedLocale(): string | null {
  try {
    return window.localStorage.getItem(LOCALE_COOKIE_KEY);
  } catch {
    return null; // private mode / storage disabled
  }
}

function writeCachedLocale(locale: AppLocale) {
  try {
    window.localStorage.setItem(LOCALE_COOKIE_KEY, locale);
  } catch {
    /* private mode / storage disabled — detection falls back to browser lang */
  }
  try {
    // Mirror to a cookie so the server root layout paints the *next* request
    // in this locale — SSR first paint (DESIGN.md locale principle).
    document.cookie = `${LOCALE_COOKIE_KEY}=${locale}; path=/; max-age=31536000; samesite=lax`;
  } catch {
    /* cookies disabled — client-side boot detection still covers paint */
  }
}

function browserLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  return navigator.languages?.length ? navigator.languages : [navigator.language];
}

export function useI18n(): { locale: AppLocale; t: MessageTree } {
  const { org } = useOrgSettings();
  const serverLocale = useContext(BootLocaleContext);

  // The server rendered with `serverLocale` (cookie → Accept-Language), so the
  // first client render starts there too — hydration parity. The layout
  // effect then re-resolves from the localStorage cache / browser language
  // before first paint; the org row stays authoritative once it loads.
  const [bootLocale, setBootLocale] = useState<AppLocale | null>(serverLocale);
  useIsomorphicLayoutEffect(() => {
    setBootLocale(detectInitialLocale(readCachedLocale(), browserLanguages()));
  }, []);

  const locale = org ? resolveAppLocale(org.locale) : (bootLocale ?? "en");

  // The org row is authoritative — remember it for the next paint (and, via
  // the cookie, for the server's next render).
  useEffect(() => {
    if (org) writeCachedLocale(resolveAppLocale(org.locale));
  }, [org]);

  const t = useMemo(() => getMessages(locale), [locale]);
  return { locale, t };
}
