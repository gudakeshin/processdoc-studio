import { z } from "zod";

export const runEventItemSchema = z.object({
  id: z.number(),
  event_type: z.string(),
  payload: z.record(z.string(), z.unknown()),
});

export const runEventsResponseSchema = z.object({
  run_id: z.string().optional(),
  status: z.string(),
  plan: z.unknown().optional(),
  items: z.array(runEventItemSchema),
});

export type RunEventsResponseValidated = z.infer<typeof runEventsResponseSchema>;

/**
 * Artifact bag keys the Run Studio reads; unknown keys flow through untyped.
 * Mirrors RunArtifactsResponse.artifacts in backend/app/api/run_artifacts.py.
 */
export type RunArtifactsBag = {
  plan?: unknown;
  plan_payload?: { project_id?: string } & Record<string, unknown>;
  visual_qa_report?: unknown;
  assembled_context?: unknown;
  process_model?: unknown;
  pptx_slides?: unknown;
  qa_report?: unknown;
  guardrail_report?: unknown;
  handoff_bundle_available?: unknown;
  ready_downloads?: unknown[];
  output_filenames?: Record<string, string>;
  leading_practices?: string[];
  memory_summary?: { non_negotiables?: string[] } & Record<string, unknown>;
  narrative_md?: string;
  sop_markdown?: string;
  raci_markdown?: string;
  raci_html?: string;
  deck_html?: string;
  drawio_xml?: string;
  process_map_mermaid?: string;
  docx_base64?: string;
  pdf_base64?: string;
  xlsx_base64?: string;
  deck_pdf_base64?: string;
  raci_xlsx_base64?: string;
} & Record<string, unknown>;

export const runArtifactsResponseSchema = z.looseObject({
  run_id: z.string().optional(),
  project_id: z.string().optional(),
  status: z.string().optional(),
  instruction: z.string().optional(),
  output_types: z.array(z.string()).optional(),
  custom_output_types: z.array(z.string()).optional(),
  output_type_representations: z.record(z.string(), z.string()).optional(),
  artifacts: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const deadLetterItemSchema = z.looseObject({
  id: z.string().optional(),
  run_id: z.string().optional(),
  project_id: z.string().optional(),
  reason: z.string().optional(),
  status: z.string().optional(),
  replay_attempts: z.number().optional(),
  replay_blocked_reason: z.string().optional(),
});

export type DeadLetterItem = z.infer<typeof deadLetterItemSchema>;

export const deadLetterResponseSchema = z.looseObject({
  project_id: z.string().optional(),
  items: z.array(deadLetterItemSchema).optional(),
});

