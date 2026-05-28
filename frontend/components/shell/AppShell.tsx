"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { ShellSidebar } from "@/components/shell/ShellSidebar";
import { ShellTopbar } from "@/components/shell/ShellTopbar";
import { cn } from "@/lib/utils";

const noShellRoutes = ["/login"];

const MATRIX_LS_KEYS = ["processdoc.matrixTheme", "processdoc.matrixThemeLeftPane"] as const;

function readMatrixThemeFromStorage(): boolean {
  if (typeof window === "undefined") return false;
  return (
    MATRIX_LS_KEYS.some((k) => window.localStorage.getItem(k) === "true")
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const noShell = noShellRoutes.some((prefix) => pathname.startsWith(prefix));
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [desktopNavCollapsed, setDesktopNavCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("processdoc.desktopNavCollapsed") === "true";
  });
  const [matrixTheme, setMatrixTheme] = useState(readMatrixThemeFromStorage);

  useEffect(() => {
    if (typeof document === "undefined") return;
    if (noShell) {
      document.documentElement.classList.remove("matrix-app-html");
      return;
    }
    document.documentElement.classList.toggle("matrix-app-html", matrixTheme);
    return () => document.documentElement.classList.remove("matrix-app-html");
  }, [matrixTheme, noShell]);

  const persistMatrixTheme = useCallback((enabled: boolean) => {
    setMatrixTheme(enabled);
    if (typeof window === "undefined") return;
    const v = enabled ? "true" : "false";
    window.localStorage.setItem("processdoc.matrixTheme", v);
    window.localStorage.setItem("processdoc.matrixThemeLeftPane", v);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("processdoc.desktopNavCollapsed", desktopNavCollapsed ? "true" : "false");
  }, [desktopNavCollapsed]);

  useEffect(() => {
    // Close the mobile nav whenever the route changes. Syncing with router
    // state is a legitimate setState-in-effect; cascading render is intended.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMobileNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileNavOpen]);

  if (noShell) {
    return <>{children}</>;
  }

  return (
    <div
      className={cn(
        "flex min-h-screen",
        !matrixTheme && "bg-[var(--primary-50)] text-[var(--primary-900)]",
        matrixTheme && "matrix-app",
      )}
    >
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[100] focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-[var(--primary-900)] focus:shadow-lg focus:outline-2 focus:outline-[var(--accent-blue)]"
      >
        Skip to main content
      </a>
      <ShellSidebar
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
        desktopCollapsed={desktopNavCollapsed}
        onDesktopToggle={() => setDesktopNavCollapsed((prev) => !prev)}
        matrixTheme={matrixTheme}
        onMatrixThemeChange={persistMatrixTheme}
      />
      <div className="app-shell-body relative z-[1] min-w-0 flex-1">
        <ShellTopbar onMenuClick={() => setMobileNavOpen(true)} />
        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1400px] p-4 md:p-6 outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}
