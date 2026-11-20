import { BrandLanding } from "@/components/brand-landing/BrandLanding";
import { resolveLandingLocale } from "@/components/brand-landing/locale";

/**
 * The public landing (Tunç Çağı). It replaced the earlier C-Suite landing,
 * whose components were removed from the codebase.
 */
export default function LandingPage() {
  return <BrandLanding locale={resolveLandingLocale()} />;
}
