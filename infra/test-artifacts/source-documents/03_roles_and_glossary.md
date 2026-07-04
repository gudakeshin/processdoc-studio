# Northwind P2P — Roles, RACI Primer, and Glossary

## Organizational context

Northwind Manufacturing ($2.1B revenue, 4,200 employees) is mid-way through a finance transformation program. The Procure-to-Pay workstream spans Shared Services (Bangalore + Chicago), Regional Finance (US, EU), Procurement, Supply Chain, and IT.

---

## Role definitions

### Business roles

| Role | Description | FTE / headcount |
|------|-------------|-----------------|
| **Requester** | Any employee initiating a purchase or service need | ~1,800 eligible |
| **Line manager** | Budget owner; approves requisitions per DOA | ~220 |
| **Category manager** | Strategic sourcing owner for a spend category | 8 |
| **Buyer** | Operational procurement; creates POs | 47 |
| **Receiving clerk** | Posts goods receipts at plant warehouses | 34 |
| **AP clerk** | Invoice entry, matching, posting | 22 |
| **AP supervisor** | Exception queue, team scheduling | 4 |
| **AP manager** | Policies, accruals, vendor relations | 3 |
| **Procurement director** | P2P policy owner for buy-side | 1 |
| **Controller** | Financial control, close, SOX | 1 |
| **Treasury analyst** | Payment execution | 2 |
| **IT application owner** | SAP, Coupa, Kofax support | 3 |

### System roles (SAP)

- `Z_REQ_CREATE` — Requisition creation
- `Z_PO_CREATE` — Purchase order creation
- `Z_GR_POST` — Goods receipt
- `Z_INV_PARK` — Invoice parking
- `Z_INV_POST` — Invoice posting
- `Z_PAY_PROPOSE` — Payment proposal

---

## RACI primer (activities → accountable party)

Legend: **R** Responsible, **A** Accountable, **C** Consulted, **I** Informed

| Activity | Requester | Line mgr | Buyer | Receiving | AP clerk | AP mgr | Controller | Procurement dir |
|----------|-----------|----------|-------|-----------|----------|--------|------------|-----------------|
| Create requisition | R | A | I | — | — | — | — | I |
| Approve requisition | I | A/R | C | — | — | — | — | I |
| Create PO | I | I | R | — | — | — | — | A |
| Post goods receipt | C | I | I | R | I | — | — | — |
| Capture invoice | — | — | I | — | R | A | — | — |
| Resolve match exception | C | C | R | C | R | A | I | C |
| Post invoice to GL | — | — | — | — | R | A | C | — |
| Run payment | — | — | — | — | I | C | A | — |
| Month-end accrual | — | I | I | C | R | A | A | I |
| Vendor master create/change | C | I | R | — | C | C | A | A |

*Note: Summit Plastics (NetSuite) uses a simplified matrix — to be harmonized in target state.*

---

## Glossary

| Term | Definition |
|------|------------|
| **P2P** | Procure-to-Pay — end-to-end process from requisition through payment |
| **Three-way match** | Automated comparison of purchase order, goods receipt, and invoice |
| **GR/IR** | Goods receipt / invoice receipt clearing account |
| **DOA** | Delegation of authority — approval limits by role and category |
| **STP** | Straight-through processing — invoice auto-posted without manual touch |
| **MDG** | Master Data Governance — vendor and material master stewardship |
| **MRO** | Maintenance, repair, and operations indirect spend |
| **ASN** | Advanced shipping notice from vendor |
| **Kofax** | Invoice capture and OCR platform used by US AP hub |
| **Coupa** | Cloud procurement for catalog and spot buys |
| **SOD** | Segregation of duties — SOX control preventing toxic combinations |
| **DPO** | Days payable outstanding |
| **Non-PO invoice** | Invoice without purchase order — allowed only per FIN-AP-014 |

---

## Escalation paths

1. **Match exception unresolved > 3 days** → AP supervisor → Buyer → Category manager
2. **Invoice > $50,000 without PO** → AP manager → Controller (policy exception)
3. **Vendor master duplicate suspected** → Buyer → MDG steward → IT
4. **Payment block (credit hold)** → AP manager → Procurement director → Vendor

---

## Document control

This primer supports SOP, RACI matrix, and process map generation for the Northwind P2P transformation test scenario. All metrics and role counts are illustrative baselines from workshop materials dated February 2026.
