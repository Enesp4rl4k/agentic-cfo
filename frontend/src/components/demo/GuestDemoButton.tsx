"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { startGuestDemo } from "@/lib/demo";

/**
 * One-click guest demo entry button (DEMO_PLAN D1).
 *
 * Parents keep their own styling by passing `className` and children — this
 * component owns only the async flow: mint a guest session → NextAuth sign-in
 * → land on the upload page (where QuickDemoBanner starts the sample analysis).
 * Failures render as an honest inline retry label, never a silent dead click.
 */
export function GuestDemoButton({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const router = useRouter();

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
      disabled={loading}
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
