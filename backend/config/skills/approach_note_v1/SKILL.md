---
id: approach_note_v1
domain: Strategy & Ops
display_name: Approach Note Specialist
output_types:
- docx
- narrative
version: 1.0.0
description: Creates structured Approach Notes that define how a problem should be
  solved and why. Use when users ask for an approach note, methodology note, POV,
  thinking note, or strategic framework document.
use_when: the user asks to write or draft an approach note, methodology note, POV,
  method paper, approach paper, diagnostic note, strategic framework document, or
  asks how we should approach this problem
tools:
- retrieve_context
- memory_lookup
- qa_validator
workflow_steps:
- Identify use context (pre-proposal, client-facing, or practice development)
- Bound the problem statement and gather constraints, knowns, and unknowns
- Draft all 7 sections with falsifiable hypothesis and method-specific approach
- Run QA checks for rigor, non-generic language, and decision-oriented conclusion
feedback_loop:
- Check section completeness
- Validate hypothesis quality and evidence strength
- Strengthen Section 02, Section 05, and limitations where weak
- Finalize output with a clear decision request
freedom_level: medium
quality_thresholds:
  docx: 0.9
  narrative: 0.9
acceptance_checks:
- All 7 Approach Note sections are present
- Hypothesis is falsifiable and causal (not a task list)
- Standard approach failure mode is explicit and non-trivial
- At least 2 falsification signals are listed
- Conclusion requests a specific decision or action
default_representation: docx
companion_files:
- ./deloitte_approach_note_leading_practices.md
source_url: approach-note.skill
sample_instruction: Draft a client-facing approach note for finance transformation
  that argues why the standard assessment model fails, states a falsifiable hypothesis,
  and proposes a method-specific plan with risks and decision request.
custom: false
---

Use the approach-note method from approach-note.skill. Produce an argument-led Approach Note using the 7 required sections: Problem Framing, Why the Standard Approach Fails, Our Hypothesis, The Proposed Approach, What We Will Learn and When, Risks and Intellectual Limitations, and Conclusion with Decision Request. Enforce hypothesis-first writing, explicit evidence level, and epistemic honesty. Distinguish this from sales proposals and status reporting. Default to DOCX-oriented structure, with structured markdown fallback when DOCX is not requested.

Strengthen consulting rigor using `deloitte_approach_note_leading_practices.md` (evidence grading, decision ask, distinction from BRD/proposal). Optional QA: `python scripts/check_approach_sections.py` on markdown drafts.
