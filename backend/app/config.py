from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent

DATASET_DIR = PROJECT_DIR / "dataset"
UPLOAD_DIR = PROJECT_DIR / "uploads"
INVOICE_DIR = PROJECT_DIR / "generated_invoices"
LOG_DIR = PROJECT_DIR / "logs"

DATABASE_URL = f"sqlite:///{BACKEND_DIR / 'touchless_invoice_agent.db'}"

SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg"}
CONFIDENCE_THRESHOLD = 90.0
COMPANY_NAME = "TASC Outsourcing"
