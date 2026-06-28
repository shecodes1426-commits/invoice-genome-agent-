from typing import Any

from pydantic import BaseModel, Field


class ExtractedInvoiceData(BaseModel):
    employee_id: str | None = ""
    employee_name: str | None = ""
    client: str | None = ""
    client_code: str | None = ""
    working_days: int | None = None
    hours: float | None = None
    overtime: float | None = None
    salary: float | None = None
    month: str | None = "June 2026"


class UploadResponse(BaseModel):
    upload_id: int
    filename: str
    status: str
    message: str


class ExtractRequest(BaseModel):
    upload_id: int | None = None
    text: str | None = None


class ExtractResponse(BaseModel):
    extraction_id: int
    upload_id: int | None
    extracted_text: str
    data: ExtractedInvoiceData
    confidence: dict[str, float]
    status: str


class ValidateRequest(BaseModel):
    extraction_id: int | None = None
    upload_id: int | None = None
    data: ExtractedInvoiceData | None = None


class ValidateResponse(BaseModel):
    status: str
    reasons: list[str]
    confidence: float
    extraction_id: int
    exception_id: int | None = None


class InvoiceRequest(BaseModel):
    extraction_id: int | None = None
    exception_id: int | None = None
    data: ExtractedInvoiceData | None = None


class InvoiceResponse(BaseModel):
    invoice_id: int
    invoice_number: str
    amount: float
    download_url: str


class ExceptionEditRequest(BaseModel):
    employee_id: str | None = Field(default=None)
    employee_name: str | None = Field(default=None)
    client: str | None = Field(default=None)
    client_code: str | None = Field(default=None)
    working_days: int | None = Field(default=None)
    hours: float | None = Field(default=None)
    overtime: float | None = Field(default=None)
    salary: float | None = Field(default=None)
    month: str | None = Field(default=None)


class DashboardResponse(BaseModel):
    uploaded_files: int
    generated_invoices: int
    validation_count: int
    pending_review: int
    completed_invoices: int
    todays_uploads: int
    touchless_rate: float
    total_value: float
    recent_uploads: list[dict[str, Any]]
    recent_invoices: list[dict[str, Any]]
    activity: list[dict[str, Any]]
