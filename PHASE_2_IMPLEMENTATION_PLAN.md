# Phase 2 Implementation Plan: Generalized Deliverable Architecture

**Date**: 2026-04-08  
**Status**: Planning  
**Duration**: 4-6 weeks  
**Objective**: Extend Phase 1 fixes to all deliverables (PPTX, DOCX, PDF, XLSX) through architectural abstraction

---

## Context

Phase 1 successfully fixed blank PPTX slides through 5 targeted fixes. However, these fixes are PPTX-specific scattered across the codebase.

**Phase 2 Goal**: Generalize Phase 1 patterns into a pluggable architecture so:
- All deliverables benefit from improvements
- New output types inherit fixes automatically
- Quality rules apply uniformly
- Branding is centralized
- Content enrichment is reusable

---

## Architecture Overview

### Current State (Before Phase 2)
```
Coordinator
  ├─ PPTX Agent → storage.py (PPTX rendering) → deliverable_quality.py (PPTX validation)
  ├─ DOCX Agent → storage.py (DOCX rendering) → deliverable_quality.py (DOCX validation)
  ├─ PDF Agent → storage.py (PDF rendering) → deliverable_quality.py (PDF validation)
  └─ Narrative Agent → (no validation)

Problem: Duplication, scattered logic, no uniform patterns
```

### Desired State (After Phase 2)
```
Coordinator
  ├─ Content Enrichment Engine (once per run)
  │  └─ Builds metrics, risks, value drivers
  │
  ├─ Agent (any type: PPTX, DOCX, PDF, etc.)
  │  └─ Receives enriched context
  │
  ├─ Deliverable Registry (routes by type)
  │  ├─ IDeliverable (PPTX impl)
  │  ├─ IDeliverable (DOCX impl)
  │  ├─ IDeliverable (PDF impl)
  │  └─ IDeliverable (custom impl)
  │
  ├─ Branding Service (centralized)
  │  └─ Applies to all types
  │
  ├─ Unified Quality Framework
  │  ├─ Pluggable quality rules
  │  └─ Applies to all types
  │
  └─ Output (any type, same quality standard)
```

---

## Phase 2 Scope: 3 Core Components

### Component 1: Deliverable Abstraction

**Purpose**: Eliminate output-type-specific code scattered in storage.py

**Design**:
```python
# Interface
class IDeliverable(ABC):
    """Contract all deliverables must implement"""
    
    @abstractmethod
    def render(self, data: dict) -> bytes:
        """Generate output file (PPTX, DOCX, PDF, etc.)"""
        pass
    
    @abstractmethod
    def validate(self, data: dict) -> ValidationResult:
        """Check completeness, structure, content"""
        pass
    
    @abstractmethod
    def apply_branding(self, data: dict) -> dict:
        """Apply consistent branding"""
        pass

# Implementations
class PPTXDeliverable(IDeliverable):
    def render(self, data): ... # Extracted from storage.py
    def validate(self, data): ... # _validate_pptx_completeness
    def apply_branding(self, data): ... # Apply color palette

class DOCXDeliverable(IDeliverable):
    def render(self, data): ... # Extracted from storage.py
    def validate(self, data): ... # DOCX validation
    def apply_branding(self, data): ... # Apply styles

# Registry
class DeliverableRegistry:
    _implementations = {
        "pptx": PPTXDeliverable,
        "docx": DOCXDeliverable,
        "pdf": PDFDeliverable,
    }
    
    @classmethod
    def get(cls, output_type: str) -> IDeliverable:
        impl = cls._implementations.get(output_type)
        if not impl:
            raise ValueError(f"Unknown output type: {output_type}")
        return impl()
```

**Benefits**:
- ✅ PPTX logic no longer scattered in storage.py
- ✅ New output type added in 1 day (not 3-4)
- ✅ Uniform interface for all types
- ✅ Easy to test each type independently

**Files to Create**:
- `/backend/app/core/deliverable.py` — IDeliverable interface + registry
- `/backend/app/core/deliverable_pptx.py` — PPTX implementation
- `/backend/app/core/deliverable_docx.py` — DOCX implementation
- `/backend/app/core/deliverable_pdf.py` — PDF implementation

**Files to Refactor**:
- `/backend/app/services/storage.py` — Remove rendering logic, use registry

---

### Component 2: Branding Service

**Purpose**: Centralized, extensible branding for all deliverables

**Design**:
```python
# Branding config (per project/org)
class BrandingProfile:
    """Brand definition: colors, fonts, logos, styles"""
    
    colors: dict = {
        "primary": "#2E7D32",  # Green
        "accent": "#1565C0",   # Dark blue
        "warning": "#F57C00",  # Orange
    }
    
    fonts: dict = {
        "heading": "Montserrat",
        "body": "Open Sans",
    }
    
    logos: dict = {
        "main": "path/to/logo.png",
        "favicon": "path/to/favicon.ico",
    }
    
    # Per-type customization
    pptx_theme = {...}
    docx_template = {...}
    pdf_styles = {...}

# Service (applies branding)
class BrandingService:
    def __init__(self, profile: BrandingProfile):
        self.profile = profile
    
    def apply_to_pptx(self, pptx_data: dict) -> dict:
        """Apply branding to PPTX slides"""
        for slide in pptx_data.get("slides", []):
            # Apply color tokens
            for card in slide.get("stat_cards", []):
                card["fill"] = self.profile.colors.get("primary")
        return pptx_data
    
    def apply_to_docx(self, docx_data: dict) -> dict:
        """Apply branding to DOCX document"""
        # Apply font, color, logo
        return docx_data
    
    def apply_to_pdf(self, pdf_data: dict) -> dict:
        """Apply branding to PDF"""
        # Apply header/footer, watermark
        return pdf_data
```

