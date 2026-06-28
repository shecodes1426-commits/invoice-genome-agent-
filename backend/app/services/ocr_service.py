from pathlib import Path

import pdfplumber


def _tesseract_image(path: Path) -> tuple[str, float]:
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(path))
        return text, 82.0 if text.strip() else 0.0
    except Exception:
        return "", 0.0


def _easyocr_image(path: Path) -> tuple[str, float]:
    try:
        import easyocr

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        results = reader.readtext(str(path))
        if not results:
            return "", 0.0
        text = "\n".join(item[1] for item in results)
        confidence = sum(float(item[2]) for item in results) / len(results) * 100
        return text, round(confidence, 2)
    except Exception:
        return _tesseract_image(path)


def extract_text_from_file(path: str | Path) -> tuple[str, float]:
    file_path = Path(path)
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        text_parts: list[str] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or "")
            text = "\n".join(text_parts).strip()
            if text:
                return text, 96.0
        except Exception:
            pass
        return "", 0.0

    if ext in {".png", ".jpg", ".jpeg"}:
        return _easyocr_image(file_path)

    return "", 0.0
