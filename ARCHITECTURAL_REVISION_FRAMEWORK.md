# Architectural Revision: Framework-Level Improvements for All Deliverables

**Date**: 2026-04-08  
**Scope**: Generalize storytelling, branding, and quality improvements across ALL output types  
**Current State**: Output-type-specific implementations (branding hardcoded for PPTX, quality rules scattered)  
**Target State**: Pluggable, extensible framework where improvements apply uniformly

---

## Executive Summary

The current codebase has **asymmetric implementations**:
- **Branding**: Hardcoded in `storage.py` for PPTX only; absent from DOCX, PDF, XLSX
- **Quality rules**: Output-specific contracts; no unified narrative coherence evaluation
- **Data enrichment**: Built separately for each agent (pptx_context, docx_context, etc.)
- **User intent classification**: Duplicated logic or missing in many agents
- **Storytelling patterns**: PPTX has rigid structure; other formats have none

**This revision proposes 5 core architectural abstractions:**

1. **Deliverable Abstraction** — Interface for all output types to implement
2. **Branding Service** — Centralized, extensible styling layer
3. **Quality Framework** — Unified evaluation with pluggable rules
4. **Content Enrichment Engine** — Pre-agent context building with intent classification
5. **Artifact Renderer Registry** — Pluggable renderers per output type

**Result**: New output types added without changing core framework; branding and storytelling improvements apply automatically to all types.

---

## Part 1: Current Architecture Problems

### Problem 1.1: Branding is Hardcoded for PPTX

**Location**: `/backend/app/services/storage.py` lines 381–393

```python
_B: dict[str, RGBColor] = {  # HARDCODED
    "green": RGBColor(0x86, 0xBC, 0x25),
    "dark": RGBColor(0x1A, 0x1A, 0x1A),
    ...
}
```

