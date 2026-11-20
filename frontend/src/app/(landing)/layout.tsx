import type { Metadata } from "next";
import { resolveLandingLocale } from "@/components/brand-landing/locale";
import { brand } from "@/lib/branding";
import { getMessages } from "@/lib/i18n";

/**
 * Landing layout — no auth required, no sidebar. Served at / for unauthenticated
 * visitors; the brand landing (DESIGN.md → Brand layer) renders inside it.
 *
 * The brand fonts come from `@/lib/brand-fonts`, scoped by variable so the app's Inter stays untouched.
 */
export function generateMetadata(): Metadata {
  const { hero } = getMessages(resolveLandingLocale()).brandLanding;
  return {
    title: `${brand.name} — ${hero.titleBefore}${hero.titleEm}${hero.titleAfter}`,
    description: hero.lead,
  };
}

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div lang={resolveLandingLocale()}>
      {children}
    </div>
  );
}
