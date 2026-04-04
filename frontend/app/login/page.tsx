"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useAuth } from "@/lib/auth-context";

function LoginForm() {
  const { login, ready } = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/projects";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  if (!ready) {
    return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  }

  return (
    <div className="deloitte-surface p-8 shadow-sm">
      <div className="mb-6 text-sm font-semibold text-[var(--text-default)]">
        <span className="text-[var(--accent-green)]">Deloitte</span> ProcessDoc Studio
      </div>
      <h1 className="text-xl font-semibold text-[var(--text-default)]">Sign in</h1>
      <p className="mt-2 text-sm text-[var(--text-muted)]">
        First sign-in creates your account. Use a strong password for local development.
      </p>
      <form onSubmit={onSubmit} className="mt-6 grid gap-4">
        <label className="grid gap-1.5 text-sm font-medium text-[var(--text-default)]">
          Email
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-[var(--text-default)]">
          Password
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </label>
        {error ? (
          <p className="rounded-md border border-[color:color-mix(in_srgb,var(--error)_35%,white)] bg-[var(--error-light)] px-3 py-2 text-sm text-[var(--error)]">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={busy} className="w-full justify-center">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm">
        <Link href="/" className="text-[var(--accent-blue)]">
          Home
        </Link>
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--primary-50)] px-4 py-10">
      <div className="w-full max-w-[420px]">
        <Suspense
          fallback={<p className="text-center text-sm text-[var(--text-muted)]">Loading…</p>}
        >
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
