"use client";

import { useMemo, useEffect, useState, useRef, useCallback } from "react";

import { type ApprovalBannerState } from "@/components/run-studio/ApprovalBanner";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import {
  buildVisualQaChatMarkdown,
  chatIncludesVisualQaForRun,
  type VisualQaReportLike,
} from "@/lib/visualQaChatMessage";
import { mergeRunEventEnvelope, runTodosFromEvents } from "@/lib/runTodosFromEvents";
import { emitToast } from "@/lib/toast-bus";
import { parseEventLine, type ParsedRunEvent } from "@/lib/runEvents";
import { useCoworkState } from "@/hooks/useCoworkState";

export const AGENT_GRAPH_ENABLED = process.env.NEXT_PUBLIC_AGENT_GRAPH_ENABLED !== "false";
export const SCRATCHPAD_VISIBLE = process.env.NEXT_PUBLIC_SCRATCHPAD_VISIBLE !== "false";

export type ChatMessage = {
  id?: number;
  clientId?: string;
  role: "user" | "assistant";
  content: string;
  ts: number;
  metadata?: {
    template_output_types?: string[];
    custom_output_types?: string[];
    output_type_representations?: Record<string, string>;
    requires_output_type_confirmation?: boolean;
    requires_user_approval?: boolean;
    ready_to_run?: boolean;
    approval_reason?: string;
    rationale?: string;
    instruction?: string;
    open_questions?: string[];
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
    kind?: string;
    run_id?: string;
    status?: string;
  };
};

export type UseRunStudioArgs = {
  pid: string;
  rid: string;
  liveEvents: string[];
  streamError: string | null;
  pollMode: boolean;
};

