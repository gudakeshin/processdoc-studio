**PROCESSDOC STUDIO**
System Architecture & Product Specification
Comprehensive Edition  —  All Versions Consolidated
AI-Powered Consulting Documentation Platform
Cowork-Style Agentic Model  |  7-Gate Guardrail Pipeline  |  DPDP Act Compliance
This document supersedes all prior versions (v1, v2, v3).
All content from prior versions is fully incorporated herein.

# **Executive Summary**

ProcessDoc Studio is an AI-powered consulting documentation platform that transforms unstructured source materials—engagement notes, interview transcripts, process descriptions, client data—into production-ready consulting deliverables: process maps (draw.io), RACI matrices, standard operating procedures (SOPs), narrative reports, gap analyses, and stakeholder presentations.
The platform is built on a Cowork-style agentic architecture. A central Coordinator agent orchestrates multiple specialist sub-agents, each running an internal tool loop (think → call tool → observe → refine). A dedicated QA Agent Loop performs Cowork-style post-generation quality review before outputs reach the seven-gate Guardrail Pipeline. All outputs are grounded in project-specific context assembled via a tiered BM25 Context Engine, with live web_search capability integrated throughout every agent.
The platform targets consulting practitioners across three domains: Strategy & Operations, Technology & Digital Transformation, and Enterprise Technology & Performance. It integrates with the firm's Microsoft OneDrive Leading Practice Library via the Graph API, enforces brand and style standards, and—as of this version—fully implements India DPDP Act 2023 compliance for all engagements involving Indian personal data.
Key differentiators: (1) Cowork-style agentic loop with HITL plan approval; (2) Dedicated QA Agent Loop (max 2 iterations) before guardrails; (3) 7-gate Guardrail Pipeline including DPDP Compliance Gate 7; (4) Real-time web_search integrated throughout all agents and QA loop; (5) User-controlled writing style (formality, persona, verbosity, audience); (6) Extensible custom skills via JSON upload; (7) Multi-user collaboration with project-level RBAC and real-time WebSocket sync.

# **1. Vision & Goals**


## **1.1 Vision Statement**

To be the intelligent documentation co-pilot for consulting practitioners—compressing the time from raw engagement data to polished client deliverable by 10x, while enforcing quality, brand compliance, and regulatory standards automatically.

## **1.2 Strategic Goals**

- Reduce document creation cycle time from days to hours for standard deliverables.
- Eliminate manual formatting, citation validation, and brand compliance checks.
- Provide a single source of truth for engagement context across multi-member project teams.
- Enable practitioners to codify and reuse firm-wide leading practices at the point of document creation.
- Ensure all outputs meet India DPDP Act 2023 requirements for engagements involving Indian personal data.
- Allow practitioners to define and share custom skill modules without engineering involvement.

## **1.3 Target Users**


# **2. System Overview**


## **2.1 High-Level Data Flow**

A user uploads source documents (PDFs, DOCX, transcripts, spreadsheets) to a project workspace and issues a natural-language instruction specifying the deliverable type and any style preferences. The Coordinator agent analyses the request, loads tiered context, selects the appropriate skill card(s), builds a work plan, and—after HITL plan approval—spawns specialist sub-agents. Each sub-agent runs an internal tool loop calling retrieve_context, search_leading_practices, web_search, draw tools, and style validators. Generated output passes through the QA Agent Loop (up to 2 iterations) and then the 7-gate Guardrail Pipeline before being written to the project run folder and surfaced to the user.

## **2.2 Technology Stack**


# **3. Architecture Diagram**

Figure 1: ProcessDocStudio v4 System Architecture — 7-layer technical stack
The diagram below shows the complete system architecture: frontend panels, Coordinator agent (8-step lifecycle), specialist sub-agents, QA Agent Loop, 7-gate Guardrail Pipeline (including DPDP Gate 7), Tool Registry (including web_search), Tiered Context Assembly Engine, Consulting Skills Registry with Custom Skills support, OneDrive LP Library integration, Style & Brand Engine, Anthropic Claude API, DPDP Compliance Engine, and Persistence layer with DPDP Consent Ledger.
Architecture v4.0 — Incorporates: Cowork-Style Agentic Loop · QA Agent Loop · 7-gate Guardrail Pipeline (incl. DPDP Gate 7) · web_search tool · Custom Skills registry · DPDP Compliance Engine · DPDP Consent Ledger. All components described in detail in Section 4.

# **4. Architecture Deep Dive**


## **4.1 Frontend — Next.js 14 App Router**

The frontend is a Next.js 14 application using the App Router. Route structure: /projects/[pid] (project home), /projects/[pid]/runs/[rid] (live run view with SSE stream), /projects/[pid]/workspace (document manager), /projects/[pid]/settings (output types, brand, DPDP), /admin/skills (custom skills library), /admin/lp-library (OneDrive LP browser).

#### **Key Frontend Panels**

