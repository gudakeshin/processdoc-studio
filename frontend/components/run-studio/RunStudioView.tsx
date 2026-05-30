"use client";

import dynamic from "next/dynamic";
import { memo, useMemo } from "react";

import { ZoneAInstruction } from "@/components/run-studio/ZoneAInstruction";
import { ZoneCLiveMonitor } from "@/components/run-studio/ZoneCLiveMonitor";
import { ApprovalBanner } from "@/components/run-studio/ApprovalBanner";
import { ApprovalBannerRedesigned } from "@/components/run-studio/ApprovalBannerRedesigned";
import { ToolActivityFeed } from "@/components/run-studio/ToolActivityFeed";
import { ActivityFeedRedesigned } from "@/components/run-studio/ActivityFeedRedesigned";
import { SystemBanner } from "@/components/run-studio/SystemBanner";
import { RunChecklist } from "@/components/run-studio/RunChecklist";
import { SwarmPanel } from "@/components/run-studio/SwarmPanel";
import { Button } from "@/components/ui/Button";
import { AGENT_GRAPH_ENABLED, SCRATCHPAD_VISIBLE, type UseRunStudioReturn } from "@/hooks/useRunStudio";

const DrawioCollabEditor = dynamic(() => import("@/components/DrawioCollabEditor"), {
  ssr: false,
  loading: () => <p className="text-sm text-[var(--text-muted)]">Loading collaborative editor...</p>,
});
const WikiArtifactSection = dynamic(
  () => import("@/components/wiki/WikiArtifactSection").then((m) => ({ default: m.WikiArtifactSection })),
  { ssr: false, loading: () => null },
);