**Issues**:
- Colors, fonts, logos only apply to PPTX
- DOCX, PDF, XLSX have no branding layer
- Adding custom branding requires modifying storage.py
- No way to apply customer-specific colors/fonts/logos to all outputs
- Branding logic mixed with rendering logic (can't reuse)

**Impact**: 
- ProcessDoc identity lost in non-PPTX outputs
- Customer branding impossible
- Adding a new output type requires duplicating branding logic

---

### Problem 1.2: Quality Rules are Output-Type-Specific

**Location**: `/backend/config/quality_contracts/`

```
proposal_finance_v1.json  ← proposal only
brd_v1.json              ← BRD only
No unified narrative_coherence.json
```

**Issues**:
- Each output type has different quality dimensions
- Narrative coherence only evaluated for proposals, not PPTX/DOCX/PDF
- Adding a new quality rule requires skill-specific contracts
- No consistency check across deliverables
- Remediation logic duplicated in coordinator.py + deliverable_quality.py

**Impact**:
- Weak narratives in PPTX not caught (no coherence rubric)
- Inconsistent quality bar across output types
- New improvements (intent classification, data enrichment) must be retrofitted per agent

---

### Problem 1.3: Data Enrichment Built Separately Per Agent

**Location**: `/backend/app/agents/subagents.py`

```python
def run_docx_agent(ctx: AgentContext, ...):
    # Builds context in _docx_user_context_appendix()
    context = _docx_user_context_appendix(ctx, ...)  # One way

def run_pptx_agent(ctx: AgentContext, ...):
    # Different context building in _pptx_user_context_appendix()
    context = _pptx_user_context_appendix(ctx, ...)  # Another way

def run_xlsx_agent(ctx: AgentContext, ...):
    # Yet another way (or missing entirely)
    context = _xlsx_context_or_default(ctx, ...)
```

**Issues**:
- Context enrichment duplicated across agents
- Data enrichment (ProcessModel analytics, metrics) only in PPTX
- User intent classification nowhere (should be pre-agent)
- Prior artifact context handling inconsistent
- New enrichment (e.g., risk extraction) must be added to 6+ agents separately

**Impact**:
- Inconsistent quality of agent context
- Difficult to add new context types (must update all agents)
- Data insights only in PPTX; DOCX/PDF miss enrichment

---

### Problem 1.4: User Intent Classification Missing or Duplicated

**Location**: None (or hardcoded in agent prompts)

**Current state**:
- No global intent classification before agent routing
- PPTX agent infers intent from user_instruction (ad-hoc)
- Narrative agent doesn't know if risk-focused or value-focused
- Different agents have different inference logic (or none)

**Issues**:
- Narrative arc decisions made by individual agents independently
- Audience adaptation only in PPTX (if at all)
- Risk-mitigation focus not communicated to all agents
- Storytelling improvements can't be applied platform-wide

**Impact**:
- Decks (PPTX) might be risk-focused but narratives (DOCX) value-focused
- Audience mismatch across outputs
- Inconsistent framing across deliverables

---

### Problem 1.5: Artifact Rendering is Output-Type-Specific

**Location**: `/backend/app/services/storage.py` lines 230–782

```python
def _write_pptx_output(...):  # 400+ lines PPTX-specific
    ...

def _write_xlsx_output(...):  # Different structure
    ...

def _write_docx_output(...):  # Different flow
    ...
```

**Issues**:
- No shared interface for renderers
- Adding a new output type requires new render function
- Branding/styling logic duplicated per type
- Quality validation only applied to PPTX (visual QA)
- Post-processing applied inconsistently (some types, not others)

**Impact**:
- Hard to add new output types
- Inconsistent branding application
- Quality checks only apply to some types
- Code duplication across renderers

---

## Part 2: Proposed Framework Architecture

### Architecture 2.1: Deliverable Abstraction (Interface-Based)

**Proposed Structure**:

Create `/backend/app/core/deliverable.py` — Define contracts all output types must implement:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class DeliverableMetadata:
    """Metadata about a deliverable type"""
    output_type: str           # "pptx", "docx", "xlsx", "pdf", "process_map"
    file_extension: str        # ".pptx", ".docx", etc.
    mime_type: str             # "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    supports_branding: bool    # Can this format apply brand colors/fonts/logos?
    supports_quality_rubric: bool  # Can this format be evaluated for narrative/quality?
    requires_rendering: bool   # Does state need to be rendered (pptx, docx) vs. already rendered (pdf)?
    intermediate_format: str   # "json" (pptx_slides), "markdown" (docx), etc.
    skill_output_key: str      # "pptx_slides", "docx_markdown", etc.

class IDeliverable(ABC):
    """Interface all output types must implement"""
    
    @abstractmethod
    def get_metadata(self) -> DeliverableMetadata:
        """Return metadata about this deliverable type"""
        pass
    
    @abstractmethod
    def render(
        self, 
        intermediate_content: str | dict,  # JSON for PPTX, markdown for DOCX, etc.
        branding: BrandingContext,
        output_path: str
    ) -> None:
        """Render intermediate content to final format with branding applied"""
        pass
    
    @abstractmethod
    def extract_quality_signals(self, output_path: str) -> dict[str, Any]:
        """Extract structural metadata for quality evaluation"""
        # PPTX: shape counts, density, colors, chrome
        # DOCX: heading hierarchy, word count, structure
        # XLSX: sheet count, row/col count, RACI detection
        # PDF: page count, text density
        pass
    
    @abstractmethod
    def apply_branding(
        self,
        intermediate_content: str | dict,
        branding: BrandingContext
    ) -> str | dict:
        """Apply branding (colors, fonts, logos) to intermediate content"""
        pass

class DeliverableRegistry:
    """Runtime registry of available deliverables"""
    _deliverables: Dict[str, IDeliverable] = {}
    
    @classmethod
    def register(cls, output_type: str, deliverable: IDeliverable) -> None:
        cls._deliverables[output_type] = deliverable
    
    @classmethod
    def get(cls, output_type: str) -> IDeliverable:
        if output_type not in cls._deliverables:
            raise ValueError(f"Unknown output type: {output_type}")
        return cls._deliverables[output_type]
    
    @classmethod
    def all(cls) -> Dict[str, IDeliverable]:
        return cls._deliverables.copy()
```

**Implementation for each output type**:

```python
# /backend/app/core/deliverable_pptx.py
class PPTXDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="pptx",
            file_extension=".pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            supports_branding=True,
            supports_quality_rubric=True,
            requires_rendering=True,
            intermediate_format="json",
            skill_output_key="pptx_slides"
        )
    
    def render(self, intermediate_content, branding, output_path):
        # Current storage.py::_write_pptx_output() logic
        pptx_slides = json.loads(intermediate_content)
        prs = Presentation(prs_blank_sldsz)
        for slide_json in pptx_slides["slides"]:
            slide = self._render_slide(slide_json, branding, prs)
        prs.save(output_path)
    
    def extract_quality_signals(self, output_path):
        # Current visual_qa.py logic
        return {
            "per_slide_metadata": [...],
            "chrome_detected": True,
            "content_density": 0.72,
            ...
        }
    
    def apply_branding(self, intermediate_content, branding):
        # Branding applied during render, but could extract for pre-validation
        pptx_slides = json.loads(intermediate_content)
        for slide in pptx_slides["slides"]:
            slide["_brand_applied"] = branding.primary_color
        return json.dumps(pptx_slides)

# /backend/app/core/deliverable_docx.py
class DOCXDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="docx",
            supports_branding=True,  # Can apply header colors, fonts
            supports_quality_rubric=True,
            requires_rendering=True,
            intermediate_format="markdown",
            skill_output_key="docx_markdown"
        )
    
    def render(self, intermediate_content, branding, output_path):
        # Current storage.py::_write_docx_output() + branding injection
        doc = Document()
        blocks = parse_markdown(intermediate_content)
        for block in blocks:
            para = doc.add_paragraph(block.text)
            para.style = self._get_style_with_branding(block.style, branding)
            if block.type == "heading_1":
                para.runs[0].font.color.rgb = branding.primary_color
        doc.save(output_path)
    
    def extract_quality_signals(self, output_path):
        doc = Document(output_path)
        return {
            "heading_hierarchy": [...],
            "word_count": sum(len(p.text.split()) for p in doc.paragraphs),
            "structure_score": 0.85,
            ...
        }
    
    def apply_branding(self, intermediate_content, branding):
        # Inject color codes or style hints into markdown
        return intermediate_content  # Or enhanced with color directives
```

**Registration at startup** (in main.py lifespan):

```python
@app.lifespan
async def lifespan(app: FastAPI):
    # Startup
    DeliverableRegistry.register("pptx", PPTXDeliverable())
    DeliverableRegistry.register("docx", DOCXDeliverable())
    DeliverableRegistry.register("xlsx", XLSXDeliverable())
    DeliverableRegistry.register("pdf", PDFDeliverable())
    DeliverableRegistry.register("process_map", ProcessMapDeliverable())
    
    yield
    # Shutdown
