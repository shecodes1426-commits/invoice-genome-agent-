import json
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.config import CONFIDENCE_THRESHOLD
from app.models.db import Employee, ExceptionItem, ExtractionRecord, Invoice, Payroll, ValidationResult
from app.models.schemas import ExtractedInvoiceData


def _similar(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio() * 100


def data_from_record(record: ExtractionRecord) -> ExtractedInvoiceData:
    return ExtractedInvoiceData(
        employee_id=record.employee_id,
        employee_name=record.employee_name,
        client=record.client,
        client_code=record.client_code,
        working_days=record.working_days,
        hours=record.hours,
        overtime=record.overtime,
        salary=record.salary,
        month=record.month,
    )


def validate_invoice_data(db: Session, data: ExtractedInvoiceData, extraction: ExtractionRecord | None = None) -> tuple[str, list[str], float, ExceptionItem | None]:
    reasons: list[str] = []
    warnings: list[str] = []
    confidence_parts: list[float] = []

    mandatory = {
        "employee_id": data.employee_id,
        "employee_name": data.employee_name,
        "client": data.client or data.client_code,
        "working_days": data.working_days,
        "salary": data.salary,
        "month": data.month,
    }
    missing = [name for name, value in mandatory.items() if value in (None, "")]
    if missing:
        reasons.append(f"Missing mandatory fields: {', '.join(missing)}")

    employee = db.query(Employee).filter(Employee.emp_id == (data.employee_id or "")).first()
    if not employee:
        reasons.append("Employee ID does not exist in master data")
        confidence_parts.append(0)
    else:
        confidence_parts.append(100)
        name_score = _similar(data.employee_name, employee.full_name)
        confidence_parts.append(name_score)
        if name_score < 85:
            reasons.append(f"Employee name does not match ID. Expected {employee.full_name}")
        client_ok = (data.client_code and data.client_code == employee.client_code) or _similar(data.client, employee.client_name) >= 85
        confidence_parts.append(100 if client_ok else 30)
        if not client_ok:
            reasons.append(f"Client does not match employee. Expected {employee.client_name} ({employee.client_code})")

    if data.working_days is None:
        reasons.append("Working days missing")
    elif data.working_days > 26:
        reasons.append("Working days cannot exceed 26")
    elif data.working_days < 20:
        warnings.append("Working days below expected 20-26 range")
    else:
        confidence_parts.append(100)

    payroll = None
    if employee:
        payroll = db.query(Payroll).filter(Payroll.emp_id == employee.emp_id, Payroll.pay_period == (data.month or "June 2026")).first()
    if not payroll:
        reasons.append("Payroll record missing for employee and month")
    else:
        expected_values = [payroll.net_pay, payroll.gross, payroll.basic + payroll.housing + payroll.transport + payroll.food + payroll.phone]
        salary = float(data.salary or 0)
        if any(abs(salary - expected) <= 1.0 for expected in expected_values):
            confidence_parts.append(100)
        else:
            reasons.append(f"Salary mismatch. Expected net pay AED {payroll.net_pay:.2f}")
            confidence_parts.append(max(0, 100 - min(abs(salary - payroll.net_pay) / max(payroll.net_pay, 1) * 100, 100)))

    duplicate = (
        db.query(Invoice)
        .filter(
            Invoice.employee_id == (data.employee_id or ""),
            Invoice.client_name == (data.client or ""),
            Invoice.month == (data.month or "June 2026"),
        )
        .first()
    )
    if duplicate:
        reasons.append(f"Duplicate invoice detected: {duplicate.invoice_number}")
        confidence_parts.append(0)

    base_confidence = extraction.overall_confidence if extraction else 95.0
    validation_confidence = round((sum(confidence_parts) / len(confidence_parts)) if confidence_parts else 0, 2)
    confidence = round((base_confidence + validation_confidence) / 2, 2)

    if reasons:
        status = "Error"
    elif warnings:
        status = "Warning"
        reasons.extend(warnings)
    else:
        status = "Valid"
        reasons.append("All validation rules passed")

    exception = None
    if status != "Valid" or confidence < CONFIDENCE_THRESHOLD:
        if extraction:
            exception = ExceptionItem(
                extraction_id=extraction.id,
                upload_id=extraction.upload_id,
                reason="; ".join(reasons),
                confidence=confidence,
            )
            db.add(exception)
            extraction.status = "review"

    if extraction:
        db.add(ValidationResult(extraction_id=extraction.id, status=status, reasons=json.dumps(reasons), confidence=confidence))
        if status == "Valid":
            extraction.status = "validated"

    db.commit()
    if exception:
        db.refresh(exception)
    return status, reasons, confidence, exception
