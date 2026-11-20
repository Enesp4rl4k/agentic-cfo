"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { StormShip } from "@/components/brand-landing/StormShip";
import { useI18n } from "@/hooks/useI18n";

/**
 * The ink panel beside the sign-in and sign-up forms: the storm scene, the mark, the
 * promise of the product in its own words and what the visitor gets. It states only
 * what the product does. No quote from a person, no compliance badge, no figure that
 * has not been measured (DESIGN.md → Copy).
 */
export function AuthBrandPanel({ items }: { items: { icon: LucideIcon; text: string }[] }) {
  const { t } = useI18n();
  const hero = t.brandLanding.hero;

  return (
    <div className="dark relative hidden w-[42%] flex-col justify-between overflow-hidden bg-background p-10 text-foreground lg:flex">
      <div aria-hidden="true" className="absolute inset-0">
        <StormShip label={hero.sceneLabel} />
      </div>
      <div
        aria-hidden="true"
        className="absolute inset-0"
        style={{ background: "linear-gradient(to top, rgb(26 26 31 / 0.94) 30%, rgb(26 26 31 / 0.35) 70%, rgb(26 26 31 / 0.55))" }}
      />

      <div className="relative z-10">
        <Link href="/" className="inline-flex rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Logo size="md" />
        </Link>
      </div>

      <div className="relative z-10 space-y-6">
        <div className="space-y-2">
          <p className="tc-display m-0 text-[38px] italic leading-[1.08]">{hero.tagline}</p>
          <p className="m-0 max-w-md text-sm text-muted-foreground">{hero.lead}</p>
        </div>
        <ul className="space-y-3">
          {items.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-center gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border">
                <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
              </span>
              <span className="text-sm text-foreground/85">{text}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