```

**Benefits**:
- New output types added without modifying coordinator/storage
- Consistent interface for all types
- Branding/quality/rendering logic localized per type
- Easy to test/mock each deliverable type
- Coordinator doesn't need to know about specific types

---

### Architecture 2.2: Branding Service (Centralized, Extensible)

**Proposed Structure**:

Create `/backend/app/services/branding_service.py`:

```python
from dataclasses import dataclass
from enum import Enum

class BrandingLevel(Enum):
    DELOITTE_DEFAULT = "deloitte_default"  # Hardcoded default
    PROJECT_CUSTOM = "project_custom"       # From ProjectBrand DB
    SKILL_OVERRIDE = "skill_override"       # From skill instructions
    RUNTIME_OVERRIDE = "runtime_override"   # From run config

@dataclass
class ColorPalette:
    """Color harmony palette"""
    primary: str          # hex #86BC25
    complementary: str    # hex opposing hue
    accent_light: str     # lightened primary
    accent_dark: str      # darkened primary
    neutral_light: str    # light gray
    neutral_dark: str     # dark gray
    text_primary: str     # text on light bg
    text_inverse: str     # text on dark bg

@dataclass
class BrandingContext:
    """Runtime branding applied to all deliverables"""
    level: BrandingLevel
    primary_color: str
    palette: ColorPalette
    font_family: str
    font_size_base: int
    logo_url: str | None
    company_name: str
    custom_footer_text: str | None

class BrandingService:
    def __init__(self, db: Session):
        self.db = db
        self.default_brand = self._build_deloitte_default()
    
    def _build_deloitte_default(self) -> BrandingContext:
        """Deloitte branding as fallback"""
        palette = ColorPalette(
            primary="#86BC25",
            complementary="#E8007C",  # Magenta opposite
            accent_light="#EBF5D3",
            accent_dark="#5A8A00",
            neutral_light="#AAAAAA",
            neutral_dark="#1A1A1A",
            text_primary="#1A1A1A",
            text_inverse="#FFFFFF"
        )
        return BrandingContext(
            level=BrandingLevel.DELOITTE_DEFAULT,
            primary_color="#86BC25",
            palette=palette,
            font_family="Calibri",
            font_size_base=11,
            logo_url=None,
            company_name="Deloitte",
            custom_footer_text="Deloitte."
        )
    
    def get_branding_for_run(
        self,
        project_id: int,
        skill_card: dict | None = None,
        run_config: dict | None = None
    ) -> BrandingContext:
        """
        Resolve branding at runtime with priority:
        1. Runtime override (run config)
        2. Skill override (skill card)
        3. Project custom (ProjectBrand table)
        4. Deloitte default
        """
        
        # Priority 1: Runtime override
        if run_config and run_config.get("brand_override"):
            return self._build_from_override(run_config["brand_override"])
        
        # Priority 2: Skill override
        if skill_card and skill_card.get("brand_override"):
            return self._build_from_override(skill_card["brand_override"])
        
        # Priority 3: Project custom
        project_brand = self.db.query(ProjectBrand).filter_by(
            project_id=project_id
        ).first()
        if project_brand:
            return self._build_from_db(project_brand)
        
        # Priority 4: Deloitte default
        return self.default_brand
    
    def _build_from_db(self, project_brand: ProjectBrand) -> BrandingContext:
        """Build branding from ProjectBrand ORM"""
        palette = self._generate_palette(project_brand.primary_color)
        return BrandingContext(
            level=BrandingLevel.PROJECT_CUSTOM,
            primary_color=project_brand.primary_color,
            palette=palette,
            font_family=project_brand.font_family or "Calibri",
            font_size_base=project_brand.font_size_base or 11,
            logo_url=project_brand.logo_url,
            company_name=project_brand.company_name or "Company",
            custom_footer_text=project_brand.footer_text
        )
    
    def _build_from_override(self, override: dict) -> BrandingContext:
        """Build from runtime override dict"""
        palette = self._generate_palette(override.get("primary_color", "#86BC25"))
        return BrandingContext(
            level=BrandingLevel.RUNTIME_OVERRIDE,
            primary_color=override.get("primary_color", "#86BC25"),
            palette=palette,
            font_family=override.get("font_family", "Calibri"),
            font_size_base=override.get("font_size_base", 11),
            logo_url=override.get("logo_url"),
            company_name=override.get("company_name", "Company"),
            custom_footer_text=override.get("footer_text")
        )
    
    def _generate_palette(self, primary_hex: str) -> ColorPalette:
        """Generate harmonious color palette from primary color"""
        # Use colorspacious or similar to generate complementary, triadic, etc.
        primary_rgb = hex_to_rgb(primary_hex)
        complementary = invert_hue(primary_rgb)
        
        return ColorPalette(
            primary=primary_hex,
            complementary=rgb_to_hex(complementary),
            accent_light=lighten(primary_hex, 0.4),
            accent_dark=darken(primary_hex, 0.3),
            neutral_light="#AAAAAA",
            neutral_dark="#1A1A1A",
            text_primary="#1A1A1A",
            text_inverse="#FFFFFF"
        )
