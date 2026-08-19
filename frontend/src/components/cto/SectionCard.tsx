"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface SectionCardProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}

export function SectionCard({ title, icon, children }: SectionCardProps) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        className="flex w-full items-center justify-between p-4 text-left"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          {icon}
          {title}
        </div>
        {open ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        )}
      </button>
      {open && <div className="border-t border-border p-4">{children}</div>}
    </div>
  );
}

// ── Severity badge ─────────────────────────────────────────────────────────────

const SEVERITY_CLASSES: Record<string, string> = {
  critical: "bg-destructive/20 text-destructive border-destructive/30",
  high:     "bg-orange-500/20 text-orange-400 border-orange-500/30",
  medium:   "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  low:      "bg-muted text-muted-foreground border-border",
};

export function SeverityBadge({ severity }: { severity: string }) {
  const cls = SEVERITY_CLASSES[severity] ?? SEVERITY_CLASSES.low;
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}>
      {severity}
    </span>
  );
}
