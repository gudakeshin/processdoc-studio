"use client";

import { useParams } from "next/navigation";

import { RunStudioView } from "@/components/run-studio/RunStudioView";
import { useRunStudio } from "@/hooks/useRunStudio";

export default function RunStudio({
  liveEvents,
  streamError,
  pollMode,
}: {
  liveEvents: string[];
  streamError: string | null;
  pollMode: boolean;
}) {
  const params = useParams();
  const pid =
    typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const rid =
    typeof params.rid === "string" ? params.rid : Array.isArray(params.rid) ? params.rid[0] ?? "" : "";

  const studio = useRunStudio({ pid, rid, liveEvents, streamError, pollMode });
  return <RunStudioView {...studio} />;
}
