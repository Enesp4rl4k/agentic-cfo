"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { X, ChevronRight, ChevronLeft, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { STORAGE_PREFIX } from "@/lib/branding";

// ── Tour step definition ──────────────────────────────────────────────────────

export interface TourStep {
  /** CSS selector or element ID to highlight */
  target:       string;
  /** Popover title */
  title:        string;
  /** Popover body content */
  content:      string;
  /** Where to place the popover relative to the target */
  placement?:   "top" | "bottom" | "left" | "right" | "center";
  /** Optional action button in the popover */
  action?:      { label: string; onClick: () => void };
}

// ── Built-in tour definitions ─────────────────────────────────────────────────

export const DASHBOARD_TOUR: TourStep[] = [
  {
    target:    "body",
    title:     "Agentic CFO'ya Hoş Geldiniz 🎉",
    content:   "Bu hızlı tur size platformun ana özelliklerini gösterecek. Hazırsanız başlayalım!",
    placement: "center",
  },
  {
    target:    "[data-tour='upload']",
    title:     "Veri Yükleme",
    content:   "Banka ekstrenizi, Excel veya CSV dosyanızı buraya yükleyin. Paraşüt ve Logo Tiger doğrudan bağlanabilir.",
    placement: "right",
  },
  {
    target:    "[data-tour='command-palette']",
    title:     "Komut Paleti (Ctrl+K)",
    content:   "Ctrl+K ile her sayfadan hızlıca gezinebilirsiniz. Türkçe arama desteklenir.",
    placement: "bottom",
  },
  {
    target:    "[data-tour='intelligence']",
    title:     "Cross-Domain Intelligence",
    content:   "Tüm C-Suite verilerini birleştiren merkezi analiz. SWOT, benchmark, proaktif alertler burada.",
    placement: "right",
  },
  {
    target:    "[data-tour='chat']",
    title:     "CFO Asistanı",
    content:   "Şirket verileriniz hakkında Türkçe soru sorun. 'Nakit pisti ne kadar?' — anında yanıt.",
    placement: "right",
  },
];

// ── Tour storage ──────────────────────────────────────────────────────────────

const TOUR_STORAGE_KEY        = `${STORAGE_PREFIX}_tour_completed`;
const TOUR_PENDING_STORAGE_KEY = `${STORAGE_PREFIX}_tour_pending`;

export function isTourCompleted(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem(TOUR_STORAGE_KEY) === "1";
}

export function markTourCompleted(): void {
  localStorage.setItem(TOUR_STORAGE_KEY, "1");
  localStorage.removeItem(TOUR_PENDING_STORAGE_KEY);
}

export function resetTour(): void {
  localStorage.removeItem(TOUR_STORAGE_KEY);
}

/**
 * Called right after a successful first upload.
 * Dashboard reads this flag on mount and auto-starts the tour.
 */
export function markTourPending(): void {
  if (typeof window === "undefined") return;
  if (!isTourCompleted()) {
    localStorage.setItem(TOUR_PENDING_STORAGE_KEY, "1");
  }
}

export function isTourPending(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(TOUR_PENDING_STORAGE_KEY) === "1";
}

export function clearTourPending(): void {
  localStorage.removeItem(TOUR_PENDING_STORAGE_KEY);
}

// ── Position calculation ──────────────────────────────────────────────────────

interface PopoverPosition {
  top:   number;
  left:  number;
  width: number;
}

function getPopoverPosition(
  el: Element | null,
  placement: TourStep["placement"] = "bottom",
  popoverW = 320,
  popoverH = 180,
): PopoverPosition {
  if (!el || placement === "center") {
    return {
      top:   window.innerHeight / 2 - popoverH / 2,
      left:  window.innerWidth  / 2 - popoverW / 2,
      width: popoverW,
    };
  }

  const rect = el.getBoundingClientRect();
  const gap  = 12;
  let top = 0, left = 0;

  switch (placement) {
    case "bottom":
      top  = rect.bottom + gap;
      left = rect.left + rect.width / 2 - popoverW / 2;
      break;
    case "top":
      top  = rect.top - popoverH - gap;
      left = rect.left + rect.width / 2 - popoverW / 2;
      break;
    case "right":
      top  = rect.top + rect.height / 2 - popoverH / 2;
      left = rect.right + gap;
      break;
    case "left":
      top  = rect.top + rect.height / 2 - popoverH / 2;
      left = rect.left - popoverW - gap;
      break;
  }

  // Clamp to viewport
  left = Math.max(12, Math.min(left, window.innerWidth - popoverW - 12));
  top  = Math.max(12, Math.min(top,  window.innerHeight - popoverH - 12));

  return { top, left, width: popoverW };
}

// ── Spotlight overlay ──────────────────────────────────────────────────────────

