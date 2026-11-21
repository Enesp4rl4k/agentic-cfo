"use client";

import * as React from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { useCan } from "@/hooks/useCan";
import { cn } from "@/lib/utils";
import type { GatedAction } from "@/lib/roles";

/**
 * A button for an action the backend guards by role. When the role may not,
 * it stays visible but inert: `aria-disabled` (not `disabled`, which cannot be
 * focused or hovered, so the reason would never show), no click, and the reason
 * as its title and description. The caller's own `disabled` (no month chosen yet) is
 * dropped while blocked: the reason is the only thing the person needs to see.
 */
export const CanButton = React.forwardRef<HTMLButtonElement, ButtonProps & { action: GatedAction }>(
  ({ action, onClick, className, title, children, disabled, ...rest }, ref) => {
    const can = useCan(action);
    const reasonId = React.useId();
    if (can.allowed) {
      return (
        <Button ref={ref} onClick={onClick} className={className} title={title} disabled={disabled} {...rest}>
          {children}
        </Button>
      );
    }
    return (
      <>
        <Button
          ref={ref}
          {...rest}
          type="button"
          aria-disabled="true"
          aria-describedby={reasonId}
          title={can.reason ?? undefined}
          className={cn("cursor-not-allowed opacity-50", className)}
          onClick={(e) => e.preventDefault()}
        >
          {children}
        </Button>
        <span id={reasonId} className="sr-only">
          {can.reason}
        </span>
      </>
    );
  },
);
CanButton.displayName = "CanButton";
