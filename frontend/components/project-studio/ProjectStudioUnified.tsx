"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { EmptyState } from "@/components/ui/EmptyState";
import { ZonePanelErrorBoundary } from "@/components/ErrorBoundary";
import { ToolActivityFeed } from "@/components/run-studio/ToolActivityFeed";
import { ApprovalBanner } from "@/components/run-studio/ApprovalBanner";
import { ZoneAInstruction } from "@/components/run-studio/ZoneAInstruction";
import { ZoneCLiveMonitor } from "@/components/run-studio/ZoneCLiveMonitor";
import { RunHealthPanel } from "@/components/run-studio/RunHealthPanel";
import { ActivityTodoList } from "@/components/activity/ActivityTodoList";
import { WikiQuickAccess } from "@/components/wiki/WikiQuickAccess";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  useClearRunsMutation,
  useDeleteRunMutation,
  useRunsQuery,
} from "@/hooks/useRuns";
import { useRunStudio, type ChatMessage } from "@/hooks/useRunStudio";
import { useCoworkState } from "@/hooks/useCoworkState";
import { useRunStream } from "@/hooks/useRunStream";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import { buildTokenBreakdown, formatCostCompact, formatTokenCount } from "@/lib/formatTokens";
import { useLiveTokens, useProjectTokenUsage, computeProjectTotals } from "@/hooks/useLiveTokens";


type Props = {
  pid: string;
  initialRunId?: string | null;
};

function CollapsibleSection({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border border-[var(--surface-border)] bg-white">
      <button
        type="button"
        className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open ? <div className="border-t border-[var(--surface-border)] p-3">{children}</div> : null}
    </section>
  );
}

