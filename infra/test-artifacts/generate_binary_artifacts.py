#!/usr/bin/env python3
"""Generate binary test artifacts (DOCX, XLSX) for ProcessDoc manual testing."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT_DIR = Path(__file__).resolve().parent / "source-documents"


def _build_sop_docx(path: Path) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    title = doc.add_heading("Standard Operating Procedure", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("Accounts Payable — Three-Way Match Exception Handling")
    doc.add_paragraph("Document ID: SOP-AP-003 | Version 1.4 | Owner: Priya Sharma, AP Manager")

    doc.add_heading("1. Purpose", level=1)
    doc.add_paragraph(
        "This procedure defines how Accounts Payable staff investigate, route, and resolve "
        "three-way match exceptions in SAP for Northwind Manufacturing US and EU entities. "
        "It ensures invoices are posted accurately, on time, and in compliance with FIN-AP-014."
    )

    doc.add_heading("2. Scope", level=1)
    doc.add_paragraph(
        "Applies to all PO-backed invoices processed through SAP S/4HANA (US) and SAP ECC (EU). "
        "Excludes Summit Plastics (NetSuite) — see SOP-AP-003-NETSUITE."
    )

    doc.add_heading("3. Roles and responsibilities", level=1)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    hdr[0].text = "Role"
    hdr[1].text = "Responsibility"
    hdr[2].text = "System access"
    rows = [
        ("AP clerk", "Triage exceptions, contact requester/buyer, park invoices", "Z_INV_PARK"),
        ("AP supervisor", "Escalate aged items, approve tolerance overrides ≤2%", "Z_INV_POST"),
        ("Buyer", "Resolve price/qty variances with vendor", "Z_PO_CREATE"),
        ("Requester", "Confirm receipt or service completion", "Z_REQ_CREATE"),
        ("AP manager", "Approve policy exceptions >$10K", "Z_INV_POST"),
    ]
    for role, resp, access in rows:
        row = table.add_row().cells
        row[0].text = role
        row[1].text = resp
        row[2].text = access

    doc.add_heading("4. Procedure", level=1)
    steps = [
        (
            "4.1 Exception identification",
            "SAP auto-match runs on invoice parking. Failed matches appear in transaction FBL1N "
            "exception queue with reason code (PRICE, QTY, GR_MISSING, TAX, DUPLICATE).",
        ),
        (
            "4.2 Initial triage (AP clerk)",
            "Within 4 business hours: validate vendor, PO number, and invoice date. "
            "Assign standard reason code. If GR_MISSING, notify requester via workflow.",
        ),
        (
            "4.3 Buyer engagement",
            "For PRICE or QTY variances: buyer contacts vendor within 2 business days. "
            "Document outcome in SAP notes field. Tolerance: ±2% on catalog items per policy.",
        ),
        (
            "4.4 Receipt confirmation",
            "Requester or warehouse posts GR within 3 business days of notification. "
            "AP clerk re-runs match.",
        ),
        (
            "4.5 Posting and audit trail",
            "On successful match, AP clerk posts invoice. Retain Kofax image and approval "
            "workflow PDF per records retention policy (7 years).",
        ),
        (
            "4.6 Escalation",
            "Unresolved >3 business days: AP supervisor. >5 days: AP manager + Controller notification.",
        ),
    ]
    for heading, body in steps:
        doc.add_heading(heading, level=2)
        doc.add_paragraph(body)

    doc.add_heading("5. Key controls", level=1)
    for item in [
        "Segregation: same user cannot create PO and post invoice (SOX AP-07).",
        "Dual approval required for manual tolerance override >2%.",
        "All exceptions logged with standardized reason codes (max 12 codes).",
        "Monthly sample of 25 exceptions reviewed by Internal Audit.",
    ]:
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("6. References", level=1)
    doc.add_paragraph("FIN-AP-014 Non-PO Invoice Policy")
    doc.add_paragraph("SOX Control Matrix AP-07, AP-09")
    doc.add_paragraph("Northwind P2P Current State Assessment (Feb 2026)")

    doc.save(path)


def _style_header_row(ws, row: int = 1) -> None:
    fill = PatternFill("solid", fgColor="1F4E79")
    font = Font(bold=True, color="FFFFFF", size=11)
    for cell in ws[row]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _auto_width(ws, min_width: int = 12, max_width: int = 36) -> None:
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        max_len = 0
        for row in range(1, ws.max_row + 1):
            val = ws.cell(row=row, column=col).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[letter].width = min(max(max_len + 2, min_width), max_width)


def _build_raci_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "RACI Matrix"

    roles = [
        "Requester",
        "Line Manager",
        "Buyer",
        "Receiving",
        "AP Clerk",
        "AP Supervisor",
        "AP Manager",
        "Controller",
        "Procurement Dir",
        "Treasury",
    ]
    activities = [
        ("Create requisition", "R", "A", "I", "-", "-", "-", "-", "-", "I", "-"),
        ("Approve requisition", "I", "R/A", "C", "-", "-", "-", "-", "-", "I", "-"),
        ("Create purchase order", "I", "I", "R", "-", "-", "-", "-", "-", "A", "-"),
        ("Post goods receipt", "C", "I", "I", "R", "I", "-", "-", "-", "-", "-"),
        ("Capture vendor invoice", "-", "-", "I", "-", "R", "I", "A", "-", "-", "-"),
        ("Resolve match exception", "C", "C", "R", "C", "R", "A", "I", "C", "-", "-"),
        ("Post invoice to GL", "-", "-", "-", "-", "R", "I", "A", "C", "-", "-"),
        ("Execute payment run", "-", "-", "-", "-", "I", "I", "C", "A", "-", "R"),
        ("Month-end GR/IR accrual", "-", "I", "I", "C", "R", "I", "A", "A", "-", "-"),
        ("Vendor master create/change", "C", "I", "R", "-", "C", "-", "C", "A", "A", "-"),
        ("Vendor statement reconciliation", "-", "-", "-", "-", "R", "I", "A", "C", "-", "I"),
    ]

    ws.append(["Activity / Deliverable"] + roles)
    for row in activities:
        ws.append(list(row))
    _style_header_row(ws)
    ws.freeze_panes = "B2"
    _auto_width(ws)

    # KPI sheet
    kpi = wb.create_sheet("KPI Baseline")
    kpi.append(["Metric", "Current", "Target", "Unit", "Source"])
    kpi_rows = [
        ("Straight-through match rate", "78%", "90%", "percent", "AP dashboard Q4 2025"),
        ("Days to pay (US)", "14.2", "10.0", "days", "Jan 2026 close"),
        ("Days to pay (EU)", "23.1", "14.0", "days", "Jan 2026 close"),
        ("Vendor onboarding", "18", "7", "business days", "Procurement ops"),
        ("PO compliance", "84%", "95%", "percent", "Spend cube FY2025"),
        ("GR/IR >30 days", "$2.1M", "$0.5M", "USD", "Jan 2026 BS"),
        ("Cost per invoice", "$4.85", "$3.20", "USD", "SSC benchmark 2025"),
    ]
    for r in kpi_rows:
        kpi.append(list(r))
    _style_header_row(kpi)
    _auto_width(kpi)

    # Exception log sample
    exc = wb.create_sheet("Exception Sample")
    exc.append(["Invoice ID", "Vendor", "PO", "Reason Code", "Amount USD", "Age Days", "Owner"])
    samples = [
        ("INV-88421", "Acme Industrial Supply", "4500123987", "PRICE", 12450.00, 4, "Buyer"),
        ("INV-88435", "Global Freight LLC", "4500124012", "GR_MISSING", 3200.00, 7, "Requester"),
        ("INV-88440", "TechParts GmbH", "4500119876", "QTY", 8920.50, 2, "Buyer"),
        ("INV-88452", "Summit Packaging", "4500124100", "TAX", 1560.00, 1, "AP Clerk"),
        ("INV-88461", "Acme Industrial Supply", "4500123987", "DUPLICATE", 12450.00, 3, "AP Supervisor"),
    ]
    for s in samples:
        exc.append(list(s))
    _style_header_row(exc)
    _auto_width(exc)

    wb.save(path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sop = OUT_DIR / "06_ap_match_exception_sop_draft.docx"
    raci = OUT_DIR / "07_p2p_raci_and_kpi_workbook.xlsx"
    _build_sop_docx(sop)
    _build_raci_xlsx(raci)
    print(f"Wrote {sop}")
    print(f"Wrote {raci}")


if __name__ == "__main__":
    main()
