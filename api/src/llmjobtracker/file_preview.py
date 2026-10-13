"""Turning a file's bytes into something a browser can render, for the Preview overlay (D-107).

One dispatcher by extension, shared by every place a file is listed (profile files today; a
job application's own files once Phase 3's file table exists, planning/files.md). This is
plain conversion code, run for the user when a Preview button is clicked — never a Claude Code
invocation (D-108): rendering a preview is not a model step, and should not spend a prompt.

Email files are untrusted (D-26, D-38): their HTML is stripped down to a small, inert tag set
before it ever reaches the browser, in addition to the sandboxed iframe the frontend renders it
in. No remote image is allowed through, so a preview cannot act as a read-receipt beacon.
"""

import email
import email.policy
import re
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from typing import Final

import bleach
import dxpdf
import extract_msg


class UnsupportedPreview(Exception):
    """No preview exists for this file type. The UI falls back to Open in the default app."""


@dataclass(frozen=True)
class Preview:
    kind: str  # "pdf" | "text" | "markdown" | "html"
    # PDF bytes for "pdf"; decoded, ready-to-render text for every other kind.
    content: bytes | str


# A small, inert tag set: enough to read an email's layout, nothing that can act (no script,
# no form, no iframe) or phone home (no img — see the module docstring).
_ALLOWED_TAGS: Final = [
    "p",
    "br",
    "div",
    "span",
    "b",
    "i",
    "u",
    "strong",
    "em",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "a",
    "blockquote",
    "pre",
    "code",
    "hr",
]
_ALLOWED_ATTRS: Final = {"a": ["href"]}
# bleach's strip=True unwraps a disallowed tag but leaves its text content behind — a <script>
# or <style> body would otherwise show up as inert but visible text. Dropped first, tag and
# content together, before the general sanitize pass.
_SCRIPT_OR_STYLE: Final = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def preview_for(name: str, content: bytes) -> Preview:
    """Build a Preview for one file's bytes, dispatched by its extension.

    Raises UnsupportedPreview for anything else, so the caller can fall back to Open.
    """
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix == "md":
        return Preview(kind="markdown", content=_decode(content))
    if suffix == "txt":
        return Preview(kind="text", content=_decode(content))
    if suffix == "pdf":
        return Preview(kind="pdf", content=content)
    if suffix == "docx":
        return Preview(kind="pdf", content=dxpdf.convert(content))
    if suffix == "eml":
        return Preview(kind="html", content=_eml_to_html(content))
    if suffix == "msg":
        return Preview(kind="html", content=_msg_to_html(content))
    raise UnsupportedPreview(
        f"There is no preview for .{suffix} files yet. Open it in its default app instead."
    )


def _decode(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _sanitize(html: str) -> str:
    without_scripts = _SCRIPT_OR_STYLE.sub("", html)
    return bleach.clean(without_scripts, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


def _header_rows(pairs: list[tuple[str, str | None]]) -> str:
    rows = [
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in pairs
        if value
    ]
    return f"<table class='email-headers'>{''.join(rows)}</table>" if rows else ""


def _as_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _body_from_message(message: EmailMessage) -> tuple[str, bool]:
    """The best body part to show from a stdlib email.message.EmailMessage: (text, is_html)."""
    if message.is_multipart():
        html_part = message.get_body(preferencelist=("html",))
        if html_part is not None:
            return html_part.get_content(), True
        plain_part = message.get_body(preferencelist=("plain",))
        if plain_part is not None:
            return plain_part.get_content(), False
        return "(no readable body)", False
    return message.get_content(), message.get_content_type() == "text/html"


def _eml_to_html(data: bytes) -> str:
    message = email.message_from_bytes(data, policy=email.policy.default)
    headers = _header_rows(
        [
            ("From", message.get("From")),
            ("To", message.get("To")),
            ("Date", message.get("Date")),
            ("Subject", message.get("Subject")),
        ]
    )
    body, is_html = _body_from_message(message)
    body_html = body if is_html else f"<pre>{escape(body)}</pre>"
    return _sanitize(f"{headers}<hr>{body_html}")


@dataclass(frozen=True)
class EmailText:
    sender: str | None
    date: str | None
    subject: str | None
    body: str


def eml_to_text(data: bytes) -> EmailText:
    """An .eml's plain text, for a prompt to read (job_pipeline.py's Application history step) —
    not a preview: no sandboxing needed here, since the text never reaches a browser as HTML."""
    message = email.message_from_bytes(data, policy=email.policy.default)
    body, is_html = _body_from_message(message)
    text = bleach.clean(body, tags=[], strip=True) if is_html else body
    return EmailText(
        sender=message.get("From"),
        date=message.get("Date"),
        subject=message.get("Subject"),
        body=text.strip(),
    )


def msg_to_text(data: bytes) -> EmailText:
    """A .msg's plain text, the same way eml_to_text reads an .eml."""
    with extract_msg.openMsg(data) as parsed:
        html_body = _as_text(getattr(parsed, "htmlBody", None))
        text = (
            bleach.clean(html_body, tags=[], strip=True)
            if html_body
            else _as_text(getattr(parsed, "body", None))
        )
        return EmailText(
            sender=getattr(parsed, "sender", None),
            date=str(getattr(parsed, "date", "") or "") or None,
            subject=getattr(parsed, "subject", None),
            body=text.strip(),
        )


def _msg_to_html(data: bytes) -> str:
    """Render a .msg file as HTML (D-107).

    Not yet verified against a real .msg file — extract-msg's attribute names are confirmed
    against its own docs (Message.sender/to/date/subject/body/htmlBody), but no live Outlook
    export has been run through this yet. Confirm with a real file before Phase 6 relies on it.
    """
    with extract_msg.openMsg(data) as parsed:
        headers = _header_rows(
            [
                ("From", getattr(parsed, "sender", None)),
                ("To", getattr(parsed, "to", None)),
                ("Date", str(getattr(parsed, "date", "") or "") or None),
                ("Subject", getattr(parsed, "subject", None)),
            ]
        )
        html_body = _as_text(getattr(parsed, "htmlBody", None))
        if html_body:
            body_html = html_body
        else:
            plain = _as_text(getattr(parsed, "body", None)) or "(no readable body)"
            body_html = f"<pre>{escape(plain)}</pre>"
    return _sanitize(f"{headers}<hr>{body_html}")