- Left Panel — Document Manager: folder tree (CONTEXT.md, source_docs/, prior_runs/), drag-and-drop upload, document tagging, DPDP data classification badges.
- Centre Panel — Run Studio: instruction input with output-type selector (driven by output_types.json), writing style controls (formality / tone / persona / verbosity / audience), real-time SSE stream of agent steps and outputs, draw.io canvas with optimistic locking.
- Right Panel — Context Inspector: retrieved documents and LP snippets, relevance scores, web search results used, QA report summary, guardrail pass/fail per gate.
- DPDP Consent Panel: consent status per data principal, breach notification log, cross-border transfer warnings. Visible when project has dpdp_enabled=true.

#### **Streaming — SSEEvent Types**

The frontend uses _streamSSE() with AbortController (120 s timeout). Typed SSEEvent objects: plan_ready (HITL approval trigger), step (agent progress update), output_chunk (streaming deliverable text), qa_report (QA loop result), guardrail_event (per-gate pass/fail), done (final run manifest).

## **4.2 Backend API — FastAPI**

FastAPI application with route groups: /api/auth (JWT), /api/projects (CRUD + RBAC), /api/documents (upload, parse, list), /api/runs (create, stream, retrieve), /api/workspace/{pid}/skills (custom skills), /api/workspace/{pid}/output-types (output type config), /api/lp-library (search OneDrive), /api/dpdp (consent, breach, rights).

#### **ProcessDocState — Shared State TypedDict**

All LangGraph nodes communicate through ProcessDocState, carrying: raw_text, user_instruction, requested_outputs, process_model (Pydantic), style_profile, assembled_context, drawio_xml, raci_html, sop_markdown, narrative_md, skill_card, lp_snippets, web_search_results, qa_report, guardrail_report, dpdp_flags, run_id, project_id, workspace_path, retry_count.

#### **ProcessModel — Pydantic Intermediate Representation**

Canonical process representation: process_name (str), roles (list[str]), steps (list[ProcessStep]), decisions (list[DecisionBranch]), swimlanes (dict[str, list[str]]), metadata (dict). ProcessStep: id, name, role, inputs, outputs, tools, duration_estimate, notes. DecisionBranch: id, condition, true_path, false_path.

## **4.3 Cowork-Style Agentic Coordinator**

The Coordinator is the central orchestration node in the LangGraph StateGraph. It implements an 8-step lifecycle modelled on the Cowork architecture: Analyse → Load Context → Select Skills → Build Plan (HITL) → Spawn Sub-agents → QA Agent Loop → Guardrail Pipeline → Persist.

#### **Step 1 — Analyse Request**

Parse user_instruction to extract: requested output types (mapped against output_types.json), consulting domain (Strategy & Ops / Tech & Digital / Enterprise Tech & Perf), client context markers, and DPDP-triggering keywords (Aadhaar, PAN, UPI, health records, Indian resident data).

#### **Step 2 — Load Context (Tiered Context Assembly Engine)**

Assembles a context bundle within a 32,000-character budget across four tiers. Tier 0: CONTEXT.md + style_profile (always included, ~2K chars). Tier 0b: selected skill card (~1.5K). Tier 1: OneDrive LP Library snippets via search_leading_practices + BM25 (up to 12K). Tier 2: source_docs/ chunks via retrieve_context + multi-query expansion + MMR deduplication (up to 10K). Tier 3: prior run outputs from runs/ (up to 4.5K). Documents SHA-256 cached (TTLCache → Redis).

#### **Step 3 — Select Skills**

Load matching skill card from skill_registry.json (built-in) or custom_skills/ (user-defined). The card specifies: output types, required tools, output schema, quality thresholds, and domain-specific prompting instructions.

#### **Step 4 — Build Plan (HITL Approval)**

Emit plan_ready SSE event containing: skill card selected, context summary (document count, LP snippets retrieved, web search plan), sub-agents to spawn, estimated token budget, DPDP flags. User must explicitly approve via Run Studio UI. Plan is editable before approval.

#### **Step 5 — Spawn Sub-agents**

For each requested output type, a specialist sub-agent is instantiated with a shared state slice. Sub-agents run concurrently where the dependency graph permits. Each runs an internal tool loop: think → call_tool → observe → refine (max 3 iterations per sub-agent).

#### **Step 6 — QA Agent Loop**

After all sub-agents complete, the QA Agent reviews all outputs in a dedicated 6-step loop (max 2 iterations). Full specification in Section 4.5.

#### **Step 7 — Guardrail Pipeline**

All post-QA outputs pass sequentially through seven guardrail gates. Full specification in Section 4.6.

#### **Step 8 — Persist**

Write all outputs to runs/{run_id}/: manifest.json, drawio.xml (validated), raci.html, sop.md, narrative.md, qa_report.json, guardrail_report.json, dpdp_report.json. Update run metadata in PostgreSQL. Emit done SSE event. Append DPDP Consent Ledger records if dpdp_flags active.

## **4.4 Specialist Sub-agents**

Each sub-agent is a LangGraph node receiving a focused slice of shared state. Sub-agents are instantiated dynamically from the skill card's output_types list.

#### **Process Extraction Agent**

Parses source documents to populate ProcessModel. Uses retrieve_context and web_search for ambiguous process terminology. Validates against SIPOC, BPMN taxonomy. Produces ProcessModel JSON consumed by all downstream agents.

#### **Draw.io / Process Map Agent**

