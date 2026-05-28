"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DeckCanvas, type CanvasSlide } from "./DeckCanvas";

export type DeckTabPanelProps = {
  slides: CanvasSlide[];
  onElementClick?: (args: { slideIndex: number; elementPath: string }) => void;
  slideRegenerateBusyIndex?: number | null;
  className?: string;
};

/**
 * Rich deck viewer used inside the run studio "Deck" tab.
 *
 * - Left rail: compact thumbnails (slide index + type + title) with keyboard nav.
 * - Main pane: full DeckCanvas rendering for the focused slide.
 * - Clicking any element fires `onElementClick` (same contract DeckCanvas uses)
 *   so the parent can open the existing "regenerate slide" modal with the
 *   element path prefilled.
 *
 * Keyboard shortcuts (when the panel has focus):
 *   ↓ / j / PageDown → next slide
 *   ↑ / k / PageUp   → previous slide
 *   Home / End        → first / last slide
 *   Enter             → open regeneration modal for the focused slide title
 */
export function DeckTabPanel({
  slides,
  onElementClick,
  slideRegenerateBusyIndex,
  className,
}: DeckTabPanelProps) {
  const normalized = useMemo(() => {
    if (!Array.isArray(slides)) return [] as CanvasSlide[];
    return slides.filter((s): s is CanvasSlide => Boolean(s) && typeof s === "object");
  }, [slides]);

  const [focusIdxState, setFocusIdx] = useState(0);
  // Clamp during render instead of setState-in-effect so a shrinking slides
  // array can never leave the focus pointer dangling past the new end.
  const focusIdx = Math.min(focusIdxState, Math.max(0, normalized.length - 1));
  const railRef = useRef<HTMLDivElement | null>(null);
  const mainRef = useRef<HTMLDivElement | null>(null);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (normalized.length === 0) return;
      let handled = true;
      switch (event.key) {
        case "ArrowDown":
        case "j":
        case "PageDown":
          setFocusIdx((i) => Math.min(normalized.length - 1, i + 1));
          break;
        case "ArrowUp":
        case "k":
        case "PageUp":
          setFocusIdx((i) => Math.max(0, i - 1));
          break;
        case "Home":
          setFocusIdx(0);
          break;
        case "End":
          setFocusIdx(normalized.length - 1);
          break;
        case "Enter":
          if (onElementClick) {
            const slide = normalized[focusIdx];
            const idx = Number(slide?.slide_index) > 0 ? Number(slide.slide_index) : focusIdx + 1;
            onElementClick({ slideIndex: idx, elementPath: "title" });
          } else {
            handled = false;
          }
          break;
        default:
          handled = false;
      }
      if (handled) event.preventDefault();
    },
    [focusIdx, normalized, onElementClick]
  );

  if (normalized.length === 0) {
    return (
      <div className={className || "space-y-2"}>
        <p className="text-xs text-[var(--text-muted)]">No slide JSON available yet. Generate a deck first.</p>
      </div>
    );
  }

  const focused = normalized[focusIdx];
  const focusedDisplayIdx =
    Number(focused?.slide_index) > 0 ? Number(focused.slide_index) : focusIdx + 1;

  return (
    <div
      ref={mainRef}
      className={className || "flex h-full min-h-0 flex-col gap-3 md:flex-row"}
      role="region"
      aria-label="Deck preview"
    >
      <div
        ref={railRef}
        role="listbox"
        aria-label="Slide thumbnails"
        aria-activedescendant={`deck-thumb-${focusIdx}`}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="flex max-h-[480px] w-full shrink-0 flex-col gap-1 overflow-auto rounded border border-[var(--surface-border)] bg-white p-1 md:max-h-[560px] md:w-48"
      >
        {normalized.map((slide, idx) => {
          const displayIdx = Number(slide?.slide_index) > 0 ? Number(slide.slide_index) : idx + 1;
          const title = String(slide?.title || `Slide ${displayIdx}`).trim();
          const kind = String(slide?.slide_type || "bullets");
          const active = idx === focusIdx;
          const busy = slideRegenerateBusyIndex === displayIdx;
          return (
            <button
              key={`deck-thumb-${idx}`}
              id={`deck-thumb-${idx}`}
              type="button"
              role="option"
              aria-selected={active}
              onClick={() => setFocusIdx(idx)}
              className={`flex flex-col gap-0.5 rounded border px-2 py-1.5 text-left text-2xs transition-colors ${
                active
                  ? "border-[var(--primary-900)] bg-[var(--primary-100)] text-[var(--text-default)]"
                  : "border-[var(--surface-border)] text-[var(--text-muted)] hover:bg-[var(--surface-muted)]"
              }`}
            >
              <span className="flex items-center justify-between gap-1">
                <span className="font-semibold">Slide {displayIdx}</span>
                <span className="truncate text-[10px] uppercase tracking-wide opacity-70">{kind}</span>
              </span>
              <span className="truncate text-[11px] leading-tight">{title}</span>
              {busy ? (
                <span className="text-[10px] text-[var(--info)]">Regenerating…</span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div
        className="min-h-0 flex-1 overflow-auto rounded border border-[var(--surface-border)] bg-white p-2"
        aria-label={`Slide ${focusedDisplayIdx} preview`}
      >
        <div className="mb-2 flex items-center justify-between">
          <p className="text-2xs text-[var(--text-muted)]">
            Slide {focusedDisplayIdx} of {normalized.length} · {String(focused?.slide_type || "bullets")}
          </p>
          <p className="text-[10px] text-[var(--text-muted)]">
            ↑/↓ navigate · click any element to regenerate
          </p>
        </div>
        <DeckCanvas slides={[focused]} onElementClick={onElementClick} />
      </div>
    </div>
  );
}
