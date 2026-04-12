"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import type { ChatMessage } from "@/hooks/useRunStudio";
import { CoordinatorWikiContext } from "@/components/wiki/CoordinatorWikiContext";

type DecisionPrompt = {
  id: string;
  label: string;
  mode: "single_select" | "multi_select";
  required?: boolean;
  min_select?: number;
  options: Array<{ value: string; label: string }>;
  selected_values?: string[];
};
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
  onSubmitDecisions: (answers: Record<string, string[]>) => Promise<void>;
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
                  <div className="space-y-0.5">{renderMarkdown(m.content)}</div>
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

        {openQuestions.length > 0 ? (
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
