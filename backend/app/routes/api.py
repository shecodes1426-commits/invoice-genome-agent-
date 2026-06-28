import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai.rule_parser import create_extraction, parse_excel, parse_text
from app.config import INVOICE_DIR, SUPPORTED_UPLOAD_EXTENSIONS, UPLOAD_DIR
from app.database.session import get_db
from app.invoice.generator import generate_invoice_pdf
from app.models.db import AppLog, Employee, ExceptionItem, ExtractionRecord, Invoice, UploadedFile, ValidationResult
from app.models.schemas import (
    DashboardResponse,
    ExceptionEditRequest,
    ExtractRequest,
    ExtractResponse,
    InvoiceRequest,
    InvoiceResponse,
    UploadResponse,
    ValidateRequest,
    ValidateResponse,
)
from app.services.ocr_service import extract_text_from_file
from app.utils.logging import log_event
from app.validation.engine import data_from_record, validate_invoice_data


router = APIRouter()


def _record_to_payload(record: ExtractionRecord) -> dict:
    return {
        "id": record.id,
        "employee_id": record.employee_id,
        "employee_name": record.employee_name,
        "client": record.client,
        "client_code": record.client_code,
        "working_days": record.working_days,
        "hours": record.hours,
        "overtime": record.overtime,
        "salary": record.salary,
        "month": record.month,
        "confidence": round(record.overall_confidence or 0, 2),
        "status": record.status,
    }


def _process_upload(db: Session, upload: UploadedFile) -> ExtractionRecord:
    path = Path(upload.file_path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        parsed = parse_excel(db, path)
        if not parsed:
            raise HTTPException(status_code=422, detail="No invoice-like rows found in Excel file")
        data, confidence, raw_text = parsed[0]
        upload.extracted_text = raw_text
        upload.ocr_confidence = 100
        extraction = create_extraction(db, upload.id, data, confidence, raw_text)
    else:
        text, ocr_conf = extract_text_from_file(path)
        upload.extracted_text = text
        upload.ocr_confidence = ocr_conf
        data, confidence = parse_text(db, text)
        confidence["ocr"] = ocr_conf
        confidence["overall"] = round((confidence.get("overall", 0) + ocr_conf) / 2, 2) if ocr_conf else confidence.get("overall", 0)
        extraction = create_extraction(db, upload.id, data, confidence, text)

    upload.status = "extracted"
    db.commit()
    status, reasons, confidence_score, exception = validate_invoice_data(db, data_from_record(extraction), extraction)
    log_event(db, "validation", f"Extraction {extraction.id}: {status} ({confidence_score}%) - {'; '.join(reasons)}")
    if status == "Valid":
        invoice = generate_invoice_pdf(db, extraction)
        log_event(db, "invoice", f"Generated {invoice.invoice_number} for extraction {extraction.id}")
    elif exception:
        log_event(db, "exception", f"Queued exception {exception.id} for extraction {extraction.id}")
    return extraction


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF, Excel, PNG, JPG, or JPEG.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}{ext}"
    path = UPLOAD_DIR / stored
    with path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    upload = UploadedFile(original_filename=file.filename or stored, stored_filename=stored, file_path=str(path), file_type=ext.lstrip("."))
    db.add(upload)
    db.commit()
    db.refresh(upload)
    log_event(db, "upload", f"Uploaded {upload.original_filename} as {stored}")

    try:
        _process_upload(db, upload)
        message = "Uploaded, extracted, validated, and routed successfully"
    except HTTPException:
        upload.status = "failed"
        db.commit()
        raise
    except Exception as exc:
        upload.status = "failed"
        db.commit()
        log_event(db, "error", f"Upload pipeline failed for {upload.id}: {exc}", "ERROR")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return UploadResponse(upload_id=upload.id, filename=upload.original_filename, status=upload.status, message=message)


@router.post("/extract", response_model=ExtractResponse)
def extract(request: ExtractRequest, db: Session = Depends(get_db)):
    upload = None
    if request.upload_id:
        upload = db.query(UploadedFile).filter(UploadedFile.id == request.upload_id).first()
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        extraction = _process_upload(db, upload)
        text = upload.extracted_text or ""
    else:
        text = request.text or ""
        data, confidence = parse_text(db, text)
        extraction = create_extraction(db, None, data, confidence, text)

    return ExtractResponse(
        extraction_id=extraction.id,
        upload_id=upload.id if upload else None,
        extracted_text=text,
        data=data_from_record(extraction),
        confidence={"ocr": upload.ocr_confidence if upload else 90.0, "extraction": extraction.extraction_confidence, "matching": extraction.matching_confidence, "overall": extraction.overall_confidence},
        status=extraction.status,
    )


@router.post("/validate", response_model=ValidateResponse)
def validate(request: ValidateRequest, db: Session = Depends(get_db)):
    extraction = None
    if request.extraction_id:
        extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == request.extraction_id).first()
    elif request.upload_id:
        extraction = db.query(ExtractionRecord).filter(ExtractionRecord.upload_id == request.upload_id).order_by(ExtractionRecord.id.desc()).first()
    if not extraction and not request.data:
        raise HTTPException(status_code=404, detail="Extraction not found")

    data = data_from_record(extraction) if extraction else request.data
    status, reasons, confidence, exception = validate_invoice_data(db, data, extraction)
    return ValidateResponse(status=status, reasons=reasons, confidence=confidence, extraction_id=extraction.id if extraction else 0, exception_id=exception.id if exception else None)