export function useRunStudio({ pid, rid, liveEvents, streamError, pollMode }: UseRunStudioArgs) {
  const [instruction, setInstruction] = useState("");
  const [selectedOutputTypes, setSelectedOutputTypes] = useState<string[]>([]);
  const [customOutputInput, setCustomOutputInput] = useState("");
  const [outputTypeRepresentations, setOutputTypeRepresentations] = useState<Record<string, string>>({});
  const [recommendationNote, setRecommendationNote] = useState<string | null>(null);

  const { token, api } = useAuth();
  const canRenderEditor = useMemo(() => Boolean(pid && rid), [pid, rid]);
  const [artifacts, setArtifacts] = useState<any | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [backpressureRetrySec, setBackpressureRetrySec] = useState<number | null>(null);
  const [deadLetters, setDeadLetters] = useState<any[]>([]);
  const [deadLetterLoading, setDeadLetterLoading] = useState(false);
  const [deadLetterMsg, setDeadLetterMsg] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [finalApproveBusy, setFinalApproveBusy] = useState(false);
  const [savePlanBusy, setSavePlanBusy] = useState(false);
  const [runControlBusy, setRunControlBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [permissionSimBusy, setPermissionSimBusy] = useState(false);
  const [permissionSimResult, setPermissionSimResult] = useState<any | null>(null);
  const [hooksBusy, setHooksBusy] = useState(false);
  const [hooksData, setHooksData] = useState<Array<Record<string, unknown>>>([]);

  const latestAssistantMetadata = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
      const m = chatMessages[i];
      if (m.role !== "assistant" || !m.metadata) continue;
      if (m.metadata.kind === "visual_qa_report" || m.metadata.kind === "skill_selection") continue;
      return m.metadata;
    }
    return null;
  }, [chatMessages]);

  const vqaArtifactKey = useMemo(() => {
    const vq = artifacts?.visual_qa_report as VisualQaReportLike | undefined;
    if (!vq || typeof vq !== "object") return "";
    const st = String(vq.status ?? "");
    const f = Array.isArray(vq.findings) ? vq.findings.length : 0;
    const s = String(vq.summary ?? "").slice(0, 120);
    return `${st}:${f}:${s}`;
  }, [artifacts?.visual_qa_report]);

  const instructionChatMessages = useMemo((): ChatMessage[] => {
    if (!rid) return chatMessages;
    let withSystem = chatMessages;
    let latestSkillPayload: any | null = null;
    for (let i = liveEvents.length - 1; i >= 0; i -= 1) {
      const line = liveEvents[i];
      if (!line.startsWith("skill_selection:")) continue;
      const raw = line.slice("skill_selection:".length).trim();
      try {
        latestSkillPayload = JSON.parse(raw);
      } catch {
        latestSkillPayload = null;
      }
      break;
    }
    if (latestSkillPayload && !chatMessages.some((m) => m.metadata?.kind === "skill_selection" && m.metadata?.run_id === rid)) {
      const skillsByOutput = latestSkillPayload.skills_by_output_type;
      const lines: string[] = [];
      if (skillsByOutput && typeof skillsByOutput === "object") {
        for (const [out, cards] of Object.entries(skillsByOutput as Record<string, unknown>)) {
          if (!Array.isArray(cards) || cards.length === 0) continue;
          const first = cards[0] as Record<string, unknown>;
          const sid = String(first?.id ?? "").trim();
          const dn = String(first?.display_name ?? "").trim();
          lines.push(`- ${out}: ${dn || sid || "auto"}`);
        }
      }
      if (lines.length > 0) {
        withSystem = [
          ...withSystem,
          {
            clientId: `skill-selection-fallback-${rid}`,
            role: "assistant",
            content: `Using skill routing for this run:\n${lines.join("\n")}`,
            ts: 0,
            metadata: {
              kind: "skill_selection",
              run_id: rid,
            },
          },
        ];
      }
    }
    const vq = artifacts?.visual_qa_report;
    if (!vq || typeof vq !== "object") return withSystem;
    if (chatIncludesVisualQaForRun(withSystem, rid)) return withSystem;
    const body = buildVisualQaChatMarkdown(vq as VisualQaReportLike, rid);
    return [
      ...withSystem,
      {
        clientId: `visual-qa-fallback-${rid}`,
        role: "assistant",
        content: body,
        ts: 0,
        metadata: {
          kind: "visual_qa_report",
          run_id: rid,
          status: String((vq as { status?: string }).status ?? ""),
        },
      },
    ];
  }, [chatMessages, rid, liveEvents, vqaArtifactKey, artifacts?.visual_qa_report]);

  const runChecklistTodos = useMemo(() => runTodosFromEvents(liveEvents), [liveEvents]);
  const blockedContext = useMemo(() => {
    for (let i = liveEvents.length - 1; i >= 0; i -= 1) {
      const line = liveEvents[i];
      if (!line.startsWith("step:")) continue;
      const raw = line.slice("step:".length).trim();
      try {
        const obj = mergeRunEventEnvelope(JSON.parse(raw) as Record<string, unknown>);
        if (obj.status === "plan_blocked") {
          return {
            stage: typeof obj.blocked_stage === "string" ? obj.blocked_stage : "",
            reason: typeof obj.blocked_reason === "string" ? obj.blocked_reason : "",
            code: typeof obj.blocked_code === "string" ? obj.blocked_code : "",
          };
        }
      } catch {
        continue;
      }
    }
    return null;
  }, [liveEvents]);

  const refreshChatFromServer = useCallback(
    async (opts?: { reportErrors?: boolean }) => {
      if (!token || !pid) return;
      try {
        const res = await api(`/api/projects/${encodeURIComponent(pid)}/conversation`);
        const data = (await res.json().catch(() => ({}))) as {
          detail?: string;
          conversation_id?: string;
          messages?: Array<{
            id: number;
            role: "user" | "assistant";
            content: string;
            metadata?: ChatMessage["metadata"];
            created_at?: string | null;
          }>;
        };
        if (!res.ok) {
          if (opts?.reportErrors) {
            setArtifactsError(extractApiErrorMessage(data, "Failed to load conversation"));
          }
          return;
        }
        setConversationId(data.conversation_id ?? null);
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
        if (opts?.reportErrors) {
          setArtifactsError(e instanceof Error ? e.message : "Failed to load conversation");
        }
      }
    },
    [api, pid, token]
  );

  const refreshArtifactsFromServer = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!token || !pid || !rid) return;
      if (!opts?.silent) {
        setArtifactsLoading(true);
      }
      setArtifactsError(null);
      try {
        const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/artifacts`);
        const data = (await res.json().catch(() => ({}))) as {
          detail?: string;
          status?: string;
          artifacts?: any;
          instruction?: string;
          output_types?: string[];
          custom_output_types?: string[];
          output_type_representations?: Record<string, string>;
        };
        if (!res.ok) {
          throw new Error(extractApiErrorMessage(data, "Failed to load run artifacts"));
        }
        setRunStatus(data.status ?? null);
        setArtifacts(data.artifacts ?? null);
        setInstruction(data.instruction ?? "");
        setSelectedOutputTypes(Array.isArray(data.output_types) ? data.output_types : []);
        setCustomOutputInput(Array.isArray(data.custom_output_types) ? data.custom_output_types.join("\n") : "");
        setOutputTypeRepresentations(
          data.output_type_representations && typeof data.output_type_representations === "object"
            ? data.output_type_representations
            : {}
        );
      } catch (e) {
        setArtifactsError(e instanceof Error ? e.message : "Failed to load run artifacts");
      } finally {
        if (!opts?.silent) {
          setArtifactsLoading(false);
        }
      }
    },
    [api, token, pid, rid]
  );

  useEffect(() => {
    if (!token || !pid || !rid) return;
    setArtifactsLoading(true);
    setArtifactsError(null);
    setArtifacts(null);
    setRunStatus(null);
    void refreshArtifactsFromServer();
  }, [token, pid, rid, refreshArtifactsFromServer]);

  useEffect(() => {
    if (!token || !pid) return;
    void refreshChatFromServer({ reportErrors: true });
  }, [pid, token, refreshChatFromServer]);

  // When a run is selected (e.g. after "Confirm plan and start run"), reload chat from the server.
  // Pre-run messages only updated ProjectStudioUnified local state; without this, the thread looks empty.
  useEffect(() => {
    if (!token || !pid || !rid) return;
    void refreshChatFromServer();
  }, [token, pid, rid, refreshChatFromServer]);

  const lastVisualQaEventIdx = useRef(-1);
  const lastVqaArtifactSig = useRef("");

  useEffect(() => {
    lastVisualQaEventIdx.current = -1;
    lastVqaArtifactSig.current = "";
  }, [rid]);

  useEffect(() => {
    if (!token || !pid) return;
    let vqaIdx = -1;
    for (let i = liveEvents.length - 1; i >= 0; i -= 1) {
      if (liveEvents[i].startsWith("visual_qa_report:")) {
        vqaIdx = i;
        break;
      }
    }
    if (vqaIdx < 0 || vqaIdx === lastVisualQaEventIdx.current) return;
    lastVisualQaEventIdx.current = vqaIdx;
    void refreshChatFromServer();
    window.setTimeout(() => {
      void refreshChatFromServer();
    }, 750);
  }, [liveEvents, token, pid, refreshChatFromServer]);

  useEffect(() => {
    if (!token || !pid) return;
    const vq = artifacts?.visual_qa_report;
    if (!vq || typeof vq !== "object") return;
    const status = String((vq as { status?: string }).status ?? "");
    const findingsLen = Array.isArray((vq as { findings?: unknown[] }).findings)
      ? (vq as { findings: unknown[] }).findings.length
      : 0;
    const remediation = String((vq as { remediation_rounds?: unknown }).remediation_rounds ?? "");
    const sig = `${status}:${findingsLen}:${remediation}`;
    if (!status && findingsLen === 0) return;
    if (sig === lastVqaArtifactSig.current) return;
    lastVqaArtifactSig.current = sig;
    const t1 = window.setTimeout(() => {
      void refreshChatFromServer();
    }, 450);
    const t2 = window.setTimeout(() => {
      void refreshChatFromServer();
    }, 1800);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [artifacts?.visual_qa_report, token, pid, refreshChatFromServer]);

  const lastArtifactRefreshEventIdx = useRef(-1);
  useEffect(() => {
    lastArtifactRefreshEventIdx.current = -1;
  }, [rid]);

  useEffect(() => {
    if (!token || !pid || !rid) return;
    const refreshablePrefixes = [
      "step:",
      "qa_report:",
      "guardrail_report:",
      "visual_qa_report:",
      "evaluator_pipeline:",
      "run_todo_snapshot:",
      "done:",
      "failed:",
    ];
    let idx = -1;
    for (let i = liveEvents.length - 1; i >= 0; i -= 1) {
      if (refreshablePrefixes.some((p) => liveEvents[i].startsWith(p))) {
        idx = i;
        break;
      }
    }
    if (idx < 0 || idx === lastArtifactRefreshEventIdx.current) return;
    lastArtifactRefreshEventIdx.current = idx;
    const t = window.setTimeout(() => {
      void refreshArtifactsFromServer({ silent: true });
    }, 120);
    return () => window.clearTimeout(t);
  }, [liveEvents, token, pid, rid, refreshArtifactsFromServer]);

  useEffect(() => {
    if (backpressureRetrySec === null || backpressureRetrySec <= 0) return;
    const t = window.setTimeout(() => {
      setBackpressureRetrySec((prev) => {
        if (prev === null) return null;
        return prev > 0 ? prev - 1 : 0;
      });
    }, 1000);
    return () => window.clearTimeout(t);
  }, [backpressureRetrySec]);

  useEffect(() => {
    if (backpressureRetrySec !== 0) return;
    if (runStatus !== "plan_ready") {
      setBackpressureRetrySec(null);
      return;
    }
    void approvePlan();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backpressureRetrySec, runStatus]);

  useEffect(() => {
    if (!token || !pid) return;
    void loadDeadLetters();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, pid]);

  useEffect(() => {
    if (!token || !pid) return;
    void loadHooks();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, pid]);

  async function approvePlan() {
    if (!pid || !rid) return;
    if (runStatus !== "plan_ready") {
      setBackpressureRetrySec(null);
      setArtifactsError(`Run is in status '${runStatus ?? "unknown"}' and cannot be approved right now.`);
      return;
    }
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/approve`, {
        method: "POST",
      });
      if (!res.ok) {
        const retryAfter = res.headers.get("Retry-After");
        const queueDepth = res.headers.get("X-Admission-Queue-Depth");
        const projectLimit = res.headers.get("X-Admission-Project-Limit");
        const globalLimit = res.headers.get("X-Admission-Global-Limit");
        const userLimit = res.headers.get("X-Admission-User-Limit");
        const data = (await res.json().catch(() => ({}))) as {
          detail?: string | { message?: string };
        };
        if (res.status === 429) {
          const retrySec = retryAfter ? Number.parseInt(retryAfter, 10) : NaN;
          setBackpressureRetrySec(Number.isFinite(retrySec) && retrySec > 0 ? retrySec : 5);
          const retryIn = retryAfter ? `${retryAfter}s` : "a short interval";
          throw new Error(
            `System is currently throttling new run approvals. Retry in ${retryIn}. ` +
              `Queue depth: ${queueDepth ?? "n/a"}, limits (project/global/user): ` +
              `${projectLimit ?? "n/a"}/${globalLimit ?? "n/a"}/${userLimit ?? "n/a"}.`
          );
        }
        throw new Error(extractApiErrorMessage(data, "Approve failed"));
      }
      setBackpressureRetrySec(null);

      // Refresh run status + artifacts.
      setArtifactsLoading(true);
      const r2 = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/artifacts`);
      const data2 = (await r2.json().catch(() => ({}))) as any;
      if (!r2.ok) {
        throw new Error(extractApiErrorMessage(data2, "Failed to refresh artifacts"));
      }
      setRunStatus(data2.status ?? null);
      setArtifacts(data2.artifacts ?? null);
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setArtifactsLoading(false);
    }
  }

  async function sendChatMessage() {
    const msg = chatInput.trim();
    if (!pid || chatBusy || !msg) return;
    setChatBusy(true);
    setArtifactsError(null);
    try {
      setChatInput("");
      const res = await api(`/api/projects/${encodeURIComponent(pid)}/conversation/messages`, {
        method: "POST",
        body: JSON.stringify({ content: msg }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        detail?: string;
        conversation_id?: string;
        template_output_types?: string[];
        custom_output_types?: string[];
        output_type_representations?: Record<string, string>;
        rationale?: string;
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
      const template = Array.isArray(data.template_output_types) ? data.template_output_types : [];
      const custom = Array.isArray(data.custom_output_types) ? data.custom_output_types : [];
      const reps =
        data.output_type_representations && typeof data.output_type_representations === "object"
          ? data.output_type_representations
          : {};
      if (template.length) {
        setSelectedOutputTypes(template);
      }
      setCustomOutputInput(custom.join("\n"));
      setOutputTypeRepresentations(reps);
      if (typeof data.rationale === "string" && data.rationale) {
        setRecommendationNote(data.rationale);
      }
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
      setInstruction(msg);
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Conversation send failed");
    } finally {
      setChatBusy(false);
    }
  }

  async function savePlan() {
    if (!pid || !rid || savePlanBusy) return;
    setSavePlanBusy(true);
    setArtifactsError(null);
    try {
      const customOutputTypes = customOutputInput
        .split("\n")
        .map((x) => x.trim())
        .filter(Boolean);
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/plan`, {
        method: "PATCH",
        body: JSON.stringify({
          instruction,
          output_types: selectedOutputTypes,
          custom_output_types: customOutputTypes,
          output_type_representations: outputTypeRepresentations,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to save plan"));
      setRunStatus("plan_ready");
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Failed to save plan");
    } finally {
      setSavePlanBusy(false);
    }
  }

  async function submitDecisionAnswers(answers: Record<string, string[]>) {
    if (!pid || !conversationId || decisionBusy) return;
    setDecisionBusy(true);
    setArtifactsError(null);
    try {
      const formatted = Object.entries(answers).map(([prompt_id, selected_values]) => ({
        prompt_id,
        selected_values,
      }));
      const res = await api(`/api/projects/${encodeURIComponent(pid)}/conversation/decisions`, {
        method: "POST",
        body: JSON.stringify({
          conversation_id: conversationId,
          plan_hash: latestAssistantMetadata?.plan_hash,
          answers: formatted,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        detail?: string;
        messages?: Array<{
          id: number;
          role: "user" | "assistant";
          content: string;
          metadata?: ChatMessage["metadata"];
          created_at?: string | null;
        }>;
      };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to apply decisions"));
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
      setArtifactsError(e instanceof Error ? e.message : "Failed to apply decisions");
    } finally {
      setDecisionBusy(false);
    }
  }

  async function controlRun(action: "pause" | "resume" | "stop") {
    if (!pid || !rid || runControlBusy) return;
    setRunControlBusy(true);
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/control`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string; status?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Control action failed"));
      if (typeof data.status === "string") {
        setRunStatus(data.status);
      }
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Control action failed");
    } finally {
      setRunControlBusy(false);
    }
  }

  async function applyTaskAction(taskId: string, action: "retry" | "skip" | "approve") {
    if (!pid || !rid || !taskId) return;
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/tasks/${encodeURIComponent(taskId)}/actions`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Task action failed"));
      await refreshArtifactsFromServer({ silent: true });
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Task action failed");
    }
  }

  async function simulatePermissionPreflight() {
    if (!pid || permissionSimBusy) return;
    setPermissionSimBusy(true);
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/permission/simulate`, {
        method: "POST",
        body: JSON.stringify({
          run_status: "plan_ready",
          requested_outputs: selectedOutputTypes,
          has_approval: true,
          enforce_policy: false,
          plan_payload: artifacts?.plan ?? {},
        }),
      });
      const data = (await res.json().catch(() => ({}))) as any;
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Permission simulation failed"));
      setPermissionSimResult(data);
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Permission simulation failed");
    } finally {
      setPermissionSimBusy(false);
    }
  }

  async function loadHooks() {
    if (!pid || hooksBusy) return;
    setHooksBusy(true);
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/hooks`);
      const data = (await res.json().catch(() => ({}))) as { hooks?: Array<Record<string, unknown>>; detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load hooks"));
      setHooksData(Array.isArray(data.hooks) ? data.hooks : []);
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Failed to load hooks");
    } finally {
      setHooksBusy(false);
    }
  }

  async function disableHookByName(hookName: string, reason: string) {
    if (!pid || !hookName.trim()) return;
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/hooks/disable`, {
        method: "POST",
        body: JSON.stringify({ hook_name: hookName.trim(), reason: reason.trim() }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to disable hook"));
      await loadHooks();
      emitToast({ message: `Hook ${hookName.trim()} disabled`, kind: "success" });
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Failed to disable hook");
    }
  }

  async function loadDeadLetters() {
    if (!pid) return;
    setDeadLetterLoading(true);
    setDeadLetterMsg(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/queue/dead-letter`);
      const data = (await res.json().catch(() => ({}))) as { items?: any[]; detail?: string };
      if (!res.ok) {
        throw new Error(extractApiErrorMessage(data, "Failed to load dead-letter items"));
      }
      setDeadLetters(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      setDeadLetterMsg(e instanceof Error ? e.message : "Failed to load dead-letter items");
    } finally {
      setDeadLetterLoading(false);
    }
  }

  async function replayDeadLetter(itemId: string) {
    if (!pid) return;
    setDeadLetterMsg(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/queue/dead-letter/replay`, {
        method: "POST",
        body: JSON.stringify({ item_id: itemId }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string | { message?: string } };
      if (!res.ok) {
        throw new Error(extractApiErrorMessage(data, "Replay failed"));
      }
      setDeadLetterMsg(`Replayed dead-letter item: ${itemId}`);
      await loadDeadLetters();
    } catch (e) {
      setDeadLetterMsg(e instanceof Error ? e.message : "Replay failed");
    }
  }

  async function resetDeadLetterAttempts(itemId: string) {
    if (!pid) return;
    setDeadLetterMsg(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/queue/dead-letter/reset-attempts`, {
        method: "POST",
        body: JSON.stringify({ item_id: itemId }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string | { message?: string } };
      if (!res.ok) {
        throw new Error(extractApiErrorMessage(data, "Reset attempts failed"));
      }
      setDeadLetterMsg(`Reset replay attempts: ${itemId}`);
      await loadDeadLetters();
    } catch (e) {
      setDeadLetterMsg(e instanceof Error ? e.message : "Reset attempts failed");
    }
  }

  async function finalApproveDeliverable() {
    if (!pid || !rid || finalApproveBusy) return;
    setFinalApproveBusy(true);
    setArtifactsError(null);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/final-approve`, {
        method: "POST",
        body: JSON.stringify({ notes: "User final approval from studio chat." }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) {
        throw new Error(extractApiErrorMessage(data, "Final approval failed"));
      }
      const refresh = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/artifacts`);
      const refreshData = (await refresh.json().catch(() => ({}))) as { detail?: string; status?: string; artifacts?: unknown };
      if (!refresh.ok) {
        throw new Error(extractApiErrorMessage(refreshData, "Failed to refresh artifacts"));
      }
      setRunStatus(refreshData.status ?? null);
      setArtifacts((refreshData as any).artifacts ?? null);
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : "Final approval failed");
    } finally {
      setFinalApproveBusy(false);
    }
  }

  function downloadText(filename: string, content: string) {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /** Prefer API-provided download names (client_deliverable_date.ext); fall back only for legacy responses. */
  function downloadDisplayName(map: Record<string, string>, key: string, legacyFallback: string): string {
    const v = map[key];
    return v && String(v).trim() ? String(v).trim() : legacyFallback;
  }

  const downloadBtnClass =
    "max-w-[min(100%,16rem)] text-left text-xs font-normal leading-snug whitespace-normal break-words [overflow-wrap:anywhere] py-2";

  function downloadBase64(filename: string, b64: string, mimeType: string) {
    const bytes = Uint8Array.from(atob(b64 || ""), (c) => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const processMapPref = outputTypeRepresentations.process_map;
  const raciPref = outputTypeRepresentations.raci;
  const readyDownloads = Array.isArray(artifacts?.ready_downloads) ? artifacts.ready_downloads.map((x: unknown) => String(x)) : [];
  const outputFilenames = artifacts?.output_filenames && typeof artifacts.output_filenames === "object"
    ? (artifacts.output_filenames as Record<string, string>)
    : {};
  const showProcessMapCollab = selectedOutputTypes.includes("process_map");
  const statusSteps = ["plan_ready", "plan_blocked", "approved", "running", "review_ready", "done"] as const;
  const currentStepIndex = runStatus ? statusSteps.indexOf(runStatus as (typeof statusSteps)[number]) : -1;
  const openQuestions = Array.isArray(latestAssistantMetadata?.open_questions)
    ? latestAssistantMetadata.open_questions.filter((x) => typeof x === "string")
    : [];
  const parsedRunEvents = useMemo(() => {
    const out: ParsedRunEvent[] = [];
    for (const line of liveEvents) {
      const p = parseEventLine(line);
      if (p) out.push(p);
    }
    return out;
  }, [liveEvents]);
  const coworkState = useCoworkState({
    parsedEvents: parsedRunEvents,
    messages: instructionChatMessages,
    openQuestions,
  });
  const decisionPrompts = Array.isArray(latestAssistantMetadata?.decision_prompts)
    ? latestAssistantMetadata.decision_prompts
    : [];
  const unresolvedPromptIds = Array.isArray(latestAssistantMetadata?.unresolved_prompt_ids)
    ? latestAssistantMetadata.unresolved_prompt_ids.filter((x) => typeof x === "string")
    : [];
  const evaluatorSummary = (artifacts?.evaluator_pipeline ?? null) as
    | {
        qa_passed?: boolean;
        visual_qa_passed?: boolean;
        guardrails_passed?: boolean;
        status?: string;
      }
    | null;

  // Unified approval state for the persistent banner
  const approvalBannerState = useMemo<ApprovalBannerState>(() => {
    if (runStatus === "plan_ready") {
      return {
        type: "plan_ready",
        saving: savePlanBusy,
        onSave: savePlan,
        onApprove: approvePlan,
      };
    }
    if (runStatus === "plan_blocked") {
      return {
        type: "plan_blocked",
        blockedStage: blockedContext?.stage,
        blockedReason: blockedContext?.reason,
        blockedCode: blockedContext?.code,
        onResimulate: simulatePermissionPreflight,
      };
    }
    if (runStatus === "review_ready") {
      return {
        type: "review_ready",
        busy: finalApproveBusy,
        onApprove: finalApproveDeliverable,
      };
    }
    if (
      runStatus === "plan_ready" &&
      (latestAssistantMetadata?.requires_user_approval ||
        latestAssistantMetadata?.ready_to_run)
    ) {
      return {
        type: "hitl_gate",
        reason:
          latestAssistantMetadata.approval_reason ??
          "Your Digital Teammate is asking for explicit approval before execution.",
        onApprove: approvePlan,
      };
    }
    return null;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runStatus, savePlanBusy, finalApproveBusy, latestAssistantMetadata, blockedContext]);

  // Download buttons — rendered inside ToolActivityFeed's Artifacts tab
  const downloadsContent =
    readyDownloads.length > 0 || artifacts?.qa_report || artifacts?.guardrail_report || artifacts?.visual_qa_report ? (
      <div className="flex flex-wrap gap-2 text-xs">
        {readyDownloads.includes("docx") && (() => {
          const fname = downloadDisplayName(outputFilenames, "docx", "output.docx");
          return (
            <Button type="button" className={downloadBtnClass} title={fname} onClick={() => downloadBase64(fname, String(artifacts.docx_base64 || ""), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}>
              {fname}
            </Button>
          );
        })()}
        {readyDownloads.includes("pptx") && (() => {
          const fname = downloadDisplayName(outputFilenames, "pptx", "output.pptx");
          return (
            <Button type="button" className={downloadBtnClass} title={fname} onClick={() => downloadBase64(fname, String(artifacts.pptx_base64 || ""), "application/vnd.openxmlformats-officedocument.presentationml.presentation")}>
              {fname}
            </Button>
          );
        })()}
        {readyDownloads.includes("xlsx") && (() => {
          const fname = downloadDisplayName(outputFilenames, "xlsx", "output.xlsx");
          return (
            <Button type="button" className={downloadBtnClass} title={fname} onClick={() => downloadBase64(fname, String(artifacts.xlsx_base64 || ""), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}>
              {fname}
            </Button>
          );
        })()}
        {readyDownloads.includes("pdf") && (() => {
          const fname = downloadDisplayName(outputFilenames, "pdf", "output.pdf");
          return (
            <Button type="button" className={downloadBtnClass} title={fname} onClick={() => downloadBase64(fname, String(artifacts.pdf_base64 || ""), "application/pdf")}>
              {fname}
            </Button>
          );
        })()}
        {(readyDownloads.includes("process_map_drawio") || readyDownloads.includes("process_map_mermaid")) && (() => {
          const isMermaid = processMapPref === "mermaid";
          const fname = downloadDisplayName(
            outputFilenames,
            isMermaid ? "process_map_mermaid" : "process_map_drawio",
            isMermaid ? "process_map.mmd" : "process_map.drawio.xml"
          );
          return (
            <Button type="button" variant="secondary" className={downloadBtnClass} title={fname} onClick={() => downloadText(fname, isMermaid ? (artifacts.process_map_mermaid || "") : (artifacts.drawio_xml || ""))}>
              {fname}
            </Button>
          );
        })()}
        {(readyDownloads.includes("raci_html") || readyDownloads.includes("raci_markdown") || readyDownloads.includes("raci_xlsx")) && (() => {
          let fname: string;
          let onClick: () => void;
          if (raciPref === "xlsx") {
            fname = downloadDisplayName(outputFilenames, "raci_xlsx", "raci.xlsx");
            onClick = () => downloadBase64(fname, String(artifacts.raci_xlsx_base64 || ""), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
          } else if (raciPref === "markdown") {
            fname = downloadDisplayName(outputFilenames, "raci_markdown", "raci.md");
            onClick = () => downloadText(fname, artifacts.raci_markdown || "");
          } else {
            fname = downloadDisplayName(outputFilenames, "raci_html", "raci.html");
            onClick = () => downloadText(fname, artifacts.raci_html || "");
          }
          return (
            <Button type="button" variant="secondary" className={downloadBtnClass} title={fname} onClick={onClick}>
              {fname}
            </Button>
          );
        })()}
        {readyDownloads.includes("sop_markdown") && (() => {
          const fname = downloadDisplayName(outputFilenames, "sop_markdown", "sop.md");
          return (
            <Button type="button" className={downloadBtnClass} title={fname} onClick={() => downloadText(fname, artifacts.sop_markdown || "")}>
              {fname}
            </Button>
          );
        })()}
        {readyDownloads.includes("narrative_md") && (() => {
          const fname = downloadDisplayName(outputFilenames, "narrative_md", "narrative.md");
          return (
            <Button type="button" className={downloadBtnClass} title={fname} onClick={() => downloadText(fname, artifacts.narrative_md || "")}>
              {fname}
            </Button>
          );
        })()}
        {artifacts?.qa_report ? (() => {
          const fname = downloadDisplayName(outputFilenames, "qa_report", "qa_report.json");
          return (
            <Button type="button" variant="secondary" className={downloadBtnClass} title={fname} onClick={() => downloadText(fname, JSON.stringify(artifacts.qa_report ?? {}, null, 2))}>
              {fname}
            </Button>
          );
        })() : null}
        {artifacts?.guardrail_report ? (() => {
          const fname = downloadDisplayName(outputFilenames, "guardrail_report", "guardrail_report.json");
          return (
            <Button type="button" variant="secondary" className={downloadBtnClass} title={fname} onClick={() => downloadText(fname, JSON.stringify(artifacts.guardrail_report ?? {}, null, 2))}>
              {fname}
            </Button>
          );
        })() : null}
        {artifacts?.visual_qa_report &&
        typeof artifacts.visual_qa_report === "object" &&
        Object.keys(artifacts.visual_qa_report as object).length > 0
          ? (() => {
              const fname = downloadDisplayName(outputFilenames, "visual_qa_report", "visual_qa_report.json");
              return (
                <Button type="button" variant="secondary" className={downloadBtnClass} title={fname} onClick={() => downloadText(fname, JSON.stringify(artifacts.visual_qa_report ?? {}, null, 2))}>
                  {fname}
                </Button>
              );
            })()
          : null}
      </div>
    ) : null;

  return {
    pid,
    rid,
    liveEvents,
    pollMode,
    streamError,
    instruction,
    selectedOutputTypes,
    customOutputInput,
    outputTypeRepresentations,
    recommendationNote,
    artifacts,
    runStatus,
    artifactsLoading,
    artifactsError,
    backpressureRetrySec,
    setBackpressureRetrySec,
    chatMessages,
    chatInput,
    setChatInput,
    chatBusy,
    conversationId,
    finalApproveBusy,
    savePlanBusy,
    runControlBusy,
    decisionBusy,
    permissionSimBusy,
    permissionSimResult,
    hooksBusy,
    hooksData,
    latestAssistantMetadata,
    instructionChatMessages,
    runChecklistTodos,
    parsedRunEvents,
    blockedContext,
    vqaArtifactKey,
    refreshChatFromServer,
    refreshArtifactsFromServer,
    approvePlan,
    sendChatMessage,
    savePlan,
    submitDecisionAnswers: submitDecisionAnswers,
    applyTaskAction,
    controlRun,
    simulatePermissionPreflight,
    loadHooks,
    disableHookByName,
    loadDeadLetters,
    replayDeadLetter,
    resetDeadLetterAttempts,
    finalApproveDeliverable,
    downloadText,
    downloadDisplayName,
    downloadBase64,
    readyDownloads,
    outputFilenames,
    showProcessMapCollab,
    statusSteps,
    currentStepIndex,
    openQuestions,
    coworkThinkingTrace: coworkState.thinkingTrace,
    coworkThinkingStatements: coworkState.thinkingStatements,
    coworkHasThinkingTrace: coworkState.hasThinkingTrace,
    coworkThinkingExpanded: coworkState.thinkingExpanded,
    setCoworkThinkingExpanded: coworkState.setThinkingExpanded,
    decisionPrompts,
    unresolvedPromptIds,
    evaluatorSummary,
    approvalBannerState,
    downloadsContent,
    canRenderEditor: Boolean(pid && rid),
    runControls: {
      canPause: runStatus === "approved",
      canResume: runStatus === "plan_ready",
      canStop: runStatus !== "done" && runStatus !== "failed",
      busy: runControlBusy,
      onPause: () => void controlRun("pause"),
      onResume: () => void controlRun("resume"),
      onStop: () => void controlRun("stop"),
    },
    hooksPanel: {
      hooks: hooksData,
      loading: hooksBusy,
      onRefresh: () => void loadHooks(),
      onDisable: (name: string, reason: string) => void disableHookByName(name, reason),
    },
    permissionPanel: {
      busy: permissionSimBusy,
      result: permissionSimResult,
      onSimulate: () => void simulatePermissionPreflight(),
    },
    processMapPref,
    raciPref,
    deadLetters,
    deadLetterLoading,
    deadLetterMsg,
  };
}

export type UseRunStudioReturn = ReturnType<typeof useRunStudio>;
