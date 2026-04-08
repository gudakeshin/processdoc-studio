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
          "bg-[#86BC24] text-white hover:bg-[#7aa71f] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F0B0B]",
        variant === "secondary" &&
          "border-2 border-[#0F0B0B] bg-white text-[#0F0B0B] hover:bg-[#f6f8f9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F0B0B]",
        variant === "ghost" && "text-[#4C4C4C] hover:bg-[#f6f8f9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F0B0B]",
        className
      )}
      {...props}
    />
  );
}