Converts ProcessModel to mxGraphModel XML. Runs xml_validator (schema / IDs / edges, max 2 retries). Applies swimlane layout algorithm. Uses check_brand_compliance to validate colour palette against brand_profile.json.

#### **RACI Agent**

Derives RACI from ProcessModel.roles and ProcessModel.steps. Calls web_search to verify role taxonomy and industry norms. Produces HTML table and CSV. Validates completeness: every step has at least one Responsible and one Accountable.

#### **SOP Agent**

Generates step-by-step SOPs from ProcessModel. Applies apply_style_profile for writing style. Uses retrieve_context to pull LP snippets as examples. Inserts validated references via validate_references.

#### **Narrative / Report Agent**

Generates executive narrative, gap analysis, or stakeholder update per skill card. Performs web_search for industry benchmarks, regulatory references, and market data. Applies check_brand_compliance and apply_style_profile.

#### **Custom Skill Sub-agents**

When a user-defined custom skill is selected, a sub-agent is configured from the custom skill JSON (see Section 4.10). It has access to the full tool registry and the same shared context slice as built-in sub-agents.

## **4.5 QA Agent Loop — Cowork-Style Quality Assurance**

[Cowork-style] The QA Agent Loop is a dedicated post-generation review stage modelled on Cowork's quality assurance pattern. It runs after all sub-agents complete and before the Guardrail Pipeline. Maximum 2 iterations per run.
The QA Agent is a full reasoning agent with access to the complete tool registry. It reviews all outputs holistically and can loop back to targeted sub-agents for correction.

#### **QA Loop — 6 Steps**

- Read & Parse Output: Read all generated outputs from shared state. For structured outputs (draw.io XML, RACI HTML), parse and validate structure. For prose, tokenise and index.
- Cross-check vs Source Documents: Use retrieve_context to pull back original source chunks. Compare claims, roles, process steps, and data values in generated outputs against source. Flag discrepancies.
- Web Search Fact Verification: For factual claims, regulatory references, industry benchmarks, and process framework citations, call web_search(query) to verify against current sources. Log all verification results.
- Logic & Coherence Check: Validate internal consistency — RACI roles match draw.io swimlane roles; SOP steps match ProcessModel steps; narrative references correct process names and role counts.
- Score & QA Report: Assign quality score (0.0–1.0) per output type across: factual accuracy, source coverage, structural completeness, style conformance. Produce qa_report.json.
- Pass (score >= 0.8) or Loop Back: If all scores >= 0.8, mark QA_PASS and proceed to Guardrail Pipeline. If any score < 0.8, issue targeted correction instructions to relevant sub-agent(s) and re-run. Maximum 2 total iterations.
QA Agent tool access: retrieve_context, web_search, validate_references, check_brand_compliance, read_document. The QA Agent does not call apply_style_profile — style is validated, not re-applied at this stage.

## **4.6 Seven-Gate Guardrail Pipeline**

After QA approval, all outputs pass sequentially through seven guardrail gates. Gate failure routes outputs back to the relevant sub-agent with specific correction instructions (max 1 retry). Persistent failures surface as user warnings.
Gate 7 is the only HARD BLOCK gate. If Gate 7 fails after 1 retry, the run is quarantined and the DPO email receives an automated breach notification report. A 72-hour DPDP notification clock starts.

## **4.7 Tool Registry**

All agents (Coordinator, specialist sub-agents, QA Agent) have access to a shared tool registry. Tools are registered with the LangGraph tool executor. Custom skills may declare additional tool dependencies.

## **4.8 Tiered Context Assembly Engine**

Invoked during Coordinator Step 2. Assembles a context bundle within a strict 32,000-character budget across four priority tiers with BM25 scoring, multi-query expansion, and MMR deduplication.

#### **Context Budget Allocation**


#### **Parse Cache & Multi-Query Expansion**

All parsed documents are SHA-256 keyed and cached (TTLCache, 1-hour TTL; production: Redis). Cache invalidated on re-upload. For Tier 2 retrieval, the instruction is expanded into 3 parallel sub-queries: (1) literal instruction, (2) process/role focused variant, (3) domain terminology variant. Results merged and MMR-deduplicated.

## **4.9 Consulting Skills Registry**

The skills registry (skill_registry.json) defines all available output types and agent configurations. Skills decouple output-type knowledge from agent code. New skills can be added without code changes.

#### **Built-in Consulting Skills**


#### **Skill Card Schema**

- id: string — unique skill identifier
- domain: string — consulting domain
- display_name: string — shown in UI output-type selector
- output_types: string[] — list of output type IDs from output_types.json
- tools: string[] — required tools from Tool Registry
- prompt_instructions: string — domain-specific additions injected into sub-agent system prompts
- quality_thresholds: object — per-output minimum QA scores (default: 0.80)
- custom: boolean — false for built-in; true for user-defined

## **4.10 Custom Skills Management**

[NEW in v4.0] Users can define and upload custom skill modules without engineering involvement. Custom skills integrate seamlessly with the Coordinator, QA Agent Loop, and Guardrail Pipeline.
Practice leads and admins create custom skills via Admin > Skills. Custom skill cards are stored in custom_skills/ and registered in skill_registry.json with custom: true. They appear in the output-type selector alongside built-in skills.

