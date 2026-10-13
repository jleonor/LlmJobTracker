from pathlib import Path
from typing import Any

import pytest

from llmjobtracker.file_preview import UnsupportedPreview, preview_for

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic"


def test_markdown_is_decoded_as_text() -> None:
    preview = preview_for("Career history.md", b"# Title\n\nSome *text*.")
    assert preview.kind == "markdown"
    assert preview.content == "# Title\n\nSome *text*."


def test_plain_text_is_decoded() -> None:
    preview = preview_for("notes.txt", b"hello")
    assert preview.kind == "text"
    assert preview.content == "hello"


def test_pdf_passes_through_unchanged() -> None:
    data = (FIXTURES / "profile" / "cv_en.pdf").read_bytes()
    preview = preview_for("cv.pdf", data)
    assert preview.kind == "pdf"
    assert preview.content == data


def test_docx_is_converted_to_a_real_pdf() -> None:
    data = (FIXTURES / "profile" / "cv_en.docx").read_bytes()
    preview = preview_for("cv.docx", data)
    assert preview.kind == "pdf"
    assert isinstance(preview.content, bytes)
    assert preview.content[:5] == b"%PDF-"


def test_an_unknown_extension_is_refused() -> None:
    with pytest.raises(UnsupportedPreview):
        preview_for("archive.zip", b"PK\x03\x04")


def test_a_file_with_no_extension_is_refused() -> None:
    with pytest.raises(UnsupportedPreview):
        preview_for("README", b"text")


def test_eml_renders_the_html_part_and_strips_the_script(tmp_path: Path) -> None:
    data = (FIXTURES / "files" / "sample.eml").read_bytes()
    preview = preview_for("message.eml", data)
    assert preview.kind == "html"
    assert isinstance(preview.content, str)
    assert "Thursday at 2pm" in preview.content
    assert "<script" not in preview.content
    assert "alert(" not in preview.content
    assert "hiring@example.com" in preview.content  # the From header, shown as plain text


def test_eml_falls_back_to_the_text_part_when_there_is_no_html() -> None:
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "a@example.com"
    message["To"] = "b@example.com"
    message["Subject"] = "Plain only"
    message.set_content("Just text, <b>not</b> html.")

    preview = preview_for("plain.eml", message.as_bytes())
    assert preview.kind == "html"
    assert isinstance(preview.content, str)
    # The angle brackets are escaped, not rendered as a tag, since the source part is plain text.
    assert "&lt;b&gt;" in preview.content


class _FakeMsg:
    """Stands in for extract_msg.MSGFile: only the attributes _msg_to_html reads."""

    sender = "sender@example.com"
    to = "recipient@example.com"
    date = "2026-10-06 09:00:00"
    subject = "A synthetic message"
    body = "Plain body with <angle> brackets."
    htmlBody: Any = None

    def __enter__(self) -> "_FakeMsg":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_msg_renders_the_plain_body_when_there_is_no_html(monkeypatch: pytest.MonkeyPatch) -> None:
    import extract_msg

    monkeypatch.setattr(extract_msg, "openMsg", lambda _data: _FakeMsg())

    preview = preview_for("message.msg", b"not a real msg file")
    assert preview.kind == "html"
    assert isinstance(preview.content, str)
    assert "A synthetic message" in preview.content
    assert "&lt;angle&gt;" in preview.content  # escaped, not rendered as a tag


def test_msg_renders_the_html_body_and_strips_a_script(monkeypatch: pytest.MonkeyPatch) -> None:
    import extract_msg

    class _HtmlMsg(_FakeMsg):
        htmlBody = b"<p>Hello</p><script>alert('x')</script>"

    monkeypatch.setattr(extract_msg, "openMsg", lambda _data: _HtmlMsg())

    preview = preview_for("message.msg", b"not a real msg file")
    assert isinstance(preview.content, str)
    assert "<p>Hello</p>" in preview.content
    assert "<script" not in preview.content
