import re
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.db import Employee, ExtractionRecord, Payroll
from app.models.schemas import ExtractedInvoiceData


EMP_ID_RE = re.compile(r"\bEMP[-\s]?\d{5}\b", re.IGNORECASE)
MONEY_RE = re.compile(r"(?:AED|salary|net pay|gross|total|amount|pay)[:\sA-Za-z]*([0-9][0-9,]*(?:\.\d+)?)", re.IGNORECASE)


def normalize_emp_id(value: str | None) -> str:
    if not value:
        return ""
    match = EMP_ID_RE.search(value)
    if match:
        return match.group(0).upper().replace(" ", "").replace("-", "")
    return value.strip().upper().replace(" ", "").replace("-", "")


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _month(text: str) -> str:
    match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\b", text, re.I)
    return match.group(0).title() if match else "June 2026"


def _match_employee(db: Session, data: ExtractedInvoiceData) -> tuple[Employee | None, float]:
    if data.employee_id:
        emp = db.query(Employee).filter(Employee.emp_id == normalize_emp_id(data.employee_id)).first()
        if emp:
            return emp, 100.0

    if data.employee_name:
        employees = db.query(Employee).all()
        names = {emp.full_name: emp for emp in employees}
        match = get_close_matches(data.employee_name, names.keys(), n=1, cutoff=0.55)
        if match:
            score = SequenceMatcher(None, data.employee_name.lower(), match[0].lower()).ratio() * 100
            return names[match[0]], round(score, 2)

    return None, 0.0


def parse_text(db: Session, text: str) -> tuple[ExtractedInvoiceData, dict[str, float]]:
    clean = re.sub(r"[ \t]+", " ", text or "")
    emp_id_match = EMP_ID_RE.search(clean)
    employee_id = normalize_emp_id(emp_id_match.group(0)) if emp_id_match else ""

    name = ""
    name_patterns = [
        r"(?:Employee Name|Employee|Name)\s*[:\-]\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})",
        r"\b([A-Z][a-z]+\s+(?:Al\s+)?[A-Z][a-z]+)\b",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, clean)
        if match:
            name = match.group(1).strip()
            break

    client = ""
    client_code = ""
    code_match = re.search(r"\bCL\d{3}\b", clean, re.I)
    if code_match:
        client_code = code_match.group(0).upper()
    client_match = re.search(r"(?:Client Name|Client|Bill To)\s*[:\-]\s*([A-Za-z0-9&.,\s]+)", clean, re.I)
    if client_match:
        client = client_match.group(1).split("\n")[0].strip(" .")

    data = ExtractedInvoiceData(
        employee_id=employee_id,
        employee_name=name,
        client=client,
        client_code=client_code,
        working_days=int(_number(r"(?:Working Days|Days Worked|Days)\s*[:\-]?\s*(\d{1,2})", clean) or 0) or None,
        hours=_number(r"(?:Hours Worked|Hours)\s*[:\-]?\s*(\d+(?:\.\d+)?)", clean),
        overtime=_number(r"(?:Overtime Hours|OT Hours|Overtime|OT)\s*[:\-]?\s*(\d+(?:\.\d+)?)", clean),
        salary=None,
        month=_month(clean),
    )
    money = MONEY_RE.findall(clean)
    if money:
        data.salary = float(money[-1].replace(",", ""))

    emp, match_conf = _match_employee(db, data)
    if emp:
        data.employee_id = emp.emp_id
        data.employee_name = emp.full_name
        if not data.client_code:
            data.client_code = emp.client_code
        if not data.client:
            data.client = emp.client_name
        payroll = db.query(Payroll).filter(Payroll.emp_id == emp.emp_id, Payroll.pay_period == data.month).first()
        if payroll:
            data.working_days = data.working_days or payroll.working_days
            data.overtime = payroll.ot_hours if data.overtime is None else data.overtime
            data.salary = data.salary or payroll.net_pay
            data.hours = data.hours or float((data.working_days or payroll.working_days) * 8)

    present = [data.employee_id, data.employee_name, data.client or data.client_code, data.working_days, data.salary]
    extraction_conf = round(55 + (sum(1 for item in present if item not in (None, "")) / len(present)) * 35, 2)
    overall = round((extraction_conf + match_conf) / 2, 2) if match_conf else extraction_conf
    return data, {"ocr": 90.0 if clean else 0.0, "extraction": extraction_conf, "matching": match_conf, "overall": overall}


