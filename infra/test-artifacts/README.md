# ProcessDoc Test Artifacts

Realistic, professional source documents and run scenarios for manual and integration testing. The fictional client is **Northwind Manufacturing** — a mid-market manufacturer undergoing a **Procure-to-Pay (P2P)** finance transformation.

## Contents

```
infra/test-artifacts/
├── README.md                          ← this file
├── generate_binary_artifacts.py       ← builds DOCX + XLSX
├── source-documents/                  ← upload these to a project
│   ├── 01_procure_to_pay_current_state.md
│   ├── 02_discovery_workshop_notes.txt
│   ├── 03_roles_and_glossary.md
│   ├── 04_systems_and_volumes.csv
│   ├── 05_baseline_metrics_memo.md
│   ├── 06_ap_match_exception_sop_draft.docx   (generated)
│   └── 07_p2p_raci_and_kpi_workbook.xlsx      (generated)
└── run-scenarios/
    └── README.md                      ← copy-paste run instructions
```

## Quick start

### 1. Generate binary artifacts (first time)

```bash
cd infra/test-artifacts
python3 generate_binary_artifacts.py
```

Requires `python-docx` and `openpyxl` (installed with the backend venv):

```bash
cd backend && source .venv/bin/activate && pip install -e ".[dev]"
```

### 2. Upload to a project

1. Open http://localhost:3000 and create or open a project.
2. In **Documents**, upload all files from `source-documents/` (drag-and-drop supports multiple files).
3. Wait for parse confirmation — supported formats: `.md`, `.txt`, `.csv`, `.docx`, `.xlsx`.

### 3. Run a test scenario

Open `run-scenarios/README.md`, pick a scenario (A–F), and paste the instruction into Run Assistant. Confirm the plan and approve execution.

**Recommended first run:** Scenario C (executive deck) with files `01`, `02`, and `05` uploaded — fast feedback on PPTX quality without a full multi-output run.

## What each source document provides

| File | Format | Rich content for |
|------|--------|------------------|
| `01_procure_to_pay_current_state.md` | Markdown | Process steps, roles, systems, risks, metrics |
| `02_discovery_workshop_notes.txt` | Plain text | Stakeholder quotes, pain voting, action items |
| `03_roles_and_glossary.md` | Markdown | RACI primer, glossary, escalation paths |
| `04_systems_and_volumes.csv` | CSV | Systems landscape, transaction volumes |
| `05_baseline_metrics_memo.md` | Markdown | Finance memo: baseline KPIs, targets, benefits case |
| `06_ap_match_exception_sop_draft.docx` | Word | Existing SOP to refine/extend |
| `07_p2p_raci_and_kpi_workbook.xlsx` | Excel | RACI matrix, KPI sheet, exception samples |

## Design notes

- **Fictional but realistic** — metrics, role titles, SAP transaction codes, and SOX references mirror real finance transformations.
- **Cross-format** — exercises the full upload/parser pipeline (text extraction, chunking, wiki ingest).
- **Multi-output** — content supports SOP, RACI, narrative, process map, DOCX, XLSX, and PPTX generation in a single run.
- **Grounding-friendly** — explicit `(source: …)` markers and cited baseline metrics help validate QA/guardrail behavior.

## Regenerating artifacts

Safe to re-run `generate_binary_artifacts.py` at any time — it overwrites only the DOCX and XLSX files.

## Related fixtures

Automated tests use separate fixtures under `backend/tests/fixtures/` (e.g. `run_pov_apollo/` for Apollo Tyres R2R regression). This folder is for **human-driven** UI and end-to-end testing.
