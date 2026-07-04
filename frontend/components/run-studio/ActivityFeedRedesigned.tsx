"use client";

import { CheckCircle2, CircleDashed, Loader2, PanelRightClose, PanelRightOpen, XCircle } from "lucide-react";
import React, { useMemo, useState } from "react";
import type { ParsedRunEvent } from "@/lib/runEvents";
import type { RunTodoRow } from "@/lib/runTodosFromEvents";
import { useTodoChecklistState } from "@/hooks/useTodoChecklistState";

/**
 * ActivityFeedRedesigned — enhanced activity sidebar with tabbed interface.
 *
 * Redesigned version of ToolActivityFeed with:
 * - Cleaner tab interface (Activity, Artifacts, Context, Governance)
 * - Better visual hierarchy and spacing
 * - Improved event grouping display
 * - Consistent use of status colors and icons
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToolCall = {
  name: string;
  status: "running" | "done" | "failed";
  summary: string;
};

type SkillGroup = {
  key: string;
  skillName: string;
  status: "running" | "done" | "failed" | "queued";
  tools: ToolCall[];
};

type TabType = "activity" | "artifacts" | "context" | "governance";

// ---------------------------------------------------------------------------
// Event parsing helpers (extracted from ToolActivityFeed)
// ---------------------------------------------------------------------------

function parseEventLine(line: string): {
  eventType: string;
  payloadObj: Record<string, unknown> | null;
} {
  const sep = line.indexOf(":");
  const eventType = (sep >= 0 ? line.slice(0, sep) : "step").trim();
  const payloadText = (sep >= 0 ? line.slice(sep + 1) : line).trim();
  let payloadObj: Record<string, unknown> | null = null;
  try {
    const parsed = JSON.parse(payloadText);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      payloadObj = parsed as Record<string, unknown>;
    }
  } catch {
    /* ignore unparseable payloads */
  }
  return { eventType, payloadObj };
}

function mergeRunEventPayload(p: Record<string, unknown> | null): Record<string, unknown> {
  if (!p) return {};
  const inner = p.payload;
  if (inner && typeof inner === "object" && !Array.isArray(inner)) {
    return { ...p, ...(inner as Record<string, unknown>) };
  }
  return p;
}

