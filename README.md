# Touchless Invoice Agent

FastAPI backend wired to the existing `index.html` dashboard. The UI styling and layout are preserved; JavaScript now calls real REST APIs.

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Startup Seeding

On startup, the app reads:

- `dataset/w1.xlsx`
- `dataset/w2.docx`
- `dataset/problem_statement.pdf`

It populates SQLite with customers, employees, payroll, and test-case guidance automatically. The database file is created at `backend/touchless_invoice_agent.db`.

## Workflow

1. Upload PDF, Excel, PNG, JPG, or JPEG.
2. Excel files are parsed with pandas/openpyxl. PDF/image files go through text extraction/OCR.
3. Rule-based extraction converts content into invoice JSON.
4. Validation checks employee, client, salary, working days, duplicates, and missing fields.
5. Valid records generate invoice PDFs in `generated_invoices/`.
6. Low-confidence or invalid records are placed in the exception queue for approve/reject/edit.

## API

- `POST /upload`
- `POST /extract`
- `POST /validate`
- `POST /generate-invoice`
- `GET /dashboard`
- `GET /employees`
- `GET /invoice/{id}`
- `GET /exceptions`
- `POST /approve/{id}`
- `POST /reject/{id}`
- `POST /exceptions/{id}/edit`

OCR uses EasyOCR when available and Tesseract as fallback for image files. Text PDFs are extracted with pdfplumber.
