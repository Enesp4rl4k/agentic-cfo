// Dashboard utility functions for formatting and styling

/**
 * Convert a numeric value to a color based on thresholds.
 * Used for risk scores, KPIs, health indicators.
 */
export function valueToColor(
  value: number,
  thresholds: { good: number; warning: number } = { good: 75, warning: 50 }
): string {
  if (value >= thresholds.good) return "text-emerald-500";
  if (value >= thresholds.warning) return "text-amber-500";
  return "text-red-500";
}

/**
 * Format a number as currency.
 * Accepts "TRY", "USD", or legacy "₺" symbol string.
 */
export function formatCurrency(value: number, currency: string = "TRY"): string {
  // Accept legacy "₺" calls — treat as TRY
  const resolved = currency === "₺" ? "TRY" : currency;
  try {
    return new Intl.NumberFormat("tr-TR", {
      style: "currency",
      currency: resolved,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    // Fallback for unrecognized currency codes
    return `${currency}${value.toLocaleString("tr-TR", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  }
}

/**
 * Format a decimal as percentage
 */
export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Format large numbers with K/M/B suffixes
 */
export function formatCompact(value: number, decimals = 1): string {
  if (Math.abs(value) >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(decimals)}B`;
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(decimals)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `${(value / 1_000).toFixed(decimals)}K`;
  }
  return value.toFixed(decimals);
}

/**
 * Format a number with locale-aware separators
 */
export function formatNumber(value: number, decimals = 0): string {
  return value.toLocaleString("tr-TR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Get a CSS color class for severity levels
 */
export function severityToColor(severity: string): string {
  switch (severity.toLowerCase()) {
    case "critical":
      return "text-red-500 bg-red-500/10 border-red-500/30";
    case "high":
      return "text-orange-500 bg-orange-500/10 border-orange-500/30";
    case "medium":
      return "text-amber-500 bg-amber-500/10 border-amber-500/30";
    case "low":
      return "text-blue-500 bg-blue-500/10 border-blue-500/30";
    default:
      return "text-muted-foreground bg-muted border-border";
  }
}

/**
 * Get a CSS color class for severity (alias used by audit/coo pages).
 * @param severity - severity level string
 * @param solid - if true, returns a solid background variant (text-white friendly)
 */
export function getSeverityColorClass(severity: string, solid = false): string {
  if (solid) {
    switch (severity.toLowerCase()) {
      case "critical": return "bg-red-600";
      case "high":     return "bg-orange-500";
      case "medium":   return "bg-amber-500";
      case "low":      return "bg-blue-500";
      default:         return "bg-muted-foreground";
    }
  }
  return severityToColor(severity);
}

/**
 * Get trend indicator icon/color
 */
export function getTrendStyle(trend: string): {
  color: string;
  direction: "up" | "down" | "stable";
} {
  switch (trend.toLowerCase()) {
    case "up":
    case "increasing":
    case "improving":
      return { color: "text-emerald-500", direction: "up" };
    case "down":
    case "decreasing":
    case "declining":
      return { color: "text-red-500", direction: "down" };
    default:
      return { color: "text-muted-foreground", direction: "stable" };
  }
}

/**
 * Calculate health score color
 */
export function healthScoreColor(score: number): string {
  if (score >= 80) return "text-emerald-500";
  if (score >= 60) return "text-blue-500";
  if (score >= 40) return "text-amber-500";
  return "text-red-500";
}

/**
 * Format a date string to Turkish locale (DD.MM.YYYY)
 */
export function formatDateTR(dateString: string | null | undefined): string {
  if (!dateString) return "—";
  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return dateString;
    return date.toLocaleDateString("tr-TR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return dateString;
  }
}

/**
 * Calculate number of days between two date strings
 */
export function daysBetween(
  dateA: string | null | undefined,
  dateB: string | null | undefined = new Date().toISOString()
): number {
  if (!dateA || !dateB) return 0;
  const a = new Date(dateA).getTime();
  const b = new Date(dateB).getTime();
  return Math.round(Math.abs(b - a) / 86_400_000);
}

/**
 * Generate heatmap matrix data from a 2D array of numbers.
 * Returns normalized values (0–1) for color mapping.
 */
export function generateHeatmapData(
  matrix: number[][],
  labels: string[]
): { row: string; col: string; value: number; raw: number }[] {
  const result: { row: string; col: string; value: number; raw: number }[] = [];
  const flat = matrix.flat();
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const range = max - min || 1;

  for (let r = 0; r < matrix.length; r++) {
    for (let c = 0; c < (matrix[r]?.length ?? 0); c++) {
      const raw = matrix[r][c] ?? 0;
      result.push({
        row: labels[r] ?? `R${r}`,
        col: labels[c] ?? `C${c}`,
        value: (raw - min) / range,
        raw,
      });
    }
  }
  return result;
}

/**
 * Format date as relative time
 */
export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 30) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

/**
 * Generate gradient background for cards
 */
export function getGradientClass(theme: "primary" | "success" | "warning" | "danger"): string {
  switch (theme) {
    case "primary":
      return "bg-gradient-to-br from-blue-500/10 to-purple-500/10";
    case "success":
      return "bg-gradient-to-br from-emerald-500/10 to-teal-500/10";
    case "warning":
      return "bg-gradient-to-br from-amber-500/10 to-orange-500/10";
    case "danger":
      return "bg-gradient-to-br from-red-500/10 to-pink-500/10";
  }
}
