"use client";

import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import type { WaitingCounts } from "@/hooks/useWaitingCounts";

/**
 * Everything waiting for this person's decision, one line per kind with its count, each a link to where it
 * is answered: sections of the approvals screen, or the specialised screen (held rows). Kinds with nothing
 * waiting are not listed.
 */
export function WaitingSummary({ counts }: Readonly<{ counts: WaitingCounts }>) {
  const { t } = useI18n();
  const copy = t.heldAnalysis.queues;
  const kinds: { key: keyof Omit<WaitingCounts, "total" | "loading">; label: string; href: string }[] = [
    { key: "analyses", label: copy.analyses, href: "#analizler" },
    { key: "rows", label: copy.rows, href: "/bekleyen-kayitlar" },
    { key: "duplicates", label: copy.duplicates, href: "#mukerrer" },
    { key: "settlements", label: copy.settlements, href: "#eslesmeler" },
    { key: "plans", label: copy.plans, href: "#odeme-plani" },
    { key: "agents", label: copy.agents, href: "#rol-sonuclari" },
  ];
  const listed = kinds.filter((k) => counts[k.key] > 0);
  if (listed.length === 0) return null;
  return (
    <nav aria-label={copy.title.replace("{n}", String(counts.total))} className="space-y-2">
      <p className="m-0 text-sm font-medium">{copy.title.replace("{n}", String(counts.total))}</p>
      <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
        {listed.map((k) => (
          <li key={k.key}>
            <Link
              href={k.href}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-border px-4 text-sm hover:bg-muted"
            >
              <span>{k.label}</span>
              <span className="tc-mono font-semibold">{counts[k.key]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
