---
id: brd_v1
domain: Business Analysis
display_name: Business Requirements Document Specialist
output_types:
- docx
- pptx
version: 1.0.0
description: Creates formal, traceable Business Requirement Documents (BRDs) with
  functional and non-functional requirements. Use when users ask for BRD, FRD, requirements
  specification, or requirement registers.
use_when: the user asks to write, create, or draft a BRD, requirements specification,
  functional specification, FRD, requirements register, or asks to document what the
  system/process must do
tools:
- retrieve_context
- memory_lookup
- qa_validator
workflow_steps:
- Identify BRD type (system, process, integration, or report) and domain context
- Collect and bound scope, stakeholders, objectives, assumptions, and constraints
- Draft all 10 sections with traceable functional and non-functional requirements
- Run QA checks for EARS syntax, ID traceability, MoSCoW prioritization, and measurable
  NFRs
feedback_loop:
- Check 10-section completeness
- Validate requirement quality and testability
- Fix ambiguity, missing traceability, or solution leakage
- Finalize with sign-off and change-control clarity
freedom_level: low
quality_thresholds:
  docx: 0.92
  pptx: 0.9
acceptance_checks:
- All 10 BRD sections are present and labeled
- Functional requirements use EARS syntax and unique IDs
- Each requirement has a MoSCoW priority
- Non-functional requirements are measurable and compliance-specific where applicable
- Governance includes traceability, sign-off authority, and change control
default_representation: docx
companion_files:
- ./deloitte_brd_leading_practices.md
- ./sap_s4hana_requirements_primer.md
source_url: brd.skill
sample_instruction: Draft a BRD for an FP&A planning platform with EARS-based functional
  requirements, measurable NFRs, MoSCoW priorities, traceability IDs, and an optional
  stakeholder summary deck.
custom: false
---

Use the BRD method from brd.skill. Produce a 10-section BRD that clearly separates requirements from solution design: Executive Overview, Scope, Stakeholders and User Roles, Current State Baseline, Assumptions/Dependencies/Constraints, Functional Requirements, Non-Functional Requirements, Data Requirements, Reporting and Output Requirements, and Governance/Traceability/Sign-off. Enforce EARS syntax for functional requirements, MoSCoW priority, requirement IDs, and measurable non-functional criteria. Default to DOCX as the authoritative artifact, with PPTX summary output when requested.

Apply consulting-grade depth using the companions in this folder: `deloitte_brd_leading_practices.md` (traceability, RTM, anti-patterns) and `sap_s4hana_requirements_primer.md` when the programme is SAP/S/4HANA (fit–standard–gap, Activate phase alignment). Optional QA: `python scripts/check_brd_sections.py` on markdown drafts.

## Progressive Loading Branches

- **SAP / S4HANA programs**: load `sap_s4hana_requirements_primer.md` first, then `deloitte_brd_leading_practices.md`.
- **Non-SAP programs**: load only `deloitte_brd_leading_practices.md`.
- **PPTX summary requested**: keep DOCX as source of truth; derive PPTX from finalized section map instead of re-authoring from scratch.
