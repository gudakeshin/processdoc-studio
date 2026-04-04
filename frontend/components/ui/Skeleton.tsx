import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-[color:color-mix(in_srgb,var(--primary-200)_60%,white)]", className)}
      aria-hidden
    />
  );
}
