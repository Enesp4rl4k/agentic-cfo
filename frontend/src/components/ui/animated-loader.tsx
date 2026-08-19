"use client";
/**
 * AnimatedLoader — Premium loading state component.
 *
 * Variants:
 *   - "spinner"  : Orbital ring spinner (default)
 *   - "dots"     : Three bouncing dots
 *   - "pulse"    : Single pulsing circle
 *   - "bars"     : Animated equalizer bars
 *   - "skeleton" : Shimmer skeleton blocks
 *   - "lottie"   : Lottie animation (falls back to spinner)
 *
 * Usage:
 *   <AnimatedLoader />
 *   <AnimatedLoader variant="dots" size="lg" label="Analiz yapılıyor…" />
 *   <AnimatedLoader variant="skeleton" lines={3} />
 */

import { cn } from "@/lib/utils";
import { LottiePlayer } from "./lottie-player";

// ── Types ─────────────────────────────────────────────────────────────────────

type LoaderVariant = "spinner" | "dots" | "pulse" | "bars" | "skeleton" | "lottie";
type LoaderSize = "xs" | "sm" | "md" | "lg" | "xl";

interface AnimatedLoaderProps {
  variant?: LoaderVariant;
  size?: LoaderSize;
  label?: string;
  /** For variant="skeleton": number of shimmer lines */
  lines?: number;
  /** For variant="skeleton": show a header block above lines */
  withHeader?: boolean;
  className?: string;
  /** Center in parent container */
  centered?: boolean;
}

// ── Size map ──────────────────────────────────────────────────────────────────

const SIZE_PX: Record<LoaderSize, number> = {
  xs: 16,
  sm: 24,
  md: 32,
  lg: 48,
  xl: 64,
};

const LABEL_SIZE: Record<LoaderSize, string> = {
  xs: "text-[10px]",
  sm: "text-xs",
  md: "text-sm",
  lg: "text-sm",
  xl: "text-base",
};

// ── Spinner ───────────────────────────────────────────────────────────────────

function Spinner({ px }: { px: number }) {
  const stroke = px < 24 ? 2 : px < 40 ? 2.5 : 3;
  const r = (px / 2) - stroke * 1.5;
  const circ = 2 * Math.PI * r;
  const dash = circ * 0.28;

  return (
    <svg
      width={px}
      height={px}
      viewBox={`0 0 ${px} ${px}`}
      fill="none"
      aria-hidden="true"
    >
      {/* Track */}
      <circle
        cx={px / 2}
        cy={px / 2}
        r={r}
        stroke="currentColor"
        strokeWidth={stroke}
        strokeOpacity="0.12"
        className="text-primary"
      />
      {/* Fill arc */}
      <circle
        cx={px / 2}
        cy={px / 2}
        r={r}
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circ}`}
        style={{
          animation: "spin 900ms linear infinite",
          transformOrigin: "center",
        }}
        className="text-primary"
      />
    </svg>
  );
}

// ── Dots ──────────────────────────────────────────────────────────────────────

function Dots({ px }: { px: number }) {
  const dotSize = Math.max(4, Math.round(px / 6));
  return (
    <div
      className="flex items-center"
      style={{ gap: dotSize, height: px }}
      aria-hidden="true"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="rounded-full bg-primary"
          style={{
            width: dotSize,
            height: dotSize,
            animation: "bounce-subtle 1.2s ease-in-out infinite",
            animationDelay: `${i * 180}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ── Pulse ─────────────────────────────────────────────────────────────────────

function Pulse({ px }: { px: number }) {
  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: px, height: px }}
      aria-hidden="true"
    >
      <span
        className="absolute rounded-full bg-primary opacity-20"
        style={{
          width: px,
          height: px,
          animation: "ping-slow 1.5s cubic-bezier(0, 0, 0.2, 1) infinite",
        }}
      />
      <span
        className="rounded-full bg-primary"
        style={{ width: px * 0.4, height: px * 0.4 }}
      />
    </div>
  );
}

// ── Bars ──────────────────────────────────────────────────────────────────────

function Bars({ px }: { px: number }) {
  const barW = Math.max(3, Math.round(px / 8));
  const gaps = barW;
  const heights = [0.5, 0.85, 0.65, 1, 0.4];
  return (
    <div
      className="flex items-end"
      style={{ width: px, height: px, gap: gaps }}
      aria-hidden="true"
    >
      {heights.map((h, i) => (
        <span
          key={i}
          className="rounded-sm bg-primary"
          style={{
            width: barW,
            height: px * h,
            animation: "bounce-subtle 1.2s ease-in-out infinite",
            animationDelay: `${i * 120}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ lines, withHeader }: { lines: number; withHeader: boolean }) {
  return (
    <div className="w-full space-y-3" aria-hidden="true">
      {withHeader && (
        <div className="skeleton h-5 w-40 rounded" />
      )}
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton rounded"
          style={{
            height: 14,
            width: `${85 - i * 10}%`,
            animationDelay: `${i * 80}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnimatedLoader({
  variant = "spinner",
  size = "md",
  label,
  lines = 3,
  withHeader = false,
  className,
  centered = false,
}: AnimatedLoaderProps) {
  const px = SIZE_PX[size];

  const inner = (() => {
    switch (variant) {
      case "spinner":  return <Spinner px={px} />;
      case "dots":     return <Dots px={px} />;
      case "pulse":    return <Pulse px={px} />;
      case "bars":     return <Bars px={px} />;
      case "skeleton": return <Skeleton lines={lines} withHeader={withHeader} />;
      case "lottie":   return <LottiePlayer preset="loading" size={px} />;
      default:         return <Spinner px={px} />;
    }
  })();

  const content = (
    <div
      className={cn(
        "flex flex-col items-center gap-3",
        centered && "absolute inset-0 flex items-center justify-center",
        className
      )}
      role="status"
      aria-label={label ?? "Yükleniyor"}
    >
      {variant !== "skeleton" ? inner : null}
      {variant === "skeleton" ? inner : null}
      {label && (
        <p className={cn("text-muted-foreground animate-fade-in", LABEL_SIZE[size])}>
          {label}
        </p>
      )}
      <span className="sr-only">{label ?? "Yükleniyor"}</span>
    </div>
  );

  return content;
}

// ── Page-level full-screen loader ─────────────────────────────────────────────

export function PageLoader({ label }: { label?: string }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
      <LottiePlayer preset="loading" size={80} />
      {label && (
        <p className="animate-fade-in text-sm text-muted-foreground">{label}</p>
      )}
    </div>
  );
}

// ── Inline button spinner ─────────────────────────────────────────────────────

export function ButtonSpinner({ className }: { className?: string }) {
  return (
    <Spinner px={16} />
  );
}
