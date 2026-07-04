"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { label: "Studio", segment: "" },
  { label: "Agent Ops", segment: "runs" },
  { label: "Models", segment: "models" },
  { label: "Wiki", segment: "wiki" },
  { label: "Workspace", segment: "workspace" },
  { label: "Settings", segment: "settings" },
] as const;

export function ProjectNav({ pid }: { pid: string }) {
  const pathname = usePathname();
  const base = `/projects/${pid}`;

  return (
    <nav className="flex overflow-x-auto border-b border-[var(--surface-border)] bg-[var(--surface-default)]">
      {NAV_ITEMS.map(({ label, segment }) => {
        const href = segment ? `${base}/${segment}` : base;
        const isActive = segment
          ? Boolean(pathname?.startsWith(`${base}/${segment}`))
          : pathname === base;
        return (
          <Link
            key={label}
            href={href}
            className={[
              "shrink-0 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              isActive
                ? "border-[var(--accent)] text-[var(--text-default)]"
                : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-default)]",
            ].join(" ")}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
