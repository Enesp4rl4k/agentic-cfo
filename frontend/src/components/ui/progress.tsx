import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * shadcn's Progress without @radix-ui/react-progress (not installed): the same
 * markup Radix renders — a div with role="progressbar" and a translated bar.
 */
interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number | null;
  max?: number;
  indicatorClassName?: string;
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value, max = 100, indicatorClassName, ...props }, ref) => {
    const pct = value == null ? null : Math.min(100, Math.max(0, (value / max) * 100));
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value ?? undefined}
        data-state={pct == null ? "indeterminate" : pct >= 100 ? "complete" : "loading"}
        className={cn("relative h-2 w-full overflow-hidden rounded-full bg-primary/20", className)}
        {...props}
      >
        <div
          className={cn("h-full w-full flex-1 bg-primary transition-transform", indicatorClassName)}
          style={{ transform: `translateX(-${100 - (pct ?? 0)}%)` }}
        />
      </div>
    );
  }
);
Progress.displayName = "Progress";

export { Progress };
