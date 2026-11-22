import { LegacyGate } from "@/components/legacy-gate";

export default function LegacyDashboardLayout({ children }: { children: React.ReactNode }) {
  return <LegacyGate>{children}</LegacyGate>;
}
