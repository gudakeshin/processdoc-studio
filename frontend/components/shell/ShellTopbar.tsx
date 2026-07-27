"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type ShellTopbarProps = {
  onMenuClick?: () => void;
};

export function ShellTopbar({ onMenuClick }: ShellTopbarProps) {
  const pathname = usePathname();
  const crumb = pathname.split("/").filter(Boolean).slice(-2).join(" / ") || "projects";

  return (
    <header className="app-shell-topbar sticky top-0 z-40 flex h-14 items-center justify-between border-b border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white/95 px-4 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3 text-sm text-[var(--text-muted)]">
        <button
          type="button"
          className="flex h-11 w-11 shrink-0 items-center justify-center border border-[var(--surface-border)] bg-[var(--surface-muted)] text-[var(--text-default)] lg:hidden"
          onClick={onMenuClick}
          aria-label="Open navigation menu"
        >
          <Menu size={22} strokeWidth={2} aria-hidden />
        </button>
        <span className="truncate bg-[var(--surface-muted)] px-2 py-0.5 text-xs tracking-wide text-[var(--text-muted)]">
          /{crumb}
        </span>
        <span className="status-pill status-pill--success hidden sm:inline-flex">
          Local-first history
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-3 text-sm text-[var(--accent-blue)]">
        <Link href="/permissions">Permissions</Link>
        <Link href="/login">Account</Link>
      </div>
    </header>
  );
}