function SpotlightOverlay({ target }: { target: string }) {
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    const el = target === "body" ? null : document.querySelector(target);
    if (el) {
      const r = el.getBoundingClientRect();
      setRect(r);
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      setRect(null);
    }
  }, [target]);

  if (!rect) {
    return <div className="fixed inset-0 z-[90] bg-black/50 backdrop-blur-[1px]" />;
  }

  const pad = 6;
  const x   = rect.left   - pad;
  const y   = rect.top    - pad;
  const w   = rect.width  + pad * 2;
  const h   = rect.height + pad * 2;

  return (
    <div className="fixed inset-0 z-[90] pointer-events-none">
      {/* Top */}
      <div className="absolute bg-black/60" style={{ top: 0, left: 0, right: 0, height: y }} />
      {/* Bottom */}
      <div className="absolute bg-black/60" style={{ top: y + h, left: 0, right: 0, bottom: 0 }} />
      {/* Left */}
      <div className="absolute bg-black/60" style={{ top: y, left: 0, width: x, height: h }} />
      {/* Right */}
      <div className="absolute bg-black/60" style={{ top: y, left: x + w, right: 0, height: h }} />
      {/* Highlight ring */}
      <div
        className="absolute rounded-lg ring-2 ring-primary ring-offset-0 shadow-[0_0_0_9999px_rgba(0,0,0,0)]"
        style={{ top: y, left: x, width: w, height: h }}
      />
    </div>
  );
}

// ── Tour popover ──────────────────────────────────────────────────────────────

interface TourPopoverProps {
  step:    TourStep;
  index:   number;
  total:   number;
  onNext:  () => void;
  onPrev:  () => void;
  onSkip:  () => void;
}

function TourPopover({ step, index, total, onNext, onPrev, onSkip }: TourPopoverProps) {
  const [pos, setPos] = useState<PopoverPosition>({ top: 0, left: 0, width: 320 });

  useEffect(() => {
    const el = step.target === "body" ? null : document.querySelector(step.target);
    setPos(getPopoverPosition(el, step.placement));
  }, [step]);

  const isFirst = index === 0;
  const isLast  = index === total - 1;

  return (
    <div
      role="dialog"
      aria-label={`Tur adımı ${index + 1} / ${total}: ${step.title}`}
      className="fixed z-[95] w-80 rounded-xl border border-primary/30 bg-card shadow-xl"
      style={{ top: pos.top, left: pos.left, width: pos.width }}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="text-xs text-muted-foreground">{index + 1} / {total}</span>
        </div>
        <button
          onClick={onSkip}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          aria-label="Turu kapat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Content */}
      <div className="px-4 py-3 space-y-1.5">
        <p className="font-semibold text-sm">{step.title}</p>
        <p className="text-xs text-muted-foreground leading-relaxed">{step.content}</p>
        {step.action && (
          <button
            onClick={step.action.onClick}
            className="mt-1 text-xs text-primary hover:underline"
          >
            {step.action.label} →
          </button>
        )}
      </div>

      {/* Progress dots */}
      <div className="flex justify-center gap-1 py-2">
        {Array.from({ length: total }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "rounded-full transition-all",
              i === index ? "w-4 h-1.5 bg-primary" : "w-1.5 h-1.5 bg-muted-foreground/30"
            )}
          />
        ))}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
        <button
          onClick={onSkip}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Atla
        </button>
        <div className="flex items-center gap-2">
          {!isFirst && (
            <Button size="sm" variant="outline" onClick={onPrev} className="h-7 px-2">
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button size="sm" onClick={onNext} className="h-7 px-3 text-xs">
            {isLast ? "Bitir" : "İleri"}
            {!isLast && <ChevronRight className="h-3.5 w-3.5 ml-1" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Main ProductTour component ────────────────────────────────────────────────

interface ProductTourProps {
  steps:        TourStep[];
  /** Auto-start if tour not completed yet */
  autoStart?:   boolean;
  onComplete?:  () => void;
}

export function ProductTour({ steps, autoStart = false, onComplete }: ProductTourProps) {
  const [active,  setActive]  = useState(false);
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (autoStart && !isTourCompleted()) {
      // Delay to allow page to render
      const t = setTimeout(() => setActive(true), 1500);
      return () => clearTimeout(t);
    }
  }, [autoStart]);

  const complete = useCallback(() => {
    setActive(false);
    markTourCompleted();
    onComplete?.();
  }, [onComplete]);

  const next = useCallback(() => {
    if (current < steps.length - 1) {
      setCurrent((i) => i + 1);
    } else {
      complete();
    }
  }, [current, steps.length, complete]);

  const prev = useCallback(() => {
    setCurrent((i) => Math.max(0, i - 1));
  }, []);

  if (!active || steps.length === 0) return null;

  const step = steps[current];

  return (
    <>
      <SpotlightOverlay target={step.target} />
      <TourPopover
        step={step}
        index={current}
        total={steps.length}
        onNext={next}
        onPrev={prev}
        onSkip={complete}
      />
    </>
  );
}

// ── useTour hook ──────────────────────────────────────────────────────────────

export function useTour(steps: TourStep[] = DASHBOARD_TOUR) {
  const [running, setRunning] = useState(false);

  const start   = useCallback(() => { resetTour(); setRunning(true); }, []);
  const stop    = useCallback(() => setRunning(false), []);
  const restart = useCallback(() => { resetTour(); setRunning(true); }, []);

  return { running, start, stop, restart };
}
