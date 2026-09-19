"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw, Home } from "lucide-react";
import Link from "next/link";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    // Production: report to Sentry
    // if (process.env.NODE_ENV === "production") {
    //   Sentry.captureException(error);
    // }
    if (process.env.NODE_ENV === "development") {
      console.error("[GlobalError boundary]", {
        message: error.message,
        digest: error.digest,
        stack: error.stack,
      });
    }
  }, [error]);

  return (
    // Marker for scripts/page_sweep.py: a rendered error boundary is how the
    // sweep knows a page blew up, without matching on Turkish copy.
    <div data-error-boundary="root" className="flex min-h-screen flex-col items-center justify-center bg-background p-4 text-foreground">
      <div className="w-full max-w-md rounded-xl border border-destructive/30 bg-destructive/5 p-8 text-center">

        {/* Icon */}
        <div className="mb-5 flex justify-center">
          <div className="rounded-full bg-destructive/10 p-4">
            <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
          </div>
        </div>

        {/* Message */}
        <h1 className="mb-2 text-xl font-bold tracking-tight">Beklenmedik bir hata oluştu</h1>
        <p className="mb-1 text-sm leading-relaxed text-muted-foreground">
          Uygulama düzeyinde bir sorun var. Sayfayı yenileyin ya da ana panele dönün.
        </p>

        {/* Error reference */}
        {error.digest && (
          <p className="mt-3 mb-5 font-mono text-[10px] text-muted-foreground/50">
            ref: {error.digest}
          </p>
        )}

        {/* Dev stack trace */}
        {process.env.NODE_ENV === "development" && error.message && (
          <details className="mb-5 text-left">
            <summary className="mb-1 cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              Hata detayı (dev only)
            </summary>
            <pre className="overflow-auto rounded-md bg-muted/50 p-3 text-[11px] text-muted-foreground max-h-40">
              {error.message}
              {error.stack ? `\n\n${error.stack}` : ""}
            </pre>
          </details>
        )}

        {/* Actions */}
        <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-center">
          <button
            onClick={reset}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Tekrar Dene
          </button>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:border-border/80 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <Home className="h-4 w-4" aria-hidden="true" />
            Ana Panel
          </Link>
        </div>
      </div>
    </div>
  );
}
