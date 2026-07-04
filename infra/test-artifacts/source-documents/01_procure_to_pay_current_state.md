# Northwind Manufacturing — Procure-to-Pay Current State

**Document owner:** Finance Transformation PMO  
**Version:** 2.1 (as-is baseline)  
**Effective date:** 2026-01-15  
**Scope:** Indirect spend and direct materials procurement across US and EU entities

---

## Executive summary

Northwind Manufacturing operates a decentralized Procure-to-Pay (P2P) process across three ERP instances (SAP S/4HANA US, SAP ECC EU legacy, and NetSuite for the acquired Summit Plastics division). Monthly indirect spend averages **$18.4M** with **~12,400 invoices** and **~3,200 purchase orders** (source: FY2025 AP operational dashboard, January 2026 close).

Key pain points include manual three-way match exceptions (22% of PO-backed invoices), inconsistent vendor onboarding (average 18 business days), and fragmented approval routing that delays month-end accruals.

---

## Process overview

The end-to-end P2P cycle comprises six macro stages:

1. **Demand identification** — Requisition created in ERP or via email to shared services
2. **Sourcing & PO creation** — Buyer assigns vendor, negotiates price, issues PO
3. **Receipt & confirmation** — Warehouse or requester confirms goods/services received
4. **Invoice capture** — AP scans/email-ingests vendor invoices
5. **Match & approve** — Three-way match (PO, receipt, invoice) with exception handling
6. **Payment & close** — Payment run, accrual true-up, GL posting, vendor statement reconciliation

**Cycle time (median):** 14 calendar days from PO approval to payment for domestic vendors; 23 days for cross-border.

---

## Detailed process steps

### Stage 1 — Requisition

| Step | Activity | Role | System | SLA |
|------|----------|------|--------|-----|
| 1.1 | Requester identifies need and creates requisition | Requester | SAP / email | 1 day |
| 1.2 | Manager approves spend against budget | Line manager | SAP workflow | 2 days |
| 1.3 | Procurement reviews catalog vs. non-catalog | Buyer | SAP MM | 1 day |

**Controls:** Budget check at requisition; segregation of duties between requester and approver for amounts > $5,000.

### Stage 2 — Purchase order

| Step | Activity | Role | System | SLA |
|------|----------|------|--------|-----|
| 2.1 | Buyer selects approved vendor | Buyer | SAP | Same day |
| 2.2 | PO issued and transmitted (EDI or email) | Buyer | SAP / Coupa | 1 day |
| 2.3 | Vendor acknowledgment logged | Buyer | SharePoint tracker | 2 days |

**Exception:** Non-PO invoices are permitted only for utilities, freight, and pre-approved petty-cash vendors (policy FIN-AP-014).

### Stage 3 — Receipt

| Step | Activity | Role | System | SLA |
|------|----------|------|------|-----|
| 3.1 | Goods receipt posted in warehouse | Warehouse clerk | SAP WM | Upon delivery |
| 3.2 | Service entry sheet for professional services | Requester | SAP | Within 5 days of service |
| 3.3 | Receipt notification to AP | System | SAP | Automatic |

### Stage 4 — Invoice capture

| Step | Activity | Role | System | SLA |
|------|----------|------|--------|-----|
| 4.1 | Invoice received (mail, email, portal) | AP clerk | Kofax / shared mailbox | Daily batch |
| 4.2 | OCR extraction and vendor lookup | AP clerk | Kofax | 4 hours per batch |
| 4.3 | Invoice parked in SAP with document type | AP clerk | SAP FI | Same day |

**Volume:** ~620 invoices/day across US shared services center (Bangalore back-office handles EU legacy entity).

### Stage 5 — Match and approve

| Step | Activity | Role | System | SLA |
|------|----------|------|--------|-----|
| 5.1 | Auto three-way match | System | SAP | Real-time |
| 5.2 | Exception routed to buyer or requester | AP supervisor | SAP workflow | 3 days |
| 5.3 | Tax and coding review for exceptions > $10K | AP manager | SAP | 2 days |
| 5.4 | Invoice posted to GL | AP clerk | SAP | Upon resolution |

**Match rate:** 78% straight-through processing; 22% require manual intervention (source: Q4 2025 AP metrics).

### Stage 6 — Payment and close

| Step | Activity | Role | System | SLA |
|------|----------|------|--------|-----|
| 6.1 | Payment proposal generated | Treasury | SAP | Twice weekly |
| 6.2 | Dual approval for wires > $100K | AP manager + Controller | SAP | 1 day |
| 6.3 | Payment execution and remittance | Treasury | Bank portal | Per schedule |
| 6.4 | Month-end accrual for GR/IR clearing | AP manager | SAP | T+3 close calendar |
| 6.5 | Vendor statement reconciliation | AP clerk | Excel + SAP | Monthly |

---

## Key roles

- **Requester** — Initiates need; confirms service receipt
- **Line manager** — Budget and business approval
- **Buyer / Procurement** — Vendor selection, PO creation, match exception resolution
- **Warehouse clerk** — Goods receipt
- **AP clerk** — Invoice capture, parking, posting
- **AP supervisor** — Exception queue management
- **AP manager** — Policy, accruals, high-value approvals
- **Controller** — Close oversight, SOX controls
- **Treasury** — Payment runs and banking

---

## Systems landscape

| System | Function | Entities |
|--------|----------|----------|
| SAP S/4HANA | ERP — US manufacturing | NWM-US |
| SAP ECC 6.0 | ERP — EU legacy | NWM-EU |
| NetSuite | ERP — Summit Plastics | SUMMIT |
| Coupa | Catalog and spot-buy | US indirect |
| Kofax | Invoice OCR and workflow | US AP hub |
| SharePoint | Vendor onboarding tracker | Global |
| BlackLine | Account reconciliations | Global |

---

## Known risks and control gaps

1. **Duplicate vendor master records** — Estimated 4% duplicate rate in US vendor file (source: MDG audit, Nov 2025).
2. **Segregation of duties** — 11 users with both PO creation and invoice posting in Summit NetSuite (remediation in progress).
3. **Accrual accuracy** — GR/IR aging > 30 days represents $2.1M (source: January 2026 close pack).
4. **Policy adherence** — 8% of payments lack PO where policy requires one (sample audit, Q3 2025).

---

## Transformation objectives (target state hints)

- Consolidate to single SAP instance by FY2027
- Achieve 90%+ straight-through match via improved catalog adoption
- Reduce vendor onboarding to 7 business days with automated KYC
- Implement AI-assisted exception coding for price/quantity variances
- Standardize global SOPs and RACI across regions

---

## References

- FIN-AP-014 Non-PO Invoice Policy
- FIN-CLOSE-003 Month-End Close Calendar
- SOX Control Matrix — AP-01 through AP-12
- FY2025 External Audit Management Letter (P2P observations)
