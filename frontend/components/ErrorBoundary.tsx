"use client";

import React, { type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };

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
    console.error("ErrorBoundary:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
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
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