```

**Integration in coordinator**:

```python
# In coordinator.py::run()
branding_service = BrandingService(db)
branding = branding_service.get_branding_for_run(
    project_id=state.project_id,
    skill_card=state.skill_card,
    run_config=state.run_config
)

# Pass branding to all agents in AgentContext
ctx = build_agent_context(state, branding=branding)

# When rendering artifacts
for output_type in requested_outputs:
    deliverable = DeliverableRegistry.get(output_type)
    intermediate = state[deliverable.metadata.skill_output_key]
    
    output_path = workspace_path / f"output{deliverable.file_extension}"
    deliverable.render(intermediate, branding, output_path)
```

**Benefits**:
- All output types use same branding logic
- Branding resolution centralized (priority-based)
- Easy to add new branding source (skill override, run config, etc.)
- Palette generation automatic from primary color
- DB-backed custom branding per project
- No duplication across storage.py, subagents, etc.

---

### Architecture 2.3: Unified Quality Framework

**Proposed Structure**:

Create `/backend/app/core/quality_framework.py`:

```python
from abc import ABC, abstractmethod
from enum import Enum

class QualityDimension(Enum):
    """Standard dimensions across all deliverables"""
    CONTENT_QUALITY = "content_quality"
    NARRATIVE_COHERENCE = "narrative_coherence"
    VISUAL_DESIGN = "visual_design"
    BRANDING_COMPLIANCE = "branding_compliance"
    STRUCTURE_ADHERENCE = "structure_adherence"

class QualityRule(ABC):
    """Base class for pluggable quality rules"""
    dimension: QualityDimension
    applicable_output_types: set[str]  # {"pptx", "docx", ...}
    
    @abstractmethod
    def evaluate(
        self,
        artifact_path: str,
        metadata: dict,
        agent_context: AgentContext,
        branding: BrandingContext
    ) -> dict:
        """
        Evaluate artifact against this rule.
        Return: {
            "score": 0.85,
            "issues": ["Issue 1", "Issue 2"],
            "remediation_hint": "Action to fix"
        }
        """
        pass

# Concrete rules

class NarrativeCoherenceRule(QualityRule):
    """Evaluates narrative arc quality (applies to PPTX, DOCX, Narrative)"""
    dimension = QualityDimension.NARRATIVE_COHERENCE
    applicable_output_types = {"pptx", "docx", "pdf"}
    
    def __init__(self, claude_client):
        self.claude = claude_client
    
    def evaluate(self, artifact_path, metadata, agent_context, branding):
        # Extract content from artifact
        if artifact_path.endswith(".pptx"):
            content = extract_pptx_text(artifact_path)
        elif artifact_path.endswith(".docx"):
            content = extract_docx_text(artifact_path)
        else:
            return {"score": 1.0, "issues": []}
        
        # Evaluate narrative arc via Claude
        response = self.claude.generate(
            system="You are a narrative coherence expert.",
            user=f"""
            Evaluate this content for narrative coherence using this rubric:
            {NARRATIVE_COHERENCE_RUBRIC}
            
            Content:
            {content[:5000]}
            
            Return JSON: {{"score": 0.0-1.0, "issues": [], "suggestion": ""}}
            """
        )
        
        return json.loads(response)

class BrandingComplianceRule(QualityRule):
    """Validates branding applied correctly (applies to all types)"""
    dimension = QualityDimension.BRANDING_COMPLIANCE
    applicable_output_types = {"pptx", "docx", "pdf", "xlsx"}
    
    def evaluate(self, artifact_path, metadata, agent_context, branding):
        checks = {
            "primary_color_used": self._check_primary_color(artifact_path, branding),
            "logo_present": self._check_logo(artifact_path, branding) if branding.logo_url else True,
            "font_consistent": self._check_font(artifact_path, branding),
        }
        
        score = sum(checks.values()) / len(checks)
        issues = [k for k, v in checks.items() if not v]
        
        return {
            "score": score,
            "issues": issues,
            "remediation_hint": "Regenerate with proper branding applied"
        }

class ContentQualityRule(QualityRule):
    """Validates content quality (applies to all types)"""
    dimension = QualityDimension.CONTENT_QUALITY
    applicable_output_types = {"pptx", "docx", "pdf", "xlsx"}
    
    def evaluate(self, artifact_path, metadata, agent_context, branding):
        # Check metric sourcing, data validation, etc.
        signals = metadata.get("quality_signals", {})
        
        issues = []
        if signals.get("unsourced_metrics", 0) > 2:
            issues.append("Multiple unsourced metrics detected")
        
        score = 1.0 - (len(issues) * 0.1)
        
        return {"score": max(0, score), "issues": issues}

