"use client";

import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/hooks/useI18n";
import { getDeliveryStatus, type DeliveryFailure } from "@/lib/api/deliveryStatus";
import { isForbidden } from "@/lib/forbidden";
import { hasRoleClass } from "@/lib/roles";

/**
 * Per Slack or webhook destination: when a message last went out, when one last failed, and why in words.
 * Read-only, for owner and admin (the server answers 403 to everyone else, and the block is not drawn for
 * them). The destination is shown by its host; the address itself, which carries a secret, is never sent here.
 * A reason the server has no words for is shown as "neden bildirilmedi", never as a raw code.
 */
export function DeliveryStatusCard() {
  const { t, locale } = useI18n();
  const d = t.deliveryStatus;
  const { data: session } = useSession();
  const role = session?.user?.role;
  const allowed = hasRoleClass(role, "decider");
  const q = useQuery({ queryKey: ["delivery-status"], queryFn: getDeliveryStatus, retry: false, enabled: allowed });
  if (!allowed) return null;

  const dateTag = locale === "tr" ? "tr-TR" : "en-US";
  const when = (iso: string) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(dateTag);
  };
  const words = (f: DeliveryFailure | null): string => (f ? (locale === "tr" ? f.tr : f.en) : "") || d.reasonFallback;
  const channels = d.channels as Record<string, string>;

  return (
    <Card className="space-y-3 p-4">
      <h2 className="tc-display m-0 text-[20px]">{d.title}</h2>
      <p className="m-0 text-sm text-muted-foreground">{d.intro}</p>
      {q.isLoading && <Skeleton aria-label={d.loading} className="h-16 w-full" />}
      {q.isError && (
        <p role="alert" className="m-0 text-sm text-destructive">
          {isForbidden(q.error) ? d.forbidden : d.loadFailed}
        </p>
      )}
      {q.data && q.data.length === 0 && <p className="m-0 text-sm text-muted-foreground">{d.empty}</p>}
      {q.data && q.data.length > 0 && (
        <ul className="m-0 list-none space-y-3 p-0">
          {q.data.map((dest) => (
            <li key={`${dest.channel}:${dest.destination}`} className="space-y-1 rounded-md border border-border p-3">
              <p className="m-0 text-sm font-medium">
                {channels[dest.channel] ?? dest.channel} · <span className="font-normal">{dest.destination}</span>
              </p>
              {(dest.failing || dest.last_success_at) && (
                <p className={dest.failing ? "m-0 text-xs font-medium text-destructive" : "m-0 text-xs text-muted-foreground"}>
                  {dest.failing ? d.failing : d.working}
                </p>
              )}
              <p className="m-0 text-xs text-muted-foreground">
                {dest.last_success_at ? d.lastSuccess.replace("{when}", when(dest.last_success_at)) : d.noSuccess}
              </p>
              <p className="m-0 text-xs text-muted-foreground">
                {dest.last_failure_at ? d.lastFailure.replace("{when}", when(dest.last_failure_at)) : d.noFailure}
                {dest.last_failure_at && ` · ${d.reason.replace("{reason}", words(dest.last_failure))}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
