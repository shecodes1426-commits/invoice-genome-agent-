import json
from pathlib import Path

import pandas as pd
import pdfplumber
from docx import Document
from sqlalchemy.orm import Session

from app.config import DATASET_DIR
from app.models.db import Customer, Employee, Payroll, TestCase
from app.utils.logging import log_event


def _safe_float(value) -> float:
    if pd.isna(value):
        return 0.0
    return float(value)


def _safe_str(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _load_docx_context(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    doc = Document(path)
    rows: list[dict[str, str]] = []
    for table in doc.tables:
        if not table.rows:
            continue
        headers = [cell.text.strip() for cell in table.rows[0].cells]
        if "Case" in headers and "Input format" in headers:
            for row in table.rows[1:]:
                cells = [cell.text.strip() for cell in row.cells]
                if cells and cells[0].lower().startswith("case"):
                    rows.append(
                        {
                            "case_name": cells[0],
                            "input_format": cells[1] if len(cells) > 1 else "",
                            "provided_input": cells[2] if len(cells) > 2 else "",
                            "generation_notes": cells[3] if len(cells) > 3 else "",
                        }
                    )
    return rows


def _load_pdf_summary(path: Path) -> str:
    if not path.exists():
        return ""
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def seed_database(db: Session) -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    workbook = DATASET_DIR / "w1.xlsx"
    if not workbook.exists():
        log_event(db, "dataset", "w1.xlsx not found; startup seed skipped", "WARNING")
        return

    customers = pd.read_excel(workbook, sheet_name="Customers")
    employees = pd.read_excel(workbook, sheet_name="Employees")
    payroll = pd.read_excel(workbook, sheet_name="Payroll_June2026")
    test_cases = pd.read_excel(workbook, sheet_name="TestCases", header=None)

    db.query(Customer).delete()
    db.query(Employee).delete()
    db.query(Payroll).delete()
    db.query(TestCase).delete()
    db.commit()

    for _, row in customers.iterrows():
        db.add(
            Customer(
                client_code=_safe_str(row["Client Code"]),
                client_name=_safe_str(row["Client Name"]),
                city=_safe_str(row["City"]),
                industry=_safe_str(row["Industry"]),
                contact_email=_safe_str(row["Contact Email"]),
                status=_safe_str(row["Status"]),
            )
        )

    for _, row in employees.iterrows():
        db.add(
            Employee(
                emp_id=_safe_str(row["Emp ID"]),
                full_name=_safe_str(row["Full Name"]),
                first_name=_safe_str(row["First Name"]),
                last_name=_safe_str(row["Last Name"]),
                email=_safe_str(row["Email"]),
                client_code=_safe_str(row["Client Code"]),
                client_name=_safe_str(row["Client Name"]),
                job_title=_safe_str(row["Job Title"]),
                department=_safe_str(row["Department"]),
                nationality=_safe_str(row["Nationality"]),
                date_of_joining=_safe_str(row["Date of Joining"]),
                status=_safe_str(row["Status"]),
                iban=_safe_str(row["IBAN"]),
                basic=_safe_float(row["Basic"]),
                housing=_safe_float(row["Housing"]),
                transport=_safe_float(row["Transport"]),
                food=_safe_float(row["Food"]),
                phone=_safe_float(row["Phone"]),
                total_ctc=_safe_float(row["Total CTC"]),
            )
        )

    for _, row in payroll.iterrows():
        db.add(
            Payroll(
                emp_id=_safe_str(row["Emp ID"]),
                employee_name=_safe_str(row["Employee Name"]),
                client_code=_safe_str(row["Client Code"]),
                client_name=_safe_str(row["Client Name"]),
                pay_period=_safe_str(row["Pay Period"]),
                basic=_safe_float(row["Basic"]),
                housing=_safe_float(row["Housing"]),
                transport=_safe_float(row["Transport"]),
                food=_safe_float(row["Food"]),
                phone=_safe_float(row["Phone"]),
                gross=_safe_float(row["Gross"]),
                ot_hours=_safe_float(row["OT Hours"]),
                ot_amount=_safe_float(row["OT Amount"]),
                deductions=_safe_float(row["Deductions"]),
                net_pay=_safe_float(row["Net Pay"]),
                currency=_safe_str(row["Currency"]),
                working_days=int(row["Working Days"]),
            )
        )

    docx_cases = _load_docx_context(DATASET_DIR / "w2.docx")
    if docx_cases:
        cases = docx_cases
    else:
        cases = []
        for _, row in test_cases.iterrows():
            if _safe_str(row[0]).lower().startswith("case "):
                cases.append(
                    {
                        "case_name": _safe_str(row[0]),
                        "input_format": _safe_str(row[1]),
                        "provided_input": _safe_str(row[2]),
                        "generation_notes": _safe_str(row[3]),
                    }
                )

    problem_text = _load_pdf_summary(DATASET_DIR / "problem_statement.pdf")
    if problem_text:
        cases.append(
            {
                "case_name": "Problem Statement",
                "input_format": "PDF",
                "provided_input": "Touchless Invoice Agent requirements",
                "generation_notes": problem_text[:1000],
            }
        )

    for case in cases:
        db.add(TestCase(**case))

    db.commit()
    log_event(
        db,
        "dataset",
        json.dumps({"customers": len(customers), "employees": len(employees), "payroll": len(payroll), "test_cases": len(cases)}),
    )
