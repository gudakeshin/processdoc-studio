"use client";

import {
  BookOpen,
  Brain,
  CalendarClock,
  FolderOpen,
  Lock,
  Puzzle,
  Settings2,
  SlidersHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { MatrixThemeToggle } from "@/components/project-studio/MatrixThemeToggle";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

const links = [
  { href: "/projects", label: "Projects", icon: FolderOpen },
  { href: "/admin/skills", label: "Skills", icon: Puzzle },
  { href: "/admin/lp-library", label: "LP Library", icon: BookOpen },
  { href: "/admin/dpdp", label: "DPDP", icon: Lock },
  { href: "/tasks", label: "Scheduled Tasks", icon: CalendarClock },
  { href: "/customize", label: "Customize", icon: SlidersHorizontal },
  { href: "/memory", label: "Memory", icon: Brain },
  { href: "/projects", label: "Settings", icon: Settings2 },
];

function NavLinkList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      {links.map((item) => {
        const Icon = item.icon;
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={`${item.href}:${item.label}`}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "flex min-h-11 items-center gap-2 rounded-md px-2 py-2 text-sm transition !no-underline",
              active
                ? "bg-[color:color-mix(in_srgb,var(--accent-blue)_30%,black)] !text-white shadow-sm"
                : "!text-[#d9dee3] hover:bg-[color:color-mix(in_srgb,var(--primary-800)_82%,black)] hover:!text-white"
            )}
          >
            <Icon size={18} />
            {item.label}
          </Link>
        );
      })}
    </>
  );
}

type ShellSidebarProps = {
  mobileOpen?: boolean;
  onMobileClose?: () => void;
  desktopCollapsed?: boolean;
  onDesktopToggle?: () => void;
  matrixTheme?: boolean;
  onMatrixThemeChange?: (enabled: boolean) => void;
};

