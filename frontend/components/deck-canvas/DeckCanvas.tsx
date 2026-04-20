"use client";

import React from "react";

type GenericRow = Record<string, unknown>;

export type CanvasSlide = {
  slide_id?: string;
  slide_index?: number;
  title?: string;
  subtitle?: string;
  slide_type?: string;
  bullets?: string[];
  stat_cards?: GenericRow[];
  column_cards?: GenericRow[];
  stack_layers?: GenericRow[];
  table?: {
    headers?: string[];
    rows?: string[][];
  };
};

export type DeckCanvasProps = {
  slides: CanvasSlide[];
  className?: string;
  onElementClick?: (args: { slideIndex: number; elementPath: string }) => void;
};

function asText(v: unknown): string {
  return String(v ?? "").trim();
}

function SlideTypeBody({
  slide,
  slideIndex,
  onElementClick,
}: {
  slide: CanvasSlide;
  slideIndex: number;
  onElementClick?: (args: { slideIndex: number; elementPath: string }) => void;
}) {
  const click = (elementPath: string) => onElementClick?.({ slideIndex, elementPath });
  const t = asText(slide.slide_type || "bullets");
  if (t === "title") {
    return (
      <div className="space-y-2">
        <h2
          className="cursor-pointer text-xl font-semibold"
          data-element-path="title"
          onClick={() => click("title")}
        >
          {asText(slide.title || "Untitled")}
        </h2>
        <p
          className="cursor-pointer text-sm text-[var(--text-muted)]"
          data-element-path="subtitle"
          onClick={() => click("subtitle")}
        >
          {asText(slide.subtitle || "Executive overview")}
        </p>
      </div>
    );
  }
  if (t === "stat_cards") {
    const cards = Array.isArray(slide.stat_cards) ? slide.stat_cards : [];
    return (
      <div className="grid gap-2 md:grid-cols-3">
        {cards.map((c, i) => (
          <div
            key={`stat-${i}`}
            className="cursor-pointer rounded border border-[var(--surface-border)] p-2"
            data-element-path={`stat_cards[${i}]`}
            onClick={() => click(`stat_cards[${i}]`)}
          >
            <p className="text-lg font-semibold">{asText(c.stat || "—")}</p>
            <p className="text-xs text-[var(--text-muted)]">{asText(c.label || "")}</p>
          </div>
        ))}
      </div>
    );
  }
  if (t === "column_cards") {
    const cards = Array.isArray(slide.column_cards) ? slide.column_cards : [];
    return (
      <div className="grid gap-2 md:grid-cols-3">
        {cards.map((c, i) => (
          <div
            key={`col-${i}`}
            className="cursor-pointer rounded border border-[var(--surface-border)] p-2"
            data-element-path={`column_cards[${i}]`}
            onClick={() => click(`column_cards[${i}]`)}
          >
            <p className="text-sm font-semibold">{asText(c.heading || `Column ${i + 1}`)}</p>
            <p className="mt-1 text-xs text-[var(--text-muted)]">{asText(c.body || "")}</p>
          </div>
        ))}
      </div>
    );
  }
  if (t === "stack_layers") {
    const layers = Array.isArray(slide.stack_layers) ? slide.stack_layers : [];
    return (
      <div className="space-y-1.5">
        {layers.map((layer, i) => (
          <div
            key={`layer-${i}`}
            className="cursor-pointer rounded border border-[var(--surface-border)] p-2"
            data-element-path={`stack_layers[${i}]`}
            onClick={() => click(`stack_layers[${i}]`)}
          >
            <p className="text-sm font-semibold">{asText(layer.label || `Layer ${i + 1}`)}</p>
            <p className="text-xs text-[var(--text-muted)]">{asText(layer.description || "")}</p>
          </div>
        ))}
      </div>
    );
  }
  if (t === "table") {
    const headers = Array.isArray(slide.table?.headers) ? slide.table?.headers : [];
    const rows = Array.isArray(slide.table?.rows) ? slide.table?.rows : [];
    return (
      <div className="overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th
                  key={`h-${i}`}
                  className="cursor-pointer border border-[var(--surface-border)] px-2 py-1 text-left"
                  data-element-path={`table.headers[${i}]`}
                  onClick={() => click(`table.headers[${i}]`)}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`r-${i}`}>
                {r.map((cell, j) => (
                  <td
                    key={`c-${i}-${j}`}
                    className="cursor-pointer border border-[var(--surface-border)] px-2 py-1"
                    data-element-path={`table.rows[${i}][${j}]`}
                    onClick={() => click(`table.rows[${i}][${j}]`)}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (t === "section_divider") {
    return (
      <div className="rounded bg-[var(--surface-muted)] p-4 text-center">
        <h2 className="cursor-pointer text-xl font-semibold" onClick={() => click("title")}>
          {asText(slide.title || "Section")}
        </h2>
        <p className="cursor-pointer text-sm text-[var(--text-muted)]" onClick={() => click("subtitle")}>
          {asText(slide.subtitle || "")}
        </p>
      </div>
    );
  }

  const bullets = Array.isArray(slide.bullets) ? slide.bullets : [];
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {bullets.map((b, i) => (
        <li
          key={`b-${i}`}
          className="cursor-pointer"
          data-element-path={`bullets[${i}]`}
          onClick={() => click(`bullets[${i}]`)}
        >
          {b}
        </li>
      ))}
    </ul>
  );
}

export function DeckCanvas({ slides, className, onElementClick }: DeckCanvasProps) {
  const resolved = Array.isArray(slides) ? slides : [];
  return (
    <div className={className || "space-y-3"}>
      {resolved.map((slide, i) => {
        const index = Number(slide.slide_index || i + 1);
        const title = asText(slide.title || `Slide ${index}`);
        return (
          <section
            key={asText(slide.slide_id || `slide-${index}`)}
            className="rounded-lg border border-[var(--surface-border)] bg-white p-3"
            data-slide-index={index}
          >
            <header className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold text-[var(--text-muted)]">Slide {index}</p>
              <p className="truncate text-xs text-[var(--text-muted)]">{asText(slide.slide_type || "bullets")}</p>
            </header>
            {slide.slide_type !== "title" ? (
              <h3
                className="mb-2 cursor-pointer text-sm font-semibold"
                data-element-path="title"
                onClick={() => onElementClick?.({ slideIndex: index, elementPath: "title" })}
              >
                {title}
              </h3>
            ) : null}
            <SlideTypeBody slide={slide} slideIndex={index} onElementClick={onElementClick} />
          </section>
        );
      })}
    </div>
  );
}

