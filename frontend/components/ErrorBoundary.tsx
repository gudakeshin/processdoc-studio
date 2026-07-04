"use client";

import React, { type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** Optional scoped fallback (e.g. for a single panel) instead of the full-page default. */
  fallback?: (reset: () => void) => ReactNode;
  /** Label used in the default fallback's heading/log line to identify which region failed. */
  label?: string;
};

type State = { error: Error | null };

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`ErrorBoundary${this.props.label ? ` (${this.props.label})` : ""}:`, error, info.componentStack);
  }

  reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.reset);
      }
      return (
        <main className="mx-auto max-w-lg space-y-3 p-8">
          <h1 className="text-xl font-semibold text-[var(--primary-900)]">Something went wrong</h1>
          <p className="text-sm text-[var(--primary-700)]">
            The page hit an unexpected error. Try reloading. If it keeps happening, check the browser console for
            details.
          </p>
          <button
            type="button"
            className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-3 py-2 text-sm text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
            onClick={this.reset}
          >
            Try again
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}

/** Compact inline fallback for a single Studio panel/zone, styled like the rest of the panel chrome. */
export function ZonePanelErrorBoundary({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ErrorBoundary
      label={label}
      fallback={(reset) => (
        <div className="space-y-2 border border-[var(--surface-border)] bg-[var(--surface-muted)] p-3 text-sm">
          <p className="font-medium text-[var(--primary-900)]">{label} hit an error.</p>
          <p className="text-xs text-[var(--text-muted)]">
            The rest of the Studio is unaffected. Check the browser console for details.
          </p>
          <button
            type="button"
            className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-2 py-1 text-xs text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
            onClick={reset}
          >
            Try again
          </button>
        </div>
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
