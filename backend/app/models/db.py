from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database.session import Base


class Customer(Base):
    __tablename__ = "customers"

    client_code = Column(String, primary_key=True, index=True)
    client_name = Column(String, nullable=False, index=True)
    city = Column(String)
    industry = Column(String)
    contact_email = Column(String)
    status = Column(String)


class Employee(Base):
    __tablename__ = "employees"

    emp_id = Column(String, primary_key=True, index=True)
    full_name = Column(String, nullable=False, index=True)
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String, index=True)
    client_code = Column(String, ForeignKey("customers.client_code"), index=True)
    client_name = Column(String, index=True)
    job_title = Column(String)
    department = Column(String)
    nationality = Column(String)
    date_of_joining = Column(String)
    status = Column(String)
    iban = Column(String)
    basic = Column(Float, default=0)
    housing = Column(Float, default=0)
    transport = Column(Float, default=0)
    food = Column(Float, default=0)
    phone = Column(Float, default=0)
    total_ctc = Column(Float, default=0)

    customer = relationship("Customer")


class Payroll(Base):
    __tablename__ = "payroll"

    id = Column(Integer, primary_key=True)
    emp_id = Column(String, ForeignKey("employees.emp_id"), index=True)
    employee_name = Column(String, index=True)
    client_code = Column(String, index=True)
    client_name = Column(String, index=True)
    pay_period = Column(String, index=True)
    basic = Column(Float, default=0)
    housing = Column(Float, default=0)
    transport = Column(Float, default=0)
    food = Column(Float, default=0)
    phone = Column(Float, default=0)
    gross = Column(Float, default=0)
    ot_hours = Column(Float, default=0)
    ot_amount = Column(Float, default=0)
    deductions = Column(Float, default=0)
    net_pay = Column(Float, default=0)
    currency = Column(String, default="AED")
    working_days = Column(Integer, default=0)

    employee = relationship("Employee")
    __table_args__ = (UniqueConstraint("emp_id", "pay_period", name="uq_payroll_emp_period"),)


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True)
    case_name = Column(String, index=True)
    input_format = Column(String)
    provided_input = Column(Text)
    generation_notes = Column(Text)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, index=True)
    status = Column(String, default="uploaded", index=True)
    extracted_text = Column(Text, default="")
    ocr_confidence = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ExtractionRecord(Base):
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=True)
    employee_id = Column(String, index=True)
    employee_name = Column(String, index=True)
    client = Column(String, index=True)
    client_code = Column(String, index=True)
    working_days = Column(Integer)
    hours = Column(Float)
    overtime = Column(Float)
    salary = Column(Float)
    month = Column(String, default="June 2026")
    raw_text = Column(Text, default="")
    extraction_confidence = Column(Float, default=0)
    matching_confidence = Column(Float, default=0)
    overall_confidence = Column(Float, default=0)
    status = Column(String, default="extracted", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id"), index=True)
    status = Column(String, index=True)
    reasons = Column(Text, default="[]")
    confidence = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ExceptionItem(Base):
    __tablename__ = "exception_queue"

    id = Column(Integer, primary_key=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id"), index=True)
    upload_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=True)
    reason = Column(Text)
    status = Column(String, default="pending", index=True)
    confidence = Column(Float, default=0)
    assigned_to = Column(String, default="Human Reviewer")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    invoice_number = Column(String, unique=True, index=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id"), index=True)
    employee_id = Column(String, index=True)
    employee_name = Column(String)
    client_name = Column(String, index=True)
    month = Column(String, index=True)
    amount = Column(Float, default=0)
    pdf_path = Column(String)
    status = Column(String, default="generated", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    __table_args__ = (UniqueConstraint("employee_id", "client_name", "month", name="uq_invoice_emp_client_month"),)


class AppLog(Base):
    __tablename__ = "app_logs"

    id = Column(Integer, primary_key=True)
    event_type = Column(String, index=True)
    message = Column(Text)
    level = Column(String, default="INFO")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
