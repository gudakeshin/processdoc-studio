# PowerPoint Generation Quality Improvement Plan

**Date**: 2026-04-08  
**Scope**: Content quality, storytelling, branding, and quality loop enhancements  
**Current State**: Production-grade system with 8-slide mandatory structure, hardcoded Deloitte branding, contract-driven QA  

---

## Executive Summary

The current PPT generation system is **structurally sound** but has three critical gaps:

1. **Storytelling is formulaic** — Fixed 8-slide sequence + predetermined content layout leaves no room for narrative variety or audience-specific adaptation
2. **Branding is rigid** — Hardcoded Deloitte green/dark palette with no project/customer customization; font is fixed to Calibri
3. **Quality loop is incomplete** — Visual QA generates hints but doesn't auto-remediate; no rubric for "narrative coherence" or "story arc quality"

**This document proposes 23 targeted improvements** across four dimensions, organized by effort level (Quick Wins, Medium Effort, Deep Refactors).

---

## Part 1: Storytelling Quality Improvements

### Problem Statement
- **Current behavior**: Slides follow a rigid order (Overview → Metrics → Pillars → Layers → Roles → Table → Metrics → Actions) regardless of content or audience
- **Impact**: Decks feel templated; narrative doesn't adapt to user intent (e.g., risk-focused vs. capability-focused decks look identical)
- **Root cause**: `run_pptx_agent()` enforces mandatory slide sequence without user instruction flexibility

### Improvement 1.1 [Quick Win] — User Intent Classification
**What**: Parse user instruction to infer narrative focus  
**How**:
- Add intent detection regex patterns to `subagents.py::run_pptx_agent()`:
  - Risk-focused: detects keywords (risk, mitigation, contingency, failure modes, controls)
  - Value-focused: detects (cost, benefit, ROI, efficiency, productivity, savings)
  - Capability-focused: detects (capability, maturity, strength, advantage, differentiation)
  - Compliance-focused: detects (compliance, regulatory, audit, governance, policy)
  
- Route detected intent to narrative_v2 skill as extra context:
  ```python
  user_intent = classify_intent(user_instruction)
  pptx_prompt = f"""
  User instruction focuses on: {user_intent}
  Adjust narrative arc to emphasize {intent_adjective}:
  - Lead with {emphasis_slide_type}
  - Minimize {de-emphasis_slide_type}
  """
  ```

**Expected outcome**: Decks adapt structure based on user focus (risk-first → compliance-first; value-first → metrics-first)

**Files to modify**:
- `/backend/app/agents/subagents.py` (lines 1950–2000: `run_pptx_agent()`)
- `/backend/config/skills/pptx_v1/SKILL.md` (add intent-based slide ordering guidance)

---

### Improvement 1.2 [Quick Win] — Narrative Arc Quality Rubric
**What**: Add a quality dimension specifically for story coherence  
**How**:
- Create `/backend/config/quality_contracts/pptx_narrative_rubric.json`:
  ```json
  {
    "dimension": "narrative_coherence",
    "weight": 0.25,
    "rubric": {
      "hook_strength": "Does slide 1 set up the story? (title + badges compelling)",
      "logical_flow": "Is the sequence (overview → detail → action) coherent?",
      "climax": "Does the deck build toward a conclusion/recommendation?",
      "call_to_action": "Is final 'Next Actions' slide specific and urgent?"
    }
  }
  ```

- Integrate into `deliverable_quality.py` as a Claude rubric evaluation:
  ```python
  claude_narrative_score = evaluate_narrative_arc(
      pptx_markdown_excerpt,
      intent=user_intent,
      rubric=narrative_coherence_rubric
  )
  ```

- If score < 0.7, trigger rewrite with narrative feedback:
  ```
  "Narrative flow weak: improve hook on slide 1, strengthen call-to-action on final slide"
  ```

**Expected outcome**: Slides 1–8 evaluated for story coherence, not just structure. Weak arcs get specific remediation.

**Files to modify**:
- `/backend/config/quality_contracts/pptx_narrative_rubric.json` (new)
- `/backend/app/services/deliverable_quality.py` (lines 260–330: add narrative_coherence dimension)

---

### Improvement 1.3 [Medium Effort] — Flexible Slide Sequencing
**What**: Allow Claude to reorder slides based on user intent  
**How**:
- Modify `run_pptx_agent()` to generate a *suggested sequence* as first step:
  ```python
  # Step 1: Ask Claude to propose optimal sequence given user intent
  sequence_proposal = claude.generate(
      system="You are a business storytelling expert.",
      user=f"""
      User intent: {user_intent}
      Available slide types: title, stat_cards, column_cards, stack_layers, bullets, table, chart, section_divider
      Suggest a 8-10 slide sequence that optimizes for {intent}.
      Return JSON: {{"slide_sequence": ["type1", "type2", ...]}}
      """
  )
  
  # Step 2: Generate slides in proposed order, not mandatory order
  slides = []
  for slide_type in sequence_proposal.slide_sequence:
      slide = claude.generate_slide(slide_type, context)
      slides.append(slide)
  ```

