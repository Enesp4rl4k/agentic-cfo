import { notFound } from "next/navigation";
import { legacyDashboardsEnabled } from "@/lib/legacy-dashboards";

/**
 * Layout of every legacy dashboard route (lib/legacy-dashboards): with the flag off the segment
 * answers "not found" before its page is rendered, so nothing is fetched and no placeholder shows.
 * A server component on purpose: the page below it is a client component that would fetch on mount.
 */
export function LegacyGate({ children }: { children: React.ReactNode }) {
  if (!legacyDashboardsEnabled()) notFound();
  return <>{children}</>;
}

export default LegacyGate;
