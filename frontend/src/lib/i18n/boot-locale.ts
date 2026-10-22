"use client";
/**
 * Server-provided boot locale.
 *
 * The root layout resolves the first-paint locale on the server (locale
 * cookie → Accept-Language) and passes it through `Providers`. Server HTML
 * and the first client render therefore paint the same language — no English
 * flash while org settings load, and no hydration mismatch when the cache
 * catches up.
 */
import { createContext, useContext } from "react";
import type { AppLocale } from "@/lib/i18n";

export const BootLocaleContext = createContext<AppLocale | null>(null);

export function useBootLocale(): AppLocale | null {
  return useContext(BootLocaleContext);
}