class UnifiedQualityFramework:
    """Applies rules uniformly across all output types"""
    
    def __init__(self, db: Session, claude_client):
        self.db = db
        self.claude = claude_client
        self.rules: dict[QualityDimension, list[QualityRule]] = {
            QualityDimension.NARRATIVE_COHERENCE: [NarrativeCoherenceRule(claude_client)],
            QualityDimension.BRANDING_COMPLIANCE: [BrandingComplianceRule()],
            QualityDimension.CONTENT_QUALITY: [ContentQualityRule()],
            # Add more dimensions as needed
        }
    
    def evaluate_deliverable(
        self,
        artifact_path: str,
        output_type: str,
        agent_context: AgentContext,
        branding: BrandingContext
    ) -> dict:
        """
        Evaluate artifact against all applicable rules.
        Return comprehensive quality report.
        """
        deliverable = DeliverableRegistry.get(output_type)
        
        # Extract quality signals from artifact
        quality_signals = deliverable.extract_quality_signals(artifact_path)
        
        # Evaluate each dimension
        dimension_scores = {}
        for dimension, rules in self.rules.items():
            applicable_rules = [
                r for r in rules 
                if output_type in r.applicable_output_types
            ]
            
            if not applicable_rules:
                continue
            
            rule_scores = []
            all_issues = []
            
            for rule in applicable_rules:
                result = rule.evaluate(artifact_path, quality_signals, agent_context, branding)
                rule_scores.append(result["score"])
                all_issues.extend(result.get("issues", []))
            
            dimension_scores[dimension.value] = {
                "score": sum(rule_scores) / len(rule_scores) if rule_scores else 1.0,
                "issues": all_issues
            }
        
        # Aggregate
        aggregate_score = (
            sum(d["score"] for d in dimension_scores.values()) / len(dimension_scores)
            if dimension_scores else 1.0
        )
        
        return {
            "artifact_path": artifact_path,
            "output_type": output_type,
            "aggregate_score": aggregate_score,
            "dimensions": dimension_scores,
            "passed": aggregate_score >= 0.75,  # Configurable threshold
            "timestamp": datetime.utcnow()
        }
    
    def register_rule(self, dimension: QualityDimension, rule: QualityRule) -> None:
        """Extensibility: add rules at runtime"""
        if dimension not in self.rules:
            self.rules[dimension] = []
        self.rules[dimension].append(rule)
```

**Integration in coordinator**:

```python
# In coordinator.py
quality_framework = UnifiedQualityFramework(db, claude_client)

# After rendering all artifacts
for output_type in requested_outputs:
    artifact_path = workspace_path / f"output.{deliverable.file_extension}"
    report = quality_framework.evaluate_deliverable(
        artifact_path=artifact_path,
        output_type=output_type,
        agent_context=ctx,
        branding=branding
    )
    
    state[f"quality_report_{output_type}"] = report
    
    if not report["passed"]:
        # Trigger remediation
        await _remediate_deliverable(output_type, report)
```

**Benefits**:
- Same rules apply to all output types
- Narrative coherence evaluated for PPTX, DOCX, PDF uniformly
- Easy to add new rules (register_rule)
- Dimension-based evaluation (not output-type-based)
- Remediation triggered consistently

---

### Architecture 2.4: Content Enrichment Engine

**Proposed Structure**:

Create `/backend/app/services/content_enrichment.py`:

```python
@dataclass
class ContentEnrichment:
    """Pre-agent enrichment built once, reused by all agents"""
    user_intent: UserIntent          # risk | value | capability | compliance
    audience_type: AudienceType      # executive | operational | board | team
    process_analytics: ProcessAnalytics  # steps, roles, metrics
    risk_profile: RiskProfile        # Identified risks, controls
    value_drivers: list[ValueDriver] # Cost, speed, quality improvements
    context_snippets: ContextSnippets  # Prior artifacts excerpt

class UserIntent(Enum):
    RISK_FOCUSED = "risk"
    VALUE_FOCUSED = "value"
    CAPABILITY_FOCUSED = "capability"
    COMPLIANCE_FOCUSED = "compliance"
    GENERAL = "general"

class ContentEnrichmentEngine:
    """Builds enrichment once at coordinator level, passed to all agents"""
    
    def __init__(self, db: Session, claude_client):
        self.db = db
        self.claude = claude_client
    
    def enrich(
        self,
        user_instruction: str,
        process_model: dict,
        prior_artifacts: dict
    ) -> ContentEnrichment:
        """Build enrichment for this run"""
        
        # 1. Classify user intent
        intent = self._classify_intent(user_instruction)
        
        # 2. Infer audience
        audience = self._infer_audience(user_instruction)
        
        # 3. Extract process analytics
        analytics = self._extract_analytics(process_model)
        
        # 4. Identify risks and value drivers
        risk_profile = self._build_risk_profile(process_model, intent)
        value_drivers = self._identify_value_drivers(process_model, intent)
        
        # 5. Prepare context snippets
        context = self._prepare_context(prior_artifacts)
        
        return ContentEnrichment(
            user_intent=intent,
            audience_type=audience,
            process_analytics=analytics,
            risk_profile=risk_profile,
            value_drivers=value_drivers,
            context_snippets=context
        )
    
    def _classify_intent(self, instruction: str) -> UserIntent:
        """Classify primary user intent"""
        keywords = {
            UserIntent.RISK_FOCUSED: ["risk", "mitigation", "contingency", "failure"],
            UserIntent.VALUE_FOCUSED: ["cost", "benefit", "ROI", "efficiency", "savings"],
            UserIntent.CAPABILITY_FOCUSED: ["capability", "maturity", "strength", "advantage"],
            UserIntent.COMPLIANCE_FOCUSED: ["compliance", "regulatory", "audit", "governance"],
        }
        
        for intent, keywords_list in keywords.items():
            if any(kw in instruction.lower() for kw in keywords_list):
                return intent
        
        return UserIntent.GENERAL
    
    def _infer_audience(self, instruction: str) -> str:
        """Infer intended audience"""
        if "executive" in instruction.lower() or "board" in instruction.lower():
            return "executive"
        elif "operations" in instruction.lower() or "team" in instruction.lower():
            return "operational"
        elif "audit" in instruction.lower() or "governance" in instruction.lower():
            return "board"
        return "general"
    
    def _extract_analytics(self, process_model: dict) -> ProcessAnalytics:
        """Extract quantitative analytics from ProcessModel"""
        return ProcessAnalytics(
            steps_count=len(process_model.get("steps", [])),
            roles_count=len(set(s.get("owner") for s in process_model.get("steps", []))),
            decision_points=sum(1 for s in process_model.get("steps", []) if s.get("type") == "decision"),
            handoffs=self._count_handoffs(process_model),
            critical_controls=self._extract_controls(process_model),
            cycle_time=process_model.get("metadata", {}).get("cycle_time"),
            error_rate=process_model.get("metadata", {}).get("error_rate")
        )
    
    def _build_risk_profile(self, process_model: dict, intent: UserIntent) -> RiskProfile:
        """Identify risks relevant to user intent"""
        if intent == UserIntent.RISK_FOCUSED:
            # Surface all risks
            risks = process_model.get("risks", [])
        else:
            # Surface only high-severity risks
            risks = [r for r in process_model.get("risks", []) if r.get("severity") == "high"]
        
        controls = self._extract_controls(process_model)
        
        return RiskProfile(risks=risks, controls=controls)
    
    def _identify_value_drivers(self, process_model: dict, intent: UserIntent) -> list:
        """Extract value improvement opportunities"""
        if intent == UserIntent.VALUE_FOCUSED:
            # Return all opportunities
            return process_model.get("improvement_opportunities", [])
        else:
            # Return top 3
            return process_model.get("improvement_opportunities", [])[:3]
