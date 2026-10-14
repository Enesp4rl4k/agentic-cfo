"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { startGuestDemo } from "@/lib/demo";

/**
 * One-click guest demo entry button (DEMO_PLAN D1).
 *
 * Parents keep their own styling by passing `className` and children — this
 * component owns only the async flow: mint a guest session → NextAuth sign-in
 * → land on the upload page (where QuickDemoBanner starts the sample analysis).
 * Failures render as an honest inline retry label, never a silent dead click.
 *
 * The button ships `disabled` in the server HTML and only arms after this
 * subtree has hydrated: a click before hydration reaches no handler at all
 * (observed as an intermittent dead click under dev-server CPU load), and a
 * disabled button — which Playwright waits on and real visitors see as
 * "preparing" — beats silently swallowing the click.
 */
export function GuestDemoButton({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const [hydrated, setHydrated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setHydrated(true);
  }, []);

  const handleClick = async () => {
    if (loading) return;
    setLoading(true);
    setFailed(false);

    const ok = await startGuestDemo();
    if (ok) {
      router.push("/upload");
      router.refresh();
      return;
    }
    setFailed(true);
    setLoading(false);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={!hydrated || loading}
      className={className}
    >
      {loading
        ? "Demo hazırlanıyor…"
        : failed
          ? "Başlatılamadı — tekrar deneyin"
          : children}
    </button>
  );
}
