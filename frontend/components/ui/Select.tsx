import { type SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

// Shared select primitive so app routes don't embed native <select> tags directly.
export function Select({ className, ...props }: SelectProps) {
  return (
    <select
      {...props}
      className={cn(
        "input-select-base w-full min-h-11 text-sm outline-none ring-[var(--accent-blue-light)] transition focus:ring-2",
        className
      )}
    />
  );
}

