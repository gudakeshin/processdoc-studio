import { type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
};

export function Button({ className, variant = "primary", ...props }: Props) {
  return (
    <button
      className={cn(
        "rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" &&
          "bg-[var(--accent-blue)] text-white hover:bg-[var(--accent-indigo)] focus-visible:outline-[var(--accent-green)]",
        variant === "secondary" &&
          "border border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] bg-white text-[var(--primary-900)] hover:bg-[var(--primary-50)]",
        variant === "ghost" && "text-[var(--primary-700)] hover:bg-[color:color-mix(in_srgb,var(--primary-100)_70%,white)]",
        className
      )}
      {...props}
    />
  );
}