export function ShellSidebar({
  mobileOpen = false,
  onMobileClose,
  desktopCollapsed = false,
  onDesktopToggle,
  matrixTheme = false,
  onMatrixThemeChange,
}: ShellSidebarProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const lastActiveElRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!mobileOpen) {
      // Restore focus after closing the dialog.
      lastActiveElRef.current?.focus?.();
      return;
    }

    lastActiveElRef.current = document.activeElement as HTMLElement | null;

    const panel = panelRef.current;
    // Focus the first actionable element inside the dialog.
    const focusFirst = () => {
      const el = panel?.querySelector<HTMLElement>(
        'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])'
      );
      el?.focus?.();
    };

    // Defer to ensure the panel is mounted and tabbable.
    const t = window.setTimeout(focusFirst, 0);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onMobileClose?.();
        return;
      }

      if (e.key !== "Tab") return;
      if (!panel) return;

      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')
      ).filter((node) => !node.hasAttribute("disabled") && node.tabIndex !== -1);

      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;

      if (e.shiftKey) {
        if (!active || active === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(t);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mobileOpen, onMobileClose]);

  const matrixToggleDesktop =
    onMatrixThemeChange != null ? (
      <MatrixThemeToggle
        id="matrix-theme-sidebar-desktop"
        enabled={matrixTheme}
        onChange={onMatrixThemeChange}
        crt={matrixTheme}
        variant="sidebar"
      />
    ) : null;

  return (
    <>
      <aside
        className={cn(
          "shell-sidebar relative hidden h-screen shrink-0 flex-col border-r border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] bg-[var(--primary-950)] p-4 text-[#f3f6f8] transition-[width] lg:flex",
          desktopCollapsed ? "w-[72px]" : "w-[260px]"
        )}
      >
        <div className="mb-6 flex shrink-0 items-center justify-between gap-2 px-2 text-sm font-semibold">
          {desktopCollapsed ? (
            <span className="text-xs text-[#d9dee3]">ProcessDoc</span>
          ) : (
            <span>
              <span className="text-[var(--accent-green)]">Deloitte</span> ProcessDoc Studio
            </span>
          )}
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded border border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--primary-800)_78%,black)] text-[#f3f6f8]"
            onClick={onDesktopToggle}
            aria-label={desktopCollapsed ? "Expand navigation" : "Collapse navigation"}
            aria-expanded={!desktopCollapsed}
          >
            {desktopCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>
        {desktopCollapsed ? (
          <div className="min-h-0 flex-1" aria-hidden />
        ) : (
          <nav className="shell-sidebar-nav min-h-0 flex-1 space-y-1 overflow-y-auto">
            <NavLinkList />
          </nav>
        )}
        {matrixToggleDesktop ? (
          <div
            className={cn(
              "shell-sidebar-footer mt-auto shrink-0 border-t border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] pt-3",
              desktopCollapsed && "flex justify-center px-0 pt-2"
            )}
          >
            {desktopCollapsed ? (
              <label className="flex cursor-pointer flex-col items-center gap-1" title="Matrix theme">
                <input
                  type="checkbox"
                  role="switch"
                  checked={matrixTheme}
                  onChange={(e) => onMatrixThemeChange?.(e.target.checked)}
                  aria-checked={matrixTheme}
                  aria-label="Matrix theme"
                  className={cn(
                    "h-5 w-5 cursor-pointer",
                    matrixTheme ? "matrix-crt-checkbox" : "rounded border-2 border-[#5a6b78] accent-[var(--accent-green)]"
                  )}
                />
                <span className="text-[10px] uppercase tracking-wide text-[#9aa5b1]">MX</span>
              </label>
            ) : (
              matrixToggleDesktop
            )}
          </div>
        ) : null}
        {desktopCollapsed ? (
          <button
            type="button"
            className="absolute -right-3 top-4 flex h-7 w-7 items-center justify-center rounded-full border border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] bg-[var(--primary-900)] text-[#f3f6f8] shadow"
            onClick={onDesktopToggle}
            aria-label="Expand navigation"
            aria-expanded={false}
            title="Expand navigation"
          >
            <PanelLeftOpen size={14} />
          </button>
        ) : null}
      </aside>

      {/* Mobile drawer */}
      <div
        className={cn(
          "fixed inset-0 z-50 lg:hidden",
          mobileOpen ? "pointer-events-auto" : "pointer-events-none"
        )}
        aria-hidden={!mobileOpen}
      >
        <Button
          type="button"
          variant="ghost"
          className={cn(
            "absolute inset-0 rounded-none bg-black/40 p-0 hover:bg-black/40 transition-opacity motion-reduce:transition-none",
            mobileOpen ? "opacity-100" : "opacity-0"
          )}
          aria-label="Close navigation menu"
          onClick={onMobileClose}
        >
          <span className="sr-only">Close navigation menu</span>
        </Button>
        <div
          className={cn(
            "absolute left-0 top-0 flex h-full w-[min(280px,92vw)] flex-col border-r border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] bg-[var(--primary-950)] p-4 text-[#f3f6f8] shadow-xl transition-transform motion-reduce:transition-none",
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          )}
          role="dialog"
          aria-modal="true"
          aria-labelledby="mobile-nav-title"
          ref={panelRef}
        >
          <div className="mb-4 flex shrink-0 items-center justify-between gap-2">
            <div id="mobile-nav-title" className="text-sm font-semibold">
              <span className="text-[var(--accent-green)]">Deloitte</span> ProcessDoc
            </div>
            <Button
              type="button"
              variant="ghost"
              className="flex h-11 w-11 items-center justify-center rounded-md p-0 text-[#f3f6f8] hover:bg-[color:color-mix(in_srgb,var(--primary-800)_82%,black)] hover:text-[#f3f6f8] bg-transparent"
              onClick={onMobileClose}
              aria-label="Close menu"
            >
              <X size={20} className="text-[#f3f6f8]" />
            </Button>
          </div>
          <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            <NavLinkList onNavigate={onMobileClose} />
          </nav>
          {onMatrixThemeChange ? (
            <div className="shell-sidebar-footer mt-auto shrink-0 border-t border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] pt-3">
              <MatrixThemeToggle
                id="matrix-theme-sidebar-mobile"
                enabled={matrixTheme}
                onChange={onMatrixThemeChange}
                crt={matrixTheme}
                variant="sidebar"
              />
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
