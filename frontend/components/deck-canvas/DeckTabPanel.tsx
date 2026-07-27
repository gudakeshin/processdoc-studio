"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DeckCanvas, type CanvasSlide } from "./DeckCanvas";

export type DeckTabPanelProps = {
  slides: CanvasSlide[];
  onElementClick?: (args: { slideIndex: number; elementPath: string }) => void;
  slideRegenerateBusyIndex?: number | null;
  /** Base64 of soffice-rendered deck.pdf — preferred fidelity preview when present. */
  deckPdfBase64?: string | null;
  className?: string;
};

/**
 * Rich deck viewer used inside the run studio "Deck" tab.
 *
 * - Left rail: compact thumbnails (slide index + type + title) with keyboard nav.
 * - Main pane: fidelity PDF (soffice→PDF of output.pptx) when available, else
 *   interactive DeckCanvas. Toggle lets reviewers switch modes.
 * - Clicking any element in canvas mode fires `onElementClick`.
 */
export function DeckTabPanel({
  slides,
  onElementClick,
  slideRegenerateBusyIndex,
  deckPdfBase64,
  className,
}: DeckTabPanelProps) {
  const normalized = useMemo(() => {
    if (!Array.isArray(slides)) return [] as CanvasSlide[];
    return slides.filter((s): s is CanvasSlide => Boolean(s) && typeof s === "object");
  }, [slides]);

  const hasPdf = Boolean(deckPdfBase64 && deckPdfBase64.length > 32);
  const [mode, setMode] = useState<"fidelity" | "interactive">(hasPdf ? "fidelity" : "interactive");
  const [focusIdxState, setFocusIdx] = useState(0);
  const focusIdx = Math.min(focusIdxState, Math.max(0, normalized.length - 1));
  const railRef = useRef<HTMLDivElement | null>(null);
  const mainRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (hasPdf) setMode("fidelity");
  }, [hasPdf]);

  const pdfUrl = useMemo(() => {
    if (!hasPdf || !deckPdfBase64) return null;
    return `data:application/pdf;base64,${deckPdfBase64}`;
  }, [hasPdf, deckPdfBase64]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (normalized.length === 0 || mode === "fidelity") return;
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
    [normalized, focusIdx, onElementClick, mode]
  );

  if (normalized.length === 0 && !hasPdf) {
    return (
      <p className="text-sm text-[var(--text-muted)]">
        Deck preview becomes available after the PPTX slide JSON is generated.
      </p>
    );
  }

  const focused = normalized[focusIdx];

  return (
    <div
      className={className}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      role="region"
      aria-label="Deck preview"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded border border-[var(--surface-border)] text-2xs">
          <button
            type="button"
            className={`px-2 py-1 ${mode === "fidelity" ? "bg-[var(--surface-raised)] font-semibold" : ""}`}
            disabled={!hasPdf}
            onClick={() => setMode("fidelity")}
            title={hasPdf ? "Office-faithful PDF from output.pptx" : "PDF not available yet"}
          >
            Fidelity (PDF)
          </button>
          <button
            type="button"
            className={`px-2 py-1 ${mode === "interactive" ? "bg-[var(--surface-raised)] font-semibold" : ""}`}
            onClick={() => setMode("interactive")}
          >
            Interactive
          </button>
        </div>
        {mode === "fidelity" ? (
          <span className="text-2xs text-[var(--text-muted)]">
            Rendered from output.pptx via LibreOffice — pixel-faithful to the download.
          </span>
        ) : (
          <span className="text-2xs text-[var(--text-muted)]">
            Click an element to queue a targeted slide rewrite.
          </span>
        )}
      </div>

      {mode === "fidelity" && pdfUrl ? (
        <iframe
          title="Deck fidelity preview"
          src={pdfUrl}
          className="min-h-[480px] w-full flex-1 rounded border border-[var(--surface-border)] bg-white"
        />
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 md:flex-row">
          <div
            ref={railRef}
            className="max-h-[480px] w-full shrink-0 space-y-1 overflow-auto md:w-48"
            role="listbox"
            aria-label="Slide thumbnails"
          >
            {normalized.map((slide, i) => {
              const title = String(slide.title || `Slide ${i + 1}`);
              const type = String(slide.slide_type || "slide");
              const selected = i === focusIdx;
              const busy = slideRegenerateBusyIndex === i + 1;
              return (
                <button
                  key={`thumb-${i}`}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={`w-full rounded border px-2 py-1.5 text-left text-2xs ${
                    selected
                      ? "border-[var(--accent-blue)] bg-[var(--surface-raised)]"
                      : "border-[var(--surface-border)]"
                  }`}
                  onClick={() => setFocusIdx(i)}
                >
                  <span className="font-semibold text-[var(--text-default)]">
                    {i + 1}. {type}
                    {busy ? "…" : ""}
                  </span>
                  <span className="mt-0.5 block truncate text-[var(--text-muted)]">{title}</span>
                </button>
              );
            })}
          </div>
          <div ref={mainRef} className="min-h-0 min-w-0 flex-1 overflow-auto">
            {focused ? (
              <DeckCanvas slides={[focused]} onElementClick={onElementClick} />
            ) : (
              <p className="text-sm text-[var(--text-muted)]">Select a slide.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
