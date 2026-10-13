"""Revise (LLM): one Claude Job per chat turn, revising one generated profile document.

Extends profile_pipeline.py (D-106, Agent/specs/revise-steps.md). A revise conversation is
scoped to one of the three profile documents. Each user message queues one single-prompt
Claude Job, kind `revise_<own file kind>` (for example `revise_own_full_cv_history`); the
prompt is built when the job runs, not when it is queued, so it always reads the latest
document and the latest context files, even if an earlier turn in the same conversation is
still queued or has failed.

The answer picks its own mode (D-110): MODE: edit, a list of exact old-text/new-text
replacements applied by code, for most requests; MODE: rewrite, the full document, only when
the request cannot be expressed as a small number of such edits. A full-document answer, asked
for every time, tended to reword parts of the document the user never asked to change, even
when told to keep its structure — a code-applied, verbatim-matched edit cannot touch anything
it was not given.

The result of a turn is stored exactly where a fresh generation would be (profile_outputs,
and the generated file in its own_* slot, D-84) — a revised document is not a different kind
of thing from a generated one, just a later version of it.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from llmjobtracker.claude_job_queue import (
    ClaudeJobQueue,
    OnResult,
    PromptRejected,
    RenderedPrompt,
    Renderer,
)
from llmjobtracker.claude_jobs import PromptRow
from llmjobtracker.profile_files import store_generated_file
from llmjobtracker.profile_pipeline import (
    DEFAULT_RULES_PATH,
    DOCUMENT_FILENAMES,
    EVIDENCE_KINDS,
    MAX_PROMPT_CHARS,
    OWN_KINDS,
    PREAMBLE,
    PROMPT_KIND_FOR_OWN,
    PROMPT_KINDS,
    QUESTIONNAIRE_KINDS,
    ProfileNotReady,
    clean_document,
    document_block,
    inputs_for,
    latest_document,
    own_upload,
    store_output,
    usable_files,
    writing_rules_text,
)
from llmjobtracker.profile_pipeline import make_pipeline as make_profile_pipeline
from llmjobtracker.revise_turns import create_turn, prior_messages, turn_for_job
from llmjobtracker.runner import RunResult

REVISE_PREFIX: Final = "revise_"

DOCUMENT_LABELS: Final[dict[str, str]] = {
    "full_cv_history": "CAREER HISTORY",
    "questionnaire_analysis": "QUESTIONNAIRE ANALYSIS",
    "strategy": "STRATEGY",
}

INSTRUCTIONS: Final[dict[str, str]] = {
    "full_cv_history": (
        "Revise the career history below to satisfy the user's request in this conversation. "
        "Use only what the career history, the CVs and the letters below state; do not invent "
        "or embellish a claim to satisfy the request."
    ),
    "questionnaire_analysis": (
        "Revise the questionnaire report below to satisfy the user's request in this "
        "conversation. Use only what the questionnaire and the career history below state."
    ),
    "strategy": (
        "Revise the positioning strategy below to satisfy the user's request in this "
        "conversation. Use only what the questionnaire analysis and the career history below "
        "state."
    ),
}

# The delimiter convention mirrors the one the prompt's own FILE and document blocks already
# use (profile_pipeline.py's files_block/document_block), since the model has just read several
# examples of it in this same prompt.
EDIT_FORMAT_INSTRUCTIONS: Final = """How to answer: choose one mode, and start your answer with
exactly one of these two lines, then a blank line, then the edits or the document.

MODE: edit — for most requests: anything that changes, adds, or removes specific parts of the
document without touching the rest. List each change as one block:

=== EDIT ===
OLD:
<the exact text being replaced, copied character for character from the current document above,
with enough surrounding context that it appears only once in it>
NEW:
<the replacement text>
=== END EDIT ===

Use as many === EDIT === blocks as the request needs. OLD must match the current document
exactly and appear in it exactly once — do not paraphrase it. Keep each OLD as short as it can
be while still being unique.

