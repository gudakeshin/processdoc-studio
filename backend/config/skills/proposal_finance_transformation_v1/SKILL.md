---
id: proposal_finance_transformation_v1
quality_contract_id: proposal_finance_v1
domain: Finance Transformation
display_name: Finance Transformation Proposal Specialist
output_types:
- docx
- pptx
version: 1.1.0
description: Creates winning Finance Transformation proposals and pitch decks for
  consulting engagements including FP&A transformation, month-end close
  acceleration, finance operating model redesign, and CFO advisory.
use_when: the user asks to draft a finance transformation proposal, RFP response,
  capability statement, or CFO pitch deck
tools:
- retrieve_context
- memory_lookup
- qa_validator
workflow_steps:
- Identify Finance Transformation sub-type and target format (PPTX or DOCX)
- Build problem-led narrative (situation, insight, hypothesis, approach, why us)
- Draft required sections with CFO metrics, value levers, and risk mitigations
- Validate with quality checklist and anti-pattern guardrails before finalizing
feedback_loop:
- Check 10-section completeness
- Validate FT specificity and benchmark usage
- Strengthen CFO-value articulation and risk register quality
- Finalize output in requested format
freedom_level: medium
quality_thresholds:
  docx: 0.92
  pptx: 0.92
acceptance_checks:
- All 10 proposal sections are present and labeled
- Finance Transformation sub-type is explicitly identified and consistent throughout
- Executive summary opens with the client finance problem, not firm credentials
- Client understanding section is benchmark-anchored and client-specific
- Commercial/value summary uses CFO-readable metrics
default_representation: pptx
companion_files:
- ./README.md
- ./references/story-arc.md
- ./references/cfo-metrics.md
- ./references/anti-patterns.md
- ./references/benchmarks.md
- ./references/approach-template.md
- ./references/risk-register.md
- ./templates/proposal-outline.md
- ./templates/pitch-deck-outline.md
- ./templates/value-case-template.md
- ./templates/case-patterns.md
- ./templates/quality-checklist.md
- ./deloitte_proposal_leading_practices.md
source_url: proposal-finance-transformation.skill
sample_instruction: Draft a Finance Transformation proposal for close acceleration
  and FP&A redesign, including a PPTX pitch deck and a DOCX narrative variant with
  CFO-centric value metrics.
custom: false
---

# Finance Transformation Proposal Skill

Produces CFO-facing proposals and pitch decks for finance transformation engagements. Use problem-led storytelling, quantified value articulation, and structured risk management to build credible, compelling narratives.

## Progressive Reference Loading Map

Load references by engagement type instead of loading the entire library at once:
- **Close acceleration** -> `references/cfo-metrics.md`, `references/approach-template.md`, `templates/value-case-template.md`
- **FP&A transformation** -> `references/cfo-metrics.md`, `references/benchmarks.md`, `templates/proposal-outline.md`
- **Operating model / GBS** -> `references/story-arc.md`, `references/risk-register.md`, `templates/pitch-deck-outline.md`
- **RFP / capability statement** -> `templates/proposal-outline.md`, `templates/quality-checklist.md`, `references/anti-patterns.md`

## What this skill creates

**DOCX Proposal** (50-80 pages)
- Comprehensive narrative with ten-section framework
- Problem statement, benchmarks, detailed approach, risks, case patterns
- Suitable for RFP responses, board submissions, detailed sell

**PPTX Pitch Deck** (12-18 slides)
- Executive-focused slide deck for CFO/CEO meeting
- Problem, hypothesis, approach, value case, risks
- Suitable for first presentations, executive selling moments

**Hybrid** (PPTX + appendix DOCX)
- Pitch deck for meeting + detailed narrative for follow-up review

## Core methodology

Finance transformation proposals follow a **problem-led story arc**:

1. **Client situation** - Finance operating challenge (close calendar, forecast reliability, FTE cost, control incidents)
2. **Insight** - What is misunderstood or underestimated about root cause
3. **Hypothesis** - What will move the needle (1-2 crisp sentences)
4. **What we will do** - Phased approach, decision gates, client commitments
5. **Why us** - Evidence of comparable outcomes (proportional, not dominant)

## Key principles

**Use metrics the CFO tracks** - Close calendar (days), forecast accuracy (%), DSO/DPO (days), finance cost per revenue (%), control metrics (issues, rework %, manual journal %)

