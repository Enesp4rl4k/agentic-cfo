"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Building2, Check, ChevronDown, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { getMemberships, switchOrg } from "@/lib/api/orgs";
import { useCompanyContextStore } from "@/store/companyContext";
import { useI18n } from "@/hooks/useI18n";

export const MEMBERSHIPS_KEY = ["org-memberships"] as const;

/**
 * Switch the organisation you are acting in.
 *
 * Shown only to someone who belongs to more than one — in practice a mali
 * müşavir with clients. Everyone else sees nothing, so a single-company user's
 * header is unchanged.
 *
 * After a switch the page is reloaded rather than patched: every query, the
 * persisted active job and the organisation-scoped state belong to the
 * organisation just left, and showing any of it under another company's name
 * would be a wrong-company mistake in a finance product.
 */
export function OrgSwitcher() {
  const { t } = useI18n();
  const s = t.orgSwitcher;
  const { status } = useSession();
  const { clearWorkspace } = useCompanyContextStore();
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: MEMBERSHIPS_KEY,
    queryFn: getMemberships,
    enabled: status === "authenticated",
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const memberships = data?.memberships ?? [];
  if (memberships.length < 2) return null;

  const active = memberships.find((m) => m.active) ?? null;

  async function choose(orgId: string) {
    if (busyId || orgId === active?.org_id) {
      setOpen(false);
      return;
    }
    setBusyId(orgId);
    setError(null);
    try {
      await switchOrg(orgId);
      clearWorkspace();
      window.location.assign("/command-center");
    } catch (e) {
      setBusyId(null);
      setError(e instanceof Error ? e.message : s.failed);
    }
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-xs transition-colors",
          "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={s.trigger}
      >
        <Building2 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="max-w-[140px] truncate font-medium text-foreground/90">
          {active?.name ?? s.pick}
        </span>
        <ChevronDown
          className={cn("h-3 w-3 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="menu"
            aria-label={s.menuLabel}
            className="absolute right-0 top-full z-20 mt-1.5 w-64 rounded-xl border border-border bg-card py-1 shadow-xl shadow-black/20"
          >
            <p className="px-3 py-2 text-[11px] text-muted-foreground">{s.heading}</p>
            {memberships.map((m) => (
              <button
                key={m.org_id}
                type="button"
                role="menuitemradio"
                aria-checked={m.active}
                disabled={busyId !== null}
                onClick={() => void choose(m.org_id)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors",
                  "hover:bg-muted focus-visible:bg-muted focus-visible:outline-none disabled:opacity-60",
                  m.active && "bg-muted/60",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-foreground">{m.name}</span>
                  <span className="block text-[11px] text-muted-foreground">
                    {s.roles[m.role] ?? m.role}
                  </span>
                </span>
                {busyId === m.org_id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" aria-hidden="true" />
                ) : m.active ? (
                  <Check className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                ) : null}
              </button>
            ))}
            {error && (
              <p role="alert" className="border-t border-border px-3 py-2 text-[11px] text-destructive">
                {error}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
