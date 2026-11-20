import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { Providers } from "@/app/providers";
import { brandFontVars } from "@/lib/brand-fonts";
import { brand, STORAGE_PREFIX } from "@/lib/branding";
import { detectInitialLocale, LOCALE_COOKIE_KEY, type AppLocale } from "@/lib/i18n";
import "@/styles/globals.css";

/**
 * Runs before first paint so a dark-theme visitor never sees a light flash, on every page.
 * Same rule as ThemeProvider: the saved choice wins, otherwise the system's.
 */
const THEME_SCRIPT =
  `try{var t=localStorage.getItem("${STORAGE_PREFIX}_theme")||"system";` +
  `var d=t==="dark"||(t==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);` +
  `document.documentElement.classList.toggle("dark",d)}catch(e){}`;

export const metadata: Metadata = {
  title: brand.name,
  description:
    "Şirketlerin nakit rotası, kendi belgelerinden çizilir. Her rakam, onu doğuran belgeye kadar izlenir.",
};

/**
 * First-paint locale, resolved on the server: the locale cookie wins (it
 * mirrors the last org-resolved value), Accept-Language seeds the very first
 * visit. Flows into `Providers` so server HTML and hydration agree — role
 * headers never paint English first for a Turkish org (DESIGN.md locale
 * principle). The org row remains authoritative and DocumentLang corrects
 * `<html lang>` once it resolves.
 */
function resolveInitialLocale(): AppLocale {
  const localeCookie = cookies().get(LOCALE_COOKIE_KEY)?.value ?? null;
  const acceptLanguage = headers().get("accept-language") ?? "";
  const languages = acceptLanguage
    .split(",")
    .map((part) => part.split(";")[0].trim())
    .filter(Boolean);
  return detectInitialLocale(localeCookie, languages);
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const initialLocale = resolveInitialLocale();
  return (
    <html lang={initialLocale} suppressHydrationWarning>
      <body className={`${brandFontVars} font-sans`}>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
        <Providers initialLocale={initialLocale}>{children}</Providers>
      </body>
    </html>
  );
}
