"use client";

import { useEffect, useState } from "react";

import { type ToastPayload, subscribeToast } from "@/lib/toast-bus";

export function GlobalToastListener() {
  const [toast, setToast] = useState<ToastPayload | null>(null);

  useEffect(() => {
    return subscribeToast((payload) => {
      setToast(payload);
      globalThis.setTimeout(() => setToast(null), 4500);
    });
  }, []);

  if (!toast) return null;

  const kind = toast.kind ?? "info";
  const cls =
    kind === "success"
      ? "alert alert--success border-[var(--surface-border-strong)]"
      : kind === "error"
        ? "alert alert--error"
        : "alert alert--info";

  return (
    <div role="status" aria-live="polite" className={`fixed bottom-4 right-4 z-[60] max-w-sm shadow-lg ${cls}`}>
      {toast.message}
    </div>
  );
}
