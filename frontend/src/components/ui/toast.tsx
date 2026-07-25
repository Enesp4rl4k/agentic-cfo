"use client";

import * as RadixToast from "@radix-ui/react-toast";
import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { CheckCircle, AlertCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type ToastVariant = "success" | "error" | "info";

interface Toast {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toast: (opts: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((opts: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { ...opts, id }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const value: ToastContextValue = {
    toast: addToast,
    success: (title, description) => addToast({ title, description, variant: "success" }),
    error: (title, description) => addToast({ title, description, variant: "error" }),
  };

  return (
    <ToastContext.Provider value={value}>
      <RadixToast.Provider swipeDirection="right">
        {children}

        {toasts.map((t) => (
          <RadixToast.Root
            key={t.id}
            open
            onOpenChange={(open) => !open && removeToast(t.id)}
            duration={4000}
            className={cn(
              "flex items-start gap-3 rounded-lg border px-4 py-3 shadow-lg",
              "data-[state=open]:animate-in data-[state=closed]:animate-out",
              "data-[state=closed]:slide-out-to-right-full data-[state=open]:slide-in-from-right-full",
              "data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)]",
              "transition-transform duration-150",
              t.variant === "success"
                ? "border-emerald-600/30 bg-emerald-950/60 text-emerald-300"
                : t.variant === "error"
                ? "border-destructive/30 bg-destructive/10 text-destructive"
                : "border-border bg-card text-foreground"
            )}
          >
            {t.variant === "success" ? (
              <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            ) : t.variant === "error" ? (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            ) : null}

            <div className="flex-1">
              <RadixToast.Title className="text-sm font-medium leading-snug">
                {t.title}
              </RadixToast.Title>
              {t.description && (
                <RadixToast.Description className="mt-0.5 text-xs opacity-80">
                  {t.description}
                </RadixToast.Description>
              )}
            </div>

            <RadixToast.Close
              className="rounded p-0.5 opacity-60 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Dismiss notification"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </RadixToast.Close>
          </RadixToast.Root>
        ))}

        <RadixToast.Viewport className="fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2 outline-none" />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
