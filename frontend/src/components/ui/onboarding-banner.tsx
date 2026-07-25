"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { X, Upload, ArrowRight, Building2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

const STEPS = [
  {
    id: "upload",
    icon: Upload,
    title: "Veri yükleyin",
    desc: "CSV, Excel veya PDF muhasebe dosyanızı yükleyin.",
    href: "/upload",
    cta: "Dosya Yükle",
  },
  {
    id: "workspace",
    icon: Building2,
    title: "Workspace kurun",
    desc: "Ekibinizi davet edin, birlikte çalışın.",
    href: "/settings/workspace",
    cta: "Ekibi Davet Et",
  },
  {
    id: "analyze",
    icon: Sparkles,
    title: "AI analizi başlatın",
    desc: "12 ajan devreye girer, 5 dakikada tam rapor.",
    href: "/upload",
    cta: "Analiz Başlat",
  },
] as const;

const STORAGE_KEY = "clevelai_onboarding_dismissed";

export function OnboardingBanner() {
  const { data: session } = useSession();
  const [dismissed, setDismissed] = useState(true); // start hidden to avoid flash
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    // Only show for newly registered users (no previous dismissal)
    const wasDismissed = typeof window !== "undefined"
      ? localStorage.getItem(STORAGE_KEY) === "1"
      : true;
    setDismissed(wasDismissed);
  }, []);

  function dismiss() {
    setDismissed(true);
    localStorage.setItem(STORAGE_KEY, "1");
  }

  // Only show when session exists and not dismissed
  if (!session || dismissed) return null;

  const step = STEPS[activeStep];
  const StepIcon = step.icon;

  return (
    <div
      role="region"
      aria-label="Getting started"
      className="relative border-b border-primary/20 bg-gradient-to-r from-primary/8 via-primary/5 to-transparent"
    >
      <div className="mx-auto flex max-w-screen-xl items-center gap-4 px-4 py-3 sm:px-6">
        {/* Step icon */}
        <div className="hidden shrink-0 sm:block">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15">
            <StepIcon className="h-4 w-4 text-primary" aria-hidden="true" />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-primary">
            Başlangıç rehberi — Adım {activeStep + 1}/{STEPS.length}
          </p>
          <p className="mt-0.5 text-sm font-medium">
            {step.title}
            <span className="ml-1.5 text-muted-foreground font-normal">{step.desc}</span>
          </p>
        </div>

        {/* Step pills */}
        <div className="hidden items-center gap-1 sm:flex">
          {STEPS.map((s, i) => (
            <button
              key={s.id}
              onClick={() => setActiveStep(i)}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === activeStep ? "w-4 bg-primary" : "w-1.5 bg-primary/30 hover:bg-primary/50"
              )}
              aria-label={`Step ${i + 1}: ${s.title}`}
              aria-current={i === activeStep ? "step" : undefined}
            />
          ))}
        </div>

        {/* CTA */}
        <Link
          href={step.href}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90"
        >
          {step.cta}
          <ArrowRight className="h-3 w-3" aria-hidden="true" />
        </Link>

        {/* Next step */}
        {activeStep < STEPS.length - 1 && (
          <button
            onClick={() => setActiveStep((s) => s + 1)}
            className="hidden shrink-0 text-xs text-muted-foreground transition-colors hover:text-foreground sm:block"
          >
            Sonraki →
          </button>
        )}

        {/* Dismiss */}
        <button
          onClick={dismiss}
          className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Başlangıç rehberini kapat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
