import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type BadgeVariant =
  | "default"
  | "success"
  | "warning"
  | "error"
  | "critical"
  | "info"
  | "secondary";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

// Semantic variant → Tailwind classes. Kept CSS-native (no --var) so the palette
// works whether design tokens are loaded or not.
const VARIANT_STYLES: Record<BadgeVariant, string> = {
  default:   "border-[#E5E5E5] bg-white text-[#0F0B0B]",
  success:   "border-green-200 bg-green-50 text-green-800",
  warning:   "border-amber-200 bg-amber-50 text-amber-800",
  error:     "border-red-200 bg-red-50 text-red-800",
  critical:  "border-red-300 bg-red-100 text-red-900",
  info:      "border-blue-200 bg-blue-50 text-blue-800",
  secondary: "border-gray-200 bg-gray-100 text-gray-700",
};

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-3 py-1 text-xs font-medium border",
        VARIANT_STYLES[variant],
        className
      )}
      {...props}
    />
  );
}