#### **Custom Skill JSON Schema (additional required fields)**

- created_by: string — user email of the creator
- version: string — semantic version (e.g., 1.0.0)
- description: string — human-readable description shown in the skill browser
- sample_instruction: string — example instruction shown to users as a prompt guide

#### **Upload Flow**

- Admin navigates to Admin > Skills > Add New Skill.
- Admin fills in the skill form (name, domain, outputs, tools, prompt instructions) or uploads a pre-authored skill JSON file.
- System validates the skill JSON against the skill card schema. Validation errors shown inline.
- Admin sets sharing scope: project-only, workspace-wide, or organisation-wide.
- Skill written to custom_skills/{skill_id}.json and registered in skill_registry.json.
- All active sessions see the new skill in the output-type selector within 30 seconds (Redis pub/sub cache invalidation).

#### **API: Custom Skills Endpoints**

POST /api/workspace/{pid}/skills — Create custom skill. Body: multipart form with skill JSON + optional icon PNG. Returns skill ID and validation report.
GET /api/workspace/{pid}/skills — List all skills (built-in + custom). Supports ?domain= and ?custom=true filters.
DELETE /api/workspace/{pid}/skills/{sid} — Delete custom skill. Requires Admin role. Error if skill referenced in active runs.

#### **Custom Skill Governance**

- Custom skills are subject to the same 7-gate Guardrail Pipeline as built-in skills.
- Organisation-scoped custom skills require Practice Lead approval before becoming visible to all users.
- Version history maintained in skill_registry.json — previous versions retained for run reproducibility.
- DPDP compliance rules apply to custom skill outputs exactly as to built-in outputs.

## **4.11 Leading Practice Library — OneDrive Integration**

The firm's LP Library is maintained in a designated OneDrive folder hierarchy, accessible via Microsoft Graph API. The integration enables contextual retrieval of relevant LP documents at generation time.

#### **Recommended OneDrive Folder Structure**

- /LP-Library/Strategy-Ops/ — strategy and operations templates and frameworks
- /LP-Library/Tech-Digital/ — digital transformation playbooks and accelerators
- /LP-Library/Enterprise-Tech/ — ERP, data, and enterprise architecture assets
- /LP-Library/Brand-Assets/ — brand_profile.json, style guides, template headers
- /LP-Library/Custom/ — organisation-specific or client-sector collections

#### **Graph API Integration**

OAuth 2.0 client credentials flow with application-level permissions (Files.Read.All on LP Library tenant). The integration: (1) indexes the LP Library folder tree on a 6-hour schedule, building a BM25 index over extracted text; (2) serves search_leading_practices(q) queries against this index; (3) returns ranked snippets with source document path, section heading, and relevance score; (4) provides direct document access via read_document(path).

#### **Security**

- LP Library is read-only from ProcessDoc Studio — no writes via this integration.
- Access tokens scoped to LP Library SharePoint site only.
- Document metadata (title, modified date, author) included in retrieval results for citation.
- DPDP-tagged LP documents excluded from retrieval when project is not DPDP-enabled.

## **4.12 Style & Brand Engine**

Ensures all outputs are consistent with firm brand standards and practitioner writing preferences. Applied at sub-agent generation time and enforced at Gate 3 (Brand Compliance) and Gate 6 (Style Enforcer).

#### **Brand Profile (brand_profile.json)**

- firm_name, firm_short_name, tagline — string identifiers
- prohibited_terms[] — terms that must not appear in client-facing outputs
- required_disclaimers[] — disclaimers auto-appended to specified output types
- colour_palette — hex codes for draw.io swimlane fills, borders, and highlights
- tone_descriptors[] — approved firm voice adjectives (e.g., professional, direct, confident, concise)
- logo_usage — rules for logo placement in headers

#### **Writing Style Controls — User-Configurable style_profile**

- formality: enum [very_formal | formal | semi_formal | conversational] — controls register and vocabulary level
- tone: enum [authoritative | collaborative | advisory | neutral] — controls framing and hedging language
- persona: string — assumed voice (e.g., 'Senior Director', 'Trusted Advisor', 'Subject Matter Expert')
- verbosity: enum [concise | balanced | detailed] — controls output length and elaboration
- audience: string — calibrates assumed knowledge level and jargon usage

## **4.13 Multi-User Workspace Management**

Every project operates within a persistent, multi-user workspace. Workspace management handles membership, RBAC, document storage, version history, and real-time collaboration.

#### **Project RBAC Roles**


#### **Workspace Folder Structure**

- workspace/{pid}/ — project root
- workspace/{pid}/CONTEXT.md — project context file
- workspace/{pid}/source_docs/ — uploaded source documents
- workspace/{pid}/runs/{run_id}/ — completed run outputs with manifest.json
- workspace/{pid}/custom_skills/ — project-scoped custom skill definitions
- workspace/{pid}/brand/ — project-level brand overrides (optional, for white-label)
- workspace/{pid}/dpdp/ — DPDP Consent Ledger and compliance records

#### **Real-Time Collaboration**