export function ProjectStudioUnified({ pid, initialRunId = null }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { token, ready, logout, api } = useAuth();
  const [hydrated, setHydrated] = useState(false);
  const didRedirectRef = useRef(false);

  const [activeRunId, setActiveRunId] = useState<string | null>(initialRunId);
  const [sidebarWidth, setSidebarWidth] = useState(380);
  const handleSidebarResizeStart = (e: ReactMouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    const onMouseMove = (moveEvent: MouseEvent) => {
      const delta = startX - moveEvent.clientX;
      const next = Math.min(720, Math.max(320, startWidth + delta));
      setSidebarWidth(next);
    };
    const onMouseUp = () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [openQuestions, setOpenQuestions] = useState<string[]>([]);
  const [planHash, setPlanHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const qc = useQueryClient();
  const runsQuery = useRunsQuery(pid, Boolean(token && pid));
  const clearRunsMutation = useClearRunsMutation(pid);
  const deleteRunMutation = useDeleteRunMutation(pid);

  const runId = activeRunId ?? "";
  const { events, parsedEvents, status: runStatus, error: streamError, pollMode } = useRunStream(pid, runId);
  const studio = useRunStudio({
    pid,
    rid: runId,
    liveEvents: events,
    streamError,
    pollMode,
  });
  const cowork = useCoworkState({
    parsedEvents,
    messages: studio.instructionChatMessages,
    openQuestions: studio.openQuestions,
  });

  // Live token polling — polls /usage every 2 s while run is executing, stops on terminal states
  const { data: liveUsage, isLive } = useLiveTokens(pid, activeRunId, runStatus);
  // Project-wide token counter — polls even during chat (no active run needed)
  const projectLiveUsage = useProjectTokenUsage(pid, isLive || chatBusy || studio.chatBusy);

  // When run reaches a terminal state, refetch the runs list so final token/cost values appear
  const prevRunStatusRef = useRef<string>("");
  useEffect(() => {
    const TERMINAL = new Set(["review_ready", "done", "failed"]);
    if (TERMINAL.has(runStatus) && !TERMINAL.has(prevRunStatusRef.current)) {
      void qc.invalidateQueries({ queryKey: ["runs", pid] });
      void qc.invalidateQueries({ queryKey: ["run-live-usage", pid, activeRunId] });
    }
    prevRunStatusRef.current = runStatus;
  }, [runStatus, pid, activeRunId, qc]);

  const latestAssistantMetadata = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
      const m = chatMessages[i];
      if (m.role === "assistant" && m.metadata) return m.metadata;
    }
    return null;
  }, [chatMessages]);

  const decisionPrompts = useMemo(
    () => (Array.isArray(latestAssistantMetadata?.decision_prompts) ? latestAssistantMetadata.decision_prompts : []),
    [latestAssistantMetadata]
  );
  const unresolvedPromptIds = useMemo(
    () =>
      Array.isArray(latestAssistantMetadata?.unresolved_prompt_ids)
        ? latestAssistantMetadata.unresolved_prompt_ids.filter((x): x is string => typeof x === "string")
        : [],
    [latestAssistantMetadata]
  );

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      if (didRedirectRef.current) return;
      didRedirectRef.current = true;
      router.replace(`/login?next=${encodeURIComponent(pathname || `/projects/${pid}`)}`);
    }
  }, [ready, token, pid, pathname, router]);

  useEffect(() => {
    if (!activeRunId) return;
    const query = new URLSearchParams(window.location.search);
    query.set("run", activeRunId);
    router.replace(`/projects/${pid}?${query.toString()}`);
  }, [activeRunId, pid, router]);

  const activeOpenQuestions = useMemo(
    () => activeRunId ? studio.openQuestions : openQuestions,
    [activeRunId, studio.openQuestions, openQuestions]
  );

  // Use latest messages: if user has sent messages (chatMessages updated), use those
  // Otherwise use studio messages which includes greeting on mount
  const activeMessages = useMemo(
    () => chatMessages.length > 0 ? chatMessages : studio.instructionChatMessages,
    [chatMessages, studio.instructionChatMessages]
  );

  const agreedDecisions = useMemo(() => {
    const msgs = activeMessages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m.role === "assistant" && m.metadata?.kind === "structure_summary" && Array.isArray(m.metadata.slides)) {
        return m.metadata.slides as Array<{ slide_num: number; title: string; key_message?: string; slide_type?: string; agreed?: boolean }>;
      }
    }
    return msgs
      .filter((m) => m.role === "assistant" && m.metadata?.kind === "slide_proposal" && m.metadata.slide?.agreed)
      .map((m) => m.metadata!.slide as { slide_num: number; title: string; key_message?: string; slide_type?: string; agreed?: boolean });
  }, [activeMessages]);

  const activeChatBusy = useMemo(
    () => activeRunId ? studio.chatBusy : chatBusy,
    [activeRunId, studio.chatBusy, chatBusy]
  );

  // Prefer studio conversation ID if available (from initial greeting load)
  const activeConversationId = useMemo(
    () => studio.conversationId || conversationId,
    [studio.conversationId, conversationId]
  );

  const activeDecisionPrompts = useMemo(
    () => activeRunId ? studio.decisionPrompts : decisionPrompts,
    [activeRunId, studio.decisionPrompts, decisionPrompts]
  );

  const activeUnresolvedPromptIds = useMemo(
    () => activeRunId ? studio.unresolvedPromptIds : unresolvedPromptIds,
    [activeRunId, studio.unresolvedPromptIds, unresolvedPromptIds]
  );

  const activeRun = useMemo(
    () => (runsQuery.data ?? []).find((r) => r.id === activeRunId) ?? null,
    [runsQuery.data, activeRunId]
  );

  const projectTotals = useMemo(
    () => computeProjectTotals(runsQuery.data ?? []),
    [runsQuery.data]
  );

  // Token/cost data to display: prefer live polling data for the current run, else DB values
  const displayUsage = useMemo(() => {
    if (liveUsage) return liveUsage;
    if (!activeRun) return null;
    return {
      input_tokens: activeRun.tokens_input ?? 0,
      output_tokens: activeRun.tokens_output ?? 0,
      cache_read_tokens: activeRun.tokens_cache_read ?? 0,
      cache_creation_tokens: activeRun.tokens_cache_creation ?? 0,
      cost_usd: activeRun.cost_usd ?? null,
      live: false,
    };
  }, [liveUsage, activeRun]);

  // Session-wide cost/tokens: live project total (process-local, resets on backend restart)
  // floored by the DB-backed total across all runs, so a restart never makes the number drop.
  const liveSessionTokens = projectLiveUsage
    ? (projectLiveUsage.input_tokens + projectLiveUsage.output_tokens +
       projectLiveUsage.cache_read_tokens + projectLiveUsage.cache_creation_tokens)
    : 0;
  const sessionCostUsd = Math.max(projectLiveUsage?.cost_usd ?? 0, projectTotals.totalCost);
  const sessionCostLabel = formatCostCompact(sessionCostUsd);
  const sessionTokens = Math.max(liveSessionTokens, projectTotals.totalTokens);

  async function sendMessage() {
    const msg = chatInput.trim();
    if (chatBusy || !msg) return;
    setChatBusy(true);
    setError(null);
    try {
      setChatInput("");
      const res = await api(`/api/projects/${encodeURIComponent(pid)}/conversation/messages`, {
        method: "POST",
        body: JSON.stringify({ content: msg }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        conversation_id?: string;
        open_questions?: string[];
        ready_for_confirmation?: boolean;
        plan_hash?: string;
        run_id?: string;
        auto_executed?: boolean;
        messages?: Array<{
          id: number;
          role: "user" | "assistant";
          content: string;
          metadata?: ChatMessage["metadata"];
          created_at?: string | null;
        }>;
      };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Conversation send failed"));
      setConversationId(data.conversation_id ?? conversationId);
      setOpenQuestions(Array.isArray(data.open_questions) ? data.open_questions : []);
      setPlanHash(typeof data.plan_hash === "string" && data.plan_hash ? data.plan_hash : null);
      const mapped = Array.isArray(data.messages)
        ? data.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            metadata: m.metadata,
            ts: m.created_at ? Date.parse(m.created_at) : Date.now(),
          }))
        : [];
      setChatMessages(mapped);
      if (data.auto_executed && typeof data.run_id === "string" && data.run_id) {
        setActiveRunId(data.run_id);
        void qc.invalidateQueries({ queryKey: ["active-runs", pid] });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Conversation send failed");
    } finally {
      setChatBusy(false);
    }
  }

  async function submitDecisionAnswers(
    answers: Record<string, string[] | { selected_values?: string[]; free_text?: string }>
  ) {
    if (!conversationId || decisionBusy) return;
    setDecisionBusy(true);
    setError(null);
    try {
      const payload = Object.entries(answers).map(([prompt_id, entry]) => {
        if (Array.isArray(entry)) {
          return { prompt_id, selected_values: entry };
        }
        return {
          prompt_id,
          selected_values: entry?.selected_values ?? [],
          free_text: entry?.free_text && entry.free_text.trim() ? entry.free_text.trim() : undefined,
        };
      });
      const res = await api(`/api/projects/${encodeURIComponent(pid)}/conversation/decisions`, {
        method: "POST",
        body: JSON.stringify({
          conversation_id: conversationId,
          plan_hash: planHash ?? undefined,
          answers: payload,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        conversation_id?: string;
        open_questions?: string[];
        ready_for_confirmation?: boolean;
        plan_hash?: string;
        messages?: Array<{ id: number; role: "user" | "assistant"; content: string; metadata?: ChatMessage["metadata"]; created_at?: string | null }>;
      };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to apply decision updates"));
      setConversationId(data.conversation_id ?? conversationId);
      setOpenQuestions(Array.isArray(data.open_questions) ? data.open_questions : []);
      setPlanHash(typeof data.plan_hash === "string" && data.plan_hash ? data.plan_hash : null);
      const mapped = Array.isArray(data.messages)
        ? data.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            metadata: m.metadata,
            ts: m.created_at ? Date.parse(m.created_at) : Date.now(),
          }))
        : [];
      setChatMessages(mapped);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to apply decision updates");
    } finally {
      setDecisionBusy(false);
    }
  }

  async function clearRuns() {
    if (clearRunsMutation.isPending) return;
    const ok = window.confirm("Clear all recent runs for this project?");
    if (!ok) return;
    setError(null);
    try {
      await clearRunsMutation.mutateAsync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear runs");
    }
  }

  async function deleteRun(runIdValue: string) {
    if (deleteRunMutation.isPending) return;
    const ok = window.confirm(`Delete run ${runIdValue}?`);
    if (!ok) return;
    try {
      await deleteRunMutation.mutateAsync(runIdValue);
      if (activeRunId === runIdValue) {
        setActiveRunId(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete run");
    }
  }

  if (!hydrated || !ready || !token) {
    return <main style={{ padding: 24 }}><p>Redirecting…</p></main>;
  }

  return (
    <main className="project-studio-compact space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Project {pid}</h1>
          <p className="text-xs text-[var(--text-muted)]">Unified Project + Studio workspace</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Token meter — always visible, updates during chat and runs */}
          <div className="flex items-center gap-2 border border-[var(--surface-border)] bg-white px-3 py-1.5 text-xs">
            <span className="text-[var(--text-muted)]">Session</span>
            <span className="font-mono font-medium">
              {formatTokenCount(sessionTokens)} tok
            </span>
            <span className="text-[var(--text-muted)]">·</span>
            <span className="font-mono font-semibold text-[var(--accent-blue)]">
              {sessionCostLabel}
            </span>
            {(isLive || chatBusy || studio.chatBusy) && (
              <span className="inline-block animate-spin text-[var(--accent-blue)]">↻</span>
            )}
          </div>
          <Button type="button" variant="ghost" onClick={logout}>Sign out</Button>
        </div>
      </header>

      {error ?<div className="alert alert--error p-2 text-sm">{error}</div> : null}

      <section
        className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_var(--sidebar-width)]"
        style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
      >
        <section className="min-w-0 space-y-3">
          <ZonePanelErrorBoundary label="Instruction chat">
            <ZoneAInstruction
              projectId={pid}
              recommendationNote={activeRunId ? studio.recommendationNote : null}
              chatMessages={activeMessages}
              chatInput={activeRunId ? studio.chatInput : chatInput}
              setChatInput={activeRunId ? studio.setChatInput : setChatInput}
              chatBusy={activeChatBusy}
              onSendChat={activeRunId ? studio.sendChatMessage : sendMessage}
              conversationId={activeConversationId}
              openQuestions={activeOpenQuestions}
              decisionPrompts={activeDecisionPrompts}
              unresolvedPromptIds={activeUnresolvedPromptIds}
              onSubmitDecisions={activeRunId ? studio.submitDecisionAnswers : submitDecisionAnswers}
              decisionBusy={activeRunId ? studio.decisionBusy : decisionBusy}
              thinkingStatements={cowork.thinkingStatements}
              hasThinkingTrace={cowork.hasThinkingTrace}
              thinkingTrace={cowork.thinkingTrace}
              thinkingExpanded={cowork.thinkingExpanded}
              onToggleThinkingTrace={() => cowork.setThinkingExpanded((prev) => !prev)}
            />
          </ZonePanelErrorBoundary>
          {activeRunId ? (
            <ApprovalBanner state={studio.approvalBannerState} />
          ) : null}
        </section>

        <aside className="relative min-w-0">
          <div
            className="absolute -left-3 top-0 z-10 hidden h-full w-3 cursor-col-resize lg:block"
            onMouseDown={handleSidebarResizeStart}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar panel"
          />
          <div className="space-y-3 border-l border-[var(--surface-border)] pl-3 bg-[var(--surface-muted)]">
          <CollapsibleSection title="Run Health" defaultOpen={true}>
            <RunHealthPanel projectId={pid} onSelectRun={(runId) => setActiveRunId(runId)} />
          </CollapsibleSection>

          <CollapsibleSection title="Project Documents" defaultOpen={true}>
            <DocumentUploader projectId={pid} />
          </CollapsibleSection>

          <CollapsibleSection title="Activity" defaultOpen={Boolean(activeRunId)}>
            <div className="space-y-4">
              {/* Project Activity To-Do List */}
              <ActivityTodoList
                projectId={pid}
                onTodoClick={(runId) => setActiveRunId(runId)}
                maxItems={10}
              />

              {/* Selected Run Activity Feed */}
              {activeRunId && (
                <div className="border-t pt-4">
                  <h4 className="text-sm font-semibold mb-3">Selected Run Activity</h4>
                  <ZonePanelErrorBoundary label="Activity feed">
                    <ToolActivityFeed
                      events={events}
                      parsedEvents={parsedEvents}
                      runChecklistTodos={studio.runChecklistTodos}
                      artifacts={studio.artifacts}
                      pollMode={pollMode}
                      streamError={streamError}
                      downloadsContent={studio.downloadsContent}
                      onTaskAction={studio.applyTaskAction}
                      onRegenerateSlide={studio.regenerateSlide}
                      onPatchSlideElement={studio.patchSlideElement}
                      slideRegenerateBusyIndex={studio.slideRegenerateBusyIndex}
                      hooksPanel={studio.hooksPanel}
                      permissionPanel={studio.permissionPanel}
                      projectId={pid}
                      runId={activeRunId ?? undefined}
                      agreedDecisions={agreedDecisions}
                    />
                  </ZonePanelErrorBoundary>
                </div>
              )}
            </div>
          </CollapsibleSection>

          <CollapsibleSection title="Execution Audit Trail" defaultOpen={Boolean(activeRunId)}>
            {activeRunId ? (
              <ZonePanelErrorBoundary label="Execution audit trail">
                <ZoneCLiveMonitor
                  events={events}
                  showAgentGraph={false}
                  runControls={studio.runControls}
                  evaluatorSummary={
                    studio.evaluatorSummary
                      ? {
                          qaPassed: Boolean(studio.evaluatorSummary.qa_passed),
                          visualQaPassed: Boolean(studio.evaluatorSummary.visual_qa_passed),
                          guardrailsPassed: Boolean(studio.evaluatorSummary.guardrails_passed),
                          status: studio.evaluatorSummary.status,
                        }
                      : null
                  }
                />
              </ZonePanelErrorBoundary>
            ) : (
              <p className="text-xs text-[var(--text-muted)]">Select a run to view execution events.</p>
            )}
          </CollapsibleSection>

          <CollapsibleSection title="Runs" defaultOpen={true}>
            <div className="max-h-[260px] space-y-1 overflow-auto">
              {(runsQuery.data ?? []).map((r) => (
                <div key={r.id} className="flex items-center justify-between gap-2 rounded border border-[var(--surface-border)] px-2 py-1.5">
                  <button
                    type="button"
                    className={`truncate text-left text-xs ${activeRunId === r.id ? "text-[var(--accent-blue)]" : ""}`}
                    onClick={() => setActiveRunId(r.id)}
                    title={`${r.id} · ${r.status}`}
                  >
                    {r.id} · {r.status}
                    {(() => {
                      const runTokens =
                        (r.tokens_input ?? 0) + (r.tokens_output ?? 0) +
                        (r.tokens_cache_read ?? 0) + (r.tokens_cache_creation ?? 0);
                      return (
                        (runTokens > 0 || formatCostCompact(r.cost_usd)) && (
                          <span className="ml-1.5 text-[var(--text-muted)]">
                            {runTokens > 0 ? `${formatTokenCount(runTokens)} tok` : null}
                            {runTokens > 0 && formatCostCompact(r.cost_usd) ? " · " : null}
                            {formatCostCompact(r.cost_usd)}
                          </span>
                        )
                      );
                    })()}
                  </button>
                  <button type="button" className="text-2xs text-[var(--error)]" onClick={() => void deleteRun(r.id)}>Delete</button>
                </div>
              ))}
              {(runsQuery.data ?? []).length === 0 ? (
                <EmptyState title="No runs yet" description="Start a new run to see execution history here." />
              ) : null}
            </div>
            {/* Token breakdown — always visible when a run is selected */}
            {activeRunId && (
              <div className="mt-2 border border-[var(--surface-border)] bg-white p-3 text-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-[var(--text-primary)]">
                    Token Usage
                    {isLive && (
                      <span className="ml-1.5 inline-block animate-spin text-[var(--accent-blue)]">↻</span>
                    )}
                  </span>
                  <span className="font-mono font-semibold text-[var(--accent-blue)]">
                    {formatCostCompact(displayUsage?.cost_usd ?? null)}
                  </span>
                </div>
                {displayUsage ? (
                  <table className="w-full">
                    <thead>
                      <tr className="text-[var(--text-muted)]">
                        <th className="text-left font-normal pb-1">Category</th>
                        <th className="text-right font-normal pb-1">Tokens</th>
                        <th className="text-right font-normal pb-1">Rate</th>
                        <th className="text-right font-normal pb-1">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(buildTokenBreakdown(displayUsage) ?? [
                        { label: "Input", tokens: 0, rate: "$3.00/MTok", cost: "$0.0000" },
                        { label: "Output", tokens: 0, rate: "$15.00/MTok", cost: "$0.0000" },
                      ]).map((row) => (
                        <tr key={row.label} className="border-t border-[var(--surface-border)]">
                          <td className="py-0.5">{row.label}</td>
                          <td className="py-0.5 text-right font-mono">{row.tokens.toLocaleString()}</td>
                          <td className="py-0.5 text-right text-[var(--text-muted)]">{row.rate}</td>
                          <td className="py-0.5 text-right font-mono">{row.cost}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="text-[var(--text-muted)]">Waiting for first LLM call…</p>
                )}
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button type="button" variant="ghost" onClick={() => void clearRuns()} disabled={clearRunsMutation.isPending}>
                {clearRunsMutation.isPending ? "Clearing..." : "Clear"}
              </Button>
              <Link href={`/projects/${pid}/workspace`} className="text-xs">Workspace</Link>
            </div>
          </CollapsibleSection>

          <CollapsibleSection title="Project Wiki" defaultOpen={!activeRunId}>
            <WikiQuickAccess projectId={pid} />
          </CollapsibleSection>
          </div>
        </aside>
      </section>
    </main>
  );
}
