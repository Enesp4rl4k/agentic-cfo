"use client";

import { cn } from "@/lib/utils";

interface LogoProps {
  size?: "sm" | "md" | "lg" | "xl";
  variant?: "full" | "icon" | "wordmark";
  className?: string;
}

const SIZE_MAP = {
  sm: { icon: 20, text: "text-sm",  gap: "gap-1.5" },
  md: { icon: 28, text: "text-base", gap: "gap-2"   },
  lg: { icon: 36, text: "text-xl",  gap: "gap-2.5" },
  xl: { icon: 48, text: "text-2xl", gap: "gap-3"   },
};

/**
 * C-Level AI logo mark — a stylized "C" with a neural spark inside.
 * The outer arc represents the "C" letterform; the inner dots represent
 * AI nodes / executive decision points.
 */
function LogoMark({ size }: { size: number }) {
  const s = size;
  const cx = s / 2;
  const cy = s / 2;
  const r  = s * 0.42;

  return (
    <svg
      width={s}
      height={s}
      viewBox={`0 0 ${s} ${s}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Glow background */}
      <circle cx={cx} cy={cy} r={r + 2} fill="url(#brandGlow)" opacity={0.2} />

      {/* "C" arc — 220° sweep (gap on right) */}
      <path
        d={`
          M ${cx + r * Math.cos(Math.PI * 0.17)} ${cy + r * Math.sin(Math.PI * 0.17)}
          A ${r} ${r} 0 1 0
            ${cx + r * Math.cos(-Math.PI * 0.17)} ${cy + r * Math.sin(-Math.PI * 0.17)}
        `}
        stroke="url(#brandGradient)"
        strokeWidth={s * 0.095}
        strokeLinecap="round"
        fill="none"
      />

      {/* Center AI node */}
      <circle cx={cx} cy={cy} r={s * 0.075} fill="url(#brandGradient)" />

      {/* Orbital dots — 3 nodes representing CFO, CEO, COO */}
      {[0, 120, 240].map((deg, i) => {
        const angle = (deg - 90) * (Math.PI / 180);
        const nr = r * 0.52;
        return (
          <circle
            key={i}
            cx={cx + nr * Math.cos(angle)}
            cy={cy + nr * Math.sin(angle)}
            r={s * 0.045}
            fill="url(#brandGradient)"
            opacity={0.8}
          />
        );
      })}

      {/* Connection lines from center to orbital dots */}
      {[0, 120, 240].map((deg, i) => {
        const angle = (deg - 90) * (Math.PI / 180);
        const nr = r * 0.52;
        return (
          <line
            key={`l${i}`}
            x1={cx}
            y1={cy}
            x2={cx + nr * Math.cos(angle)}
            y2={cy + nr * Math.sin(angle)}
            stroke="url(#brandGradient)"
            strokeWidth={s * 0.025}
            opacity={0.45}
          />
        );
      })}

      {/* Gradient definitions */}
      <defs>
        <linearGradient id="brandGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%"   stopColor="oklch(0.72 0.26 262)" />
          <stop offset="100%" stopColor="oklch(0.58 0.22 220)" />
        </linearGradient>
        <radialGradient id="brandGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="oklch(0.62 0.26 262)" stopOpacity="0.6" />
          <stop offset="100%" stopColor="oklch(0.62 0.26 262)" stopOpacity="0"   />
        </radialGradient>
      </defs>
    </svg>
  );
}

export function Logo({ size = "md", variant = "full", className }: LogoProps) {
  const cfg = SIZE_MAP[size];

  if (variant === "icon") {
    return (
      <span className={cn("inline-flex items-center", className)}>
        <LogoMark size={cfg.icon} />
      </span>
    );
  }

  if (variant === "wordmark") {
    return (
      <span className={cn("inline-flex items-center font-bold tracking-tight", cfg.text, className)}>
        <span className="bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent">
          C-Level
        </span>
        <span className="ml-1 text-foreground/90">AI</span>
      </span>
    );
  }

  // Full: icon + wordmark
  return (
    <span className={cn("inline-flex items-center", cfg.gap, className)}>
      <LogoMark size={cfg.icon} />
      <span className={cn("font-bold tracking-tight leading-none", cfg.text)}>
        <span className="bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent">
          C-Level
        </span>
        <span className="ml-1 text-foreground/90">AI</span>
      </span>
    </span>
  );
}

export default Logo;