WebSocket connections (FastAPI + Redis pub/sub) provide real-time updates: document upload notifications, run status changes, plan approval requests, draw.io canvas edits (optimistic locking with version integer), and DPDP alert broadcasts.

## **4.14 Persistence Layer**


#### **Filesystem (Primary Storage)**

All workspace files, run outputs, and custom skills stored under WORKSPACE_ROOT (env var). Single-server deployment. Migration to object storage (S3 / Azure Blob) follows the same path interface.

#### **PostgreSQL (Metadata)**

Stores: project metadata, membership records, run manifests (run_id, status, timestamps, output types, QA scores, guardrail results), document registry (path, SHA-256, parse status, DPDP classification), DPDP Consent Ledger (append-only, immutable).

#### **Redis (Sessions & Real-Time)**

Session store (JWT, TTL-based), WebSocket pub/sub (one channel per project), parse cache (SHA-256 → parsed text, 1-hour TTL), web search cache (query → results, 5-min TTL), skill registry cache (invalidated on custom skill changes).

#### **DPDP Consent Ledger**

Append-only PostgreSQL table: record_id, project_id, run_id, data_principal_id (pseudonymised), consent_type, purpose, timestamp, granted_by, revoked_at (nullable). No UPDATE or DELETE — revocation inserts a new revocation record. Full audit trail exportable as CSV for DPO review.

## **4.15 DPDP Compliance Engine — India Data Protection**

[NEW in v4.0] Comprehensive compliance support for the Digital Personal Data Protection Act 2023 (India) and DPDP Rules 2025. Active for all projects with dpdp_enabled=true.
India's DPDP Act 2023 and implementing Rules (notified in phases from November 2025 through May 2027) impose obligations on Data Fiduciaries processing digital personal data of Indian residents. As a platform that may process client engagement data including Indian personal data, ProcessDoc Studio implements comprehensive DPDP compliance controls.

#### **DPDP Act 2023 — Key Obligations Addressed**

- Consent Management (Section 6): Valid consent must be free, specific, informed, unconditional, and unambiguous. The Consent Ledger records all grants with full provenance. Revocation is recorded with timestamp.
- Purpose Limitation (Section 6(3)): Personal data processed only for the specific declared purpose. The DPDP Gate 7 check validates that requested output type is consistent with declared purpose.
- Data Minimisation (Section 6(4)): PII Scanner runs pre-processing on all source documents, redacting Aadhaar, PAN, and other sensitive personal data before agents see them. Sub-agents only work with pseudonymized data ([PERSON_ID_*]), ensuring inherent data minimisation.
- Data Principal Rights (Sections 11–13): Rights to access, correction, erasure, and grievance redress. Implemented via /api/dpdp endpoints. Access requests fulfilled within 72 hours. Erasure triggers pseudonymisation of personal data across run outputs.
- Breach Notification (Section 8): 72-hour mandatory notification to Data Protection Board of India. The Breach Notifier logs the incident, starts the notification clock, and sends an alert to the configured DPO email.
- Cross-Border Transfer (Section 16): Configurable negative list per DPDP Rules 2025 Schedule. Cross-Border Flag component blocks transfers to negative-listed jurisdictions.
- Significant Data Fiduciary (Section 10): If designated as SDF by MeitY, additional controls are activated: DPIA, Data Audit, DPO appointment. Configuration flag DPDP_SDF=true enables these.

#### **DPDP Implementation — Phase Awareness**


#### **DPDP Compliance Engine — Components**

- PII Scanner (Pre-Processing): Runs on document upload, identifies India-specific PII (Aadhaar, PAN, Passport, Voter ID, UPI VPA, health records, biometric data, caste/religion), and replaces with pseudonyms ([PERSON_ID_*], etc.). Mapping stored in Consent Ledger. Uses regex + NER model. Ensures agents never see raw PII.
- Consent Ledger: Append-only PostgreSQL table (see Section 4.14). API: POST /api/dpdp/{pid}/consent, GET /api/dpdp/{pid}/consent/{principal_id}, POST /api/dpdp/{pid}/consent/revoke.
- Cross-Border Flag: Validates data transfer destinations against DPDP Rules 2025 negative list. Configurable per organisation. Integrates with cloud provider region metadata.
- Data Principal Rights Handler: Access (GET), correction (PATCH), erasure (DELETE) workflows. Erasure scans all project runs and pseudonymises identified personal data.
- Breach Notifier: On Gate 7 quarantine, logs incident, starts 72-hour clock, sends email to configured DPO. Produces breach notification report template per DPDP Rules 2025 Schedule.
- DPDP Report: Per-run dpdp_report.json recording: PII entities found/removed/redacted, consent records referenced, cross-border flags raised, Gate 7 pass/fail, data principal IDs (pseudonymised).

# **5. Feature Specifications**

Figure 2: Architecture and Feature Map — Sections 4 & 5 overview

## **5.1 Personalization Engine**

Personalization operates at three levels, with the most specific override winning: (1) Project Defaults set by the project admin in workspace/{pid}/settings.json, (2) User Persistent Overrides learned automatically from behavior and stored in users/{uid}/projects/{pid}/preferences.json, and (3) Run-Time Transient Overrides set by the user for a single run only.