```

**Integration in coordinator**:

```python
# In coordinator.py::run()
enrichment_engine = ContentEnrichmentEngine(db, claude_client)

enrichment = enrichment_engine.enrich(
    user_instruction=state.user_instruction,
    process_model=state.process_model,
    prior_artifacts={
        "narrative": state.get("narrative_md"),
        "docx": state.get("docx_markdown"),
        "pdf": state.get("pdf_markdown"),
    }
)

# Add to AgentContext
ctx.enrichment = enrichment  # NEW field in AgentContext

# All agents can access enrichment
# Instead of duplicating context building, agents use ctx.enrichment
```

**Benefits**:
- Content enrichment built once, reused by all agents
- Intent classification at platform level
- Audience inference shared
- Risk/value extraction shared
- Eliminates duplicate logic in agent context builders
- Easy to add new enrichment types

---

### Architecture 2.5: Agent Context Enhancement

**Proposed Change to AgentContext**:

```python
@dataclass
class AgentContext:
    # ... existing fields ...
    
    # NEW: Unified enrichment (replaces scattered context builders)
    enrichment: ContentEnrichment
    branding: BrandingContext
    
    # NEW: Deliverable metadata
    deliverable_metadata: DeliverableMetadata
    
    def get_intent_for_narrative(self) -> UserIntent:
        """Convenience method for agents"""
        return self.enrichment.user_intent
    
    def get_audience_hints(self) -> str:
        """Format audience for agent prompt"""
        if self.enrichment.audience_type == "executive":
            return "Your audience: Senior executives who value ROI and strategic impact"
        elif self.enrichment.audience_type == "operational":
            return "Your audience: Operations team who needs clear procedures and roles"
        # ...
    
    def get_risk_focus(self) -> str:
        """Format risk profile for agent prompt"""
        if self.enrichment.user_intent == UserIntent.RISK_FOCUSED:
            return f"Key risks to address: {[r.name for r in self.enrichment.risk_profile.risks[:3]]}"
        return ""
    
    def get_value_emphasis(self) -> str:
        """Format value drivers for agent prompt"""
        if self.enrichment.user_intent == UserIntent.VALUE_FOCUSED:
            drivers = ", ".join(d.name for d in self.enrichment.value_drivers[:3])
            return f"Value drivers to emphasize: {drivers}"
        return ""
```

**Agent prompt enhancement**:

```python
# In any agent (docx, pptx, xlsx, etc.)
def run_agent(ctx: AgentContext, ...):
    # Instead of duplicating context building:
    user_prompt = f"""
    {ctx.user_instruction}
    
    Audience: {ctx.get_audience_hints()}
    {ctx.get_risk_focus()}
    {ctx.get_value_emphasis()}
    
    Process Analytics:
    - {ctx.enrichment.process_analytics.steps_count} steps
    - {ctx.enrichment.process_analytics.roles_count} roles
    - {ctx.enrichment.process_analytics.decision_points} decision points
    
    Prior context:
    {ctx.enrichment.context_snippets.summary}
    """
    
    response = claude.generate(system_prompt, user_prompt)
    return AgentOutput(updates={ctx.deliverable_metadata.skill_output_key: response})
