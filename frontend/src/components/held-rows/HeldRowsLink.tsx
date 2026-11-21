"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "@/hooks/useI18n";
import { listHeldRows } from "@/lib/api/heldRows";

/** "N rows wait for your review", linking to the list; renders nothing when none wait. */
export function HeldRowsLink({ jobId }: Readonly<{ jobId?: string | null }>) {
  const { t } = useI18n();
  const { data } = useQuery({
    queryKey: ["held-rows", jobId ?? "all"],
    queryFn: () => listHeldRows(jobId ?? undefined),
  });
  const count = data?.length ?? 0;
  if (count === 0) return null;
  const text = (jobId ? t.heldRows.linkJob : t.heldRows.linkWaiting).replace("{count}", String(count));
  return (
    <Link
      href={jobId ? `/bekleyen-kayitlar?job=${jobId}` : "/bekleyen-kayitlar"}
      className="inline-block text-sm font-medium underline underline-offset-2"
    >
      {text}
    </Link>
  );
}
