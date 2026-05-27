import { type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
};

export function Button({ className, variant = "primary", ...props }: Props) {
  return (
    <button
      className={cn(
        "px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60 active:brightness-90",
        variant === "primary" &&
          "bg-[var(--accent-green)] text-white hover:bg-[var(--accent-green-dark)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coral-black)]",
        variant === "secondary" &&
          "border-2 border-[var(--coral-black)] bg-white text-[var(--coral-black)] hover:bg-[var(--primary-50)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coral-black)]",
        variant === "ghost" && "text-[var(--tundora-gray)] hover:bg-[var(--primary-50)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coral-black)]",
        className
      )}
      {...props}
    />
  );
}