```

**Benefits**:
- Same context available to all agents
- Intent/audience/risk/value decisions made once
- Agents are simpler (less context building)
- Consistent framing across outputs
- Easy to add new context types (add to enrichment, all agents benefit)

---

## Part 3: Implementation Roadmap

### Phase 1: Foundation (3–4 weeks)

1. ✅ **Create Deliverable Abstraction** (2 weeks)
   - Define IDeliverable interface
   - Implement PPTXDeliverable, DOCXDeliverable, XLSXDeliverable, PDFDeliverable
   - Create DeliverableRegistry
   - Register deliverables at startup
   - Refactor storage.py to use registry

   **Files to create**:
   - `/backend/app/core/deliverable.py` (interface + registry)
   - `/backend/app/core/deliverable_pptx.py` (PPTX impl)
   - `/backend/app/core/deliverable_docx.py` (DOCX impl)
   - `/backend/app/core/deliverable_xlsx.py` (XLSX impl)
   - `/backend/app/core/deliverable_pdf.py` (PDF impl)
   - `/backend/app/core/deliverable_process_map.py` (Process Map impl)

   **Files to refactor**:
   - `/backend/app/services/storage.py` (use registry instead of hardcoded functions)

2. ✅ **Implement Branding Service** (1 week)
   - Create BrandingService with priority-based resolution
   - Implement ColorPalette generation
   - Implement ProjectBrand DB integration
   - Pass branding to all deliverables

   **Files to create**:
   - `/backend/app/services/branding_service.py` (centralized)
   - `/backend/app/db/models.py` addition (ProjectBrand table)

   **Files to refactor**:
   - `/backend/app/main.py` (initialize BrandingService)
   - `/backend/app/agents/coordinator.py` (get branding, pass to agents)

3. ✅ **Enhance AgentContext** (1 week)
   - Add enrichment, branding, deliverable_metadata fields
   - Add convenience methods (get_audience_hints, etc.)
   - Update build_agent_context() to populate new fields

   **Files to refactor**:
   - `/backend/app/agents/agent_types.py` (enhance AgentContext)
   - `/backend/app/agents/coordinator.py` (build branding + enrichment)

**Phase 1 Deliverable**: Pluggable architecture with centralized branding and enhanced context. All deliverables use same interface.

---

### Phase 2: Unified Quality Framework (2–3 weeks)

1. ✅ **Create Quality Framework** (1 week)
   - Define QualityRule interface
   - Implement NarrativeCoherenceRule, BrandingComplianceRule, ContentQualityRule
   - Create UnifiedQualityFramework
   - Register rules at startup

   **Files to create**:
   - `/backend/app/core/quality_framework.py` (framework + rules)

2. ✅ **Integrate with Coordinator** (1 week)
   - Replace per-type quality checks with framework
   - Apply rules uniformly to all artifacts
   - Trigger remediation based on unified scores

   **Files to refactor**:
   - `/backend/app/agents/coordinator.py` (use quality framework)
   - `/backend/app/services/deliverable_quality.py` (deprecate or integrate with framework)

**Phase 2 Deliverable**: Same quality rules apply to PPTX, DOCX, PDF uniformly. Narrative coherence evaluated for all types.

---

### Phase 3: Content Enrichment Engine (2–3 weeks)

1. ✅ **Implement Enrichment Engine** (1 week)
   - Create ContentEnrichmentEngine
   - Implement intent classification, audience inference, analytics extraction
   - Build enrichment once at coordinator level

   **Files to create**:
   - `/backend/app/services/content_enrichment.py` (engine)

2. ✅ **Simplify Agent Context Builders** (1 week)
   - Replace agent-specific context building with enrichment usage
   - Simplify _pptx_user_context_appendix, _docx_user_context_appendix, etc.
   - Agents use ctx.enrichment instead of duplicating logic

   **Files to refactor**:
   - `/backend/app/agents/subagents.py` (use enrichment instead of manual context)
   - `/backend/app/agents/coordinator.py` (build enrichment, pass to agents)

**Phase 3 Deliverable**: All agents (PPTX, DOCX, PDF, etc.) receive same enrichment (intent, audience, analytics). No duplicate context building.

---

## Part 4: Applying Original Improvements at Architecture Level

Once framework is in place, original improvements from PPT_QUALITY_IMPROVEMENTS.md apply **automatically** to all deliverables:

### Storytelling Improvements (Generalized)

| Original | Generalized to Framework |
|----------|-------------------------|
| User Intent Classification (PPTX only) | ContentEnrichmentEngine classifies once, all agents use |
| Narrative Coherence Rubric (PPTX) | QualityRule applies to PPTX, DOCX, PDF uniformly |
| Flexible Slide Sequencing (PPTX) | DeliverableRegistry supports custom orderings per type |
| Multi-Purpose Content Variants (PPTX) | AgentContext.get_audience_hints() available to all agents |
| "Why This Matters" Slots (PPTX) | Agent prompts include get_value_emphasis(), get_risk_focus() |

### Branding Improvements (Generalized)

| Original | Generalized to Framework |
|----------|-------------------------|
| Configurable Brand Palette (PPTX) | BrandingService applies to all deliverables |
| Logo Integration (PPTX) | Deliverable.apply_branding() handles logos per type |
| Dynamic Color Palette (PPTX) | ColorPalette.generate() used by all types |
| Font Flexibility (PPTX) | BrandingContext.font_family used by all deliverables |
| Branding Compliance Check (PPTX) | BrandingComplianceRule evaluates all types |

### Content Quality Improvements (Generalized)

| Original | Generalized to Framework |
|----------|-------------------------|
| Data Validation (PPTX) | ContentQualityRule applies to all types |
| Richer Descriptions (PPTX) | Agent prompts use enrichment analytics for all types |
| Contextual Data Enrichment (PPTX) | ContentEnrichmentEngine builds once, all agents access |
| Targeted Next Actions (PPTX) | Enrichment.value_drivers available to narrative, docx, etc. |

---

## Part 5: Adding New Deliverable Types (Extensibility)

With pluggable architecture, adding a new output type (e.g., video, interactive dashboard) is straightforward:

```python
# 1. Create deliverable implementation
class VideoDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="video",
            file_extension=".mp4",
            supports_branding=True,
            supports_quality_rubric=True,
            requires_rendering=True,
            intermediate_format="json",
            skill_output_key="video_script"
        )
    
    def render(self, intermediate_content, branding, output_path):
        # Convert JSON script to video file
        script = json.loads(intermediate_content)
        video = generate_video_from_script(script, branding)
        video.save(output_path)
    
    def extract_quality_signals(self, output_path):
        # Extract video metadata
        return {
            "duration": get_video_duration(output_path),
            "frame_count": get_frame_count(output_path),
            ...
        }

