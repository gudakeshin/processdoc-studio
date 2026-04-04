import { type InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "w-full rounded-md border border-[var(--surface-border-strong)] bg-white px-3 py-2 text-sm text-[var(--text-default)] outline-none ring-[var(--accent-blue-light)] transition focus:ring-2",
        props.className
      )}
    />
  );
}
