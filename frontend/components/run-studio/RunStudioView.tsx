"use client";

import dynamic from "next/dynamic";
import { memo } from "react";

import { ZoneAInstruction } from "@/components/run-studio/ZoneAInstruction";
import { ZoneCLiveMonitor } from "@/components/run-studio/ZoneCLiveMonitor";
import { ApprovalBanner } from "@/components/run-studio/ApprovalBanner";
import { ToolActivityFeed } from "@/components/run-studio/ToolActivityFeed";
import { RunChecklist } from "@/components/run-studio/RunChecklist";
import { SwarmPanel } from "@/components/run-studio/SwarmPanel";
import { Button } from "@/components/ui/Button";
import { AGENT_GRAPH_ENABLED, SCRATCHPAD_VISIBLE, type UseRunStudioReturn } from "@/hooks/useRunStudio";

const DrawioCollabEditor = dynamic(() => import("@/components/DrawioCollabEditor"), {
  ssr: false,
  loading: () => <p className="text-sm text-[var(--text-muted)]">Loading collaborative editor...</p>,
});

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
    backpressureRetrySec,
    setBackpressureRetrySec,
    approvePlan,
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

  return (
    <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
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
        {backpressureRetrySec !== null && backpressureRetrySec > 0 ? (
          <div className="alert alert--warning">
            Approval is temporarily throttled. Auto-retry in <strong>{backpressureRetrySec}s</strong>.
            <Button
              type="button"
              variant="secondary"
              className="ml-3 min-h-9 px-2 py-1 text-xs"
              onClick={() => {
                setBackpressureRetrySec(null);
                void approvePlan();
              }}
            >
              Retry now
            </Button>
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
        <ApprovalBanner state={approvalBannerState} />
      </section>
      <ToolActivityFeed
        events={liveEvents}
        parsedEvents={parsedRunEvents}
        runChecklistTodos={runChecklistTodos}
        artifacts={artifacts}
        pollMode={pollMode}
        streamError={streamError}
        showAgentGraph={AGENT_GRAPH_ENABLED}
        downloadsContent={downloadsContent}
        onTaskAction={applyTaskAction}
        hooksPanel={hooksPanel}
        permissionPanel={permissionPanel}
      />
    </div>
  );
}

export const RunStudioView = memo(RunStudioViewInner);
