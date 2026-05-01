"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import type { ChatMessage } from "@/hooks/useRunStudio";
import { CoordinatorWikiContext } from "@/components/wiki/CoordinatorWikiContext";

type DecisionPrompt = {
  id: string;
  label: string;
  description?: string;
  mode: "single_select" | "multi_select";
  required?: boolean;
  min_select?: number;
  allow_custom?: boolean;
  custom_placeholder?: string;
  options: Array<{ value: string; label: string; description?: string }>;
  selected_values?: string[];
};
type DecisionAnswerValue = { selected_values?: string[]; free_text?: string };
type ThinkingTraceItem = {
  id: string;
  text: string;
  kind: "thinking" | "plan" | "status" | "coordinator" | "tools" | "narrative";
};

function AssistantAvatar() {
  return (
    <div
      className="mb-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-[var(--primary-800)]"
      aria-label="Sheldon — your creative partner"
      role="img"
    >
      <span className="text-2xs font-bold text-white" aria-hidden>
        S
      </span>
    </div>
  );
}

function UserAvatarBubble() {
  return (
    <div
      className="mb-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent-blue)]"
      aria-label="Your message"
      role="img"
    >
      <span className="text-2xs font-bold text-white" aria-hidden>
        You
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collaborative building: arc proposal, slide proposal, structure summary
// ---------------------------------------------------------------------------
type ArcItem = {
  arc_key: string;
  name: string;
  structure: string;
  reasoning: string;
  lp_evidence?: string;
  is_recommended?: boolean;
};

function ArcProposalCard({
  arcs,
  onSelect,
}: {
  arcs: ArcItem[];
  onSelect: (arcKey: string) => void;
}) {
  return (
    <div className="mt-2 space-y-2">
      {arcs.map((arc) => (
        <div
          key={arc.arc_key}
          className={`rounded-lg border p-3 ${
            arc.is_recommended
              ? "border-[var(--primary-600)] bg-[var(--primary-50)]"
              : "border-[var(--surface-border)] bg-white"
          }`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1">
              <p className="text-xs font-semibold text-[var(--text-default)]">
                {arc.name}
                {arc.is_recommended && (
                  <span className="ml-1.5 rounded bg-[var(--primary-600)] px-1.5 py-0.5 text-2xs font-medium text-white">
                    Recommended
                  </span>
                )}
              </p>
              <p className="mt-0.5 text-2xs text-[var(--text-muted)]">{arc.reasoning}</p>
              {arc.lp_evidence && (
                <p className="mt-1 text-2xs italic text-[var(--text-subtle)]">
                  LP: {arc.lp_evidence.slice(0, 100)}…
                </p>
              )}
            </div>
            <button
              onClick={() => onSelect(arc.arc_key)}
              className="shrink-0 rounded bg-[var(--primary-800)] px-2.5 py-1 text-2xs font-medium text-white hover:bg-[var(--primary-700)]"
            >
              Use this
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

type SlideItem = {
  slide_num: number;
  title: string;
  slide_type: string;
  slide_type_label?: string;
  key_message: string;
  evidence_source?: string;
  sheldon_view?: string;
};

function SlideProposalCard({
  slide,
  onAgree,
  onModify,
}: {
  slide: SlideItem;
  onAgree: () => void;
  onModify: () => void;
}) {
  return (
    <div className="mt-2 rounded-lg border border-[var(--surface-border)] bg-white p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded bg-[var(--primary-100)] px-2 py-0.5 text-2xs font-semibold text-[var(--primary-800)]">
          Slide {slide.slide_num}
        </span>
        <span className="text-2xs text-[var(--text-muted)]">{slide.slide_type_label || slide.slide_type}</span>
      </div>
      <p className="text-xs font-semibold text-[var(--text-default)]">{slide.title}</p>
      <p className="mt-0.5 text-2xs text-[var(--text-muted)]">
        <span className="font-medium">Key message:</span> {slide.key_message}
      </p>
      {slide.evidence_source && (
        <p className="mt-0.5 text-2xs text-[var(--text-muted)]">
          <span className="font-medium">Evidence:</span> {slide.evidence_source}
        </p>
      )}
      {slide.sheldon_view && (
        <p className="mt-0.5 text-2xs italic text-[var(--text-subtle)]">{slide.sheldon_view}</p>
      )}
      <div className="mt-2 flex gap-2">
        <button
          onClick={onAgree}
          className="rounded bg-[var(--primary-800)] px-3 py-1 text-2xs font-medium text-white hover:bg-[var(--primary-700)]"
        >
          ✓ Agree
        </button>
        <button
          onClick={onModify}
          className="rounded border border-[var(--surface-border)] px-3 py-1 text-2xs font-medium text-[var(--text-default)] hover:bg-[var(--surface-muted)]"
        >
          ✏ Modify
        </button>
      </div>
    </div>
  );
}

function StructureSummaryCard({
  slides,
  onBuild,
}: {
  slides: Array<{ slide_num: number; title: string; key_message?: string }>;
  onBuild: () => void;
}) {
  return (
    <div className="mt-2 rounded-lg border border-[var(--primary-300)] bg-[var(--primary-50)] p-3">
      <p className="mb-2 text-xs font-semibold text-[var(--primary-900)]">Agreed deck structure</p>
      <ol className="space-y-0.5">
        {slides.map((s, idx) => (
          <li key={`${s.slide_num}-${idx}`} className="flex items-start gap-1.5 text-2xs text-[var(--text-muted)]">
            <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full bg-[var(--primary-600)] text-center text-2xs font-bold leading-4 text-white">
              {s.slide_num}
            </span>
            <span>
              <span className="font-medium text-[var(--text-default)]">{s.title}</span>
              {s.key_message ? ` — ${s.key_message}` : ""}
            </span>
          </li>
        ))}
      </ol>
      <button
        onClick={onBuild}
        className="mt-3 w-full rounded bg-[var(--primary-800)] py-1.5 text-xs font-semibold text-white hover:bg-[var(--primary-700)]"
      >
        Build the deck
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline markdown → React nodes (no external deps)
// Handles: headings, bold, italic, inline code, bullet lists, line breaks
// Only applied to assistant messages — user messages stay plain text.
// ---------------------------------------------------------------------------
function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let listBuffer: string[] = [];

  function flushList(key: string) {
    if (listBuffer.length === 0) return;
    nodes.push(
      <ul key={`ul-${key}`} className="my-1 list-disc space-y-0.5 pl-4 text-xs text-[var(--text-muted)]">
        {listBuffer.map((item, i) => (
          <li key={i}>{inlineFormat(item)}</li>
        ))}
      </ul>
    );
    listBuffer = [];
  }

  function inlineFormat(s: string): React.ReactNode[] {
    // Split on **bold**, *italic*, `code` tokens
    const parts = s.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i} className="font-semibold text-[var(--text-default)]">{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("*") && part.endsWith("*")) {
        return <em key={i}>{part.slice(1, -1)}</em>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code key={i} className="rounded bg-[var(--primary-200)] px-1 py-0.5 mono text-2xs text-[var(--text-default)]">
            {part.slice(1, -1)}
          </code>
        );
      }
      return <span key={i}>{part}</span>;
    });
  }

  lines.forEach((line, idx) => {
    const key = String(idx);

    // Headings
    const h1 = line.match(/^# (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h3 = line.match(/^### (.+)/);
    if (h1) {
      flushList(key);
      nodes.push(<p key={key} className="mt-2 text-sm font-bold text-[var(--text-default)]">{h1[1]}</p>);
      return;
    }
    if (h2) {
      flushList(key);
      nodes.push(<p key={key} className="mt-1.5 text-xs font-semibold text-[var(--primary-800)]">{h2[1]}</p>);
      return;
    }
    if (h3) {
      flushList(key);
      nodes.push(<p key={key} className="mt-1 text-xs font-medium text-[var(--text-muted)]">{h3[1]}</p>);
      return;
    }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) {
      flushList(key);
      nodes.push(<hr key={key} className="my-2 border-[var(--surface-border)]" />);
      return;
    }

    // Bullet list items
    const bullet = line.match(/^[-*] (.+)/);
    const numbered = line.match(/^\d+\. (.+)/);
    if (bullet) {
      listBuffer.push(bullet[1]);
      return;
    }
    if (numbered) {
      listBuffer.push(numbered[1]);
      return;
    }

    // Flush pending list before non-list line
    flushList(key);

    // Empty line → spacing
    if (!line.trim()) {
      nodes.push(<div key={key} className="h-1" />);
      return;
    }

    // Normal paragraph
    nodes.push(
      <p key={key} className="text-xs leading-relaxed text-[var(--text-muted)]">
        {inlineFormat(line)}
      </p>
    );
  });

  flushList("end");
  return nodes;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function ZoneAInstruction({
  recommendationNote,
  chatMessages,
  chatInput,
  setChatInput,
  chatBusy,
  onSendChat,
  conversationId,
  openQuestions,
  decisionPrompts,
  unresolvedPromptIds,
  onSubmitDecisions,
  onUpdateOutline,
  decisionBusy,
  thinkingStatements = [],
  hasThinkingTrace = false,
  thinkingTrace = [],
  thinkingExpanded = false,
  onToggleThinkingTrace = () => {},
  projectId,
  showGuidedDecisions = true,
}: {
  projectId?: string;
  recommendationNote: string | null;
  chatMessages: ChatMessage[];
  chatInput: string;
  setChatInput: (value: string) => void;
  chatBusy: boolean;
  onSendChat: () => Promise<void>;
  conversationId: string | null;
  openQuestions: string[];
  decisionPrompts: DecisionPrompt[];
  unresolvedPromptIds: string[];
  onSubmitDecisions: (
    answers: Record<string, string[] | DecisionAnswerValue>
  ) => Promise<void>;
  onUpdateOutline?: (slides: Array<{ title: string; slide_type: string; purpose?: string }>) => Promise<void>;
  decisionBusy: boolean;
  thinkingStatements?: string[];
  hasThinkingTrace?: boolean;
  thinkingTrace?: ThinkingTraceItem[];
  thinkingExpanded?: boolean;
  onToggleThinkingTrace?: () => void;
  showGuidedDecisions?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Derive run objective from the latest user message for wiki context
  const runObjective = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      if (chatMessages[i].role === "user") return chatMessages[i].content;
    }
    return "";
  }, [chatMessages]);

  const latestAssistantMeta = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
      const m = chatMessages[i];
      if (m.role === "assistant" && m.metadata) return m.metadata;
    }
    return undefined;
  }, [chatMessages]);
  const discovery = latestAssistantMeta?.discovery;
  const outlineSlides = Array.isArray(latestAssistantMeta?.deck_outline_preview?.slides)
    ? latestAssistantMeta?.deck_outline_preview?.slides
    : [];
  const documentOutline = latestAssistantMeta?.document_outline_preview;
  const documentSections = Array.isArray(documentOutline?.sections) ? documentOutline?.sections : [];
  const wikiContextRefs = Array.isArray(latestAssistantMeta?.wiki_context_refs)
    ? latestAssistantMeta?.wiki_context_refs?.filter((x) => typeof x === "string" && x.trim())
    : [];
  const [decisionDraft, setDecisionDraft] = useState<Record<string, string[]>>({});
  const [decisionCustom, setDecisionCustom] = useState<Record<string, string>>({});
  const [outlineDraft, setOutlineDraft] = useState<Array<{ title: string; slide_type: string; purpose?: string }>>([]);
  const [outlineDirty, setOutlineDirty] = useState(false);

  useEffect(() => {
    if (!Array.isArray(outlineSlides)) return;
    const normalized = outlineSlides.map((s) => ({
      title: String(s?.title || "").trim(),
      slide_type: String(s?.slide_type || "bullets").trim() || "bullets",
      purpose: String(s?.purpose || "").trim(),
    }));
    setOutlineDraft(normalized);
    setOutlineDirty(false);
  }, [latestAssistantMeta?.plan_hash]);

  // Auto-scroll to bottom when messages change or thinking indicator appears
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chatMessages, chatBusy]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!chatBusy && chatInput.trim()) void onSendChat();
    }
  }


  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-[var(--surface-border)] bg-white shadow-sm">
      {/* ── Header ── */}
      <div className="border-b border-[var(--surface-border)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--text-default)]">Creative Studio</h3>
        <p className="mt-0.5 text-xs text-[var(--text-muted)]">
          Chat with Sheldon — brainstorm ideas, explore approaches, and build deliverables together.
        </p>
      </div>

      {/* ── Message Thread ── */}
      <div
        ref={scrollRef}
        className="min-h-[140px] max-h-[400px] flex-1 space-y-3 overflow-y-auto px-4 py-3"
      >
        {chatMessages.length === 0 && !chatBusy ? (
          <p className="py-8 text-center text-xs text-[var(--text-muted)]">
            Start a conversation — tell Sheldon about your project.
          </p>
        ) : (
          chatMessages.map((m, idx) => (
            <div
              key={
                m.id != null
                  ? `msg-${m.id}`
                  : m.clientId
                    ? m.clientId
                    : `${m.ts}-${idx}`
              }
              className={`flex items-end gap-2 ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {/* Digital Teammate avatar */}
              {m.role === "assistant" && <AssistantAvatar />}

              {/* Bubble */}
              <div
                className={`max-w-[82%] rounded-lg px-3 py-2 ${
                  m.role === "user"
                    ? "rounded-br-sm bg-[var(--primary-900)] text-white"
                    : "rounded-bl-sm border border-[var(--surface-border)] bg-[var(--surface-muted)]"
                }`}
              >
                {m.role === "assistant" ? (
                  <div className="space-y-0.5">
                    {renderMarkdown(m.content)}
                    {/* Arc proposal card */}
                    {m.metadata?.kind === "arc_proposal" && Array.isArray(m.metadata.arcs) && (
                      <ArcProposalCard
                        arcs={m.metadata.arcs as ArcItem[]}
                        onSelect={(arcKey) => {
                          setChatInput(`I'd like to go with ${arcKey}`);
                          void onSendChat();
                        }}
                      />
                    )}
                    {/* Slide proposal card */}
                    {m.metadata?.kind === "slide_proposal" && m.metadata.slide && (
                      <SlideProposalCard
                        slide={m.metadata.slide as SlideItem}
                        onAgree={() => {
                          setChatInput("Agree");
                          void onSendChat();
                        }}
                        onModify={() => {
                          setChatInput(`Modify slide ${m.metadata?.slide?.slide_num}: `);
                        }}
                      />
                    )}
                    {/* Structure summary / build card */}
                    {m.metadata?.kind === "structure_summary" && Array.isArray(m.metadata.slides) && (
                      <StructureSummaryCard
                        slides={m.metadata.slides as Array<{ slide_num: number; title: string; key_message?: string }>}
                        onBuild={() => {
                          setChatInput("Build it");
                          void onSendChat();
                        }}
                      />
                    )}
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-white [overflow-wrap:anywhere]">
                    {m.content}
                  </p>
                )}
                <p
                  className={`mt-1.5 text-2xs ${
                    m.role === "user" ? "text-white/65" : "text-[var(--primary-400)]"
                  }`}
                >
                  {new Date(m.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </p>
              </div>

              {/* User avatar */}
              {m.role === "user" && <UserAvatarBubble />}
            </div>
          ))
        )}

        {recommendationNote ? (
          <div className="flex items-end justify-start gap-2">
            <AssistantAvatar />
            <div className="max-w-[82%] rounded-lg rounded-bl-sm border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2">
              <p className="text-xs leading-relaxed text-[var(--text-muted)]">{recommendationNote}</p>
            </div>
          </div>
        ) : null}

        {openQuestions.length > 0 && !showGuidedDecisions ? (
          // Only show this inline bubble when the structured Plan Decisions panel
          // is hidden — otherwise the panel is the single source of truth.
          <div className="flex items-end justify-start gap-2">
            <AssistantAvatar />
            <div className="max-w-[82%] rounded-lg rounded-bl-sm border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2">
              <p className="text-xs font-semibold text-[var(--text-default)]">
                Open decisions ({openQuestions.length})
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-[var(--text-muted)]">
                {openQuestions.map((q, i) => (
                  <li key={`oq-thread-${i}`}>{q}</li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}

        {/* ── Thinking indicator ── */}
        {chatBusy && (
          <div className="flex items-end gap-2 justify-start">
            <AssistantAvatar />
            <div className="rounded-lg rounded-bl-sm border border-[color:color-mix(in_srgb,var(--info)_25%,white)] bg-[var(--info-light)] px-3 py-2.5">
              <div className="flex items-center gap-1.5">
                <span
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--accent-blue-light)]"
                  style={{ animationDelay: "0ms" }}
                />
                <span
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--accent-blue-light)]"
                  style={{ animationDelay: "160ms" }}
                />
                <span
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--accent-blue-light)]"
                  style={{ animationDelay: "320ms" }}
                />
                <span className="ml-1 text-xs font-medium text-[var(--accent-indigo)]">Thinking…</span>
              </div>
            </div>
          </div>
        )}
        {thinkingStatements.length > 0 ? (
          <div className="rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2">
            <p className="text-2xs font-medium text-[var(--text-muted)]">Reasoning timeline</p>
            <ul className="mt-1 space-y-0.5 text-2xs text-[var(--text-muted)]">
              {thinkingStatements.map((line, idx) => (
                <li key={`${line}-${idx}`}>- {line}</li>
              ))}
            </ul>
            {hasThinkingTrace ? (
              <button
                type="button"
                className="mt-1 text-2xs text-[var(--accent-blue)] underline"
                onClick={onToggleThinkingTrace}
              >
                {thinkingExpanded ? "Hide reasoning trace" : "Show full reasoning trace"}
              </button>
            ) : null}
          </div>
        ) : null}
        {hasThinkingTrace && thinkingExpanded ? (
          <div className="rounded border border-[var(--surface-border)] bg-white p-2">
            <ul className="space-y-1 text-2xs text-[var(--text-muted)]">
              {thinkingTrace.map((item) => (
                <li key={item.id} className="flex items-start gap-1.5">
                  <span className="uppercase text-[10px]">{item.kind}</span>
                  <span>{item.text}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {/* ── Wiki Context (Option D) ── */}
      {projectId && runObjective.trim() && (
        <div className="border-t border-[var(--surface-border)] px-4 py-3">
          <details className="group">
            <summary className="cursor-pointer text-xs font-semibold text-[var(--text-muted)] hover:text-[var(--text-default)]">
              Relevant Wiki Context
            </summary>
            <div className="mt-2 max-h-[200px] overflow-y-auto">
              <CoordinatorWikiContext
                projectId={projectId}
                runObjective={runObjective}
              />
            </div>
          </details>
        </div>
      )}

      {showGuidedDecisions &&
      (decisionPrompts.length > 0 ||
        discovery ||
        outlineDraft.length > 0 ||
        (documentSections && documentSections.length > 0) ||
        (wikiContextRefs && wikiContextRefs.length > 0)) ? (
        <div className="border-t border-[var(--surface-border)] px-4 py-3 space-y-3">
          {wikiContextRefs && wikiContextRefs.length > 0 ? (
            <div className="rounded border border-[var(--surface-border)] bg-[var(--info-light)] px-2 py-1.5">
              <p className="text-2xs font-semibold text-[var(--text-default)]">
                Grounded in your wiki
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {wikiContextRefs.map((ref, idx) => (
                  <span
                    key={`wiki-ref-${idx}`}
                    className="rounded-full border border-[var(--surface-border)] bg-white px-2 py-0.5 text-2xs text-[var(--text-muted)]"
                  >
                    {ref}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {discovery ? (
            <div className="rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] p-2">
              <p className="text-2xs font-semibold text-[var(--text-default)]">Discovery</p>
              <ul className="mt-1 list-disc pl-4 text-2xs text-[var(--text-muted)]">
                <li>Client: {discovery.client?.name || "—"} ({discovery.client?.industry || "—"})</li>
                <li>Outcome: {discovery.outcome?.primary || "—"}</li>
                <li>Decision: {discovery.outcome?.decision || "—"}</li>
                <li>Themes: {Array.isArray(discovery.win_themes) && discovery.win_themes.length > 0 ? discovery.win_themes.join(", ") : "—"}</li>
              </ul>
            </div>
          ) : null}

          {decisionPrompts.length > 0 ? (
            <div className="rounded border border-[var(--surface-border)] p-2">
              <p className="text-2xs font-semibold text-[var(--text-default)]">Plan Decisions</p>
              <p className="mt-0.5 text-2xs text-[var(--text-muted)]">
                Pick the option that fits — or, where shown, type your own answer in the text field.
              </p>
              <div className="mt-2 space-y-3">
                {decisionPrompts.map((prompt) => {
                  const selected = decisionDraft[prompt.id] ?? prompt.selected_values ?? [];
                  const selectedValue = selected[0] ?? "";
                  const selectedOption = prompt.options.find((opt) => opt.value === selectedValue);
                  const customValue = decisionCustom[prompt.id] ?? "";
                  const isUnresolved = unresolvedPromptIds.includes(prompt.id);
                  return (
                    <div
                      key={prompt.id}
                      className={`rounded border px-2 py-2 ${
                        isUnresolved
                          ? "border-[var(--accent-blue)] bg-[var(--info-light)]"
                          : "border-[var(--surface-border)] bg-white"
                      }`}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <p className="text-2xs font-semibold text-[var(--text-default)]">
                          {prompt.label}
                          {prompt.required ? (
                            <span className="ml-1 text-[var(--accent-blue)]">*</span>
                          ) : null}
                        </p>
                        {isUnresolved ? (
                          <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--accent-blue)]">
                            Needs your input
                          </span>
                        ) : null}
                      </div>
                      {prompt.description ? (
                        <p className="mt-0.5 text-2xs text-[var(--text-muted)]">{prompt.description}</p>
                      ) : null}
                      <select
                        className="mt-1.5 w-full rounded border border-[var(--surface-border)] bg-white px-2 py-1 text-xs text-[var(--text-default)]"
                        value={selectedValue}
                        onChange={(e) => {
                          const next = e.target.value;
                          setDecisionDraft((prev) => ({ ...prev, [prompt.id]: next ? [next] : [] }));
                          if (next) {
                            setDecisionCustom((prev) => ({ ...prev, [prompt.id]: "" }));
                          }
                        }}
                      >
                        <option value="">Select…</option>
                        {prompt.options.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                      {selectedOption?.description ? (
                        <p className="mt-1 text-2xs italic text-[var(--text-muted)]">
                          {selectedOption.description}
                        </p>
                      ) : null}
                      {prompt.allow_custom ? (
                        <div className="mt-1.5">
                          <input
                            type="text"
                            value={customValue}
                            placeholder={prompt.custom_placeholder || "Or type your own answer…"}
                            className="w-full rounded border border-[var(--surface-border)] bg-white px-2 py-1 text-2xs text-[var(--text-default)]"
                            onChange={(e) => {
                              setDecisionCustom((prev) => ({ ...prev, [prompt.id]: e.target.value }));
                              if (e.target.value.trim()) {
                                setDecisionDraft((prev) => ({ ...prev, [prompt.id]: [] }));
                              }
                            }}
                          />
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              <div className="mt-2 flex items-center justify-between">
                <p className="text-2xs text-[var(--text-muted)]">
                  Pending: {unresolvedPromptIds.length}
                </p>
                <Button
                  type="button"
                  disabled={decisionBusy}
                  onClick={() => {
                    const payload: Record<string, DecisionAnswerValue> = {};
                    for (const prompt of decisionPrompts) {
                      const values = decisionDraft[prompt.id] ?? prompt.selected_values ?? [];
                      const custom = (decisionCustom[prompt.id] || "").trim();
                      if (values.length === 0 && !custom) continue;
                      payload[prompt.id] = {
                        selected_values: values,
                        free_text: custom || undefined,
                      };
                    }
                    void onSubmitDecisions(payload);
                  }}
                  className="px-2 py-1 text-2xs"
                >
                  {decisionBusy ? "Saving..." : "Save decisions"}
                </Button>
              </div>
            </div>
          ) : null}

          {documentSections && documentSections.length > 0 ? (
            <div className="rounded border border-[var(--surface-border)] bg-white p-2">
              <p className="text-2xs font-semibold text-[var(--text-default)]">
                Proposed document storyline
                {documentOutline?.target_pages ? (
                  <span className="ml-1 text-2xs font-normal text-[var(--text-muted)]">
                    (~{documentOutline.target_pages} pages)
                  </span>
                ) : null}
              </p>
              {documentOutline?.rationale ? (
                <p className="mt-0.5 text-2xs italic text-[var(--text-muted)]">{documentOutline.rationale}</p>
              ) : null}
              <ol className="mt-1.5 list-decimal space-y-1.5 pl-4 text-2xs text-[var(--text-muted)]">
                {documentSections.map((section, idx) => (
                  <li key={`doc-section-${idx}`}>
                    <span className="font-semibold text-[var(--text-default)]">
                      {section?.heading || `Section ${idx + 1}`}
                    </span>
                    {section?.purpose ? (
                      <span className="block italic">{section.purpose}</span>
                    ) : null}
                    {Array.isArray(section?.key_points) && section.key_points.length > 0 ? (
                      <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
                        {section.key_points.map((kp, kpi) => (
                          <li key={`doc-section-${idx}-kp-${kpi}`}>{kp}</li>
                        ))}
                      </ul>
                    ) : null}
                    {section?.evidence_pointer ? (
                      <span className="mt-0.5 block text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                        Evidence: {section.evidence_pointer}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          {outlineDraft.length > 0 ? (
            <details className="rounded border border-[var(--surface-border)] p-2">
              <summary className="cursor-pointer text-2xs font-semibold text-[var(--text-default)]">Edit outline</summary>
              <div className="mt-2 space-y-2">
                {outlineDraft.map((slide, idx) => (
                  <div key={`outline-${idx}`} className="grid grid-cols-12 gap-1">
                    <input
                      className="col-span-6 rounded border border-[var(--surface-border)] px-2 py-1 text-2xs"
                      value={slide.title}
                      onChange={(e) => {
                        setOutlineDraft((prev) => prev.map((s, i) => i === idx ? { ...s, title: e.target.value } : s));
                        setOutlineDirty(true);
                      }}
                    />
                    <input
                      className="col-span-3 rounded border border-[var(--surface-border)] px-2 py-1 text-2xs"
                      value={slide.slide_type}
                      onChange={(e) => {
                        setOutlineDraft((prev) => prev.map((s, i) => i === idx ? { ...s, slide_type: e.target.value } : s));
                        setOutlineDirty(true);
                      }}
                    />
                    <button
                      type="button"
                      className="col-span-1 rounded border border-[var(--surface-border)] text-2xs"
                      onClick={() => {
                        if (idx === 0) return;
                        setOutlineDraft((prev) => {
                          const next = [...prev];
                          [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
                          return next;
                        });
                        setOutlineDirty(true);
                      }}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="col-span-1 rounded border border-[var(--surface-border)] text-2xs"
                      onClick={() => {
                        if (idx >= outlineDraft.length - 1) return;
                        setOutlineDraft((prev) => {
                          const next = [...prev];
                          [next[idx + 1], next[idx]] = [next[idx], next[idx + 1]];
                          return next;
                        });
                        setOutlineDirty(true);
                      }}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="col-span-1 rounded border border-[var(--surface-border)] text-2xs"
                      onClick={() => {
                        setOutlineDraft((prev) => prev.filter((_, i) => i !== idx));
                        setOutlineDirty(true);
                      }}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    className="px-2 py-1 text-2xs"
                    onClick={() => {
                      setOutlineDraft((prev) => [...prev, { title: "New slide", slide_type: "bullets", purpose: "" }]);
                      setOutlineDirty(true);
                    }}
                  >
                    + Add slide
                  </Button>
                  <Button
                    type="button"
                    disabled={!outlineDirty || decisionBusy || !onUpdateOutline}
                    className="px-2 py-1 text-2xs"
                    onClick={() => void onUpdateOutline?.(outlineDraft)}
                  >
                    Save outline
                  </Button>
                </div>
              </div>
            </details>
          ) : null}
        </div>
      ) : null}

      {/* ── Input area ── */}
      <div className="border-t border-[var(--surface-border)] px-4 py-3">
        <div className="flex items-end gap-2">
          <Textarea
            rows={2}
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Chat with Sheldon… (Enter to send · Shift+Enter for newline)"
            disabled={chatBusy}
            className="flex-1 resize-none text-xs"
          />
          <Button
            type="button"
            onClick={() => void onSendChat()}
            disabled={chatBusy || !chatInput.trim()}
            className="h-[52px] shrink-0 px-4"
          >
            {chatBusy ? "…" : "Send"}
          </Button>
        </div>
        <div className="mt-1.5 flex items-center justify-between">
          <p className="text-2xs text-[var(--text-muted)]">
            Say &quot;create&quot; or &quot;build&quot; when you&apos;re ready to generate deliverables.
          </p>
          {conversationId && (
            <p className="text-2xs text-[var(--text-muted)]">Conv: {conversationId.slice(-8)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