- Constraints to enforce:
  - Must have title slide first and final "Next Actions" slide
  - Risk-focused decks must include risk/mitigation slide (new type)
  - Value-focused must lead with value-metric stat_cards
  - Max 12 slides

- Add validation:
  ```python
  validate_sequence(sequence, intent, constraints)
  # Revert to fallback order if validation fails
  ```

**Expected outcome**: Decks adapt slide order to narrative arc (e.g., risk deck starts with Risk/Mitigation; value deck leads with ROI metrics)

**Files to modify**:
- `/backend/app/agents/subagents.py` (lines 1950–2000: add sequence proposal step)
- `/backend/config/skills/pptx_v1/SKILL.md` (add flexible sequencing rules + constraints)
- `/backend/app/services/visual_qa.py` (update validation to accept proposed sequences)

---

### Improvement 1.4 [Medium Effort] — Multi-Purpose Content Variants
**What**: Generate variant content for key slides based on audience type  
**How**:
- Expand user instruction parsing to detect audience:
  - "For executives" → Finance/ROI focus, ≤5 bullets per slide, leading metrics
  - "For operations" → Procedures/workflows, step-by-step detail, roles emphasis
  - "For board" → Strategic risks, governance, controls, compliance
  - "For team" → Hands-on, role clarity, responsibilities, training

- Generate audience-specific variants of key slides:
  ```python
  # Slide 5 (Role Mandates) variant by audience
  if audience == "executives":
      bullets = ["Executive: Sponsor & approve", "CFO: Track P&L impact", ...]
  elif audience == "operations":
      bullets = ["Process Owner: Day-to-day management", "QA: Validation & testing", ...]
  ```

- Store audience hints in ProcessModel context and pass to Claude

**Expected outcome**: Same process yields different decks for different audiences (exec vs. operational versions)

**Files to modify**:
- `/backend/app/agents/subagents.py` (lines 1900–1950: add audience detection)
- `/backend/config/skills/narrative_v2/SKILL.md` (add audience-variant guidance)

---

### Improvement 1.5 [Medium Effort] — Explicit "Why This Matters" Slots
**What**: Add contextual narratives explaining the "so what" of each section  
**How**:
- Introduce optional **section_intro** slide type (not mandatory, but encouraged):
  ```json
  {
    "slide_type": "section_intro",
    "title": "Operating Model — Why This Matters",
    "narrative": "The three pillars (Governance, Quality, Productivity) determine how we execute this process. Each pillar has dependencies and success criteria."
  }
  ```

- Claude decides whether to insert intro slides based on content density/complexity
- Section intros act as narrative bridges between conceptual slides and detail slides

- Update SKILL.md:
  ```
  "section_intro slides are optional but recommended when:
   - Introducing new section (pillars, workflow layers, metrics)
   - Content might be unfamiliar to audience
   - Slide sequence makes a major conceptual shift
  "
  ```

**Expected outcome**: Decks have clearer narrative connectors; reader understands "why" before diving into details

**Files to modify**:
- `/backend/config/skills/pptx_v1/SKILL.md` (add section_intro slide type)
- `/backend/app/services/storage.py` (add `_render_section_intro()` renderer)
- `/backend/app/agents/subagents.py` (Claude decides when to insert section_intro)

---

### Improvement 1.6 [Quick Win] — Stronger Opening Hook
**What**: Enhance title slide badges to tell a mini-narrative  
**How**:
- Modify badge generation to not just list capabilities, but create a narrative hook:
  - Current: "14 Steps | 3 Roles | 2 Handoffs"
  - Better: "Streamlined 3-Role Process | 60% Faster Handoffs | Reduced Errors"

- Update prompt in `run_pptx_agent()`:
  ```
  "Badges should answer: What makes this process remarkable?
   Not: 14 Steps
   Yes: 60% Faster Than Current State
   
   Create 3-4 badges that tell why we should care about this process."
  ```

- Validation check: Badges must include a value claim (faster, reduced, improved) not just count

**Expected outcome**: Title slide immediately conveys narrative thrust, not just metrics

**Files to modify**:
- `/backend/app/agents/subagents.py` (lines 1950–1970: enhance badge generation prompt)

---

## Part 2: Branding Quality Improvements

