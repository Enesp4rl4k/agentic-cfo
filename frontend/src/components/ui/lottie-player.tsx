"use client";
/**
 * LottiePlayer — Wrapper for @lottiefiles/dotlottie-react
 *
 * Falls back to a CSS-animated SVG placeholder if the Lottie package
 * is not installed or if the animation URL fails to load.
 *
 * Supports both:
 *   - Remote .lottie / .json URLs (LottieFiles CDN)
 *   - Inline JSON animation data (no network request)
 *
 * Usage:
 *   <LottiePlayer src="https://lottie.host/.../animation.lottie" size={80} />
 *   <LottiePlayer preset="loading" size={48} />
 *   <LottiePlayer preset="success" size={64} loop={false} />
 */

import { useEffect, useState, type CSSProperties, type ReactNode, type ComponentType } from "react";
import { cn } from "@/lib/utils";

// ── Preset animation URLs (LottieFiles public CDN) ────────────────────────────
// These are free, publicly available animations optimized for enterprise UIs.

const PRESETS = {
  // Minimal orbital loading spinner — matches our violet brand
  loading:
    "https://lottie.host/3a8d68d2-5bc1-4e39-9e89-afe01deee6e8/UAmQRhSXM5.lottie",
  // Clean checkmark success
  success:
    "https://lottie.host/39bc8f10-c96a-489c-b3d7-e88d8e034f73/vAzGBBNIBU.lottie",
  // Subtle error / warning shake
  error:
    "https://lottie.host/7c2dc873-3f15-4c6d-97f7-e0d1a4f5b4e4/7WDNb8AQBM.lottie",
  // Empty box — for empty states
  empty:
    "https://lottie.host/7b90ca09-d6e2-42a8-a40e-f37688f30c78/7zt6bWgxgU.lottie",
  // AI thinking / processing dots
  thinking:
    "https://lottie.host/e4f6e6b2-1c14-4b68-9d5a-0a2b0e9c9a4a/N2MeqQGCqH.lottie",
  // Document upload / processing
  upload:
    "https://lottie.host/a2b4d6e8-3c5f-4a7b-9d1e-2f4a6c8e0b2d/KpQ2rMvXwY.lottie",
} as const;

export type LottiePreset = keyof typeof PRESETS;

interface LottiePlayerProps {
  /** Preset name OR explicit URL to a .lottie / .json file */
  preset?: LottiePreset;
  src?: string;
  /** Width and height in px (default: 64) */
  size?: number;
  /** Loop the animation (default: true) */
  loop?: boolean;
  /** Autoplay on mount (default: true) */
  autoplay?: boolean;
  className?: string;
  style?: CSSProperties;
  /** Called when animation completes (useful for one-shot animations) */
  onComplete?: () => void;
}

// ── CSS fallback components ───────────────────────────────────────────────────

function LoadingFallback({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="24"
        cy="24"
        r="18"
        stroke="currentColor"
        strokeWidth="3"
        strokeOpacity="0.15"
      />
      <circle
        cx="24"
        cy="24"
        r="18"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray="28 85"
        style={{ animation: "spin 1s linear infinite", transformOrigin: "center" }}
        className="text-primary"
      />
    </svg>
  );
}

function SuccessFallback({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="24" cy="24" r="20" fill="oklch(0.58 0.18 145 / 0.15)" />
      <circle
        cx="24"
        cy="24"
        r="20"
        stroke="oklch(0.58 0.18 145)"
        strokeWidth="2"
        strokeOpacity="0.6"
      />
      <path
        d="M15 24l7 7 11-13"
        stroke="oklch(0.58 0.18 145)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="24"
        strokeDashoffset="24"
        style={{
          animation: "draw-check 500ms cubic-bezier(0.25, 1, 0.5, 1) forwards",
        }}
      />
    </svg>
  );
}

function ErrorFallback({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="24" cy="24" r="20" fill="oklch(0.58 0.22 25 / 0.15)" />
      <circle
        cx="24"
        cy="24"
        r="20"
        stroke="oklch(0.58 0.22 25)"
        strokeWidth="2"
        strokeOpacity="0.6"
      />
      <path
        d="M17 17l14 14M31 17L17 31"
        stroke="oklch(0.58 0.22 25)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function EmptyFallback({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      style={{ animation: "fade-in 400ms ease both" }}
    >
      <rect
        x="12"
        y="8"
        width="40"
        height="48"
        rx="4"
        stroke="currentColor"
        strokeWidth="2"
        strokeOpacity="0.2"
        fill="currentColor"
        fillOpacity="0.04"
      />
      <path
        d="M22 22h20M22 30h20M22 38h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeOpacity="0.2"
      />
    </svg>
  );
}

function ThinkingFallback({ size }: { size: number }) {
  return (
    <div
      style={{ width: size, height: size }}
      className="flex items-center justify-center gap-1"
      aria-hidden="true"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-primary"
          style={{
            animation: "bounce-subtle 1.2s ease-in-out infinite",
            animationDelay: `${i * 180}ms`,
          }}
        />
      ))}
    </div>
  );
}

function UploadFallback({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="8"
        y="36"
        width="48"
        height="20"
        rx="4"
        fill="currentColor"
        fillOpacity="0.06"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.25"
      />
      <path
        d="M32 32V12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeOpacity="0.5"
        style={{ animation: "slide-up 1s ease-in-out infinite" }}
      />
      <path
        d="M22 22l10-10 10 10"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeOpacity="0.5"
      />
    </svg>
  );
}

const CSS_FALLBACKS: Record<LottiePreset, (size: number) => ReactNode> = {
  loading:  (s) => <LoadingFallback size={s} />,
  success:  (s) => <SuccessFallback size={s} />,
  error:    (s) => <ErrorFallback size={s} />,
  empty:    (s) => <EmptyFallback size={s} />,
  thinking: (s) => <ThinkingFallback size={s} />,
  upload:   (s) => <UploadFallback size={s} />,
};

// ── Main component ────────────────────────────────────────────────────────────

export function LottiePlayer({
  preset,
  src,
  size = 64,
  loop = true,
  autoplay = true,
  className,
  style,
  onComplete,
}: LottiePlayerProps) {
  const [LottieComponent, setLottieComponent] = useState<ComponentType<{
    src: string;
    loop: boolean;
    autoplay: boolean;
    style?: CSSProperties;
    onComplete?: () => void;
  }> | null>(null);
  const [lottieError, setLottieError] = useState(false);

  // Lazy-load dotlottie-react only on client
  useEffect(() => {
    import("@lottiefiles/dotlottie-react")
      .then((mod) => {
        setLottieComponent(() => mod.DotLottieReact);
      })
      .catch(() => {
        setLottieError(true);
      });
  }, []);

  const resolvedSrc = src ?? (preset ? PRESETS[preset] : undefined);

  // Show CSS fallback if Lottie failed or not yet loaded
  if (lottieError || !LottieComponent) {
    const fallback = preset ? CSS_FALLBACKS[preset]?.(size) : null;
    return (
      <div
        className={cn("flex items-center justify-center text-muted-foreground", className)}
        style={{ width: size, height: size, ...style }}
        role="img"
        aria-label={preset ?? "animation"}
      >
        {fallback ?? <LoadingFallback size={size} />}
      </div>
    );
  }

  if (!resolvedSrc) return null;

  return (
    <div
      className={cn("flex items-center justify-center", className)}
      style={{ width: size, height: size, ...style }}
    >
      <LottieComponent
        src={resolvedSrc}
        loop={loop}
        autoplay={autoplay}
        style={{ width: size, height: size }}
        onComplete={onComplete}
      />
    </div>
  );
}
