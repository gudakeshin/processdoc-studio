import { type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn(
        "w-full border border-[#E5E5E5] bg-white px-4 py-2 text-sm text-[var(--text-default)] outline-none ring-[#0F0B0B] transition focus:ring-2 focus:border-[#0F0B0B] resize-none",
        props.className
      )}
    />
  );
}
