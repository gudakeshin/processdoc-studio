"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { ToolActivityFeed } from "@/components/run-studio/ToolActivityFeed";
import { ZoneAInstruction } from "@/components/run-studio/ZoneAInstruction";
import { ZoneCLiveMonitor } from "@/components/run-studio/ZoneCLiveMonitor";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import {
  RunCreationError,
  useClearRunsMutation,
  useCreateRunMutation,
  useDeleteRunMutation,
  useRunsQuery,
} from "@/hooks/useRuns";
import { useRunStudio } from "@/hooks/useRunStudio";
import { useCoworkState } from "@/hooks/useCoworkState";
import { useRunStream } from "@/hooks/useRunStream";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

type ChatMessage = {
  id?: number;
  role: "user" | "assistant";
  content: string;
  ts: number;
  metadata?: {
    open_questions?: string[];
    ready_for_confirmation?: boolean;
    plan_hash?: string;
    decision_prompts?: Array<{
      id: string;
      label: string;
      mode: "single_select" | "multi_select";
      required?: boolean;
      min_select?: number;
      options: Array<{ value: string; label: string }>;
      selected_values?: string[];
    }>;
    unresolved_prompt_ids?: string[];
  };
};

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
    <section className="rounded-lg border border-[var(--surface-border)] bg-white">
      <button
        type="button"
        className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className="text-sm font-semibold">{title}</span>
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
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [openQuestions, setOpenQuestions] = useState<string[]>([]);
  const [readyForConfirmation, setReadyForConfirmation] = useState(false);
  const [planHash, setPlanHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runsQuery = useRunsQuery(pid, Boolean(token && pid));
  const createRunMutation = useCreateRunMutation(pid);
  const clearRunsMutation = useClearRunsMutation(pid);
  const deleteRunMutation = useDeleteRunMutation(pid);

  const runId = activeRunId ?? "";
  const { events, parsedEvents, error: streamError, pollMode } = useRunStream(pid, runId);
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
      setReadyForConfirmation(Boolean(data.ready_for_confirmation));
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
      setError(e instanceof Error ? e.message : "Conversation send failed");
    } finally {
      setChatBusy(false);
    }
  }

  async function submitDecisionAnswers(answers: Record<string, string[]>) {
    if (!conversationId || decisionBusy) return;
    setDecisionBusy(true);
    setError(null);
    try {
      const payload = Object.entries(answers).map(([prompt_id, selected_values]) => ({ prompt_id, selected_values }));
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
      setReadyForConfirmation(Boolean(data.ready_for_confirmation));
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

  async function confirmPlanAndStartRun() {
    if (!conversationId || !planHash) return;
    setError(null);
    try {
      const confirm = await api(`/api/projects/${encodeURIComponent(pid)}/conversation/confirm`, {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId, plan_hash: planHash }),
      });
      const confirmData = (await confirm.json().catch(() => ({}))) as {
        instruction?: string;
        template_output_types?: string[];
        custom_output_types?: string[];
        output_type_representations?: Record<string, string>;
      };
      if (!confirm.ok) throw new Error(extractApiErrorMessage(confirmData, "Plan confirmation failed"));
      const runIdCreated = await createRunMutation.mutateAsync({
        instruction: String(confirmData.instruction ?? "Create deliverables"),
        output_types: Array.isArray(confirmData.template_output_types) ? confirmData.template_output_types : [],
        custom_output_types: Array.isArray(confirmData.custom_output_types) ? confirmData.custom_output_types : [],
        output_type_representations:
          confirmData.output_type_representations && typeof confirmData.output_type_representations === "object"
            ? confirmData.output_type_representations
            : {},
        conversation_id: conversationId,
        plan_hash: planHash,
      });
      setActiveRunId(runIdCreated);
      setReadyForConfirmation(false);
    } catch (e) {
      if (e instanceof RunCreationError && e.code === "output_selection_required") {
        setError("Output type confirmation is required before run creation.");
      } else {
        setError(e instanceof Error ? e.message : "Run creation failed");
      }
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

  const activeOpenQuestions = activeRunId ? studio.openQuestions : openQuestions;
  const activeMessages = activeRunId ? studio.instructionChatMessages : chatMessages;
  const activeChatBusy = activeRunId ? studio.chatBusy : chatBusy;
  const activeConversationId = activeRunId ? studio.conversationId : conversationId;
  const activeDecisionPrompts = activeRunId ? studio.decisionPrompts : decisionPrompts;
  const activeUnresolvedPromptIds = activeRunId ? studio.unresolvedPromptIds : unresolvedPromptIds;

  return (
    <main className="project-studio-compact space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Project {pid}</h1>
          <p className="text-xs text-[var(--text-muted)]">Unified Project + Studio workspace</p>
        </div>
        <Button type="button" variant="ghost" onClick={logout}>Sign out</Button>
      </header>

      {error ? <div className="alert alert--error p-2 text-sm">{error}</div> : null}

      <section className="grid gap-3 lg:grid-cols-[minmax(0,2.1fr)_minmax(340px,1fr)]">
        <section className="min-w-0 space-y-3">
          <ZoneAInstruction
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
          {!activeRunId && readyForConfirmation ? (
            <div className="rounded border border-[var(--surface-border)] bg-white p-3">
              <Button type="button" onClick={() => void confirmPlanAndStartRun()}>
                Confirm plan and start run
              </Button>
            </div>
          ) : null}
        </section>

        <aside className="space-y-3 min-w-0">
          <CollapsibleSection title="Project Documents" defaultOpen={true}>
            <DocumentUploader projectId={pid} />
          </CollapsibleSection>

          <CollapsibleSection title="Activity" defaultOpen={Boolean(activeRunId)}>
            {activeRunId ? (
              <ToolActivityFeed
                events={events}
                parsedEvents={parsedEvents}
                runChecklistTodos={studio.runChecklistTodos}
                artifacts={studio.artifacts}
                pollMode={pollMode}
                streamError={streamError}
                downloadsContent={studio.downloadsContent}
                onTaskAction={studio.applyTaskAction}
                hooksPanel={studio.hooksPanel}
                permissionPanel={studio.permissionPanel}
              />
            ) : (
              <p className="text-xs text-[var(--text-muted)]">Select a run to view activity.</p>
            )}
          </CollapsibleSection>

          <CollapsibleSection title="Execution Audit Trail" defaultOpen={Boolean(activeRunId)}>
            {activeRunId ? (
              <ZoneCLiveMonitor
                events={events}
                showAgentGraph={false}
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
                  </button>
                  <button type="button" className="text-2xs text-[var(--error)]" onClick={() => void deleteRun(r.id)}>Delete</button>
                </div>
              ))}
              {(runsQuery.data ?? []).length === 0 ? <p className="text-xs text-[var(--text-muted)]">No runs yet.</p> : null}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button type="button" variant="ghost" onClick={() => void clearRuns()} disabled={clearRunsMutation.isPending}>
                {clearRunsMutation.isPending ? "Clearing..." : "Clear"}
              </Button>
              <Link href={`/projects/${pid}/workspace`} className="text-xs">Workspace</Link>
            </div>
          </CollapsibleSection>
        </aside>
      </section>
    </main>
  );
}
