"""Editing a `.docx` by numbered block, never by a tool Claude drives directly (D-130,
Agent/specs/job-llm-steps.md §5). Every paragraph and table row in the document becomes one
addressable block; an edit names a block id and either new text or (for a table row) new cells.
Formatting is preserved by construction: an edit keeps the target's own run, an insert clones the
block it follows, nothing else in the document is touched.

Shared by the Tailored CV and the Cover letter (job_pipeline.py) - a master CV and a cover letter
template are both just `.docx` files to this module, which does not know which is which.
"""

import copy
import io
from dataclasses import dataclass
from typing import Final, cast

import docx
from docx.document import Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Row
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph


class DocxEditError(Exception):
    """A block id was unknown, or an operation doesn't apply to that kind of block."""


@dataclass(frozen=True)
class Block:
    id: str
    kind: str  # "paragraph" or "row"
    text: str


@dataclass(frozen=True)
class EditOp:
    id: str
    text: str


@dataclass(frozen=True)
class InsertAfterOp:
    id: str
    text: str


@dataclass(frozen=True)
class RemoveOp:
    id: str


@dataclass(frozen=True)
class AddRowAfterOp:
    id: str
    cells: list[str]


Operation = EditOp | InsertAfterOp | RemoveOp | AddRowAfterOp


def read_document(content: bytes) -> Document:
    return docx.Document(io.BytesIO(content))


