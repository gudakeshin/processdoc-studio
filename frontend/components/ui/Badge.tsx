import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full bg-[color:color-mix(in_srgb,var(--accent-blue)_12%,white)] px-2 py-0.5 text-xs font-medium text-[var(--accent-indigo)]",
        className
      )}
      {...props}
    />
  );
}