**Benefits**:
- ✅ Brand changes apply to all types automatically
- ✅ Per-project custom branding supported
- ✅ No hardcoded colors/fonts in storage.py
- ✅ Easy A/B testing of visual variants

**Files to Create**:
- `/backend/app/services/branding_service.py` — BrandingService + BrandingProfile
- `/backend/config/branding/default.json` — Default branding profile
- `/backend/config/branding/custom/*.json` — Per-project overrides

**Configuration**:
```yaml
# settings.json or .env
branding_profile: "default"  # or "custom_acme" for specific org
```

---

### Component 3: Unified Quality Framework

**Purpose**: Single quality system for all deliverables

**Design**:
```python
# Quality rule interface
class QualityRule(ABC):
    """Single rule evaluated against any deliverable"""
    
    @abstractmethod
    def evaluate(self, deliverable_data: dict, output_type: str) -> QualityScore:
        """Return score (0-1) and diagnostics"""
        pass

# Concrete rules (reusable across types)
class Completeness Rule(QualityRule):
    """Check that all required sections/slides present"""
    
    def evaluate(self, data: dict, output_type: str) -> QualityScore:
        if output_type == "pptx":
            return _validate_pptx_completeness(data)  # Phase 1 reused
        elif output_type == "docx":
            return _validate_docx_structure(data)
        elif output_type == "pdf":
            return _validate_pdf_completeness(data)

class NarrativeCoherenceRule(QualityRule):
    """Check that content follows logical flow"""
    def evaluate(self, data: dict, output_type: str) -> QualityScore:
        # Applies to narrative_md + all document types
        pass

class BrandingComplianceRule(QualityRule):
    """Check that branding is applied correctly"""
    def evaluate(self, data: dict, output_type: str) -> QualityScore:
        # Applies to all visual types
        pass

class ContentDensityRule(QualityRule):
    """Check slide/page density (not too sparse, not too crowded)"""
    def evaluate(self, data: dict, output_type: str) -> QualityScore:
        # Applies to PPTX, DOCX, PDF
        pass

# Quality Framework
class UnifiedQualityFramework:
    def __init__(self):
        self.rules = [
            CompletenessRule(weight=0.3),
            NarrativeCoherenceRule(weight=0.25),
            BrandingComplianceRule(weight=0.2),
            ContentDensityRule(weight=0.15),
            # Can add more rules
        ]
    
    def evaluate(self, deliverable_data: dict, output_type: str) -> QualityReport:
        """Evaluate against all rules, return aggregate score"""
        scores = []
        for rule in self.rules:
            score = rule.evaluate(deliverable_data, output_type)
            scores.append((rule.weight, score))
        
        aggregate = weighted_average(scores)
        return QualityReport(
            aggregate=aggregate,
            rule_scores=scores,
            passed=aggregate >= 0.72,
        )
```

**Benefits**:
- ✅ Same rules evaluate all deliverable types
- ✅ New rule added once, applies everywhere
- ✅ Narrative + visual types evaluated consistently
- ✅ Extensible without modifying framework

**Files to Create**:
- `/backend/app/core/quality_framework.py` — Unified framework
- `/backend/app/core/quality_rules/` directory with:
  - `completeness_rule.py`
  - `narrative_coherence_rule.py`
  - `branding_compliance_rule.py`
  - `content_density_rule.py`

---

## Implementation Roadmap

### Week 1-2: Deliverable Abstraction
1. **Day 1-2**: Design IDeliverable interface
2. **Day 3-4**: Extract PPTX logic from storage.py → PPTXDeliverable
3. **Day 5**: Create DeliverableRegistry, update Coordinator to use it
4. **Test**: Verify existing PPTX generation still works (regression test)

**Success Criteria**:
- ✅ PPTXDeliverable works identically to old code
- ✅ Registry routes correctly
- ✅ Storage.py simplified

### Week 2-3: Branding Service
1. **Day 1-2**: Design BrandingProfile + BrandingService
2. **Day 3-4**: Implement PPTX branding application
3. **Day 5**: Add DOCX and PDF branding
4. **Test**: Apply custom brand to deck, verify colors/fonts

**Success Criteria**:
- ✅ Default branding applied automatically
- ✅ Custom branding loaded from config
- ✅ Colors, fonts, logos applied correctly

