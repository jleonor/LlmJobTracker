"""Text extraction for profile files, by code and never by Claude (D-41, Phase 2 step 6).

PDF is read through its text layer (pypdf). DOCX gives paragraph and table text (python-docx).
TXT and MD are read as text. Nothing is OCR'd. A file with no text layer is reported as
`no_text`, so it can be caught before any model step uses it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import docx
import pypdf

# A PDF with fewer characters than this in its text layer is treated as having no text.
MIN_TEXT_CHARS: Final = 40


@dataclass(frozen=True)
class Extraction:
    status: str  # ok, no_text, unsupported or failed (EXTRACTION_STATUSES in migrations.py)
    text: str
    message: str | None


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _pdf(path: Path) -> Extraction:
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return Extraction("failed", "", "This PDF is password protected.")
    text = _clean("\n\n".join(page.extract_text() or "" for page in reader.pages))
    if len(text) < MIN_TEXT_CHARS:
        return Extraction(
            "no_text",
            "",
            "This PDF has no text layer, so it may be a scan. Upload a text or DOCX copy.",
        )
    return Extraction("ok", text, None)


def _docx(path: Path) -> Extraction:
    document = docx.Document(str(path))
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    text = _clean("\n".join(lines))
    if not text:
        return Extraction("no_text", "", "This DOCX file has no text.")
    return Extraction("ok", text, None)


def _plain(path: Path) -> Extraction:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Older French files are often saved as Windows-1252 rather than UTF-8.
        text = raw.decode("cp1252", errors="replace")
    text = _clean(text)
    if not text:
        return Extraction("no_text", "", "This text file is empty.")
    return Extraction("ok", text, None)


def extract(path: Path) -> Extraction:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return _pdf(path)
        if suffix == ".docx":
            return _docx(path)
        if suffix in (".txt", ".md"):
            return _plain(path)
    except Exception as error:
        return Extraction("failed", "", f"Could not read this file ({type(error).__name__}).")
    return Extraction("unsupported", "", "This file type is not supported.")