function buildSkillGroups(events: ParsedRunEvent[]): SkillGroup[] {
  const groups: SkillGroup[] = [];
  const groupIndex: Record<string, number> = {};
  let queueSeen = false;
  let executionStarted = false;

  // Coordinator plan as first group if present
  for (const event of events) {
    if ((event.eventType === "coordinator_plan" || event.eventType === "execution_plan") && event.payload) {
      const ep = event.payload as Record<string, unknown>;
      const plannedOutputs = Array.isArray(ep.planned_outputs) ? (ep.planned_outputs as string[]) : [];
      if (plannedOutputs.length > 0 && !("__coordinator__" in groupIndex)) {
        groupIndex["__coordinator__"] = groups.length;
        groups.push({
          key: "__coordinator__",
          skillName: "Digital Teammate",
          status: "done",
          tools: plannedOutputs.map((o) => ({
            name: o,
            status: "done" as const,
            summary: String((ep.per_output_notes as Record<string, unknown>)?.[o] ?? "planned"),
          })),
        });
      }
    }
  }

  // Skill + tool events
  for (const event of events) {
    if (event.eventType === "step" && event.payload) {
      const ep = event.payload as Record<string, unknown>;
      const raw = String(ep.status ?? "");
      if (raw === "execution_enqueued") {
        queueSeen = true;
      }
      if (raw === "execution_started") {
        executionStarted = true;
      }
      const skillName = String(ep.skill_name ?? ep.agent ?? ep.output_type ?? ep.step ?? "Agent");
      const key = skillName.toLowerCase().replace(/\s+/g, "_");

      if (!(key in groupIndex)) {
        groupIndex[key] = groups.length;
        groups.push({
          key,
          skillName,
          status: "queued",
          tools: [],
        });
      }

      const g = groups[groupIndex[key]];
      if (raw.includes("fail") || raw.includes("error")) {
        g.status = "failed";
      } else if (raw.includes("post_processing_done") || (raw.includes("processing_done") && raw.includes("post"))) {
        g.status = "done";
      } else if (raw.includes("done") || raw.includes("complet") || raw.includes("finish")) {
        g.status = "done";
      } else if (raw.includes("post_processing_start") || (raw.includes("post_processing") && !raw.includes("done"))) {
        g.status = "running";
      } else if (raw.includes("start") || raw.includes("run")) {
        g.status = "running";
      }
    }

    // Tool call events
    if (event.eventType === "agent_tool_round" && event.payload) {
      const ep = event.payload as Record<string, unknown>;
      const skillName = String(ep.skill_name ?? ep.agent ?? ep.output_type ?? "Agent");
      const key = skillName.toLowerCase().replace(/\s+/g, "_");

      if (!(key in groupIndex)) {
        groupIndex[key] = groups.length;
        groups.push({ key, skillName, status: "running", tools: [] });
      }
      const g = groups[groupIndex[key]];

      const toolNames = Array.isArray(ep.tool_names) ? (ep.tool_names as string[]) : [];
      if (toolNames.length === 0) {
        g.tools.push({
          name: "tool round",
          status: "done",
          summary: "No tool names in event payload",
        });
      } else {
        toolNames.forEach((toolName) => {
          g.tools.push({
            name: toolName,
            status: "done",
            summary: "Tool executed",
          });
        });
      }
    }
  }

  if (queueSeen && !executionStarted && !groups.some((g) => g.key === "__queue__")) {
    groups.unshift({
      key: "__queue__",
      skillName: "Run queue",
      status: "queued",
      tools: [
        {
          name: "Queued for execution worker",
          status: "running",
          summary: "Waiting for a worker process to pick up this run.",
        },
      ],
    });
  }

  return groups;
}

// ---------------------------------------------------------------------------
// Status icons
// ---------------------------------------------------------------------------

function GroupStatusIcon({ status }: { status: SkillGroup["status"] }) {
  const baseClass = "h-3.5 w-3.5 shrink-0";
  if (status === "running") return <Loader2 className={`${baseClass} animate-spin text-[#0072B1]`} aria-hidden />;
  if (status === "done") return <CheckCircle2 className={`${baseClass} text-[#2D7A3B]`} aria-hidden />;
  if (status === "failed") return <XCircle className={`${baseClass} text-[#B23C3C]`} aria-hidden />;
  return <CircleDashed className={`${baseClass} text-[#999]`} aria-hidden />;
}

