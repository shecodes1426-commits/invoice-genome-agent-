from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.config import COMPANY_NAME, INVOICE_DIR
from app.models.db import Employee, ExtractionRecord, Invoice, Payroll
from app.validation.engine import data_from_record


def next_invoice_number(db: Session) -> str:
    count = db.query(Invoice).count() + 1
    return f"INV-{datetime.utcnow().year}-{count:05d}"


def generate_invoice_pdf(db: Session, extraction: ExtractionRecord) -> Invoice:
    existing = (
        db.query(Invoice)
        .filter(
            Invoice.employee_id == extraction.employee_id,
            Invoice.client_name == extraction.client,
            Invoice.month == extraction.month,
        )
        .first()
    )
    if existing:
        return existing

    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    data = data_from_record(extraction)
    employee = db.query(Employee).filter(Employee.emp_id == data.employee_id).first()
    payroll = db.query(Payroll).filter(Payroll.emp_id == data.employee_id, Payroll.pay_period == data.month).first()
    invoice_number = next_invoice_number(db)
    amount = float(data.salary or (payroll.net_pay if payroll else 0))
    pdf_path = INVOICE_DIR / f"{invoice_number}.pdf"

    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>{COMPANY_NAME}</b>", styles["Title"]),
        Paragraph("Touchless Invoice Agent", styles["Normal"]),
        Spacer(1, 10),
    ]

    header = [
        ["Invoice Number", invoice_number, "Date", datetime.utcnow().strftime("%Y-%m-%d")],
        ["Bill To", data.client or "", "Month", data.month or "June 2026"],
        ["Employee", f"{data.employee_name} ({data.employee_id})", "Job Title", employee.job_title if employee else ""],
    ]
    header_table = Table(header, colWidths=[34 * mm, 70 * mm, 24 * mm, 48 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fb")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7d5ce")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([header_table, Spacer(1, 14)])

    working_days = data.working_days or (payroll.working_days if payroll else 0)
    overtime = data.overtime if data.overtime is not None else (payroll.ot_hours if payroll else 0)
    salary = amount
    day_rate = salary / working_days if working_days else salary
    rows = [
        ["Description", "Quantity", "Rate (AED)", "Amount (AED)"],
        [f"{data.employee_name} - monthly staffing services", f"{working_days} days", f"{day_rate:,.2f}", f"{salary:,.2f}"],
        ["Overtime reference", f"{overtime:g} hours", "Included per payroll", "0.00"],
        ["Total", "", "", f"{salary:,.2f}"],
    ]
    table = Table(rows, colWidths=[84 * mm, 28 * mm, 34 * mm, 34 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2a78d6")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7d5ce")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f0f6ff")),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([table, Spacer(1, 12)])
    story.append(Paragraph(f"Generated automatically after validation. Confidence: {extraction.overall_confidence:.1f}%.", styles["Normal"]))
    doc.build(story)

    invoice = Invoice(
        invoice_number=invoice_number,
        extraction_id=extraction.id,
        employee_id=data.employee_id,
        employee_name=data.employee_name,
        client_name=data.client or "",
        month=data.month or "June 2026",
        amount=amount,
        pdf_path=str(pdf_path),
    )
    db.add(invoice)
    extraction.status = "invoiced"
    db.commit()
    db.refresh(invoice)
    return invoice