def document_bytes(document: Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def list_blocks(document: Document) -> list[Block]:
    """Every non-empty body paragraph and table row, in document order. A purely blank paragraph
    (a spacer) is left out - there is nothing for Claude to usefully reference it by, and it is
    still reachable as part of whatever block precedes it for an INSERT AFTER."""
    blocks: list[Block] = []
    for index, paragraph in enumerate(document.paragraphs, start=1):
        if paragraph.text.strip():
            blocks.append(Block(id=f"B{index}", kind="paragraph", text=paragraph.text))
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            text = " | ".join(cell.text for cell in row.cells)
            if text.strip():
                blocks.append(Block(id=f"T{table_index}R{row_index}", kind="row", text=text))
    return blocks


def blocks_as_text(blocks: list[Block]) -> str:
    return "\n".join(f"[{block.id}] {block.text}" for block in blocks)


@dataclass(frozen=True)
class _Resolved:
    kind: str  # "paragraph" or "row"
    paragraph: Paragraph | None = None
    row: _Row | None = None


def _resolve(document: Document) -> dict[str, _Resolved]:
    """The same id scheme as list_blocks, but holding the live python-docx objects an operation
    mutates - built fresh from `document` each call, so ids always refer to its current state."""
    resolved: dict[str, _Resolved] = {}
    for index, paragraph in enumerate(document.paragraphs, start=1):
        if paragraph.text.strip():
            resolved[f"B{index}"] = _Resolved(kind="paragraph", paragraph=paragraph)
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            if " | ".join(cell.text for cell in row.cells).strip():
                resolved[f"T{table_index}R{row_index}"] = _Resolved(kind="row", row=row)
    return resolved


def _set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    """Replace a paragraph's visible text, keeping its first run's formatting - any further runs
    are cleared rather than left stale, so a paragraph that had three runs doesn't end up with
    the new text followed by leftover fragments of the old one."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def _clone_paragraph_with_text(paragraph: Paragraph, text: str) -> Paragraph:
    """A new paragraph styled identically to `paragraph` (a deep copy of its own XML), not yet
    attached to the document - the caller places it with `addnext`."""
    cloned_element = copy.deepcopy(paragraph._p)
    clone = Paragraph(cloned_element, paragraph._parent)
    _set_paragraph_text(clone, text)
    return clone


def _remove_element(element: CT_P | CT_Row) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _clone_row_with_cells(row: _Row, cells: list[str]) -> _Row:
    cloned_element = copy.deepcopy(row._tr)
    # _Row's own stub types `parent` narrower than Parented._parent actually is at runtime -
    # the value is correct (the same table `row` itself belongs to), just over-narrowly typed.
    clone = _Row(cloned_element, cast(Table, row._parent))
    if len(clone.cells) != len(cells):
        raise DocxEditError(
            f"This table has {len(clone.cells)} columns, but {len(cells)} cell values were given."
        )
    for cell, text in zip(clone.cells, cells, strict=True):
        cell.text = text
    return clone


_MAX_OPERATIONS: Final = 50


def apply_operations(document: Document, operations: list[Operation]) -> None:
    """Apply every operation to `document` in place. Every id is checked against the document's
    actual current blocks before anything is mutated, so a bad id fails the whole batch rather
    than leaving a half-applied document (DocxEditError, caught by job_pipeline.py and turned
    into PromptRejected, D-130's verbatim-or-fail guarantee for structural edits)."""
    if not operations:
        raise DocxEditError("No edits were given.")
    if len(operations) > _MAX_OPERATIONS:
        raise DocxEditError(f"Too many edits in one answer ({len(operations)}).")
    resolved = _resolve(document)
    for op in operations:
        if op.id not in resolved:
            raise DocxEditError(f"Unknown block id: {op.id!r}")
        target = resolved[op.id]
        if isinstance(op, EditOp) and target.kind != "paragraph":
            raise DocxEditError(
                f"{op.id} is a table row; EDIT only applies to paragraphs "
                "(use ADD ROW AFTER or REMOVE for a row)."
            )
        if isinstance(op, AddRowAfterOp) and target.kind != "row":
            raise DocxEditError(f"{op.id} is a paragraph; ADD ROW AFTER needs a table row id.")

    for op in operations:
        target = resolved[op.id]
        if isinstance(op, EditOp):
            assert target.paragraph is not None
            _set_paragraph_text(target.paragraph, op.text)
        elif isinstance(op, InsertAfterOp):
            if target.kind == "paragraph":
                assert target.paragraph is not None
                new_paragraph = _clone_paragraph_with_text(target.paragraph, op.text)
                target.paragraph._p.addnext(new_paragraph._p)
            else:
                raise DocxEditError(
                    f"{op.id} is a table row; INSERT AFTER only applies to paragraphs."
                )
        elif isinstance(op, RemoveOp):
            if target.kind == "paragraph":
                assert target.paragraph is not None
                _remove_element(target.paragraph._p)
            else:
                assert target.row is not None
                _remove_element(target.row._tr)
        elif isinstance(op, AddRowAfterOp):
            assert target.row is not None
            new_row = _clone_row_with_cells(target.row, op.cells)
            target.row._tr.addnext(new_row._tr)


def strip_manual_page_breaks(document: Document) -> None:
    """Remove every manual page break - a `<w:br w:type="page"/>` run, or a paragraph's own
    `pageBreakBefore` property - so the document's pages reflow naturally from its content
    (D-164).

    Found live: a real master CV template had a manual break placed to land a specific section on
    page 2, fixed to that spot regardless of what comes before it. Tailoring legitimately adds a
    line or two (a summary sentence, an extra bullet, D-129) ahead of it, which the fixed break
    does not account for - the content right before the break can overflow onto an almost-empty
    extra page, with the rest of the document still pushed one page further. Formatting
    (`docx_editor`'s own guarantee) is unaffected: this only removes the break instruction itself,
    nothing else about the run or paragraph it was on.
    """
    for paragraph in document.paragraphs:
        p_xml = paragraph._p
        ppr = p_xml.find(qn("w:pPr"))
        if ppr is not None:
            for page_break_before in ppr.findall(qn("w:pageBreakBefore")):
                ppr.remove(page_break_before)
        for run_xml in p_xml.findall(qn("w:r")):
            for br in run_xml.findall(qn("w:br")):
                if br.get(qn("w:type")) == "page":
                    run_xml.remove(br)
