from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Protocol

from .models import GenerationConfig, MaterialDocument


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".pptx",
    ".docx",
    ".txt",
    ".md",
    ".xlsx",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class VisionClient(Protocol):
    def ocr_image(self, image_path: Path) -> str:
        ...


def scan_materials(input_dir: Path) -> list[MaterialDocument]:
    root = Path(input_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {root}")

    documents: list[MaterialDocument] = []
    for file_path in sorted(p for p in root.rglob("*") if p.is_file()):
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        documents.append(
            MaterialDocument(
                source_path=file_path,
                relative_path=file_path.relative_to(root).as_posix(),
                material_type=ext.lstrip("."),
                status="indexed",
            )
        )
    return documents


def extract_materials(
    documents: list[MaterialDocument],
    client: VisionClient | None,
    config: GenerationConfig,
) -> list[MaterialDocument]:
    extracted: list[MaterialDocument] = []
    for doc in documents:
        try:
            ext = doc.source_path.suffix.lower()
            if ext in {".txt", ".md"}:
                doc.text = _read_text(doc.source_path)
            elif ext == ".csv":
                doc.text = _read_csv(doc.source_path)
            elif ext == ".docx":
                doc.text = _read_docx(doc.source_path)
            elif ext == ".pptx":
                doc.text = _read_pptx(doc.source_path)
            elif ext == ".xlsx":
                doc.text = _read_xlsx(doc.source_path)
            elif ext == ".pdf":
                doc.text = _read_pdf(doc.source_path)
                if not doc.text.strip() and config.enable_vision_ocr:
                    doc.text = _ocr_pdf_pages(doc.source_path, client)
            elif ext in IMAGE_EXTENSIONS:
                doc.image_path = doc.source_path
                doc.text = _ocr_image(doc.source_path, client, config.enable_vision_ocr)
            doc.status = "extracted" if doc.text.strip() else "empty"
            if not doc.text.strip():
                doc.warnings.append("No text extracted; check whether the file is scanned or unsupported.")
        except Exception as exc:  # noqa: BLE001 - keep batch processing alive.
            doc.status = "failed"
            doc.warnings.append(str(exc))
        extracted.append(doc)
    return extracted


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")


def _read_csv(path: Path) -> str:
    rows: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as fh:
        reader = csv.reader(fh)
        for idx, row in enumerate(reader, start=1):
            rows.append(f"Row {idx}: " + " | ".join(row))
    return "\n".join(rows)


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required to read DOCX files.") from exc
    document = Document(path)
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    for table_index, table in enumerate(document.tables, start=1):
        paragraphs.append(f"[Table {table_index}]")
        for row in table.rows:
            paragraphs.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(paragraphs)


def _read_pptx(path: Path) -> str:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError("python-pptx is required to read PPTX files.") from exc
    prs = Presentation(path)
    slides: list[str] = []
    for index, slide in enumerate(prs.slides, start=1):
        lines = [f"[Slide {index}]"]
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                lines.append(shape.text.strip())
        slides.append("\n".join(lines))
    return "\n\n".join(slides)


def _read_xlsx(path: Path) -> str:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas and openpyxl are required to read XLSX files.") from exc
    workbook = pd.read_excel(path, sheet_name=None, dtype=str)
    parts: list[str] = []
    for sheet_name, frame in workbook.items():
        parts.append(f"[Sheet: {sheet_name}]")
        parts.append(frame.fillna("").to_csv(index=False))
    return "\n".join(parts)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required to read PDF files.") from exc
    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[Page {index}]\n{text}")
    return "\n\n".join(pages)


def _ocr_image(path: Path, client: VisionClient | None, enabled: bool) -> str:
    if not enabled:
        return ""
    if client is None:
        raise RuntimeError("Vision OCR needs a configured API client.")
    return client.ocr_image(path)


def _ocr_pdf_pages(path: Path, client: VisionClient | None) -> str:
    if client is None:
        raise RuntimeError("Vision OCR needs a configured API client.")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to OCR scanned PDF pages.") from exc

    chunks: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf = fitz.open(path)
        for page_index in range(len(pdf)):
            page = pdf.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_path = Path(temp_dir) / f"page_{page_index + 1}.png"
            pix.save(image_path)
            text = client.ocr_image(image_path)
            chunks.append(f"[Page {page_index + 1} OCR]\n{text}")
    return "\n\n".join(chunks)
