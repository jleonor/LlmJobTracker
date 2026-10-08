"""Revise (LLM): one Claude Job per chat turn, revising one generated profile document.

Extends profile_pipeline.py (D-106, Agent/specs/revise-steps.md). A revise conversation is
scoped to one of the three profile documents. Each user message queues one single-prompt
Claude Job, kind `revise_<own file kind>` (for example `revise_own_full_cv_history`); the
prompt is built when the job runs, not when it is queued, so it always reads the latest
document and the latest context files, even if an earlier turn in the same conversation is
still queued or has failed.

The result of a turn is stored exactly where a fresh generation would be (profile_outputs,
and the generated file in its own_* slot, D-84) — a revised document is not a different kind
of thing from a generated one, just a later version of it.
"""

import sqlite3
from pathlib import Path
from typing import Final

from localjobtracker.claude_job_queue import (
    ClaudeJobQueue,
    OnResult,
    PromptRejected,
    RenderedPrompt,
    Renderer,
)
from localjobtracker.claude_jobs import PromptRow
from localjobtracker.profile_files import store_generated_file
from localjobtracker.profile_pipeline import (
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
from localjobtracker.profile_pipeline import make_pipeline as make_profile_pipeline
from localjobtracker.revise_turns import create_turn, prior_messages, turn_for_job
from localjobtracker.runner import RunResult

REVISE_PREFIX: Final = "revise_"

DOCUMENT_LABELS: Final[dict[str, str]] = {
    "full_cv_history": "CAREER HISTORY",
    "questionnaire_analysis": "QUESTIONNAIRE ANALYSIS",
    "strategy": "STRATEGY",
}

INSTRUCTIONS: Final[dict[str, str]] = {
    "full_cv_history": (
        "Revise the career history below to satisfy the user's request in this conversation, "
        "keeping its structure and its sourcing style (saying in words which file a claim comes "
        "from where it matters). Use only what the career history, the CVs and the letters below "
        "state; do not invent or embellish a claim to satisfy the request."
    ),
    "questionnaire_analysis": (
        "Revise the questionnaire report below to satisfy the user's request in this "
        "conversation, keeping its section structure. Use only what the questionnaire and the "
        "career history below state."
    ),
    "strategy": (
        "Revise the positioning strategy below to satisfy the user's request in this "
        "conversation, keeping its section structure and the 'lane' terminology. Use only what "
        "the questionnaire analysis and the career history below state."
    ),
}


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
    document = clean_document(result.text)
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
