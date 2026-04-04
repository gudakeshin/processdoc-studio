"use client";

import { useParams, useSearchParams } from "next/navigation";

import { ProjectStudioUnified } from "@/components/project-studio/ProjectStudioUnified";

export default function ProjectPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const queryRunId = searchParams.get("run");

  return <ProjectStudioUnified pid={pid} initialRunId={queryRunId} />;
}
