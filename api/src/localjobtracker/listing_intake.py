"""Turning a URL, pasted text, or an uploaded file into text the user reviews before the
Listing's Generate (LLM) step runs (D-121, Agent/specs/job-llm-steps.md).

Every path here is plain code, never Claude: a URL is fetched with a timeout and a size cap and
reduced to its readable text (CLAUDE.md's product rules, D-32); an upload is read the same way a
Job Application's own files already are (extraction.py); pasted text is just cleaned. Nothing is
saved here - the result is shown to the user to review and edit, and only the reviewed text is
ever sent to a model.
"""

import tempfile
from pathlib import Path
from typing import Final

import httpx
from pydantic import BaseModel

from localjobtracker.extraction import (
    Extraction,
    clean_text,
    extract,
    extraction_from_html_text,
    html_to_text,
)

FETCH_TIMEOUT_S: Final = 10.0
# A page or upload above this is refused outright, before any extraction is attempted.
MAX_FETCH_BYTES: Final = 10 * 1024 * 1024
# Some sites refuse a request with no browser-like User-Agent.
_USER_AGENT: Final = "Mozilla/5.0 (compatible; LocalJobTracker/0.1; a local, single-user app)"
UPLOAD_EXTENSIONS: Final = frozenset({".pdf", ".docx", ".txt", ".md", ".html", ".htm"})


class ListingExtraction(BaseModel):
    method: str  # "url" | "paste" | "upload"
    source: str | None  # the URL or the uploaded file's name; None for paste
    status: str  # ok, no_text, unsupported or failed (EXTRACTION_STATUSES)
    message: str | None
    text: str


class ListingFetchError(Exception):
    """A rejected request to one of this module's routes. `status` is the HTTP status to answer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _result(method: str, source: str | None, result: Extraction) -> ListingExtraction:
    return ListingExtraction(
        method=method,
        source=source,
        status=result.status,
        message=result.message,
        text=result.text,
    )


def extract_from_url(url: str) -> ListingExtraction:
    """Fetch a URL server-side and reduce it to readable text. The page itself is never sent to
    Claude - a fallback is returned, not raised, for anything the fetch or extraction itself
    cannot get past, so the caller can show the paste box the same way as for any other
    extraction failure (CLAUDE.md's fallback rule)."""
    cleaned = url.strip()
    if not cleaned:
        raise ListingFetchError(400, "Enter a URL.")
    try:
        with httpx.Client(
            follow_redirects=True, timeout=FETCH_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}
        ) as http_client:
            response = http_client.get(cleaned)
    except httpx.InvalidURL as error:
        raise ListingFetchError(400, "That doesn't look like a URL.") from error
    except httpx.HTTPError as error:
        message = f"Could not reach this page ({type(error).__name__})."
        return _result("url", cleaned, Extraction("failed", "", message))
    if response.status_code >= 400:
        message = f"The page answered with HTTP {response.status_code}."
        return _result("url", cleaned, Extraction("failed", "", message))
    if len(response.content) > MAX_FETCH_BYTES:
        return _result("url", cleaned, Extraction("failed", "", "The page is larger than 10 MB."))
    return _result("url", cleaned, extraction_from_html_text(html_to_text(response.text)))


def extract_from_paste(text: str) -> ListingExtraction:
    cleaned = clean_text(text)
    if not cleaned:
        return _result("paste", None, Extraction("no_text", "", "Paste some text first."))
    return _result("paste", None, Extraction("ok", cleaned, None))


def extract_from_upload(filename: str, content: bytes) -> ListingExtraction:
    """Read an uploaded file's text the same way extraction.py reads any other file, without
    saving it - only the Listing's Generate (LLM) step, once the user approves the reviewed
    text, writes a stored file (job-llm-steps.md)."""
    name = (filename or "").strip() or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise ListingFetchError(415, "Use a PDF, DOCX, TXT, MD or HTML file.")
    if not content:
        raise ListingFetchError(400, "The file is empty.")
    if len(content) > MAX_FETCH_BYTES:
        raise ListingFetchError(413, "The file is larger than 10 MB.")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        result = extract(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return _result("upload", name, result)