#### **5.1.1 Automatic Behavioral Learning**

The system learns from user behavior without explicit configuration. When a user overrides a setting in 8 of their last 10 runs, the system suggests saving it as a persistent preference. If accepted, the override becomes the new Level 2 default. If dismissed, the system continues learning and re-triggers after 5 more instances.

#### **5.1.2 Writing Style Controls**

Style is the primary dimension of personalization. The style_profile captures: Formality (Very Formal / Formal / Semi-Formal / Conversational), Tone (Authoritative / Collaborative / Advisory / Neutral), Persona (free text, e.g. 'Senior Director'), Verbosity (Concise / Balanced / Detailed), and Audience (free text, e.g. 'C-suite executive with no technical background'). Style is resolved in order: run-level override > user persistent override > project-level style_profile > organisation default. Run-level overrides are not persisted unless the behavioral learning system detects a pattern and the user accepts the suggestion.

#### **5.1.3 Admin Visibility Panel**

Project admins can view team personalization patterns via GET /api/projects/{pid}/admin/team-personalization, including team-wide override frequencies, individual preferences, and an audit trail. Admins can see but cannot lock or prevent user overrides; governance operates through transparency and suggestion, not enforcement.

#### **5.1.4 Cross-Project Preference Sharing**

Users can export a style profile, favorite skills, and bookmarked LP documents as a reusable template stored in users/{uid}/templates/. Templates can be imported into other projects, enabling a user who creates a 'Board Materials' profile in one engagement to reuse it across the firm. Templates are user-owned and not shared unless explicitly exported.

## **5.2 Enhanced LP Library**

The Leading Practice Library is the firm's curated collection of consulting frameworks, templates, and reference materials hosted on OneDrive/SharePoint (see Section 4.11 for Graph API integration and security). This section covers user-facing LP features.

#### **5.2.1 Multi-Classification Model**

Documents can be classified with multiple labels (e.g. a CEO interview may be tagged [interview, strategy, vendor_analysis]), each triggering different LP retrieval. The system auto-classifies on upload with confidence scores (e.g. interview: 0.95, strategy: 0.88, technology: 0.72). Users can refine by unchecking low-relevance tags or adding custom tags. Classifications are stored in workspace/{pid}/documents/{doc_id}/classification.json.

#### **5.2.2 Project-Scoped Custom Document Types**

Each project can create custom types (e.g. 'Vendor RFP') that auto-assign classifications and LP associations. Types are managed by project admins via Project Settings > Document Types, stored in workspace/{pid}/document_types.json, and visible only within that project.

#### **5.2.3 LP Library Browser & Retrieval**

The LP Library Browser (Admin > LP Library) provides a browsable view of the OneDrive LP folder hierarchy. Users can preview documents, add bookmarks, and tag documents with output-type associations. During generation, the system gathers all source document classifications, builds a union set, and queries the LP library with those filters. The Context Inspector panel shows all LP snippets retrieved for the current run, ranked by relevance score.

#### **5.2.4 Iterative Refinement During Generation**

After clicking Generate and approving the plan, an LP Context Panel allows users to edit classifications, remove LP docs from context, search for additional docs, and save the refined context as a reusable template. This 'deeper effort' approach gives users visibility and control over LP selection while keeping defaults smart.

#### **5.2.5 LP Refresh & Discovery**

The LP index refreshes every 6 hours automatically. Admins can trigger a manual refresh. New documents added to OneDrive are automatically indexed on the next refresh cycle. During generation, repair scripts may discover additional LP documents; these discoveries are logged with confidence scores and offered to users after run completion.

#### **5.2.6 Citation & Traceability**

Each LP snippet in the output includes metadata: source document, section, triggering classifications, matched source documents, and relevance score. This enables end-to-end traceability of LP usage in the run manifest.

## **5.3 Plugin Architecture & Marketplace**

Plugins extend ProcessDocStudio's capabilities through a three-tier system: Marketplace (centralized registry for discovery), Project Configuration (project-level enablement and governance in workspace/{pid}/plugin_config.json), and Coordinator Router (dynamic routing of requests to the appropriate plugin sub-agent). Core plugins are pre-configured: Finance, Data, Productivity, and Excel.

#### **5.3.1 Skill & Plugin Browser**

The Skill Browser (Admin > Skills) provides a searchable, filterable grid of all skills (built-in and custom). Each card shows: display name, domain, supported output types, version, and usage count. The Plugin Marketplace is accessible from the same panel for discovering and installing additional plugins.

#### **5.3.2 Skill Creation Wizard**

Step-by-step wizard for creating custom skills: (1) Basic info (name, domain, description), (2) Output types selection, (3) Tool requirements, (4) Prompt template with variable placeholders, (5) Validation and preview. See Section 4.10 for the full custom skill JSON schema and governance rules.

#### **5.3.3 Versioning & Rollback**

Each skill or plugin edit creates a new version. Previous versions are retained. Run manifests record the exact skill version used, enabling reproducibility and rollback if a new version degrades quality.

#### **5.3.4 Sandboxed Execution**

