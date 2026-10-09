import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { cookies, headers } from "next/headers";
import { Providers } from "@/app/providers";
import { brand } from "@/lib/branding";
import { detectInitialLocale, LOCALE_COOKIE_KEY, type AppLocale } from "@/lib/i18n";
import "@/styles/globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: brand.name,
  description:
    "Çok rollü C-Suite zekası ve gerekçelendirilmiş yapay zeka ile yönetim işletim sistemi.",
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
      <body className={`${inter.variable} font-sans`}>
        <Providers initialLocale={initialLocale}>{children}</Providers>
      </body>
    </html>
  );
}
