import type { ReactNode } from "react";

interface RoleDashboardHeaderProps {
  title: string;
  description: string;
  actions?: ReactNode;
  context?: ReactNode;
}

export function RoleDashboardHeader({
  title,
  description,
  actions,
  context,
}: RoleDashboardHeaderProps) {
  return (
    <header className="flex flex-col justify-between gap-4 border-b border-border/80 pb-5 sm:flex-row sm:items-end">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">
          {title}
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
        {context && (
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            {context}
          </div>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
