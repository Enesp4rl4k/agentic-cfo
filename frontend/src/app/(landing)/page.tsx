import { LandingNavbar }   from "@/components/landing/LandingNavbar";
import { HeroSection }      from "@/components/landing/HeroSection";
import { SocialProofSection } from "@/components/landing/SocialProofSection";
import { FeaturesGrid }     from "@/components/landing/FeaturesGrid";
import { AgentsShowcase }   from "@/components/landing/AgentsShowcase";
import { PricingTable }     from "@/components/landing/PricingTable";
import { CTABand }          from "@/components/landing/CTABand";
import { LandingFooter }    from "@/components/landing/LandingFooter";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <LandingNavbar />
      <main>
        <HeroSection />
        <SocialProofSection />
        <FeaturesGrid />
        <AgentsShowcase />
        <PricingTable />
        <CTABand />
      </main>
      <LandingFooter />
    </div>
  );
}
