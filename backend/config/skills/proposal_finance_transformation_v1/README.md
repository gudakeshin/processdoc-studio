# Finance Transformation Proposal Skill — Complete Resource Package

**Version:** 1.0  
**Date:** March 31, 2026  
**Status:** Production-ready

---

## Overview

This is a complete, production-grade Anthropic Agent Skill for creating Finance Transformation proposals and pitch decks. It includes:

- ✅ YAML-compliant SKILL.md with optimized description for Claude discovery
- ✅ 6 comprehensive reference files with methodology, benchmarks, and templates
- ✅ 3 complete template files ready to customize for client proposals
- ✅ Skill evaluation document (how this skill compares to Anthropic best practices)
- ✅ Refactored example (how to structure production skills)

---

## File Structure

```
proposal-finance-transformation/
│
├── SKILL.md                          [Main skill file — READ THIS FIRST]
│
├── references/                        [Detailed methodology & frameworks]
│   ├── story-arc.md                   Five-step narrative structure with examples
│   ├── cfo-metrics.md                 Which CFO metrics by engagement type
│   ├── anti-patterns.md               What to avoid (with concrete examples)
│   ├── benchmarks.md                  Illustrative ranges for common metrics
│   ├── approach-template.md           Standard 4-phase delivery plan
│   └── risk-register.md               Finance-specific risks & mitigations
│
├── templates/                         [Ready-to-customize proposal templates]
│   ├── proposal-outline.md            Full 50-80 page proposal structure
│   ├── pitch-deck-outline.md          12-18 slide executive presentation
│   ├── value-case-template.md         Quantified benefits formats
│   ├── case-patterns.md               Anonymized engagement examples
│   └── quality-checklist.md           Pre-finalization verification checklist
│
└── README.md                          [This file]
```

---

## Quick Start

### For a first-time user:

1. **Read SKILL.md** (10 min)
   - Understand the core methodology
   - Review the ten-section framework
   - Identify which templates you need

2. **Choose your output type:**
   - **Pitch deck?** → Start with `templates/pitch-deck-outline.md`
   - **Full proposal?** → Start with `templates/proposal-outline.md`
   - **Value case component?** → Start with `templates/value-case-template.md`

3. **Use the reference files as needed:**
   - **Need story structure?** → `references/story-arc.md`
   - **Need CFO metrics?** → `references/cfo-metrics.md`
   - **Need risk mitigation examples?** → `references/risk-register.md`

4. **Finalize with the quality checklist:**
   - Run `templates/quality-checklist.md` before sending to client

### For Claude (Anthropic Agent):

Load this skill into Claude and say:
- "Draft a close acceleration proposal for a $2B specialty chemicals manufacturer"
- "Create a pitch deck for a finance operating model transformation"
- "Help me build a value case for FP&A transformation at a SaaS company"

Claude will navigate the references and templates automatically based on engagement type.

---

## File Descriptions

### SKILL.md (Main Skill File)

**Purpose:** Entry point for the skill. Contains YAML frontmatter, core methodology overview, quick-start guide, and navigation to all references and templates.

**When to use:** Always start here. Every user (human or Claude) should read this first.

**Key sections:**
- What this skill creates (DOCX vs. PPTX vs. hybrid)
- Core methodology (problem-led story arc)
- Key principles (CFO metrics, outcome vs. activity separation)
- Ten-section framework (mandatory vs. optional sections)
- Quick-start guide (6-step process)
- Reference navigation (what to read when)

**Customization:** YAML metadata (name, description) are production-ready. Content is generic by design; customize in referenced files.

---

### References (Detailed Methodology)

#### story-arc.md

**Purpose:** Detailed explanation of the five-step narrative structure.

