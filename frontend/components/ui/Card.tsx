import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "border border-[var(--surface-border)] bg-white p-4 shadow-sm border-t-2 border-t-[var(--deloitte-green)]",
        className
      )}
      {...props}
    />
  );
}
