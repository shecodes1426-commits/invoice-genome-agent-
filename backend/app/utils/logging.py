import logging
from logging.handlers import RotatingFileHandler

from sqlalchemy.orm import Session

from app.config import LOG_DIR
from app.models.db import AppLog


LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("touchless_invoice_agent")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


def log_event(db: Session | None, event_type: str, message: str, level: str = "INFO") -> None:
    getattr(logger, level.lower(), logger.info)(f"{event_type}: {message}")
    if db is not None:
        db.add(AppLog(event_type=event_type, message=message, level=level))
        db.commit()