**Contains:**
- Full guidance on each step (Situation, Insight, Hypothesis, Approach, Why us)
- Examples by engagement type (close, FP&A, GBS, treasury)
- Red flags (what doesn't work)
- Template language for each step

**When to use:** When building the narrative for a proposal. Provides foundation for problem statement and approach design.

**Length:** ~5 pages. Comprehensive but still concise.

---

#### cfo-metrics.md

**Purpose:** Decision tree for selecting CFO-relevant metrics by engagement type.

**Contains:**
- Metrics for close acceleration (close calendar, GL recon %, manual journals, control findings)
- Metrics for FP&A transformation (forecast accuracy, cycle time, scenario turnaround)
- Metrics for GBS/operating model (finance cost %, headcount per $B, GBS penetration, transactional FTE %)
- Metrics for working capital (DSO, DPO, DIO, cash cycle)
- Metrics for treasury (cash visibility, automation %, banking optimization)
- Benchmarking guidance (where to source benchmarks, how to use ranges)
- Red flags (metrics to avoid)

**When to use:** When building the client understanding section or value case. Ensures you're measuring what the CFO actually cares about.

**Length:** ~8 pages. Detailed decision tree with examples.

---

#### anti-patterns.md

**Purpose:** Concrete examples of what NOT to do, with explanations of why each fails and how to fix it.

**Contains:**
- 7 major anti-patterns with before/after examples:
  1. Generic "digital transformation" language
  2. Value case with only cost (no working capital/risk)
  3. Credential inflation before problem
  4. Tech-first solutions (assuming tech solves everything)
  5. Copy-paste boilerplate "global network" paragraphs
  6. Vague risk register
  7. Overselling timeline without contingency

**When to use:** As a quality check during proposal writing. If you catch yourself falling into any of these patterns, references to this file will help you fix it.

**Length:** ~10 pages. Each anti-pattern has detailed explanation + good/bad examples.

---

#### benchmarks.md

**Purpose:** Illustrative benchmark ranges for common finance metrics.

**Contains:**
- Tables for close acceleration, FP&A, GBS, working capital, treasury, control metrics
- Each table shows "Lagging," "Mature," and "Best-in-class" ranges
- Context notes for each metric (e.g., "varies by industry," "cloud systems enable faster achievement")
- How to use benchmarks in proposals (with templates)
- Important caveats about qualification and sourcing

**When to use:** When establishing the current-state problem or target-state opportunity. Provides defensible, illustrative benchmarks when client-specific data isn't available.

**Length:** ~10 pages. Detailed benchmark tables plus usage guidance.

---

#### approach-template.md

**Purpose:** Standard four-phase delivery structure (customizable by engagement type).

**Contains:**
- Phase 1: Diagnose & Design (Weeks 1-4) — current-state assessment, design
- Phase 2: Build & Configure (Weeks 5-10) — data remediation, system configuration, training prep
- Phase 3: Pilot & Stabilize (Weeks 11-14) — pilot close, refine, train full team
- Phase 4: Deploy & Transition (Weeks 15-17) — full go-live, support, handoff
- For each phase: Activities, deliverables, client commitments, decision gates
- Customization examples for GBS, FP&A, treasury engagements
- Decision gate criteria (go/no-go/proceed-with-modifications)

**When to use:** When defining the approach and timeline sections of your proposal. Provides realistic phasing and client commitment expectations.

**Length:** ~12 pages. Detailed per-phase guidance plus customization examples.

---

#### risk-register.md

**Purpose:** Finance-specific risks with real examples and concrete mitigations.

**Contains:**
- Close acceleration risks: Data quality, staff resistance, audit calendar, GL system constraints
- FP&A transformation risks: Model complexity, data availability
- GBS/operating model risks: GBS ramp-up delays, organizational change
- For each risk: Description, impact, probability, evidence, mitigation, owner, timeline
- Risk register template (copy-paste ready)
- Red flags (generic risks to avoid)

**When to use:** When building the risks section of your proposal. Ensures you identify finance-specific constraints and credible mitigations.

**Length:** ~12 pages. Detailed risk examples plus mitigation strategies.

---

### Templates (Ready-to-Customize)

#### proposal-outline.md

**Purpose:** Complete outline for 50-80 page formal proposal (DOCX).

**Contains:**
- Detailed section-by-section structure
- Placeholder content for each section (front matter, 8 core sections, appendices)
- What to include in each section (with examples)
- Customization guidance for different engagement types (FP&A, GBS, treasury)
- Appendix structure (scope, team bios, pricing, references)

**How to use:**
1. Copy the outline structure
2. Customize each section for your specific client/engagement
3. Reference the relevant files from `references/` for detailed content (e.g., use `story-arc.md` for "Client Understanding" section)
4. Fill in client-specific metrics, timelines, team names
5. Run the quality checklist before finalizing

**Length:** ~50 pages of outline (becomes 50-80 pages when filled in).

---

#### pitch-deck-outline.md

**Purpose:** Complete outline for 12-18 slide executive pitch deck (PPTX).

**Contains:**
- Slide-by-slide structure (Slides 1-18)
- Suggested content for each slide
- Visual guidance (what diagrams/charts help)
- Presentation tips (timing, talking points, Q&A preparation)
- Before/after case pattern example
- Delivery approach (5-7 min per section)

**How to use:**
1. Use this as a slide outline/storyboard
2. Create the PPTX deck with your preferred tool (PowerPoint, Keynote, Google Slides)
3. Reference `templates/case-patterns.md` for the case pattern slide
4. Reference `templates/value-case-template.md` for the value case slide
5. Run the quality checklist (Slides 15-18 sections) before presenting

**Length:** ~20 pages of detailed slide outline.

---

#### value-case-template.md

**Purpose:** Template for quantifying value across multiple levers.

**Contains:**
- Three-lever template (close + operations + risk)
- Multi-lever templates for GBS, FP&A, working capital
- For each lever: How to calculate value, realistic ranges, what makes it credible
- Value realization timeline (when each benefit is realized)
- How to present value in proposals (waterfall chart, table, narrative)
- Common mistakes to avoid (overstacking assumptions, tech-only value, one-time as annual)

**How to use:**
1. Identify your engagement type (close, GBS, FP&A, working capital)
2. Find the corresponding template in this file
3. Fill in current state, future state, value per lever
4. Add realization timeline
5. Calculate total ROI
6. Insert into "Value/Benefits" section of your proposal

**Length:** ~20 pages. Detailed value templates plus calculation guidance.

---

#### case-patterns.md

**Purpose:** Anonymized comparable engagement examples (proof of capability).

**Contains:**
- 4 detailed case patterns:
  1. Close acceleration — Manufacturing ($2B, 12→6 days, 4 months)
  2. Close acceleration — Technology ($1.5B, 10→5 days, 3 months)
  3. GBS transformation — Financial services ($5B, 0.9%→0.6% cost, 18 months)
  4. FP&A transformation — Mid-cap ($800M, 8→3 week cycle, 4 months)
- For each: Company profile, baseline metrics, approach, results, financial impact, key learning
- Templates for creating your own case patterns
- Anonymization guidelines
- How to use case patterns in proposals

**How to use:**
1. If you have comparable real client engagements, create case patterns following this structure
2. If you don't yet, reference the provided examples in your proposals
3. Customize the examples with your own metrics/timelines if similar engagements
4. Include 1-2 case patterns in full proposals; 1 case pattern in pitch decks
5. Reference relevant case pattern in the "Case Patterns" or "Why Us" sections

**Length:** ~25 pages. Detailed case pattern examples plus creation guidance.

---

#### quality-checklist.md

**Purpose:** Pre-finalization verification checklist (30-point quality gate).

**Contains:**
- Content quality checks (problem quantified, root cause specific, hypothesis crisp, value credible)
- Story arc & narrative checks (five steps present, no credential inflation, tone confident)
- Anti-patterns check (no generic language, no tech-first, no vague risks)
- Approach & delivery checks (phased plan clear, decision gates defined, team credible)
- Value case quality checks (quantified in dollars, ROI calculated, conservative assumptions)
- Risk management checks (4+ risks identified, finance-specific, concrete mitigations)
- Structure & formatting checks (executive summary self-contained, visuals support narrative, length appropriate)
- Case pattern checks (comparable company, specific metrics, anonymized)
- Tone & language checks (third-person, finance-specific terminology, no superlatives without evidence)
- Final read-through checks (5 CFO-perspective questions)
- Sign-off checklist (grammar, links, confidentiality, peer review)

**How to use:**
1. Run this checklist AFTER you've drafted the proposal/deck
2. Go through each item; mark ✓ if green, or note fix needed
3. Address all "fix if" items before finalizing
4. Have peer consultant review using this checklist
5. Only send to client when ALL items are checked ✓

**Length:** ~15 pages. Detailed checklist with examples and fixes.

---

## Supporting Documents (Included)

### skill-evaluation.md

**What it is:** Critical evaluation of the original Finance Transformation Proposal skill against Anthropic best practices.

**Contains:**
- 14 improvement opportunities (4 critical, 10 moderate)
- Detailed explanation of each issue + how to fix it
- Comparison table: Original vs. Refactored skill
- Recommended next steps (Phase 1-4 roadmap)

**Why included:** Shows how this skill was created and iterated based on Anthropic best practices. Use as reference for understanding skill design decisions.

**Length:** ~40 pages.

---

### skill-refactored-example.md

**What it is:** Concrete example of how to refactor a skill following Anthropic best practices.

**Contains:**
- Refactored SKILL.md example (150-line version with YAML, optimized description, progressive disclosure)
- Sample reference files (story-arc.md, cfo-metrics.md)
- Sample template (quality-checklist.md)
- Explanation of why each change was made
- Token efficiency comparison

**Why included:** Demonstrates the structure and thinking behind production-grade skill design. Use as reference if you want to iterate or extend this skill.

**Length:** ~30 pages.

---

## How to Use This Skill

### Option 1: Use with Anthropic Agent (Claude)

1. Upload this skill folder to Claude.ai or Claude API
2. Ask Claude to help with a finance transformation proposal:
   - "Draft a close acceleration proposal for a $2B specialty chemicals company"
   - "Create a pitch deck for a finance operating model transformation"
   - "Build a value case for FP&A transformation"

Claude will automatically navigate the skill files, pulling references and templates as needed.

---

### Option 2: Use as a Human Consultant

1. Read SKILL.md to understand the methodology
2. Choose your engagement type (close, FP&A, GBS, treasury)
3. Use the relevant templates (`proposal-outline.md` or `pitch-deck-outline.md`)
4. Pull methodology from references as you write each section
5. Run quality checklist before finalizing
6. Customize with your own case patterns and specific client data

---

### Option 3: Extend or Customize

This skill is designed to be extended:

1. **Add new case patterns** — Follow the template in `case-patterns.md`; add your own engagements
2. **Customize benchmarks** — Update `benchmarks.md` with your latest data or industry-specific ranges
3. **Add engagement type** — If this skill will be used for different engagement types (supply chain, HR transformation), create new phased approach templates in `references/`
4. **Integrate with your firm's branding** — Customize templates with your logo, color scheme, standard formatting

---

## Version History

**Version 1.0** (March 31, 2026)
- Initial production release
- Aligned with Anthropic Agent Skills best practices
- 6 reference files + 5 template files
- Covers close acceleration, FP&A, GBS, treasury, working capital engagements
- Quality checklist and anti-patterns included

---

## Support & Feedback

This skill is production-ready but designed for iteration:

- **Feedback:** If you use this skill and find sections that need clarification, email [contact]
- **New case patterns:** Send anonymized case patterns; we'll integrate into future versions
- **Industry-specific adaptations:** Let us know if you extend this for other engagement types

---

## License & Usage

This skill is proprietary to [Your Firm]. Use is restricted to authorized consultants within [Your Firm]. External distribution or use by outside parties is prohibited without written permission.

---

## Quick Reference

### Engagement Type Selection Guide

| Engagement | Key Metric | Duration | Reference Files | Template |
|---|---|---|---|---|
| **Close Acceleration** | Close calendar (days) | 4 months | story-arc, cfo-metrics, approach-template, risk-register | proposal-outline, pitch-deck-outline |
| **FP&A Transformation** | Forecast accuracy (%) | 4-6 months | cfo-metrics (FP&A section), value-case-template | proposal-outline, pitch-deck-outline |
| **GBS/Operating Model** | Finance cost (% revenue) | 6-18 months | approach-template (GBS example), risk-register (GBS section) | proposal-outline, pitch-deck-outline |
| **Working Capital** | Cash cycle (days) | 3-4 months | cfo-metrics (WC section), value-case-template (WC example) | proposal-outline, pitch-deck-outline |
| **Treasury** | Cash visibility (frequency) | 3-6 months | cfo-metrics (treasury section), approach-template (treasury example) | proposal-outline, pitch-deck-outline |

---

## File Size Reference

Total skill package: ~150 KB (all files combined)

Can be deployed to Claude.ai, Claude API, or Claude Code without token consumption until accessed.

---

**Last Updated:** March 31, 2026  
**Ready for:** Production use immediately

