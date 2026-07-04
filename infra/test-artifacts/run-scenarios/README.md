# Test run scenarios — Northwind P2P

Copy the **instruction** into Run Assistant or Run Studio after uploading source documents from `../source-documents/`.

Recommended upload set for full scenarios: all files `01`–`07`.

---

## Scenario A — Full deliverable pack

**Goal:** Exercise SOP, RACI, narrative, process map, DOCX, and XLSX in one run.

**Instruction:**

```
Using the uploaded Northwind Manufacturing Procure-to-Pay source documents, produce a complete transformation deliverable pack:

1. Standard Operating Procedure (DOCX) for three-way match exception handling — align with the existing SOP draft and workshop notes
2. RACI matrix (XLSX) covering all P2P activities across US, EU, and Summit entities
3. Process narrative (DOCX) summarizing current state, pain points, and target-state recommendations
4. Process map (draw.io) for the end-to-end P2P cycle with swimlanes for Requester, Procurement, Warehouse, AP, and Treasury
5. Executive summary deck (PPTX) — 8–10 slides for the Controller and board steering committee

Ground all metrics in the uploaded KPI baseline. Flag SOX and segregation-of-duties risks explicitly. Use a professional consulting tone.
```

---

## Scenario B — RACI and Excel only

**Goal:** Fast run focused on spreadsheet output and role clarity.

**Instruction:**

```
From the Northwind P2P workshop materials, create an Excel RACI matrix for all Procure-to-Pay activities. Include a second sheet with KPI baseline vs. target from the source metrics. Highlight Summit NetSuite SOD conflicts in a comment column.
```

---

## Scenario C — Executive deck

**Goal:** Test PPTX pipeline, storyline, and slide composition.

**Instruction:**

```
Build a 10-slide executive presentation for Northwind Manufacturing's P2P transformation program. Cover: situation/complication, current-state pain points with quantified metrics, transformation pillars, 90-day quick wins, 18-month roadmap, and expected benefits. PPTX only. Cite sources from uploaded documents.
```

---

## Scenario D — Process map and SOP

**Goal:** Test process extraction, diagram generation, and procedural documentation.

**Instruction:**

```
Create a detailed process map for Northwind's Procure-to-Pay cycle from requisition through payment. Include decision points for match exceptions and escalations. Also produce a polished SOP (DOCX) for AP exception handling that references SAP transaction codes from the source materials.
```

---

## Scenario E — Wiki ingest smoke test

**Goal:** Validate document upload + wiki ingestion without a full run.

**Steps:**

1. Upload `01_procure_to_pay_current_state.md` and `02_discovery_workshop_notes.txt`
2. Open Project Wiki → Ingest → confirm nodes created
3. Ask Run Assistant: "What are the top P2P pain points from our project wiki?"

---

## Scenario F — Guardrail / grounding stress test

**Goal:** Test QA and source-grounding behavior.

**Instruction:**

```
Write a 5-page approach note on Northwind P2P transformation with specific percentage improvements and dollar savings. Every quantitative claim must cite an uploaded source document. Include a 'Sources and assumptions' section.
```

---

## Expected outputs by type

| Output type | Scenarios | Typical artifact |
|-------------|-----------|------------------|
| `docx` | A, D, F | SOP, narrative, approach note |
| `xlsx` | A, B | RACI matrix, KPI workbook |
| `pptx` | A, C | Executive steering deck |
| `process_map` | A, D | draw.io swimlane diagram |
| `narrative` | A, F | Long-form transformation story |

---

## Tips

- Upload documents **before** confirming the run plan so the coordinator can ground outputs.
- For quicker iteration, use Scenario B or C with 2–3 source files instead of the full set.
- Re-run Scenario F after a guardrail failure to test remediation loops.
