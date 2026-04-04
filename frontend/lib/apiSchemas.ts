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

