"""Text extraction, by code and never by Claude (D-41, Phase 2 step 6; D-121, job-llm-steps.md).

PDF is read through its text layer (pypdf). DOCX gives paragraph and table text (python-docx).
TXT and MD are read as text. HTML (a saved page, or a job listing fetched by the app) is reduced
to its readable content (trafilatura), dropping navigation, cookie banners and footers. Nothing
is OCR'd. A file with no text layer, or no readable content, is reported as `no_text`, so it can
be caught before any model step uses it.
"""

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import docx
import pypdf
import trafilatura
from lxml import etree

# A PDF with fewer characters than this in its text layer is treated as having no text.
MIN_TEXT_CHARS: Final = 40


@dataclass(frozen=True)
class Extraction:
    status: str  # ok, no_text, unsupported or failed (EXTRACTION_STATUSES in migrations.py)
    text: str
    message: str | None


def clean_text(text: str) -> str:
    """Normalise line endings and surrounding whitespace. Shared by every extraction path, and
    by pasted text (listing_intake.py), which gets no other cleanup before this."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _pdf(path: Path) -> Extraction:
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return Extraction("failed", "", "This PDF is password protected.")
    text = clean_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    if len(text) < MIN_TEXT_CHARS:
        return Extraction(
            "no_text",
            "",
            "This PDF has no text layer, so it may be a scan. Upload a text or DOCX copy.",
        )
    return Extraction("ok", text, None)


W_NS: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# A text box can be stored twice: once for current Word, and again as a fallback (mc:Fallback).
MC_FALLBACK: Final = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# Headers and footers are separate parts of a DOCX file (header1.xml, footer1.xml, ...).
_HEADER_FOOTER: Final = re.compile(r"word/(header|footer)\d*\.xml")


def _paragraph_text(paragraph: etree._Element) -> str:
    # Only the text whose own paragraph is this one, so text in a nested box is not read twice.
    texts = []
    for node in paragraph.iter(f"{W_NS}t"):
        owner = node.getparent()
        while owner is not None and owner.tag != f"{W_NS}p":
            owner = owner.getparent()
        if owner is paragraph and node.text:
            texts.append(node.text)
    return "".join(texts)


def _in_fallback(paragraph: etree._Element) -> bool:
    owner = paragraph.getparent()
    while owner is not None:
        if owner.tag == MC_FALLBACK:
            return True
        owner = owner.getparent()
    return False


def _in_box(paragraph: etree._Element) -> bool:
    """Whether a paragraph sits in a text box (a shape's text), which python-docx does not read."""
    owner = paragraph.getparent()
    while owner is not None:
        if owner.tag == f"{W_NS}txbxContent":
            return True
        owner = owner.getparent()
    return False


def _docx(path: Path) -> Extraction:
    # python-docx reads the body and its tables only. Text boxes, headers and footers hold dates
    # and titles in many CVs (D-83), so every paragraph of the file's XML is read, in order.
    document = docx.Document(str(path))
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    with zipfile.ZipFile(path) as archive:
        boxed: list[str] = []
        for name in ["word/document.xml"] + sorted(
            n for n in archive.namelist() if _HEADER_FOOTER.fullmatch(n)
        ):
            root = etree.fromstring(archive.read(name))
            for paragraph in root.iter(f"{W_NS}p"):
                if _in_fallback(paragraph):
                    continue
                if name != "word/document.xml" or _in_box(paragraph):
                    text = _paragraph_text(paragraph).strip()
                    if text:
                        boxed.append(text)
    # A paragraph already read by python-docx is not repeated.
    known = set(lines)
    lines += [text for text in boxed if text not in known]
    text = clean_text("\n".join(lines))
    if not text:
        return Extraction("no_text", "", "This DOCX file has no text.")
    return Extraction("ok", text, None)


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Older French files are often saved as Windows-1252 rather than UTF-8.
        return raw.decode("cp1252", errors="replace")


def _plain(path: Path) -> Extraction:
    text = clean_text(_decode_text(path.read_bytes()))
    if not text:
        return Extraction("no_text", "", "This text file is empty.")
    return Extraction("ok", text, None)


def html_to_text(html: str) -> str:
    """The readable content of an HTML page, dropping navigation, cookie banners and footers
    (trafilatura). Shared by a saved HTML file (`_html` below) and a fetched URL's response."""
    return clean_text(trafilatura.extract(html) or "")


def extraction_from_html_text(text: str) -> Extraction:
    """The no_text check every HTML-derived extraction needs, whether the HTML came from a saved
    file (`_html` below) or a URL fetched by listing_intake.py."""
    if len(text) < MIN_TEXT_CHARS:
        return Extraction(
            "no_text",
            "",
            "No readable content could be found on this page (it may need JavaScript to show "
            "its content, or the save kept only navigation and boilerplate text).",
        )
    return Extraction("ok", text, None)


def _html(path: Path) -> Extraction:
    return extraction_from_html_text(html_to_text(_decode_text(path.read_bytes())))


def extract(path: Path) -> Extraction:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return _pdf(path)
        if suffix == ".docx":
            return _docx(path)
        if suffix in (".txt", ".md"):
            return _plain(path)
        if suffix in (".html", ".htm"):
            return _html(path)
    except Exception as error:
        return Extraction("failed", "", f"Could not read this file ({type(error).__name__}).")
    return Extraction("unsupported", "", "This file type is not supported.")
