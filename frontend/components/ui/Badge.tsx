import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-3 py-1 text-xs font-medium border border-[#E5E5E5] bg-white text-[#0F0B0B]",
        className
      )}
      {...props}
    />
  );
}