### Week 3-4: Unified Quality Framework
1. **Day 1-2**: Design QualityRule interface + framework
2. **Day 3-4**: Implement CompletenessRule (reusing Phase 1 code)
3. **Day 5**: Implement NarrativeCoherenceRule + BrandingComplianceRule
4. **Test**: Evaluate decks against all rules

**Success Criteria**:
- ✅ All deliverables evaluated consistently
- ✅ Phase 1 validation rules (completeness) reused
- ✅ New rules apply to multiple types automatically

### Week 4-5: Extended Output Types
1. **Day 1-3**: Apply abstraction to DOCX, PDF
2. **Day 4-5**: Add new output type (XLSX) as proof-of-concept

**Success Criteria**:
- ✅ DOCX uses IDeliverable pattern
- ✅ PDF uses IDeliverable pattern
- ✅ XLSX type added in 1 day (proves extensibility)

### Week 5-6: Testing & Documentation
1. **Day 1-2**: Regression testing (all existing types work)
2. **Day 3-4**: Integration testing (branding + quality framework work together)
3. **Day 5-6**: Update docs, create extension guide

**Success Criteria**:
- ✅ No regressions in existing functionality
- ✅ All deliverables pass quality gates
- ✅ Developer guide for adding new types

---

## Deliverables

### Code
- [ ] IDeliverable interface + registry
- [ ] PPTXDeliverable, DOCXDeliverable, PDFDeliverable implementations
- [ ] BrandingService + BrandingProfile
- [ ] QualityRule interface + concrete rules
- [ ] UnifiedQualityFramework
- [ ] Updated Coordinator to use new abstractions
- [ ] Integration tests
- [ ] Regression tests

### Documentation
- [ ] Architecture diagram
- [ ] Component interaction diagram
- [ ] Developer guide: Adding new output type
- [ ] Developer guide: Adding new quality rule
- [ ] Migration guide: Updating agents for new context
- [ ] API reference

### Configuration
- [ ] Default branding profile
- [ ] Example custom branding profiles
- [ ] Quality framework configuration

---

## Success Criteria

### Functional
- [x] All existing deliverables work (no regressions)
- [ ] Branding applies consistently across types
- [ ] Quality rules evaluate all types uniformly
- [ ] New output type can be added in 1 day

### Non-Functional
- [ ] Code duplication reduced by 40%
- [ ] Performance impact: <2% slower
- [ ] Test coverage: ≥85%

### User-Facing
- [ ] All deliverables meet quality bar
- [ ] Consistent branding across types
- [ ] Clear error messages if incomplete
- [ ] Automatic remediation for incomplete content

---

## Risks & Mitigations

### Risk 1: Breaking existing PPTX generation
**Probability**: Medium  
**Impact**: High  
**Mitigation**: Extract code carefully, run regression tests after each step

### Risk 2: Branding config too complex
**Probability**: Low  
**Impact**: Medium  
**Mitigation**: Start with simple profile, expand gradually

### Risk 3: Quality framework rules conflict
**Probability**: Low  
**Impact**: Medium  
**Mitigation**: Define clear rule precedence and weighting

### Risk 4: Performance regression from abstraction
**Probability**: Low  
**Impact**: Medium  
**Mitigation**: Profile before/after, optimize hot paths

---

## Dependencies

### On Phase 1
- ✅ Completeness validation (reuse _validate_pptx_completeness)
- ✅ Quality gate pattern (reuse remediation pipeline)
- ✅ Metrics injection (use ctx.enrichment)

### External
- [ ] No new dependencies
- [ ] Uses existing: pydantic, python-pptx, python-docx, pypdf

### On Other Work
- [ ] Assumes coordinator already uses ContentEnrichmentEngine
- [ ] Assumes agents receive enriched context

---

## Estimated Effort

| Component | Effort | Duration |
|-----------|--------|----------|
| Deliverable Abstraction | 20 hrs | Week 1-2 |
| Branding Service | 15 hrs | Week 2-3 |
| Quality Framework | 18 hrs | Week 3-4 |
| Extended Types (DOCX, PDF) | 12 hrs | Week 4-5 |
| Testing & Docs | 15 hrs | Week 5-6 |
| **TOTAL** | **80 hrs** | **6 weeks** |

---

## Post-Phase-2 Impact

### Velocity Improvement
- Adding new output type: 3-4 weeks → **1 day**
- Implementing quality improvement: affects 1 type → **affects all types**
- Branding update: manual per type → **automatic for all**

### Code Quality
- Duplication reduced: 40%
- Testability improved: Each type tested independently
- Maintainability improved: Changes in one place apply everywhere

### User Experience
- Consistent quality across deliverables
- Automatic improvements (Phase 1 logic applies to DOCX, PDF, etc.)
- Faster issue resolution (single framework to debug)

---

## Next Steps (Immediate)

1. **Design Review**: Present architecture to team
2. **Approval**: Confirm scope and timeline
3. **Spike**: Proof-of-concept extracting PPTX logic
4. **Kick-off**: Assign team, start Week 1

---

**Phase 2 Status**: Ready for design review  
**Confidence**: High (builds on proven Phase 1 patterns)  
**Recommendation**: Proceed with implementation  

