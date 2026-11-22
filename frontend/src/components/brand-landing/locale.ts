import { cookies, headers } from "next/headers";
import { LOCALE_COOKIE_KEY, detectInitialLocale, type AppLocale } from "@/lib/i18n";

/**
 * Locale for the brand landing, resolved on the server exactly as the root layout
 * does it: the locale cookie wins and a first visit gets Turkish (the default);
 * Accept-Language is no longer consulted. A component rendered without a locale
 * also defaults to Turkish.
 */
export function resolveLandingLocale(): AppLocale {
  const cached = cookies().get(LOCALE_COOKIE_KEY)?.value;
  const languages = (headers().get("accept-language") ?? "")
    .split(",")
    .map((part) => part.split(";")[0].trim())
    .filter(Boolean);
  return detectInitialLocale(cached, languages);
}