function StatusBadge({ status }: { status: SkillGroup["status"] }) {
  const bgColor =
    status === "running"
      ? "bg-[#E3F2FD]"
      : status === "done"
        ? "bg-[#E8F5E9]"
        : status === "failed"
          ? "bg-[#FFEBEE]"
          : "bg-[#F5F5F5]";

  const textColor =
    status === "running"
      ? "text-[#0072B1]"
      : status === "done"
        ? "text-[#2D7A3B]"
        : status === "failed"
          ? "text-[#B23C3C]"
          : "text-[#666]";

  return (
    <span className={`inline-flex items-center gap-1 text-2xs font-semibold uppercase px-2 py-1 rounded ${bgColor} ${textColor}`}>
      <GroupStatusIcon status={status} />
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Tab components
// ---------------------------------------------------------------------------

function ActivityTab({ skillGroups }: { skillGroups: SkillGroup[] }) {
  return (
    <div className="space-y-3">
      {skillGroups.length === 0 ? (
        <p className="text-xs text-[#999] px-3 py-2">No execution events yet.</p>
      ) : (
        skillGroups.map((group) => (
          <div key={group.key} className="border-l-2 border-[#E0E0E0] pl-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-[#1a1a1a]">{group.skillName}</h3>
              </div>
              <StatusBadge status={group.status} />
            </div>
            {group.tools.length > 0 && (
              <div className="mt-2 space-y-1">
                {group.tools.map((tool, idx) => (
                  <div key={`${group.key}-tool-${tool.name}-${idx}`} className="text-xs">
                    <p className="font-medium text-[#333]">{tool.name}</p>
                    <p className="text-[#666] mt-0.5">{tool.summary}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function ArtifactsTab({ artifacts }: { artifacts: any[] }) {
  const readyArtifacts = Array.isArray(artifacts) ? artifacts.filter((a) => a && a.status === "ready") : [];
  return (
    <div className="space-y-2">
      {readyArtifacts.length === 0 ? (
        <p className="text-xs text-[#999] px-3 py-2">No artifacts ready yet.</p>
      ) : (
        readyArtifacts.map((artifact, idx) => (
          <div key={artifact.name ?? `artifact-${idx}`} className="border border-[#E0E0E0] rounded p-2">
            <p className="text-xs font-semibold text-[#1a1a1a]">{artifact.name}</p>
            <p className="text-2xs text-[#666] mt-1">{artifact.type || "File"}</p>
            {artifact.size && <p className="text-2xs text-[#999] mt-1">{Math.round(artifact.size / 1024)} KB</p>}
          </div>
        ))
      )}
    </div>
  );
}

function ContextTab({ contextMetadata }: { contextMetadata?: any }) {
  const leadingPractices = contextMetadata?.leadingPractices || [];
  const nonNegotiables = contextMetadata?.nonNegotiables || [];

  return (
    <div className="space-y-4">
      {leadingPractices.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-[#1a1a1a] mb-2">Leading Practices</h3>
          <div className="space-y-1">
            {leadingPractices.map((lp: string, idx: number) => (
              <p key={`lp-${idx}-${lp.slice(0, 20)}`} className="text-2xs text-[#666] leading-relaxed">
                {lp}
              </p>
            ))}
          </div>
        </div>
      )}

      {nonNegotiables.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-[#1a1a1a] mb-2">Non-Negotiables</h3>
          <div className="space-y-1">
            {nonNegotiables.map((nn: string, idx: number) => (
              <p key={`nn-${idx}-${nn.slice(0, 20)}`} className="text-2xs text-[#666] leading-relaxed">
                {nn}
              </p>
            ))}
          </div>
        </div>
      )}

      {leadingPractices.length === 0 && nonNegotiables.length === 0 && (
        <p className="text-xs text-[#999]">No context metadata available.</p>
      )}
    </div>
  );
}

function GovernanceTab({ permissionStages }: { permissionStages?: any[] }) {
  const stages = permissionStages || [];
  return (
    <div className="space-y-2">
      {stages.length === 0 ? (
        <p className="text-xs text-[#999] px-3 py-2">No governance checks available.</p>
      ) : (
        stages.map((stage, idx) => (
          <div key={stage.name ?? `stage-${idx}`} className="border border-[#E0E0E0] rounded p-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold text-[#1a1a1a]">{stage.name}</h3>
              <span
                className={`text-2xs font-semibold px-2 py-1 rounded ${
                  stage.status === "approved" ? "bg-[#E8F5E9] text-[#2D7A3B]" : stage.status === "blocked" ? "bg-[#FFEBEE] text-[#B23C3C]" : "bg-[#FEF3E2] text-[#B8651A]"
                }`}
              >
                {stage.status}
              </span>
            </div>
            {stage.timestamp && <p className="text-2xs text-[#999] mt-1">{stage.timestamp}</p>}
          </div>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ActivityFeedRedesigned({
  parsedEvents = [],
  artifacts = [],
  runTodos = [],
  contextMetadata,
  permissionStages,
  width = 360,
  expanded = true,
  onToggleExpanded,
}: {
  parsedEvents: ParsedRunEvent[];
  artifacts: any[];
  runTodos: RunTodoRow[];
  contextMetadata?: {
    leadingPractices?: string[];
    nonNegotiables?: string[];
  };
  permissionStages?: Array<{
    name: string;
    status: "approved" | "pending" | "blocked";
    timestamp?: string;
  }>;
  width?: number;
  expanded?: boolean;
  onToggleExpanded?: () => void;
}) {
  const [activeTab, setActiveTab] = useState<TabType>("activity");

  const skillGroups = useMemo(() => buildSkillGroups(parsedEvents), [parsedEvents]);
  const todoState = useTodoChecklistState({
    parsedEvents,
    snapshotRows: runTodos,
  });

  const activityCount = skillGroups.length;
  const artifactCount = Array.isArray(artifacts) ? artifacts.filter((a) => a && a.status === "ready").length : 0;
  const governanceCount = permissionStages?.length || 0;

  const tabLabels: Record<TabType, string> = {
    activity: `Activity${activityCount > 0 ? ` (${activityCount})` : ""}`,
    artifacts: `Artifacts${artifactCount > 0 ? ` (${artifactCount})` : ""}`,
    context: "Context",
    governance: `Governance${governanceCount > 0 ? ` (${governanceCount})` : ""}`,
  };

  if (!expanded) {
    return (
      <aside
        className="min-h-0 flex flex-col items-center bg-[#F9F9F9] border-l border-[#E0E0E0] py-2"
        style={{ width: "44px" }}
        role="complementary"
        aria-label="Activity feed sidebar (collapsed)"
      >
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-label="Expand activity feed"
          aria-expanded={false}
          className="rounded p-2 text-[#666] hover:bg-[#F0F7FF] hover:text-[#0072B1]"
        >
          <PanelRightOpen className="h-4 w-4" />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className="min-h-0 flex flex-col bg-[#F9F9F9] border-l border-[#E0E0E0]"
      style={{ width: `${width}px` }}
      role="complementary"
      aria-label="Activity feed sidebar"
    >
      {/* Tab bar */}
      <div className="flex items-center border-b border-[#E0E0E0] bg-white" role="tablist" aria-label="Activity feed sections">
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-label="Collapse activity feed"
          aria-expanded={true}
          className="px-2 py-2 text-[#666] hover:bg-[#F0F7FF] hover:text-[#0072B1]"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
        {(["activity", "artifacts", "context", "governance"] as TabType[]).map((tab) => (
          <button
            key={tab}
            id={`activity-feed-tab-${tab}`}
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`activity-feed-panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => setActiveTab(tab)}
            onKeyDown={(e) => {
              const tabs: TabType[] = ["activity", "artifacts", "context", "governance"];
              const idx = tabs.indexOf(tab);
              if (e.key === "ArrowRight") { e.preventDefault(); setActiveTab(tabs[(idx + 1) % tabs.length]); }
              else if (e.key === "ArrowLeft") { e.preventDefault(); setActiveTab(tabs[(idx - 1 + tabs.length) % tabs.length]); }
              else if (e.key === "Home") { e.preventDefault(); setActiveTab(tabs[0]); }
              else if (e.key === "End") { e.preventDefault(); setActiveTab(tabs[tabs.length - 1]); }
            }}
            className={`flex-1 px-3 py-2 text-xs font-semibold uppercase transition-colors ${
              activeTab === tab
                ? "border-b-2 border-[#0072B1] text-[#0072B1] bg-[#F0F7FF]"
                : "text-[#666] hover:text-[#1a1a1a]"
            }`}
          >
            {tabLabels[tab]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div
        id={`activity-feed-panel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`activity-feed-tab-${activeTab}`}
        className="flex-1 overflow-y-auto p-3"
      >
        {activeTab === "activity" && <ActivityTab skillGroups={skillGroups} />}
        {activeTab === "artifacts" && <ArtifactsTab artifacts={artifacts} />}
        {activeTab === "context" && <ContextTab contextMetadata={contextMetadata} />}
        {activeTab === "governance" && <GovernanceTab permissionStages={permissionStages} />}
      </div>
    </aside>
  );
}
