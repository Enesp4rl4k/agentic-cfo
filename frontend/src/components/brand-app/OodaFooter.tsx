"use client";

import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

/**
 * The weekly loop as the foot of an operational page: Observe, Orient, Decide, Act.
 * `current` is the step's index; it is marked, never a link to itself.
 */
export function OodaFooter({ current }: { current: 0 | 1 | 2 | 3 }) {
  const { t } = useI18n();
  const copy = t.ooda;
  return (
    <footer className="mt-6 space-y-3 border-t border-border pt-5" aria-label={copy.label}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="tc-eyebrow text-muted-foreground" style={{ letterSpacing: "0.2em" }}>{copy.eyebrow}</span>
        <span className="tc-display text-[17px] font-medium italic text-muted-foreground">{copy.motto}</span>
      </div>
      <nav className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2">
        {copy.steps.map((step, index) => {
          const active = index === current;
          const body = (
            <>
              <span className={cn("tc-eyebrow text-[11px]", active ? "text-[color:var(--tc-ember-text)]" : "text-muted-foreground")}>
                {step.letter} · {step.verb}
              </span>
              <span className="text-sm font-semibold">{step.title}</span>
            </>
          );
          const base = "flex min-h-[44px] flex-col gap-0.5 rounded-lg border px-3 py-2.5";
          return active ? (
            <span
              key={step.verb}
              aria-current="page"
              className={cn(base, "border-[1.5px] border-[color:var(--tc-ember)]")}
              style={{ background: "color-mix(in srgb, var(--tc-ember) 10%, transparent)" }}
            >
              {body}
            </span>
          ) : (
            <Link key={step.verb} href={step.href} className={cn(base, "border-border transition-colors hover:bg-muted")}>
              {body}
            </Link>
          );
        })}
      </nav>
    </footer>
  );
}
