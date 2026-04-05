/**
 * Cowork-style Run Studio: optional hide of guided decision prompts (see RunStudioView).
 * Keep logic here so it can be unit-tested without mounting the full chat UI.
 */
export function showGuidedDecisionsSection(
  showGuidedDecisions: boolean,
  decisionPromptsLength: number,
): boolean {
  return showGuidedDecisions && decisionPromptsLength > 0;
}
