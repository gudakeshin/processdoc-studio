"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AgentOpsView } from "@/components/run-studio/AgentOpsView";
import { useAuth } from "@/lib/auth-context";

export default function AgentOpsPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const router = useRouter();
  const { token, ready } = useAuth();
  const [hydrated, setHydrated] = useState(false);
  const didRedirectRef = useRef(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      if (didRedirectRef.current) return;
      didRedirectRef.current = true;
      router.replace(`/login?next=${encodeURIComponent(`/projects/${pid}/runs`)}`);
    }
  }, [ready, token, pid, router]);

  if (!hydrated || !ready || !token) {
    return (
      <main style={{ padding: 24 }}>
        <p>Redirecting…</p>
      </main>
    );
  }

  return <AgentOpsView projectId={pid} />;
}
