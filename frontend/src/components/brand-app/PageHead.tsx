"use client";

import { useI18n } from "@/hooks/useI18n";

/**
 * The head of an operational page: the step of the weekly loop as the eyebrow
 * (e.g. "III · DECIDE"), the title in Cormorant, the one-line purpose, and room on
 * the right for a page's own actions. No new copy: the eyebrow is the loop's own.
 */
export function PageHead({
  step,
  title,
  subtitle,
  aside,
}: {
  step?: 0 | 1 | 2 | 3;
  title: string;
  subtitle?: string;
  aside?: React.ReactNode;
}) {
  const { t } = useI18n();
  const loop = step === undefined ? null : t.ooda.steps[step];
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1.5">
        {loop && (
          <span className="tc-eyebrow text-muted-foreground">
            {loop.letter} · {loop.verb}
          </span>
        )}
        <h1 className="tc-display m-0 text-4xl leading-[1.05] sm:text-[44px]">{title}</h1>
        {subtitle && <p className="m-0 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {aside}
    </div>
  );
}