function RunStudioViewInner(props: UseRunStudioReturn) {
  const {
    pid,
    rid,
    liveEvents,
    pollMode,
    streamError,
    recommendationNote,
    instructionChatMessages,
    chatInput,
    setChatInput,
    chatBusy,
    sendChatMessage,
    conversationId,
    openQuestions,
    coworkThinkingTrace,
    coworkThinkingStatements,
    coworkHasThinkingTrace,
    coworkThinkingExpanded,
    setCoworkThinkingExpanded,
    decisionPrompts,
    unresolvedPromptIds,
    submitDecisionAnswers,
    updateConversationOutline,
    decisionBusy,
    runChecklistTodos,
    parsedRunEvents,
    artifactsError,
    runStatus,
    statusSteps,
    currentStepIndex,
    evaluatorSummary,
    artifacts,
    showProcessMapCollab,
    canRenderEditor,
    processMapPref,
    approvalBannerState,
    downloadsContent,
    applyTaskAction,
    hooksPanel,
    permissionPanel,
  } = props;

  // Collect agreed slide decisions from collaborative building messages.
  const agreedDecisions = useMemo(() => {
    const all: Array<{ slide_num: number; title: string; key_message?: string; slide_type?: string; agreed?: boolean }> = [];
    // First check for a structure_summary message (has all agreed slides).
    for (let i = instructionChatMessages.length - 1; i >= 0; i--) {
      const m = instructionChatMessages[i];
      if (m.role === "assistant" && m.metadata?.kind === "structure_summary" && Array.isArray(m.metadata.slides)) {
        return m.metadata.slides as typeof all;
      }
    }
    // Fall back to accumulating individual slide_proposal messages.
    for (const m of instructionChatMessages) {
      if (m.role === "assistant" && m.metadata?.kind === "slide_proposal" && m.metadata.slide?.agreed) {
        all.push(m.metadata.slide as typeof all[number]);
      }
    }
    return all;
  }, [instructionChatMessages]);

  return (
    <div className="min-h-screen flex flex-col">
      {/* System banners — sticky top bar */}
      <div className="sticky top-0 z-40 border-b border-[#E0E0E0] bg-white">
        {pollMode && (
          <SystemBanner
            type="info"
            title="Polling mode active"
            detail="Waiting for stream reconnection..."
          />
        )}
        {approvalBannerState?.type === "plan_blocked" && (
          <SystemBanner
            type="error"
            title="Governance checks failed"
            detail={approvalBannerState.blockedReason}
          />
        )}
        {streamError && (
          <SystemBanner
            type="warn"
            title="Stream error"
            detail={streamError}
          />
        )}
      </div>

      {/* Main layout grid */}
      <div className="grid min-w-0 flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="relative flex min-h-0 flex-col gap-3">
          <div className="alert alert--info">
            Expected flow:{" "}
            <strong>Use uploaded docs, execute, pass visual QA, review/refine, final-approve, then run guardrails.</strong>
          </div>
        <div className="rounded-lg border border-[var(--surface-border)] bg-white p-3 text-xs">
          <p>
            <strong>Run status:</strong> {runStatus ?? "unknown"}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {statusSteps.map((step, idx) => {
              const active = currentStepIndex >= idx;
              return (
                <span
                  key={step}
                  className={`status-pill ${active ? "status-pill--success" : "bg-[var(--surface-muted)] text-[var(--text-muted)]"}`}
                >
                  {step}
                </span>
              );
            })}
          </div>
        </div>
        {runChecklistTodos.length > 0 ? <RunChecklist todos={runChecklistTodos} /> : null}
        {pid && rid ? <SwarmPanel pid={pid} rid={rid} liveEventsLength={liveEvents.length} /> : null}
        {artifactsError || streamError ? (
          <div className="alert alert--error text-xs">
            {artifactsError && (
              <p>
                <strong>Artifacts error:</strong> {artifactsError}
              </p>
            )}
            {streamError && (
              <p className={artifactsError ? "mt-1" : ""}>
                <strong>Stream error:</strong> {streamError}
              </p>
            )}
          </div>
        ) : null}
        {pollMode ? (
          <div className="alert alert--warning text-xs">
            Live stream is in replay/poll continuity mode. New events may arrive with slight delay.
          </div>
        ) : null}
        <ZoneAInstruction
          recommendationNote={recommendationNote}
          chatMessages={instructionChatMessages}
          chatInput={chatInput}
          setChatInput={setChatInput}
          chatBusy={chatBusy}
          onSendChat={sendChatMessage}
          conversationId={conversationId}
          openQuestions={openQuestions}
          decisionPrompts={decisionPrompts}
          unresolvedPromptIds={unresolvedPromptIds}
          onSubmitDecisions={submitDecisionAnswers}
          onUpdateOutline={updateConversationOutline}
          decisionBusy={decisionBusy}
          thinkingStatements={coworkThinkingStatements}
          hasThinkingTrace={coworkHasThinkingTrace}
          thinkingTrace={coworkThinkingTrace}
          thinkingExpanded={coworkThinkingExpanded}
          onToggleThinkingTrace={() => setCoworkThinkingExpanded((v) => !v)}
          showGuidedDecisions={process.env.NEXT_PUBLIC_PROPOSAL_DISCOVERY_ENABLED !== "false"}
        />
        <ZoneCLiveMonitor
          events={liveEvents}
          showAgentGraph={false}
          evaluatorSummary={
            evaluatorSummary
              ? {
                  qaPassed: Boolean(evaluatorSummary.qa_passed),
                  visualQaPassed: Boolean(evaluatorSummary.visual_qa_passed),
                  guardrailsPassed: Boolean(evaluatorSummary.guardrails_passed),
                  status: evaluatorSummary.status,
                }
              : null
          }
        />
        {SCRATCHPAD_VISIBLE && artifacts?.scratchpad_summary ? (
          <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--agent-purple)_28%,white)] bg-[var(--agent-purple-light)] p-3 text-xs text-[color:color-mix(in_srgb,var(--agent-purple)_85%,black)]">
            <p className="font-semibold">Working notes (safe summary)</p>
            <p className="mt-1 whitespace-pre-wrap break-words">{String(artifacts.scratchpad_summary)}</p>
          </div>
        ) : null}
        {showProcessMapCollab ? (
          <div>
            <h3 className="mb-2 text-lg font-semibold">Collaborative process map</h3>
            {canRenderEditor && processMapPref !== "mermaid" ? (
              <DrawioCollabEditor pid={pid} runId={rid} initialXml={artifacts?.drawio_xml ?? null} />
            ) : processMapPref === "mermaid" ? (
              <pre className="max-h-[280px] overflow-auto whitespace-pre-wrap rounded border border-[var(--surface-border)] bg-[var(--primary-100)] p-3 text-xs text-[var(--text-default)]">
                {typeof artifacts?.process_map_mermaid === "string"
                  ? artifacts.process_map_mermaid
                  : "No Mermaid process map generated yet."}
              </pre>
            ) : null}
          </div>
        ) : null}
        <ApprovalBannerRedesigned state={approvalBannerState} />
        {pid && rid && (
          <WikiArtifactSection runId={rid} projectId={pid} />
        )}
      </section>
        <ActivityFeedRedesigned
          parsedEvents={parsedRunEvents}
          artifacts={artifacts?.ready_downloads || []}
          runTodos={runChecklistTodos || []}
          contextMetadata={{
            leadingPractices: artifacts?.leading_practices || [],
            nonNegotiables: artifacts?.memory_summary?.non_negotiables || [],
          }}
          width={360}
        />
      </div>
    </div>
  );
}

export const RunStudioView = memo(RunStudioViewInner);
