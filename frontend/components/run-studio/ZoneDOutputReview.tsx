"use client";

export function ZoneDOutputReview({ artifacts }: { artifacts: Record<string, unknown> | null }) {
  const processMapMermaid = typeof artifacts?.process_map_mermaid === "string" ? artifacts.process_map_mermaid : "";
  const processMapDrawio = typeof artifacts?.drawio_xml === "string" ? artifacts.drawio_xml : "";
  const raciMarkdown = typeof artifacts?.raci_markdown === "string" ? artifacts.raci_markdown : "";
  const raciHtml = typeof artifacts?.raci_html === "string" ? artifacts.raci_html : "";
  const hasRaciXlsx = typeof artifacts?.raci_xlsx_base64 === "string" && artifacts.raci_xlsx_base64.length > 0;
  const hasXlsx = typeof artifacts?.xlsx_base64 === "string" && artifacts.xlsx_base64.length > 0;
  const hasPdf = typeof artifacts?.pdf_base64 === "string" && artifacts.pdf_base64.length > 0;
  const hasDocx = typeof artifacts?.docx_base64 === "string" && artifacts.docx_base64.length > 0;
  const hasPptx = typeof artifacts?.pptx_base64 === "string" && artifacts.pptx_base64.length > 0;
  const typed = Array.isArray(artifacts?.typed_outputs) ? artifacts.typed_outputs : [];

  const panel =
    "rounded-md border border-[var(--surface-border-strong)] bg-[var(--surface-muted)] p-2 text-[var(--text-default)]";

  return (
    <div className="deloitte-surface p-4">
      <h3 className="text-lg font-semibold text-[var(--text-default)]">Output Review</h3>
      <p className="mt-2 text-sm text-[var(--text-caption)]">
        {artifacts ? "Artifacts available for review and download." : "No finalized artifacts yet."}
      </p>
      {artifacts ? (
        <div className="mt-3 space-y-3 text-xs">
          <div className={panel}>
            <p className="font-medium">Generated output representations</p>
            {typed.length ? (
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {typed.map((item: any, idx) => (
                  <li key={`typed-${idx}`}>
                    {String(item.output_type ?? "output")} - {String(item.representation ?? "unknown")}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[var(--text-caption)]">No typed output metadata found yet.</p>
            )}
          </div>

          <div className={panel}>
            <p className="font-medium">Process map preview</p>
            {processMapMermaid ? (
              <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap rounded border border-[var(--surface-border)] bg-[var(--surface-default)] p-2">
                {processMapMermaid}
              </pre>
            ) : processMapDrawio ? (
              <p className="mt-1 text-[var(--text-muted)]">draw.io XML generated and available for download/editor.</p>
            ) : (
              <p className="mt-1 font-medium text-[var(--error)]">Process map output missing.</p>
            )}
          </div>

          <div className={panel}>
            <p className="font-medium">RACI preview</p>
            {raciMarkdown ? (
              <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap rounded border border-[var(--surface-border)] bg-[var(--surface-default)] p-2">
                {raciMarkdown}
              </pre>
            ) : raciHtml ? (
              <p className="mt-1 text-[var(--text-muted)]">RACI HTML generated and available for download.</p>
            ) : hasRaciXlsx ? (
              <p className="mt-1 text-[var(--text-muted)]">RACI XLSX generated and available for download.</p>
            ) : (
              <p className="mt-1 font-medium text-[var(--error)]">RACI output missing.</p>
            )}
          </div>

          <div className={panel}>
            <p className="font-medium">Document outputs</p>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              <li>DOCX: {hasDocx ? "generated" : "not generated"}</li>
              <li>PPTX: {hasPptx ? "generated" : "not generated"}</li>
              <li>XLSX: {hasXlsx || hasRaciXlsx ? "generated" : "not generated"}</li>
              <li>PDF: {hasPdf ? "generated" : "not generated"}</li>
            </ul>
          </div>
        </div>
      ) : null}
    </div>
  );
}
