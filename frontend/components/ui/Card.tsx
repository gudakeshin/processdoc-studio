import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "border border-[#E5E5E5] bg-white p-4 shadow-sm border-t-2 border-t-[#86BC24]",
        className
      )}
      {...props}
    />
  );
}
