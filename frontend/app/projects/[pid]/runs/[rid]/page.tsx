"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ProjectStudioUnified } from "@/components/project-studio/ProjectStudioUnified";
import { useAuth } from "@/lib/auth-context";

export default function RunPage() {
  const params = useParams();
  const pid =
    typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const rid =
    typeof params.rid === "string" ? params.rid : Array.isArray(params.rid) ? params.rid[0] ?? "" : "";
  const router = useRouter();
  const { token, ready } = useAuth();
  const [hydrated, setHydrated] = useState(false);
  const didRedirectRef = useRef(false);

  useEffect(() => {
    // Hydration guard to keep server/client initial markup identical.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      if (didRedirectRef.current) return;
      didRedirectRef.current = true;
      router.replace(`/login?next=${encodeURIComponent(`/projects/${pid}/runs/${rid}`)}`);
    }
  }, [ready, token, pid, rid, router]);

  if (!hydrated || !ready || !token) {
    return (
      <main style={{ padding: 24 }}>
        <p>Redirecting…</p>
      </main>
    );
  }

  return <ProjectStudioUnified pid={pid} initialRunId={rid} />;
}
