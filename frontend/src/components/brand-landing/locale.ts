import { cookies, headers } from "next/headers";
import { LOCALE_COOKIE_KEY, detectInitialLocale, type AppLocale } from "@/lib/i18n";

/**
 * Locale for the brand landing, resolved on the server exactly as the root layout
 * does it: the locale cookie wins, Accept-Language seeds a first visit, and the
 * last fallback is "en". The landing's own default (Turkish) applies only when
 * a component is rendered without a locale, never to a visitor.
 */
export function resolveLandingLocale(): AppLocale {
  const cached = cookies().get(LOCALE_COOKIE_KEY)?.value;
  const languages = (headers().get("accept-language") ?? "")
    .split(",")
    .map((part) => part.split(";")[0].trim())
    .filter(Boolean);
  return detectInitialLocale(cached, languages);
}