Plugin code executes in isolated containers: 5-second timeout, 100 MB memory limit, no external network access, PII redaction before execution. Failures are logged and can trigger escape hatch repair scripts.

#### **5.3.5 Tool-Level Governance**

Governance is enforced at the individual tool level, not the plugin level. An admin can block a specific tool without disabling the entire plugin. Tool governance includes: block execution, require approval for high-risk tools, enforce data classification rules, and full input/output audit logging.

## **5.4 Analytical Modeling Engine**

The Analytical Modeling Engine provides a generic framework for building structured models. The system does not prescribe model types; users define what they need (financial forecasts, operational simulations, resource plans, cost-benefit analyses, capacity models, or any domain-specific model). The engine provides the infrastructure: data ingestion, assumption management, versioning, scenario comparison, and output generation.

#### **5.4.1 Model Definition & Data Ingestion**

Users define a model by specifying: input data sources (Excel, CSV, database, or manual entry), assumption cells (editable parameters the model depends on), calculation logic (formulas, relationships, or agent-generated computations), and output structure (tables, charts, dashboards). The system infers schema from uploaded data and provides summary statistics for validation before modeling begins.

#### **5.4.2 Scenario Management**

Any model can have multiple named scenarios. Each scenario is a set of assumption overrides (e.g. 'Optimistic' increases growth rate, 'Conservative' reduces it). Users can compare scenarios side-by-side and the system generates variance explanations between them. Scenario definitions are stored alongside the model in workspace/{pid}/models/{model_id}/scenarios.json.

#### **5.4.3 Timestamp-Based Version Management**

Each model run produces an immutable snapshot versioned as {model_id}_v_{YYYYMMDD_HHMMSS}. Versions capture the complete state: inputs, assumptions, calculations, and outputs. Users can browse version history, compare versions, and restore previous versions. The audit trail records who generated each version and when.

#### **5.4.4 Interactive Dashboards**

Models can be visualized as self-contained interactive HTML dashboards with: KPI summary cards, time-series and comparison charts, variance waterfalls, scenario toggles, and drill-down to underlying data and assumptions. Dashboards are generated using Chart.js and can be viewed standalone or embedded in reports.

## **5.5 Excel Integration**

Excel is a first-class data format throughout ProcessDocStudio. The system can read, analyze, generate, edit, and sync Excel files.

#### **5.5.1 Read & Analyze**

Upload from local disk, OneDrive, or SharePoint. The system infers schema (column names, data types, date ranges), calculates data quality metrics (null counts, duplicates, outliers), and provides summary statistics. Analyzed data is available as context for generation, modeling, or further analysis.

#### **5.5.2 Generate & Edit**

Generate complete Excel workbooks with multiple sheets, formulas, cell formatting, validation rules, and charts. Locked formula cells protect model integrity while editable assumption cells allow user iteration. Existing workbooks can be enhanced with new sheets, updated formulas, or conditional formatting, with dependency validation to prevent breakage.

#### **5.5.3 Real-Time Bidirectional Sync**

Files stored on OneDrive/SharePoint can be synchronized on a configurable interval (default 5 minutes, target latency <30 seconds). Conflict resolution: last-write-wins on user-editable assumption cells (natural iteration), ProcessDoc wins on computed/formula cells (model integrity). Full audit trail of all changes with timestamp and user.

## **5.6 Configurable Output Formats**

All output types are defined in output_types.json. No output types are hardcoded. Each entry specifies: output_type_id, display_name, description, required_skills, output_file_type, and template_ref. Built-in output types include: SOP Document, RACI Matrix, Process Map, and Executive Summary. Custom output types can be registered by project admins, linked to custom skills.

## **5.7 DPDP Act Compliance**

See Section 4.15 for the full DPDP Compliance Engine architecture. This section covers user-facing compliance workflows only.

#### **5.7.1 Enabling DPDP Mode**

DPDP mode is enabled per-project by the Owner: Project Settings > Data Privacy > Enable DPDP Compliance. A persistent DPDP banner appears in the UI. DPDP-sensitive documents are flagged at upload and trigger Gate 7 for all runs that use them.

#### **5.7.2 Consent Management UI**

The DPDP Consent Panel shows: registered Data Principals, consent status (granted / revoked / pending), purpose statement, and grant/revocation timestamps. New consent can be recorded via the panel or API.

#### **5.7.3 Data Principal Rights & Breach Workflow**

Rights requests (access, correction, erasure) are logged via /api/dpdp/rights and surface in the DPDP Consent Panel as a work queue. If Gate 7 quarantines a run, the incident appears in the Breach Log with a 72-hour countdown timer for DPBI notification per DPDP Act requirements.

## **5.8 QA & Web Search**

See Sections 4.5 and 4.6 for full QA Agent Loop and Guardrail Pipeline architecture. This section covers user-facing quality features.

#### **5.8.1 QA Report**

After each run, the QA Report appears in the Context Inspector Panel showing: per-output quality scores (0.0-1.0), factual claims verified vs. flagged, source coverage analysis, and LP association quality. The default pass threshold is 0.80, configurable per project via Project Settings > Quality Settings.

#### **5.8.2 Web Search Integration**

