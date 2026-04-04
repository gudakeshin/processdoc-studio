"use client";

import { cn } from "@/lib/utils";

type Props = {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  id?: string;
  /** When true, use CRT sharp borders / checkbox (Matrix palette active). */
  crt?: boolean;
  className?: string;
  /** `sidebar`: labels for dark nav shell; `default`: for light page areas. */
  variant?: "default" | "sidebar";
};

export function MatrixThemeToggle({
  enabled,
  onChange,
  id = "matrix-theme-left-pane",
  crt = false,
  className,
  variant = "default",
}: Props) {
  const sidebar = variant === "sidebar";
  return (
    <div className={cn("flex w-full min-h-11 items-center justify-between gap-3", className)}>
      <div className="min-w-0">
        <label
          htmlFor={id}
          className={cn(
            "cursor-pointer select-none text-xs font-semibold",
            sidebar && !crt && "text-[#e8eef4]",
            !sidebar && "text-[var(--text-default)]",
            crt && "matrix-toggle-label-crt",
          )}
        >
          Matrix theme
        </label>
        <p
          className={cn(
            "mt-0.5 text-2xs leading-snug",
            sidebar && !crt && "text-[#9aa5b1]",
            !sidebar && "text-[var(--text-muted)]",
            crt && "text-[var(--text-muted)]",
          )}
        >
          {sidebar ? "CRT style for the whole app" : "Toggle terminal-style UI"}
        </p>
      </div>
      <input
        id={id}
        type="checkbox"
        role="switch"
        checked={enabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-checked={enabled}
        className={cn(
          "h-5 w-5 shrink-0 cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue-light)]",
          crt ? "matrix-crt-checkbox" : "rounded border-2 border-[var(--surface-border-strong)] bg-[var(--surface-default)] accent-[var(--accent-green)]",
        )}
      />
    </div>
  );
}
