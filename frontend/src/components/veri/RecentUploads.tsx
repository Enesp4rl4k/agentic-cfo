"use client";

import { useEffect, useState } from "react";
import { listJobs, type JobSummary } from "@/lib/api/cfo";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  completed: "text-success",
  failed: "text-destructive",
  awaiting_review: "text-warning",
};

/**
 * The latest uploads and where each stands. Only what the jobs list really
 * holds: the file name, the stage it reached and when it came. How many rows
 * were read is not on this list, so it is not shown.
 */
export function RecentUploads({ version }: { version: number }) {
  const { t } = useI18n();
  const copy = t.baglan.recent;
  const { org } = useOrgSettings();
  const locale = org?.locale || "tr-TR";
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    listJobs()
      .then((rows) => {
        if (!alive) return;
        setFailed(false);
        setJobs([...rows].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 8));
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [version]);

  const when = (iso: string) =>
    new Date(iso).toLocaleString(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  return (
    <section aria-label={copy.title} className="space-y-3">
      <h2 className="tc-display m-0 text-[26px] leading-[1.1]">{copy.title}</h2>
      {failed && <p className="text-sm text-destructive">{copy.failed}</p>}
      {!failed && jobs !== null && jobs.length === 0 && <p className="text-sm text-muted-foreground">{copy.empty}</p>}
      {jobs !== null && jobs.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[480px] border-collapse text-[13.5px]">
            <thead>
              <tr className="bg-muted text-left text-muted-foreground">
                <th className="px-4 py-2.5 font-medium">{copy.colFile}</th>
                <th className="px-3 py-2.5 font-medium">{copy.colStatus}</th>
                <th className="px-4 py-2.5 text-right font-medium">{copy.colArrived}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id} className="border-t border-border">
                  <td className="px-4 py-2.5 font-medium">{job.filename}</td>
                  <td className={cn("px-3 py-2.5", TONE[job.status] ?? "text-muted-foreground")}>
                    {copy.statuses[job.status] ?? job.status}
                  </td>
                  <td className="tc-mono px-4 py-2.5 text-right text-muted-foreground">{when(job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
