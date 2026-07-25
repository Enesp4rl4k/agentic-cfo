"use client";

import { useState } from "react";
import { X, Zap, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * DemoBanner — shown when NEXT_PUBLIC_DEMO_MODE=true
 * Thin, dismissible bar at the top of the dashboard layout.
 * Informs the user this is a demo with TechNova sample data.
 */
export function DemoBanner() {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  return (
    <div
      role="banner"
      aria-label="Demo mode notification"
      className={cn(
        "relative flex items-center justify-between gap-3",
        "bg-primary/10 border-b border-primary/20 px-4 py-2",
        "text-xs text-primary"
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <Zap className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
        <span className="font-medium">Demo modu</span>
        <span className="text-muted-foreground hidden sm:inline">—</span>
        <span className="text-muted-foreground hidden sm:inline truncate">
          TechNova Yazılım A.Ş. · 12 aylık gerçekçi finansal veri · 163 işlem
        </span>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <a
          href="https://github.com/your-org/agentic-cfo"
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "hidden sm:flex items-center gap-1 rounded px-2 py-0.5 text-[11px]",
            "border border-primary/30 bg-primary/5",
            "hover:bg-primary/15 transition-colors",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          )}
          aria-label="View source on GitHub"
        >
          Kaynak Kodu
          <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
        </a>

        <button
          onClick={() => setDismissed(true)}
          className={cn(
            "rounded p-0.5 text-muted-foreground",
            "hover:text-foreground transition-colors",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          )}
          aria-label="Dismiss demo banner"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