MODE: rewrite — only when the request cannot be expressed as a small number of such edits, for
example reorganising the whole document. Answer with the full revised document, as Markdown,
and nothing else, right after the MODE line."""


_MODE_LINE = re.compile(r"^MODE:\s*(edit|rewrite)\s*$", re.IGNORECASE | re.MULTILINE)
_EDIT_BLOCK = re.compile(r"=== EDIT ===\nOLD:\n(.*?)\nNEW:\n(.*?)\n=== END EDIT ===", re.DOTALL)


@dataclass(frozen=True)
class RewriteAnswer:
    document: str


@dataclass(frozen=True)
class EditAnswer:
    # (old_text, new_text) pairs, in the order the model gave them.
    edits: list[tuple[str, str]]


def parse_revise_answer(text: str) -> RewriteAnswer | EditAnswer:
    """Read a revise answer's chosen mode (D-110) and its edits or document.

    Raises PromptRejected if the mode line or its body is missing or malformed — the same way
    a built prompt is rejected, not silently guessed at.
    """
    match = _MODE_LINE.search(text)
    if match is None:
        raise PromptRejected('The answer did not start with "MODE: edit" or "MODE: rewrite".')
    mode = match.group(1).lower()
    rest = text[match.end() :].strip()
    if mode == "rewrite":
        if not rest:
            raise PromptRejected("The answer was empty.")
        return RewriteAnswer(document=rest)
    edits = [
        (block.group(1).strip(), block.group(2).strip()) for block in _EDIT_BLOCK.finditer(rest)
    ]
    edits = [(old, new) for old, new in edits if old]
    if not edits:
        raise PromptRejected("MODE: edit was given, but no === EDIT === blocks were found.")
    return EditAnswer(edits=edits)


def apply_edits(document: str, edits: list[tuple[str, str]]) -> str:
    """Apply each (old_text, new_text) pair in order, the same way Claude Code's own edit tool
    would: OLD must appear in the document exactly once, so the change is unambiguous."""
    result = document
    for old_text, new_text in edits:
        count = result.count(old_text)
        if count == 0:
            raise PromptRejected(f"Could not find this text to change: {old_text[:80]!r}")
        if count > 1:
            raise PromptRejected(
                f"This text to change is not unique in the document: {old_text[:80]!r}"
            )
        result = result.replace(old_text, new_text, 1)
    return result


def output_kind_for(prompt_kind: str) -> str | None:
    """Which document a revise prompt kind is about, or None if it is not a revise prompt."""
    if not prompt_kind.startswith(REVISE_PREFIX):
        return None
    return PROMPT_KIND_FOR_OWN.get(prompt_kind[len(REVISE_PREFIX) :])


def job_kind_for(output_kind: str) -> str:
    return f"{REVISE_PREFIX}{OWN_KINDS[output_kind]}"


def _history_block(messages: list[str]) -> str:
    if not messages:
        return "(no earlier turns in this conversation)"
    numbered = "\n\n".join(f"Turn {index + 1}: {message}" for index, message in enumerate(messages))
    return f"=== EARLIER REQUESTS ===\n{numbered}\n=== END EARLIER REQUESTS ==="


def submit_revise_turn(
    conn: sqlite3.Connection, queue: ClaudeJobQueue, output_kind: str, message: str
) -> int:
    """Queue one Revise (LLM) chat turn for a generated profile document (D-106)."""
    if output_kind not in PROMPT_KINDS:
        raise ValueError(f"Unknown output kind: {output_kind}")
    if latest_document(conn, output_kind) is None:
        raise ProfileNotReady(f"There is no {DOCUMENT_FILENAMES[output_kind]} yet to revise.")
    cleaned = message.strip()
    if not cleaned:
        raise ValueError("The message is empty.")
    job_kind = job_kind_for(output_kind)
    job_id = queue.submit(
        conn, f"Revise: {DOCUMENT_FILENAMES[output_kind]}", job_kind, [(job_kind, "")]
    )
    create_turn(conn, output_kind, job_id, cleaned)
    return job_id


def build_revise_prompt(
    conn: sqlite3.Connection, prompt: PromptRow, rules_path: Path
) -> RenderedPrompt:
    output_kind = output_kind_for(prompt.prompt_kind)
    if output_kind is None:
        # Not a revise prompt. Its text was written when the job was queued.
        return RenderedPrompt(text=prompt.prompt_text)

    stored = latest_document(conn, output_kind)
    if stored is None:
        raise PromptRejected(f"There is no {output_kind} document yet to revise.")
    turn = turn_for_job(conn, prompt.claude_job_id)
    if turn is None:
        raise PromptRejected("This revise turn was not recorded.")
    history = prior_messages(conn, output_kind, turn.id)

    rules = writing_rules_text(conn, rules_path)
    parts = [
        f"TASK: revise_{output_kind}",
        PREAMBLE.format(rules=rules),
        INSTRUCTIONS[output_kind],
        inputs_for(conn, output_kind),
        document_block(f"CURRENT {DOCUMENT_LABELS[output_kind]}", stored),
        _history_block(history),
        f"=== THE USER'S NEW REQUEST ===\n{turn.message}\n=== END REQUEST ===",
        EDIT_FORMAT_INSTRUCTIONS,
    ]
    text = "\n\n".join(parts)
    if len(text) > MAX_PROMPT_CHARS:
        raise PromptRejected(
            "The material is too large for one prompt. Remove the oldest or longest files."
        )
    return RenderedPrompt(text=text)


def _store_revise_result(
    conn: sqlite3.Connection, prompt: PromptRow, result: RunResult, data_folder: Path
) -> None:
    output_kind = output_kind_for(prompt.prompt_kind)
    if output_kind is None:
        return
    answer = parse_revise_answer(result.text)
    if isinstance(answer, RewriteAnswer):
        document = clean_document(answer.document)
    else:
        stored = latest_document(conn, output_kind)
        if stored is None:
            raise PromptRejected(f"There is no {output_kind} document anymore to edit.")
        _, current = stored
        document = clean_document(apply_edits(current, answer.edits))
    if output_kind == "full_cv_history":
        hashes = [file.sha256 for file in usable_files(conn, EVIDENCE_KINDS)]
    elif output_kind == "questionnaire_analysis":
        hashes = [file.sha256 for file in usable_files(conn, QUESTIONNAIRE_KINDS)]
    else:
        hashes = []
    store_output(conn, output_kind, document, prompt.claude_job_id, hashes, source="generated")
    own_kind = OWN_KINDS[output_kind]
    if own_upload(conn, output_kind) is None:
        # Nothing of the user's own is in this slot, so the revised answer fills it, readable
        # the same way as an upload or a fresh generation (D-84).
        store_generated_file(
            conn, data_folder, own_kind, DOCUMENT_FILENAMES[output_kind], document.encode("utf-8")
        )


def make_pipeline(
    data_folder: Path,
    rules_path: Path = DEFAULT_RULES_PATH,
) -> tuple[Renderer, OnResult]:
    """The prompt builder and answer checker for the queue: profile analysis plus Revise (LLM)."""
    profile_render, profile_on_result = make_profile_pipeline(data_folder, rules_path)

    def render(conn: sqlite3.Connection, prompt: PromptRow) -> RenderedPrompt:
        if output_kind_for(prompt.prompt_kind) is None:
            return profile_render(conn, prompt)
        return build_revise_prompt(conn, prompt, rules_path)

    def on_result(conn: sqlite3.Connection, prompt: PromptRow, result: RunResult) -> None:
        if output_kind_for(prompt.prompt_kind) is None:
            profile_on_result(conn, prompt, result)
            return
        _store_revise_result(conn, prompt, result, data_folder)

    return render, on_result