@router.post("/generate-invoice", response_model=InvoiceResponse)
def generate_invoice(request: InvoiceRequest, db: Session = Depends(get_db)):
    extraction = None
    if request.exception_id:
        exception = db.query(ExceptionItem).filter(ExceptionItem.id == request.exception_id).first()
        if not exception:
            raise HTTPException(status_code=404, detail="Exception not found")
        extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == exception.extraction_id).first()
    elif request.extraction_id:
        extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == request.extraction_id).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")

    status, reasons, _, _ = validate_invoice_data(db, data_from_record(extraction), extraction)
    if status != "Valid":
        raise HTTPException(status_code=422, detail={"status": status, "reasons": reasons})
    invoice = generate_invoice_pdf(db, extraction)
    return InvoiceResponse(invoice_id=invoice.id, invoice_number=invoice.invoice_number, amount=invoice.amount, download_url=f"/invoice/{invoice.id}")


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)
    uploads = db.query(UploadedFile).count()
    invoices = db.query(Invoice).count()
    validations = db.query(ValidationResult).count()
    pending = db.query(ExceptionItem).filter(ExceptionItem.status == "pending").count()
    completed = db.query(Invoice).filter(Invoice.status == "generated").count()
    todays_uploads = db.query(UploadedFile).filter(UploadedFile.created_at >= today, UploadedFile.created_at < tomorrow).count()
    total_value = sum(row.amount or 0 for row in db.query(Invoice).all())
    touchless_rate = round((completed / uploads * 100), 1) if uploads else 0

    recent_uploads = [
        {"id": item.id, "file": item.original_filename, "type": item.file_type.upper(), "status": item.status, "created_at": item.created_at.isoformat()}
        for item in db.query(UploadedFile).order_by(UploadedFile.created_at.desc()).limit(8)
    ]
    recent_invoices = [
        {"id": inv.id, "invoice_number": inv.invoice_number, "client": inv.client_name, "employee": inv.employee_name, "amount": inv.amount, "download_url": f"/invoice/{inv.id}"}
        for inv in db.query(Invoice).order_by(Invoice.created_at.desc()).limit(8)
    ]
    activity = [
        {"type": log.event_type, "message": log.message, "level": log.level, "created_at": log.created_at.isoformat()}
        for log in db.query(AppLog).order_by(AppLog.created_at.desc()).limit(8)
    ]
    return DashboardResponse(
        uploaded_files=uploads,
        generated_invoices=invoices,
        validation_count=validations,
        pending_review=pending,
        completed_invoices=completed,
        todays_uploads=todays_uploads,
        touchless_rate=touchless_rate,
        total_value=round(total_value, 2),
        recent_uploads=recent_uploads,
        recent_invoices=recent_invoices,
        activity=activity,
    )


@router.get("/employees")
def employees(search: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Employee)
    if search:
        like = f"%{search}%"
        query = query.filter((Employee.full_name.ilike(like)) | (Employee.emp_id.ilike(like)) | (Employee.client_name.ilike(like)))
    return [
        {
            "emp_id": emp.emp_id,
            "full_name": emp.full_name,
            "email": emp.email,
            "client_code": emp.client_code,
            "client_name": emp.client_name,
            "job_title": emp.job_title,
            "total_ctc": emp.total_ctc,
        }
        for emp in query.order_by(Employee.emp_id).limit(250)
    ]


@router.get("/invoice/{invoice_id}")
def invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv or not inv.pdf_path or not Path(inv.pdf_path).exists():
        raise HTTPException(status_code=404, detail="Invoice not found")
    return FileResponse(inv.pdf_path, media_type="application/pdf", filename=f"{inv.invoice_number}.pdf")


@router.get("/exceptions")
def exceptions(db: Session = Depends(get_db)):
    items = []
    for item in db.query(ExceptionItem).order_by(ExceptionItem.created_at.desc()).all():
        extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == item.extraction_id).first()
        items.append(
            {
                "id": item.id,
                "status": item.status,
                "reason": item.reason,
                "confidence": item.confidence,
                "assigned_to": item.assigned_to,
                "created_at": item.created_at.isoformat(),
                "extraction": _record_to_payload(extraction) if extraction else None,
            }
        )
    return items


@router.post("/approve/{exception_id}")
def approve(exception_id: int, db: Session = Depends(get_db)):
    item = db.query(ExceptionItem).filter(ExceptionItem.id == exception_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Exception not found")
    extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == item.extraction_id).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    item.status = "approved"
    item.updated_at = datetime.utcnow()
    extraction.status = "validated"
    db.commit()
    invoice = generate_invoice_pdf(db, extraction)
    log_event(db, "invoice", f"Approved exception {exception_id}; generated {invoice.invoice_number}")
    return {"status": "approved", "invoice_id": invoice.id, "download_url": f"/invoice/{invoice.id}"}


@router.post("/reject/{exception_id}")
def reject(exception_id: int, db: Session = Depends(get_db)):
    item = db.query(ExceptionItem).filter(ExceptionItem.id == exception_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Exception not found")
    item.status = "rejected"
    item.updated_at = datetime.utcnow()
    extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == item.extraction_id).first()
    if extraction:
        extraction.status = "rejected"
    db.commit()
    log_event(db, "exception", f"Rejected exception {exception_id}")
    return {"status": "rejected"}


@router.post("/exceptions/{exception_id}/edit")
def edit_exception(exception_id: int, payload: ExceptionEditRequest, db: Session = Depends(get_db)):
    item = db.query(ExceptionItem).filter(ExceptionItem.id == exception_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Exception not found")
    extraction = db.query(ExtractionRecord).filter(ExtractionRecord.id == item.extraction_id).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None and hasattr(extraction, field):
            setattr(extraction, field, value)
    item.reason = "Edited by reviewer; revalidation required"
    item.updated_at = datetime.utcnow()
    db.commit()
    status, reasons, confidence, exception = validate_invoice_data(db, data_from_record(extraction), extraction)
    return {"status": status, "reasons": reasons, "confidence": confidence, "exception_id": exception.id if exception else item.id}