def parse_excel(db: Session, path: str | Path) -> list[tuple[ExtractedInvoiceData, dict[str, float], str]]:
    sheets = pd.read_excel(path, sheet_name=None)
    parsed: list[tuple[ExtractedInvoiceData, dict[str, float], str]] = []
    for sheet_name, df in sheets.items():
        if df.empty:
            continue
        normalized_cols = {str(col).strip().lower(): col for col in df.columns}
        for _, row in df.iterrows():
            row_text = " ".join(f"{col}: {row[col]}" for col in df.columns if pd.notna(row[col]))
            data = ExtractedInvoiceData(
                employee_id=normalize_emp_id(str(row.get(normalized_cols.get("emp id", ""), ""))),
                employee_name=str(row.get(normalized_cols.get("employee name", normalized_cols.get("full name", "")), "") or ""),
                client=str(row.get(normalized_cols.get("client name", ""), "") or ""),
                client_code=str(row.get(normalized_cols.get("client code", ""), "") or ""),
                working_days=None,
                hours=None,
                overtime=None,
                salary=None,
                month=str(row.get(normalized_cols.get("pay period", ""), "") or "June 2026"),
            )
            for key in ("working days", "days"):
                if key in normalized_cols and pd.notna(row[normalized_cols[key]]):
                    data.working_days = int(row[normalized_cols[key]])
            for key in ("hours", "hours worked"):
                if key in normalized_cols and pd.notna(row[normalized_cols[key]]):
                    data.hours = float(row[normalized_cols[key]])
            for key in ("ot hours", "overtime", "overtime hours"):
                if key in normalized_cols and pd.notna(row[normalized_cols[key]]):
                    data.overtime = float(row[normalized_cols[key]])
            for key in ("net pay", "salary", "gross", "total ctc"):
                if key in normalized_cols and pd.notna(row[normalized_cols[key]]):
                    data.salary = float(row[normalized_cols[key]])
                    break
            if not any([data.employee_id, data.employee_name, data.client, data.client_code]):
                data, confidence = parse_text(db, row_text)
            else:
                emp, match_conf = _match_employee(db, data)
                if emp:
                    data.employee_id = emp.emp_id
                    data.employee_name = emp.full_name
                    data.client = data.client or emp.client_name
                    data.client_code = data.client_code or emp.client_code
                present = [data.employee_id, data.employee_name, data.client or data.client_code, data.working_days, data.salary]
                extraction_conf = round(60 + (sum(1 for item in present if item not in (None, "")) / len(present)) * 35, 2)
                confidence = {"ocr": 100.0, "extraction": extraction_conf, "matching": match_conf, "overall": round((extraction_conf + match_conf) / 2, 2)}
            parsed.append((data, confidence, f"Sheet {sheet_name}: {row_text}"))
    return parsed


def create_extraction(db: Session, upload_id: int | None, data: ExtractedInvoiceData, confidence: dict[str, float], raw_text: str) -> ExtractionRecord:
    record = ExtractionRecord(
        upload_id=upload_id,
        employee_id=data.employee_id,
        employee_name=data.employee_name,
        client=data.client,
        client_code=data.client_code,
        working_days=data.working_days,
        hours=data.hours,
        overtime=data.overtime,
        salary=data.salary,
        month=data.month or "June 2026",
        raw_text=raw_text,
        extraction_confidence=confidence.get("extraction", 0),
        matching_confidence=confidence.get("matching", 0),
        overall_confidence=confidence.get("overall", 0),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
