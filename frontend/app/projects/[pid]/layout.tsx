"use client";

import { useParams } from "next/navigation";
import { ProjectNav } from "@/components/project-studio/ProjectNav";

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";

  return (
    <div className="space-y-0">
      <ProjectNav pid={pid} />
      <div className="p-4">{children}</div>
    </div>
  );
}