# 2. Register at startup
DeliverableRegistry.register("video", VideoDeliverable())

# 3. Create video agent
def run_video_agent(ctx: AgentContext, ...):
    script = claude.generate(
        f"""
        Create video script: {ctx.user_instruction}
        Audience: {ctx.get_audience_hints()}
        {ctx.get_risk_focus()}
        
        Return JSON: {{"scenes": [{...}], "duration": 300}}
        """
    )
    return AgentOutput(updates={"video_script": script})

# 4. Map in coordinator
_OUTPUT_AGENTS["video"] = run_video_agent

# 5. Done! Video inherits:
#    - Branding via BrandingService
#    - Quality evaluation via UnifiedQualityFramework
#    - Enrichment via ContentEnrichmentEngine
#    - Intent/audience/risk/value classification
```

**No changes needed to**:
- Coordinator (already uses registry)
- Quality framework (already pluggable)
- Branding service (already generic)
- Enrichment engine (already shared)

---

## Part 6: File Structure Summary

### New Files to Create

```
/backend/app/core/
├── deliverable.py                 # IDeliverable interface + registry
├── deliverable_pptx.py
├── deliverable_docx.py
├── deliverable_xlsx.py
├── deliverable_pdf.py
├── deliverable_process_map.py
├── quality_framework.py            # Quality rules + framework

/backend/app/services/
├── branding_service.py             # Centralized branding
├── content_enrichment.py           # Pre-agent enrichment

/backend/app/db/
├── migrations/
│   └── 020_project_brand.py       # ProjectBrand table migration

/backend/config/
├── quality_rules/                  # Pluggable rules
│   ├── narrative_coherence.json
│   ├── branding_compliance.json
│   └── content_quality.json
```

### Files to Refactor

1. `/backend/app/services/storage.py`
   - Remove hardcoded brand tokens
   - Use DeliverableRegistry.get(output_type).render()
   - Remove _write_pptx_output, _write_xlsx_output, etc. (move to deliverable classes)

2. `/backend/app/agents/coordinator.py`
   - Instantiate BrandingService, ContentEnrichmentEngine, UnifiedQualityFramework
   - Build enrichment once before agent routing
   - Get branding and pass to agents
   - Use quality framework instead of per-type checks

3. `/backend/app/agents/agent_types.py`
   - Add enrichment, branding, deliverable_metadata to AgentContext
   - Add convenience methods (get_audience_hints, etc.)

4. `/backend/app/agents/subagents.py`
   - Simplify context building (use ctx.enrichment)
   - Remove duplicate intent classification, analytics extraction
   - All agents use same enrichment

5. `/backend/app/services/visual_qa.py`
   - Integrate with UnifiedQualityFramework
   - Use rule-based evaluation instead of hardcoded PPTX checks

6. `/backend/app/main.py`
   - Register deliverables at startup
   - Instantiate and initialize services

---

## Part 7: Success Metrics

### Architecture Quality
| Metric | Current | Target |
|--------|---------|--------|
| Lines of code in storage.py | 800+ | 200 (just registry usage) |
| Duplicate context-building code | 6 places (one per agent) | 1 place (enrichment engine) |
| Output types with branding | 1 (PPTX) | 5+ (all) |
| Quality rules per output type | Varies | Same for all |
| Time to add new output type | 3–4 days | 1 day |

### Feature Completeness
| Feature | Current | Target | Effort |
|---------|---------|--------|--------|
| Intent-aware narratives | PPTX only | All deliverables | Phase 3 |
| Audience-specific content | None | All deliverables | Phase 3 |
| Custom branding per project | None | 100% of projects | Phase 1 |
| Narrative coherence check | None | All deliverables | Phase 2 |
| Risk-focused content | PPTX only | All deliverables | Phase 3 |
| Value-driven emphasis | PPTX only | All deliverables | Phase 3 |

---

## Conclusion

This architectural revision transforms ProcessDoc from a **PPT-centric system with scattered logic** into a **unified, pluggable platform** where:

1. **Branding applies uniformly** to all deliverables
2. **Quality rules apply uniformly** to all deliverables
3. **Enrichment (intent, audience, analytics) built once**, reused by all agents
4. **Adding new output types** requires only implementing IDeliverable interface
5. **All improvements** in PPT_QUALITY_IMPROVEMENTS.md apply **automatically** to all types

**Total Effort**: ~8–12 weeks for Phases 1–3  
**ROI**: Extensible platform that scales; no more output-type-specific code duplication

