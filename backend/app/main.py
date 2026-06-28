from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import INVOICE_DIR, PROJECT_DIR, UPLOAD_DIR
from app.database.session import Base, SessionLocal, engine
from app.routes.api import router
from app.services.dataset_loader import seed_database


app = FastAPI(title="Touchless Invoice Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


@app.get("/")
def frontend():
    index = PROJECT_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Touchless Invoice Agent API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