### Problem Statement
- **Current behavior**: All PPTs use Deloitte green (#86BC25) + Calibri font, no customization
- **Impact**: ProcessDoc identity obscured; customer branding missing; decks look generic
- **Root cause**: Brand colors hardcoded in `/backend/app/services/storage.py` lines 382–393; no configuration layer

### Improvement 2.1 [Quick Win] — Configurable Brand Palette
**What**: Allow customer/project-specific brand colors  
**How**:
- Create `/backend/app/db/models.py` addition:
  ```python
  class ProjectBrand(Base):
      __tablename__ = "project_brands"
      project_id = Column(ForeignKey("projects.id"))
      primary_color = Column(String)  # hex: #86BC25
      accent_color = Column(String)   # hex for secondary elements
      font_family = Column(String, default="Calibri")  # Calibri, Arial, Helvetica
      logo_url = Column(String, nullable=True)  # customer logo
      created_at = Column(DateTime, default=datetime.utcnow)
      updated_at = Column(DateTime, onupdate=datetime.utcnow)
  ```

- Modify `storage.py::_write_pptx_output()` to fetch brand from DB:
  ```python
  def _write_pptx_output(run_state, pptx_slides_json, project_id):
      brand = db.query(ProjectBrand).filter_by(project_id=project_id).first()
      if not brand:
          brand = DEFAULT_DELOITTE_BRAND
      
      colors = {
          "primary": brand.primary_color,
          "accent": brand.accent_color,
          ...
      }
      # Use colors dict instead of hardcoded _B
  ```

- Add UI endpoint to `/backend/app/api/projects.py`:
  ```python
  @router.post("/api/projects/{project_id}/brand")
  def update_project_brand(project_id: int, brand: ProjectBrandUpdate):
      # Update color palette, font, logo
  ```

**Expected outcome**: Each project can have its own brand colors; Deloitte green becomes optional default

**Files to modify**:
- `/backend/app/db/models.py` (add ProjectBrand ORM model)
- `/backend/app/services/storage.py` (refactor _B dict to use fetched brand)
- `/backend/app/api/projects.py` (add brand configuration endpoint)
- `/frontend/components/project-studio/ProjectBrandSettings.tsx` (new UI)

---

### Improvement 2.2 [Quick Win] — Logo Integration
**What**: Add customer/project logo to title slide and footer  
**How**:
- Extend ProjectBrand model to include logo_url
- Modify `_render_title()` in storage.py:
  ```python
  if brand.logo_url:
      logo_image = requests.get(brand.logo_url)
      prs.slides[0].shapes.add_picture(
          logo_image,
          Inches(9.0),  # Right side of title slide
          Inches(0.3),
          height=Inches(0.5)
      )
  ```

- Add logo to footer on all content slides:
  ```python
  # In _add_chrome()
  if brand.logo_url:
      add_picture_to_footer(slide, brand.logo_url)
  ```

**Expected outcome**: Decks branded with customer logo, more professional appearance

**Files to modify**:
- `/backend/app/services/storage.py` (add logo rendering to `_render_title()` and `_add_chrome()`)
- `/backend/app/db/models.py` (add logo_url field to ProjectBrand)

---

### Improvement 2.3 [Medium Effort] — Dynamic Color Palette Generation
**What**: Auto-generate complementary color palettes for variety  
**How**:
- Implement color harmony algorithm (triadic, analogous, complementary):
  ```python
  def generate_color_palette(primary_hex):
      primary_rgb = hex_to_rgb(primary_hex)
      complementary = invert_hue(primary_rgb)
      accent_light = lighten(primary_rgb, 0.4)
      accent_dark = darken(primary_rgb, 0.3)
      
      return {
          "primary": primary_rgb,
          "complementary": complementary,
          "accent_light": accent_light,
          "accent_dark": accent_dark,
          ...
      }
  ```

- Allow users to select palette style (monochromatic, triadic, complementary) when setting brand color
- Update stat_cards/column_cards fill colors to use palette instead of hardcoded grays

**Expected outcome**: Brand colors ripple through deck; professional color harmony

**Files to modify**:
- `/backend/app/services/storage.py` (add `generate_color_palette()`)
- `/backend/app/db/models.py` (add palette_style field to ProjectBrand)

---

### Improvement 2.4 [Medium Effort] — Font Flexibility
**What**: Support multiple font families (not just Calibri)  
**How**:
- Extend ProjectBrand to include font_family and font_size_override
- Modify all text rendering in storage.py to use brand fonts:
  ```python
  FONT_FACE = brand.font_family or "Calibri"
  
  title_font = Font(
      name=FONT_FACE,
      size=Pt(brand.title_font_size or 22),
      bold=True,
      color=RGBColor(...),
  )
  ```

- Supported fonts: Calibri (default), Helvetica, Arial, Segoe UI, Georgia, Open Sans
- Allow heading vs. body font separation

**Expected outcome**: Decks match customer brand typography, not Deloitte standard

**Files to modify**:
- `/backend/app/db/models.py` (add font_family, title_font_size, body_font_size)
- `/backend/app/services/storage.py` (refactor Font() calls to use brand config)

---

### Improvement 2.5 [Quick Win] — Branding Compliance Validation
**What**: QA check for brand consistency  
**How**:
- Add branding validation to visual_qa.py:
  ```python
  def validate_branding(pptx_path, brand):
      checks = {
          "primary_color_used": color_hex_in_slides(brand.primary_color),
          "logo_present_on_title": logo_in_title_slide(),
          "logo_in_footer": logo_in_all_footers(),
          "font_consistent": font_family_throughout(brand.font_family),
          "chrome_on_all_content_slides": has_chrome_on_content_slides(),
      }
      return checks
  ```

- Surface branding issues in visual_qa_report as separate section
- Add to deliverable quality loop:
  ```
  "branding_compliance": 0.95  # All checks passed
  ```

**Expected outcome**: Branding consistency tracked and reported

**Files to modify**:
- `/backend/app/services/visual_qa.py` (add `validate_branding()` function)
- `/backend/config/quality_contracts/pptx_branding_check.json` (new)

---

## Part 3: Content Quality Improvements

### Problem Statement
- **Current behavior**: Claude generates slides with fixed schema (title, bullets, stat_cards); content is generic
- **Impact**: Decks lack context specificity; metrics aren't validated; descriptions are placeholder-quality
- **Root cause**: `run_pptx_agent()` schema is rigid; no data validation or contextual enrichment

### Improvement 3.1 [Quick Win] — Data Validation & Source Attribution
**What**: Validate metrics against ProcessModel and source them explicitly  
**How**:
- Modify stat_cards generation to require source attribution:
  ```json
  {
    "slide_type": "stat_cards",
    "cards": [
      {
        "stat": "14",
        "label": "Process Steps",
        "description": "From swimlane analysis of current state",
        "source": "ProcessModel.steps_count"  // NEW: track source
      },
      ...
    ]
  }
  ```

- Validation check in deliverable_quality:
  ```python
  def validate_stat_sources(pptx_slides):
      errors = []
      for slide in pptx_slides:
          if slide.type == "stat_cards":
              for card in slide.cards:
                  if card.source not in ProcessModel:
                      errors.append(f"Card '{card.label}' has no valid source")
      return errors
  ```

- Inject ProcessModel field mappings into Claude prompt:
  ```
  Available metrics from ProcessModel:
  - steps_count
  - roles_count
  - swimlanes_count
  - avg_cycle_time (if available)
  - cost_per_transaction (if available)
  ```

**Expected outcome**: Metrics are traceable, not fabricated

**Files to modify**:
- `/backend/app/agents/subagents.py` (inject available metrics into prompt)
- `/backend/config/skills/pptx_v1/SKILL.md` (require source attribution)
- `/backend/app/services/deliverable_quality.py` (add metric validation)

---

### Improvement 3.2 [Quick Win] — Richer Slide Descriptions
**What**: Stat card descriptions should answer "so what" not just restate the metric  
**How**:
- Enhance description generation prompt:
  ```
  NOT: "The number of steps in the workflow"
  YES: "With 14 steps, the process requires 5 decision points and 3 handoffs"
  
  Description should:
  - Highlight implications (e.g., bottlenecks, risks, opportunities)
  - Connect to business outcome
  - Suggest next action or improvement
  ```

- Add rubric for description quality in visual QA:
  ```python
  def evaluate_description_quality(description, stat_label):
      issues = []
      if description == stat_label:
          issues.append("Description is just restatement of label")
      if "provides context" not in classify_content(description):
          issues.append("Description lacks implication or insight")
      return issues
  ```

**Expected outcome**: Descriptions are insightful, not redundant

**Files to modify**:
- `/backend/app/agents/subagents.py` (enhance description prompt)
- `/backend/app/services/visual_qa.py` (add description quality check)

---

### Improvement 3.3 [Medium Effort] — Contextual Data Enrichment
**What**: Populate stat cards with actual ProcessModel data, not generic placeholders  
**How**:
- Extend `_pptx_user_context_appendix()` to include ProcessModel analytics:
  ```python
  def _enrich_context_with_analytics(process_model):
      return {
          "steps": process_model.steps_count,
          "roles": process_model.roles,
          "swimlanes": len(process_model.swimlanes),
          "decision_points": count_decision_points(process_model),
          "handoffs": count_handoffs(process_model),
          "critical_controls": extract_controls(process_model),
          "risks": extract_risks(process_model),
          "value_drivers": [
              {"driver": "speed", "current": "14 days", "target": "7 days"},
              {"driver": "cost", "current": "$100", "target": "$75"},
              ...
          ]
      }
  ```

- Prompt Claude to use this data:
  ```
  ProcessModel Analytics:
  - 14 steps, 5 roles, 3 swimlanes
  - 2 critical decision points
  - 5 key control points
  - Identified risks: [list]
  - Value improvement opportunities: [list]
  
  Use these data points in stat_cards and recommendations
  ```

**Expected outcome**: Decks are data-rich, not templated; metrics are real

**Files to modify**:
- `/backend/app/agents/subagents.py` (enhance `_pptx_user_context_appendix()`)
- `/backend/app/agents/agent_types.py` (include analytics in AgentContext)

---

### Improvement 3.4 [Medium Effort] — Targeted "Next Actions" Generation
**What**: Final slide recommendations should be process-specific, not generic  
**How**:
- Analyze ProcessModel to identify:
  - **Quick wins**: High-impact, low-effort improvements (e.g., remove redundant approval step)
  - **Dependencies**: Actions that unlock other improvements
  - **Risks**: Actions to mitigate identified risks
  - **Capability gaps**: Training or tool requirements

- Prompt Claude to generate 3 specific next actions:
  ```
  Based on ProcessModel analysis, recommend 3 next actions:
  1. [Quick win specific to this process]
  2. [Risk mitigation specific to this process]
  3. [Capability or governance gap specific to this process]
  
  Each action must be:
  - Specific (not "Improve efficiency")
  - Measurable (e.g., "Reduce cycle time by 20%")
  - Actionable (owner + timeline clear)
  ```

- Validation: Check that actions reference actual process elements (steps, roles, risks)

**Expected outcome**: Next actions are strategic and process-specific, not boilerplate

**Files to modify**:
- `/backend/app/agents/subagents.py` (lines 1979–1985: enhance final bullets generation)
- `/backend/config/skills/pptx_v1/SKILL.md` (update next actions guidance)

---

### Improvement 3.5 [Medium Effort] — Chart Data Validation & Generation
**What**: Charts should be populated with real data, not sample data  
**How**:
- Extend ProcessModel to optionally include metrics over time:
  ```python
  class ProcessMetrics(Base):
      process_id = ForeignKey("processes.id")
      metric_name = Column(String)  # "cycle_time", "error_rate", "throughput"
      values_by_period = Column(JSON)  # {"Jan": 14, "Feb": 13, ...}
      target_value = Column(Float)
  ```

- Modify chart generation:
  ```python
  def generate_chart_slides(process_model):
      for metric in process_model.metrics:
          chart_slide = {
              "slide_type": "chart",
              "chart_type": infer_chart_type(metric),  # line for trends, bar for comparison
              "categories": metric.values_by_period.keys(),
              "series": [{"name": metric.name, "values": metric.values_by_period.values()}],
              "title": f"{metric.name} Trend"
          }
  ```

- Fallback: If no metrics available, use deterministic placeholder with note "[Data required: provide actual metrics]"

**Expected outcome**: Charts show real trends, not sample data

**Files to modify**:
- `/backend/app/db/models.py` (add ProcessMetrics ORM)
- `/backend/app/agents/subagents.py` (fetch ProcessMetrics in context)

---

## Part 4: Quality Loop Improvements

### Problem Statement
- **Current behavior**: Visual QA generates remediation hints but doesn't auto-apply; narrative coherence not evaluated; no rubric for "visual storytelling"
- **Impact**: QA feedback sits in reports; low-quality narratives aren't caught; visual/story misalignment not detected
- **Root cause**: Visual QA is advisory only; no automated remediation; no narrative-specific rubric

### Improvement 4.1 [Quick Win] — Automated Slide Repair
**What**: Visual QA hints auto-trigger PPTX regeneration for flagged slides  
**How**:
- Modify `deliverable_quality.py::run_deliverable_quality_loop()`:
  ```python
  visual_qa_report = evaluate_pptx(pptx_path, ...)
  
  if visual_qa_report.status == "warn" and visual_qa_report.per_slide_findings:
      # Auto-repair
      for finding in visual_qa_report.per_slide_findings:
          if finding.severity >= "medium":
              repaired_slides = regenerate_flagged_slides(
                  pptx_slides_json,
                  flagged_slide_indices=finding.slide_index,
                  remediation_hint=finding.remediation_hint
              )
              pptx_slides_json = merge_repaired_slides(pptx_slides_json, repaired_slides)
      
      # Re-render and re-evaluate
      pptx_path = render_pptx(pptx_slides_json)
      visual_qa_report = evaluate_pptx(pptx_path, ...)  # Should improve
  ```

- Limit auto-repair to 1 iteration (manual review on 2nd failure)

**Expected outcome**: Obvious visual issues (missing chrome, low density) auto-fixed without manual intervention

**Files to modify**:
- `/backend/app/services/deliverable_quality.py` (add auto-repair loop)
- `/backend/app/agents/subagents.py` (add `regenerate_flagged_slides()` function)

---

### Improvement 4.2 [Quick Win] — Narrative Coherence Rubric
**What**: Add explicit rubric evaluation for story arc quality  
**How**:
- Create `/backend/config/quality_contracts/pptx_narrative_coherence.json`:
  ```json
  {
    "skill_id": "pptx_v1",
    "dimension": "narrative_coherence",
    "weight": 0.25,
    "threshold": 0.75,
    "rubric": {
      "opening_hook": {
        "description": "Does title slide establish why we care about this process?",
        "scoring": {
          "5": "Title + badges answer 'Why is this process important?' clearly",
          "4": "Title is clear, badges provide some context",
          "3": "Title is generic, badges list metrics only",
          "1": "Title is vague, badges are missing"
        }
      },
      "logical_flow": {
        "description": "Does slide sequence tell a coherent story?",
        "scoring": {
          "5": "Each slide logically follows; narrative arc is clear (overview→detail→action)",
          "4": "Mostly logical; minor jumps",
          "3": "Sequence is structural but not narrative",
          "1": "Random sequence, no story"
        }
      },
      "climax_and_resolution": {
        "description": "Does deck build toward conclusion?",
        "scoring": {
          "5": "Final slide offers specific, high-impact next actions",
          "4": "Final slide offers general recommendations",
          "3": "Final slide repeats prior content",
          "1": "No clear conclusion"
        }
      },
      "visual_narrative_alignment": {
        "description": "Do visuals (stat cards, stack layers, charts) support the story?",
        "scoring": {
          "5": "All visuals reinforce narrative; colors and layout guide reader",
          "4": "Most visuals support narrative; minor misalignment",
          "3": "Visuals are present but don't strongly support narrative",
          "1": "Visuals distract from narrative"
        }
      }
    }
  }
  ```

- Integrate into deliverable_quality loop:
  ```python
  narrative_score = evaluate_rubric(
      pptx_slides=pptx_slides_json,
      rubric=narrative_coherence_rubric,
      claude=claude_client
  )
  
  if narrative_score < 0.75:
      remediation = {
          "dimension": "narrative_coherence",
          "score": narrative_score,
          "issues": identify_rubric_gaps(narrative_score),
          "action": "Regenerate PPTX with improved narrative arc"
      }
  ```

**Expected outcome**: Narrative quality is measured, not assumed

**Files to modify**:
- `/backend/config/quality_contracts/pptx_narrative_coherence.json` (new)
- `/backend/app/services/deliverable_quality.py` (add narrative_coherence dimension)
- `/backend/app/services/visual_qa.py` (integrate rubric scoring)

---

### Improvement 4.3 [Medium Effort] — Multi-Dimension Quality Contract
**What**: Combine structural, narrative, branding, and content QA into one contract  
**How**:
- Create comprehensive contract in `/backend/config/quality_contracts/pptx_comprehensive.json`:
  ```json
  {
    "skill_id": "pptx_v1",
    "pass_threshold": 0.78,
    "max_revision_rounds": 2,
    "dimensions": [
      {
        "id": "content_quality",
        "weight": 0.30,
        "checks": [
          {"type": "metric_sourcing", "threshold": 0.9},
          {"type": "description_richness", "threshold": 0.8},
          {"type": "data_accuracy", "threshold": 0.95}
        ]
      },
      {
        "id": "narrative_coherence",
        "weight": 0.25,
        "rubric": "..."
      },
      {
        "id": "visual_design",
        "weight": 0.25,
        "checks": [
          {"type": "chrome_consistency", "threshold": 1.0},
          {"type": "content_density", "threshold": 0.85},
          {"type": "color_harmony", "threshold": 0.8}
        ]
      },
      {
        "id": "branding_compliance",
        "weight": 0.20,
        "checks": [
          {"type": "primary_color_used", "threshold": 1.0},
          {"type": "logo_placement", "threshold": 1.0},
          {"type": "font_consistency", "threshold": 0.95}
        ]
      }
    ]
  }
  ```

- Report aggregates all dimensions:
  ```
  Content Quality: 0.82
  Narrative Coherence: 0.74 ⚠️
  Visual Design: 0.91
  Branding Compliance: 0.88
  ─────────────────────
  AGGREGATE: 0.83 ✓ PASS
  
  Remediation needed: Improve narrative flow (build toward climax)
  ```

**Expected outcome**: Holistic quality view; clear remediation targets

**Files to modify**:
- `/backend/config/quality_contracts/pptx_comprehensive.json` (new)
- `/backend/app/services/deliverable_quality.py` (support multi-dimension contract)

---

### Improvement 4.4 [Medium Effort] — Conversation-Based Feedback Loop
**What**: Embed QA reports in project conversation and capture user feedback  
**How**:
- Enhance visual_qa_chat.py to store QA reports and allow threaded feedback:
  ```python
  # Visual QA report posted as assistant message
  def post_visual_qa_report(run_id, report):
      message = RunMessage(
          run_id=run_id,
          role="assistant",
          content=format_report(report),
          metadata={"kind": "visual_qa_report", "report_id": uuid()}
      )
      db.add(message)
      db.commit()
      
      # Send notification
      emit_event("visual_qa_report_posted", report)
  ```

- Add user feedback collection:
  ```python
  @router.post("/api/runs/{run_id}/visual-qa/{report_id}/feedback")
  def submit_qa_feedback(run_id, report_id, feedback: QAFeedbackRequest):
      # feedback: {"issue": "narrative flow weak", "severity": "medium", "suggestion": "..."}
      # Store in QAFeedback table for improvement tracking
  ```

- Mine feedback for improvement patterns:
  ```python
  def identify_improvement_patterns():
      weak_areas = db.query(QAFeedback).filter(
          QAFeedback.severity >= "medium"
      ).group_by("issue").having(count() > 5)
      # Identify top 5 recurring issues
      return weak_areas
  ```

**Expected outcome**: User feedback informs system improvements; loop is continuous

**Files to modify**:
- `/backend/app/db/models.py` (add QAFeedback ORM)
- `/backend/app/services/visual_qa_chat.py` (post reports as conversation messages)
- `/backend/app/api/runs.py` (add feedback submission endpoint)

---

### Improvement 4.5 [Medium Effort] — Versioning & Rollback for PPTX
**What**: Allow users to compare/revert to previous PPTX versions  
**How**:
- Extend Run model to track PPTX versions:
  ```python
  class RunArtifactVersion(Base):
      run_id = ForeignKey("runs.id")
      artifact_type = Column(String)  # "pptx", "docx", etc.
      version_number = Column(Integer)
      artifact_path = Column(String)
      generated_at = Column(DateTime)
      generator_notes = Column(String)  # e.g., "Auto-repaired slide 3"
      qa_report = Column(JSON)
      user_selected = Column(Boolean, default=False)  # True if user chose this version
  ```

- Endpoint to list versions:
  ```python
  @router.get("/api/runs/{run_id}/artifacts/pptx/versions")
  def list_pptx_versions(run_id):
      versions = db.query(RunArtifactVersion).filter_by(
          run_id=run_id, artifact_type="pptx"
      ).order_by(-RunArtifactVersion.version_number)
      return versions
  ```

- Endpoint to set active version:
  ```python
  @router.post("/api/runs/{run_id}/artifacts/pptx/set-version/{version_number}")
  def set_active_pptx_version(run_id, version_number):
      # Copy version to output.pptx
  ```

**Expected outcome**: Users can compare quality iterations and choose best version

**Files to modify**:
- `/backend/app/db/models.py` (add RunArtifactVersion)
- `/backend/app/services/storage.py` (create version on each save)
- `/backend/app/api/runs.py` (add version endpoints)

---

## Part 5: Implementation Roadmap

### Phase 1: Quick Wins (1–2 weeks)
Priority order for immediate impact:

1. ✅ **Improvement 1.1** — User Intent Classification
   - Effort: 3 hours
   - Impact: Enables narrative adaptation
   - Prerequisites: None

2. ✅ **Improvement 1.2** — Narrative Arc Quality Rubric
   - Effort: 4 hours
   - Impact: Narrative quality measured
   - Prerequisites: Improvement 1.1

3. ✅ **Improvement 2.1** — Configurable Brand Palette
   - Effort: 5 hours (DB schema + storage + API)
   - Impact: Customer branding capability
   - Prerequisites: None

4. ✅ **Improvement 3.1** — Data Validation & Source Attribution
   - Effort: 3 hours
   - Impact: Metrics become traceable
   - Prerequisites: None

5. ✅ **Improvement 3.2** — Richer Slide Descriptions
   - Effort: 2 hours (prompt tuning)
   - Impact: Better content quality
   - Prerequisites: None

6. ✅ **Improvement 4.1** — Automated Slide Repair
   - Effort: 6 hours
   - Impact: Auto-fix obvious quality issues
   - Prerequisites: Improvement 1.2

**Phase 1 Deliverable**: Quick wins deployed → decks adapted by user intent, branded per project, descriptions richer, narrative measured

---

### Phase 2: Medium Effort (2–4 weeks)

1. ✅ **Improvement 1.3** — Flexible Slide Sequencing
   - Effort: 8 hours
   - Prerequisites: Improvement 1.1

2. ✅ **Improvement 2.4** — Font Flexibility
   - Effort: 4 hours
   - Prerequisites: Improvement 2.1

3. ✅ **Improvement 3.3** — Contextual Data Enrichment
   - Effort: 6 hours
   - Prerequisites: Improvement 3.1

4. ✅ **Improvement 4.3** — Multi-Dimension Quality Contract
   - Effort: 8 hours
   - Prerequisites: Improvement 1.2, 4.1

**Phase 2 Deliverable**: Decks adapt structure per intent, richer data context, comprehensive QA rubric, flexible fonts

---

### Phase 3: Deep Refactors (4+ weeks)

1. ✅ **Improvement 1.4** — Multi-Purpose Content Variants
   - Effort: 12 hours
   - Prerequisites: Improvement 1.1

2. ✅ **Improvement 3.4** — Targeted Next Actions
   - Effort: 6 hours
   - Prerequisites: Improvement 3.3

3. ✅ **Improvement 4.4** — Conversation-Based Feedback Loop
   - Effort: 10 hours
   - Prerequisites: None (but Phase 2 recommended first)

4. ✅ **Improvement 4.5** — Versioning & Rollback
   - Effort: 12 hours
   - Prerequisites: None

**Phase 3 Deliverable**: Full-featured system with audience-specific variants, process-specific recommendations, user feedback loop, version control

---

## Part 6: Success Metrics

### Storytelling Quality
| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Narrative Coherence Score | N/A | 0.78+ | Rubric evaluation (Improvement 1.2) |
| Opening Hook Strength | Generic (count metrics) | Value-driven | User feedback on slide 1 |
| Sequence Flexibility | Fixed 8 slides | 60% of decks adapt sequence | Analytics on proposed sequences used |
| Audience Adaptation | None | 40% of decks use audience variants | User feedback on variant quality |

### Branding Quality
| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Brand Color Customization | 0% | 100% of projects have custom palette | ProjectBrand records created |
| Logo Integration | 0% | 80% of decks display logo | Visual QA check for logo_present |
| Font Flexibility | 1 (Calibri only) | 5+ font options | ProjectBrand.font_family values |
| Branding Compliance Score | N/A | 0.95+ average | QA dimension score |

### Content Quality
| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Metric Source Attribution | 0% | 100% traced to ProcessModel | Validation check in deliverable QA |
| Description Richness | Generic | Context-specific, insight-driven | Rubric scoring on description quality |
| Data Enrichment Coverage | Basic (step/role counts) | 70% of available metrics used | Context enrichment span |
| Chart Data Quality | 30% real, 70% placeholder | 90% real data | Chart source verification |

### Quality Loop Robustness
| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Auto-Repair Success Rate | 0% | 85% of issues auto-fixed | Repair success / visual QA flags |
| Narrative QA Coverage | 0% | 100% of decks evaluated | Dimension weight in contract |
| Multi-Dimension Evaluation | Partial | Full (content, narrative, visual, branding) | Contract dimensions count |
| User Feedback Collected | Minimal | 60% of decks receive feedback | Feedback submission rate |
| Improvement Loop Closure | None | Monthly trend analysis | Recurring issue identification |

---

## Appendix: File Structure Summary

### New Files to Create
```
/backend/config/quality_contracts/
├── pptx_narrative_coherence.json (Improvement 1.2)
├── pptx_branding_check.json (Improvement 2.5)
├── pptx_comprehensive.json (Improvement 4.3)

/backend/app/db/
├── migrations/ (ProjectBrand, ProcessMetrics, QAFeedback tables)

/frontend/components/project-studio/
├── ProjectBrandSettings.tsx (Brand configuration UI)
└── PPTXVersionHistory.tsx (Version comparison UI)
```

### Files to Modify (Priority)
1. `/backend/app/agents/subagents.py` — User intent, flexible sequencing, enriched context
2. `/backend/app/services/storage.py` — Brand palette fetching, logo rendering, font flexibility
3. `/backend/app/services/deliverable_quality.py` — Narrative rubric, comprehensive contract, auto-repair
4. `/backend/app/services/visual_qa.py` — Branding validation, narrative evaluation
5. `/backend/app/db/models.py` — ProjectBrand, ProcessMetrics, RunArtifactVersion, QAFeedback

---

## Conclusion

This plan addresses three critical gaps:

1. **Storytelling**: From templated → adaptive (user intent, flexible sequencing, narrative rubric, audience variants)
2. **Branding**: From hardcoded Deloitte → configurable (colors, fonts, logos, compliance checks)
3. **Quality Loop**: From advisory → automated (auto-repair, narrative evaluation, multi-dimension contract, feedback loop)

**Estimated Total Effort**: 20–24 weeks for full implementation (Phases 1–3)  
**Quick Win ROI**: Phase 1 alone (3–4 weeks) yields immediate narrative improvement + customer branding

**Next Steps**:
1. Prioritize Phase 1 quick wins
2. Pilot with test project
3. Gather user feedback on improvements
4. Iterate on quality metrics
5. Plan Phase 2 based on results