web_search is a first-class tool throughout the agent architecture: specialist sub-agents call it when source documents lack context (industry benchmarks, regulatory requirements, process standards), the QA Agent uses it for mandatory fact verification, and Guardrail Gates 2 and 4 use it for hallucination checks and URL validation. Primary provider: Brave Search API; fallback: Google Custom Search API. Results cached for 5 minutes in Redis, rate-limited to 60 requests/minute per project.

# **6. API Surface**


## **6.1 Authentication**


## **6.2 Projects**


## **6.3 Documents**


## **6.4 Runs**


## **6.5 Custom Skills**


## **6.6 DPDP Compliance**


# **7. User Stories**


## **7.1 Core Generation Workflow**

- As an Analyst, I want to upload engagement interview transcripts and receive a formatted process map and RACI matrix within 10 minutes, so that I can focus on analysis rather than formatting.
- As an Engagement Manager, I want to review and approve the agent's work plan before document generation, so that I retain control over deliverable scope.
- As an Analyst, I want to see which LP documents and web sources the agent used in each output, so that I can cite them accurately in client presentations.
- As an Analyst, I want the QA Agent to automatically fact-verify the generated narrative against current web sources, so that I do not manually check every figure.

## **7.2 Workspace & Collaboration**

- As an Engagement Manager, I want to invite analysts and reviewers with appropriate permissions, so that the team can collaborate without sharing files over email.
- As a team member, I want to see real-time updates when a colleague uploads a document or completes a run.
- As an Editor, I want to edit CONTEXT.md in the browser and have it immediately affect the next run.

## **7.3 Custom Skills**

- As a Practice Lead, I want to define a custom 'Regulatory Compliance Review' skill generating our firm's standard compliance checklist format, so my team does not prompt-engineer this each time.
- As an Admin, I want to approve custom skills before they are shared organisation-wide, to maintain quality and brand standards.
- As a Practitioner, I want to see which version of a skill was used for a prior run, so that I can reproduce the output.

## **7.4 Style & Brand**

- As an Engagement Manager, I want to set 'Formal / Authoritative / Senior Director persona' for Board-level deliverables and 'Semi-Formal / Collaborative' for workshop materials.
- As an Admin, I want to upload a custom brand_profile.json for a white-label client engagement, so outputs use the client's colour palette and terminology.

## **7.5 DPDP Compliance**

- As a Compliance Officer, I want the system to automatically detect and redact Aadhaar numbers and PAN cards from generated outputs, so we do not inadvertently include Indian PII in deliverables.
- As a DPO, I want an automated email notification within 1 hour of any Gate 7 quarantine event, so I can assess whether a 72-hour DPDP breach notification to DPBI is required.
- As a Data Principal, I want to submit an erasure request that removes my personal data from all project run outputs, to exercise my rights under DPDP Act 2023.
- As a Compliance Officer, I want a per-run DPDP report showing all PII entities found, redacted, and the consent basis for retained personal data.

# **8. Requirements (MoSCoW)**


## **8.1 Must Have**

- Cowork-style Coordinator with 8-step lifecycle (M1)
- Specialist sub-agents for all built-in output types (M2)
- Dedicated QA Agent Loop (max 2 iterations, score >= 0.8 threshold) (M3)
- 7-gate Guardrail Pipeline including DPDP Gate 7 (M4)
- web_search(query) tool integrated across all agents and QA loop (M5)
- HITL plan approval before run execution (M6)
- Tiered Context Assembly Engine with 32K budget (M7)
- Multi-user workspace with RBAC (Owner/Editor/Viewer) (M8)
- OneDrive LP Library integration via Graph API (M9)
- output_types.json registry — no hardcoded output types (M10)
- User-controlled writing style_profile (M11)
- DPDP Compliance Engine: PII Scanner, Consent Ledger, breach notification (M12)
- JWT authentication with project-level RBAC enforcement (M13)
- SSE streaming of run events to frontend (M14)

## **8.2 Should Have**

- Custom skills management — create, upload, version, share (S1)
- Draw.io canvas with real-time collaboration and optimistic locking (S2)
- Plagiarism check Gate 5 advisory (S3)
- DPDP Data Principal rights handler (access, correction, erasure) (S4)
- LP Library browser and document tagging in Admin UI (S5)
- QA score threshold configuration per project (S6)
- Web search result caching and rate limiting (S7)
- Cross-border transfer enforcement (DPDP Section 16 negative list) (S8)

## **8.3 Could Have**

- Significant Data Fiduciary (SDF) enhanced controls (DPIA, data audit) (C1)
- Skill performance analytics (usage, QA scores per skill) (C2)
- LP Library contribution flow (practitioners submit new LP documents) (C3)
- Multi-language support for non-English source documents (C4)
- API webhooks for external system integration (C5)
- Export run outputs to SharePoint / OneDrive automatically (C6)

## **8.4 Won't Have (This Release)**

- Mobile app (W1)
- Real-time voice-to-text document capture (W2)
- Automated client portal publishing (W3)
- Third-party eSignature integration (W4)

# **9. Success Metrics**


# **10. Open Questions**


# **Appendix A — Environment Variables**


# **Appendix B — Glossary**
