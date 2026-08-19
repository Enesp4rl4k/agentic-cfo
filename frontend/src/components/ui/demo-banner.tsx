"use client";

import { useState, useEffect } from "react";
import { Zap, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";

interface DemoBannerProps {
  onDemoStarted?: (jobId: string) => void;
  className?: string;
}

export function DemoBanner({ onDemoStarted, className }: DemoBannerProps) {
  const [visible, setVisible] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dismissed = localStorage.getItem("demo_banner_dismissed");
    if (dismissed === "1") {
      setVisible(false);
    }
  }, []);

  if (!visible) return null;

  async function handleDemoClick() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<{ data: { job_id: string } }>("/demo/seed");
      const jobId = res.data.data.job_id;
      localStorage.setItem("demo_banner_dismissed", "1");
      setVisible(false);
      onDemoStarted?.(jobId);
      // Redirect to dashboard with job
      window.location.href = `/?job=${jobId}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo başlatılamadı");
    } finally {
      setLoading(false);
    }
  }

  function handleDismiss() {
    localStorage.setItem("demo_banner_dismissed", "1");
    setVisible(false);
  }

  return (
    <div
      className={cn(
        "rounded-lg border border-blue-500/30 bg-blue-500/8 p-4 flex items-start justify-between gap-3",
        className
      )}
    >
      <div className="flex items-start gap-3 flex-1">
        <Zap className="h-5 w-5 text-blue-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm text-foreground">Demo ile Deneyin</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Sample finansal verisi yükleyerek AI CFO platformunu hemen deneyin. İçişleri bir dakika.
          </p>
          {error && <p className="text-xs text-destructive mt-1.5">{error}</p>}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button
          size="sm"
          onClick={handleDemoClick}
          disabled={loading}
          className="whitespace-nowrap"
        >
          {loading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              Başlatılıyor…
            </>
          ) : (
            "Demo Başlat"
          )}
        </Button>
        <button
          onClick={handleDismiss}
          className="rounded p-1 text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Kapat"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
