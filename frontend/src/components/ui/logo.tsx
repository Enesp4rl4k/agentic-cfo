"use client";

import { SailMark } from "@/components/brand-landing/SailMark";
import { brand } from "@/lib/branding";
import { cn } from "@/lib/utils";

interface LogoProps {
  size?: "sm" | "md" | "lg" | "xl";
  variant?: "full" | "icon" | "wordmark";
  className?: string;
}

const SIZE_MAP = {
  sm: { icon: 22, text: "text-[15px]", gap: "gap-2" },
  md: { icon: 30, text: "text-[19px]", gap: "gap-2.5" },
  lg: { icon: 38, text: "text-2xl", gap: "gap-3" },
  xl: { icon: 52, text: "text-3xl", gap: "gap-3.5" },
};

/**
 * The product mark: the sail of logo v4 and the name in Cinzel capitals
 * (DESIGN.md → Logo). The sail is the small cut below 32 px, where the mast
 * and yard carry the T. Both draw in the surrounding text colour, so the mark
 * follows the sidebar's ink panel, the top bar and the footer without props.
 *
 * The name is a Latin proper name, upper-cased by the Latin rule (TIPHYS, no dotted İ).
 */
export function Logo({ size = "md", variant = "full", className }: LogoProps) {
  const cfg = SIZE_MAP[size];
  const word = brand.name.toLocaleUpperCase("en-US");
  const mark = <SailMark size={cfg.icon} small={cfg.icon < 32} />;
  const name = (
    <span className={cn("font-cinzel font-bold leading-none tracking-[0.14em]", cfg.text)}>{word}</span>
  );

  if (variant === "icon") return <span className={cn("inline-flex items-center", className)}>{mark}</span>;
  if (variant === "wordmark") return <span className={cn("inline-flex items-center", className)}>{name}</span>;
  return (
    <span className={cn("inline-flex items-center", cfg.gap, className)}>
      {mark}
      {name}
    </span>
  );
}