**Separate outcomes from activities** - Outcomes are business results; activities are workstreams

**Articulate dependencies** - Call out what client must provide: data quality, SME availability, governance, IT release calendars

**Quantify the value case** - Use 3+ levers: cost reduction, working capital, revenue, risk

## Ten-section framework

| Section | Mandatory? | Content |
|---------|-----------|---------|
| **Executive summary** | Yes | Client problem + headline outcomes |
| **Client understanding** | Yes | Facts, benchmarks, constraints |
| **Approach** | Yes | Phases, governance, decision gates |
| **Solution/capabilities** | Usually | What changes (process, org, data, tech) |
| **Delivery** | Usually | Team shape, cadence, locations, PMO |
| **Value/benefits** | Yes | Quantified outcomes (cost, working capital, risk) |
| **Risks** | Yes | Finance-specific risks + mitigations + ownership |
| **Case patterns** | Usually | Anonymized comparable outcomes |
| **Commercial appendix** | Optional | Pricing, terms, payment schedule (if RFP) |
| **Team/credentials** | Optional | Bios, project experience |

For **pitch decks**: Compress to sections 1, 2, 3, 6, 7 + 2-3 case patterns (12-18 slides).  
For **full proposals**: Include sections 1-8 (all mandatory + usually).

## What NOT to do

See [anti-patterns.md](references/anti-patterns.md) for detailed examples. Key anti-patterns:
- [X] Generic digital-transformation language without finance specificity
- [X] Value cases with only cost takeout (no working capital, revenue, risk angles)
- [X] Credential inflation before problem is established
- [X] Assuming technology alone solves the problem

## Quick-start

**Step 1: Define the situation**
- What is the finance operating challenge? (close calendar, FP&A accuracy, GBS model, etc.)
- What is the current state? (benchmarks: see [cfo-metrics.md](references/cfo-metrics.md))
- What is the root cause? (data, process, organization, incentives)

**Step 2: Build the narrative**
- Situation -> Insight -> Hypothesis (the story)
- See [story-arc.md](references/story-arc.md) for detailed methodology

**Step 3: Select output format**
- Pitch deck -> Use [pitch-deck-outline.md](templates/pitch-deck-outline.md) (12-18 slides)
- Full proposal -> Use [proposal-outline.md](templates/proposal-outline.md) (10 sections)
- Hybrid -> Start with pitch, append detailed approach

**Step 4: Articulate value**
- Pick 2-3 value levers from [value-case-template.md](templates/value-case-template.md)
- Use benchmarks from [cfo-metrics.md](references/cfo-metrics.md) if client numbers are unknown
- Use ranges, not point estimates; label as [illustrative]

**Step 5: Risk management**
- Identify 4+ finance-specific risks (see [risk-register.md](references/risk-register.md))
- For each: impact, mitigation, owner
- Avoid generic communication-risk statements

**Step 6: Quality check**
- Run final checklist (see [quality-checklist.md](templates/quality-checklist.md))

## Reference materials

**Methodology and frameworks:**
- [Story arc](references/story-arc.md) - Five-step narrative structure
- [CFO metrics decision tree](references/cfo-metrics.md) - Which metrics to use when
- [Anti-patterns](references/anti-patterns.md) - What to avoid with examples
- [Benchmarks](references/benchmarks.md) - Illustrative ranges for common metrics

**Approach and value:**
- [Phased approach template](references/approach-template.md) - Standard 4-phase delivery structure
- [Risk register guide](references/risk-register.md) - Finance-specific risks and mitigations

**Templates and examples:**
- [Proposal outline](templates/proposal-outline.md) - Section-by-section structure for DOCX
- [Pitch deck outline](templates/pitch-deck-outline.md) - Slide structure for PPTX
- [Value case template](templates/value-case-template.md) - Quantified benefits format
- [Case patterns](templates/case-patterns.md) - Anonymized examples by engagement type
- [Quality checklist](templates/quality-checklist.md) - Pre-finalization verification

Align narrative structure and value hygiene with `deloitte_proposal_leading_practices.md` (client-first story arc, CFO metrics, risk register, anti-patterns). Optional QA: `python scripts/check_proposal_signals.py` on markdown drafts.
