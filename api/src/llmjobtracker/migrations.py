"""Versioned SQLite migrations, each with an up and a down step.

Applied versions are recorded in `schema_migrations`. Add new migrations to the end of
MIGRATIONS and never edit one that has been applied. Each migration runs in one transaction.
"""

import sqlite3
from dataclasses import dataclass

# Allowed values, from D-44 (statuses), D-54 (work mode and contract type).
# "Not Started" as migrations 1 and 2 named it (D-05, D-44). Migration 13 renames it to
# "Identified" (D-101); this frozen tuple keeps migration 2's own SQL exactly as it was applied.
_V2_STATUSES = (
    "Not Started",
    "Applied",
    "Screening",
    "Interview",
    "Offer",
    "Rejected",
    "Withdrawn",
)
# D-101 renamed "Not Started" to "Identified". Frozen here the same way _V2_STATUSES is: this is
# what migration 13's own rebuild actually applied, kept for migration 30's down step.
_V29_STATUSES = (
    "Identified",
    "Applied",
    "Screening",
    "Interview",
    "Offer",
    "Rejected",
    "Withdrawn",
)
# Current values (D-223 adds "Expired" as a third end state alongside Rejected/Withdrawn).
STATUSES = (*_V29_STATUSES, "Expired")
WORK_MODES = ("Onsite", "Hybrid", "Remote", "Unknown")
CONTRACT_TYPES = ("Full-Time", "Part-Time", "Contract/Short Term", "Other", "Unknown")
# A Job Application's own files (Agent/specs/files.md, D-111/D-112). "other" is the catch-all
# the frontend's Additional files subsection already shows anything unmatched under.
JOB_FILE_KINDS = (
    "listing",
    "master_cv",
    "tailored_cv",
    "cover_letter",
    "positioning_breakdown",
    "eml",
    "msg",
    "other",
)
# The five chat-revised sections migration 18 originally reserved (D-136). Frozen here, same
# reason _V2_STATUSES is kept above: this is what migration 18's own CREATE TABLE actually applied,
# and must stay exactly that regardless of what's added later.
_V18_JOB_REVISE_SECTION_KINDS = (
    "job_details",
    "positioning",
    "application_history",
    "tailored_cv",
    "cover_letter",
)
# The current, full set - migration 22 (D-169) widens job_revise_turns.section_kind's CHECK to add
# "interview_prep", which wasn't reserved by migration 18 since Interview preparation didn't exist
# yet. Used everywhere else in the app (job_revise_pipeline.py) and by migration 22's own new
# table shape; migration 18's table keeps using the frozen tuple above.
JOB_REVISE_SECTION_KINDS = (*_V18_JOB_REVISE_SECTION_KINDS, "interview_prep")

# Open Application values (Phase 11, D-249 to D-253; open-application-domain.md). A subset of
# STATUSES above - Screening, Interview and Offer are never written to open_applications.
OPEN_APPLICATION_STATUSES = ("Identified", "Applied", "Rejected", "Withdrawn", "Expired")
OPEN_APPLICATION_TARGET_TYPES = ("talent_pool", "unsolicited", "cold_outreach")
OPEN_APPLICATION_FILE_KINDS = ("tailored_cv", "cover_letter", "introduction_message", "other")
OPEN_APPLICATION_RESEARCH_SOURCE_TYPES = ("url", "text")
OPEN_APPLICATION_REVISE_SECTION_KINDS = (
    "company_details",
    "tailored_cv",
    "cover_letter",
    "introduction_message",
)

# Phase 2 values (D-62, D-64, D-66; Agent/specs/profile-steps.md).
CLAUDE_JOB_STATUSES = ("queued", "processing", "paused", "cancelled", "done", "failed")
PROMPT_STATUSES = ("queued", "running", "done", "failed", "cancelled")
# Kinds as migration 3 defined them. Kept here so that migration stays as it was applied.
_V3_FILE_KINDS = (
    "master_cv_en",
    "master_cv_fr",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
)
# Master CVs are one kind (English and French alike), and the user's own outputs have kinds of
# their own (2026-10-06, D-67, D-68). Migration 4 moves the rows over.
# Kinds as migration 4 defined them.
_V4_FILE_KINDS = (
    "master_cv",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
    "own_full_cv_history",
    "own_questionnaire_analysis",
    "own_strategy",
)
# The user may also upload their own Fact Sheet (D-70). Migration 5 adds it.
# Kinds as migration 5 defined them.
_V5_FILE_KINDS = (
    "master_cv",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
    "own_full_cv_history",
    "own_questionnaire_analysis",
    "own_strategy",
    "own_fact_sheet",
)
# The cover letter template is the user's own template for letters (Phase 5 uses it, D-71).
# Kinds as migration 9 defined them (migration 6 added the cover letter template, unchanged since).
_V9_FILE_KINDS = (*_V5_FILE_KINDS, "cover_letter_template")
EXTRACTION_STATUSES = ("ok", "no_text", "unsupported", "failed")
# Kinds as migration 9 defined them. The Fact Sheet is dropped as its own output (D-86).
_V9_OUTPUT_KINDS = ("full_cv_history", "fact_sheet", "questionnaire_analysis", "strategy")
# There is no own_fact_sheet upload kind: the career history is the one evidentiary document, and
# there is no schema for the user's own version of an output to be converted into (D-86). Migration
# 10 drops own_fact_sheet and the Fact Sheet output kind.
PROFILE_FILE_KINDS = tuple(kind for kind in _V9_FILE_KINDS if kind != "own_fact_sheet")
PROFILE_OUTPUT_KINDS = tuple(kind for kind in _V9_OUTPUT_KINDS if kind != "fact_sheet")
FACT_STATUSES = ("unverified", "verified", "rejected")

# Phase 7 values (D-195, D-197, D-198, D-201).
RUNNER_BACKENDS = ("claude_code", "codex")
# "reset_time" is D-75's existing behavior (auto-resume at the CLI-reported reset time),
# kept as the default so upgrading does not change how a paused job already behaves.
RETRY_POLICIES = ("reset_time", "fixed_interval", "manual_only")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: tuple[str, ...]
    down: tuple[str, ...]
    # A migration that rebuilds a table other tables reference (a CHECK can only change that way).
    # Foreign keys are switched off for it, and checked again before it commits.
    rebuild: bool = False


_V1_JOBS = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started',
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V2_JOB_APPLICATIONS = f"""
CREATE TABLE job_applications (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ({_in_list(_V2_STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V2_STATUS_HISTORY = f"""
CREATE TABLE status_history (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(_V2_STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"

_V3_CLAUDE_JOBS = f"""
CREATE TABLE claude_jobs (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    job_application_id INTEGER REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ({_in_list(CLAUDE_JOB_STATUSES)})),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT ({_NOW}),
    updated_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""

_V3_CLAUDE_JOB_PROMPTS = f"""
CREATE TABLE claude_job_prompts (
    id INTEGER PRIMARY KEY,
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    prompt_kind TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ({_in_list(PROMPT_STATUSES)})),
    result_text TEXT,
    error TEXT,
    cost_usd REAL,
    duration_ms INTEGER,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (claude_job_id, position)
)
"""

_V3_PROFILE_FILES = f"""
CREATE TABLE profile_files (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(_V3_FILE_KINDS)})),
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT ({_NOW}),
    extraction_status TEXT CHECK (
        extraction_status IS NULL OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})
    ),
    extraction_message TEXT,
    extracted_text TEXT
)
"""

_V3_PROFILE_OUTPUTS = f"""
CREATE TABLE profile_outputs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(PROFILE_OUTPUT_KINDS)})),
    version INTEGER NOT NULL CHECK (version >= 1),
    claude_job_id INTEGER REFERENCES claude_jobs(id) ON DELETE SET NULL,
    body_json TEXT NOT NULL,
    input_sha256s TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW}),
    UNIQUE (kind, version)
)
"""

_V3_FACTS = f"""
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    profile_output_id INTEGER NOT NULL REFERENCES profile_outputs(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    text TEXT NOT NULL,
    date TEXT NOT NULL CHECK (date <> ''),
    source_file_id INTEGER NOT NULL REFERENCES profile_files(id),
    source_location TEXT NOT NULL CHECK (source_location <> ''),
    status TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN ({_in_list(FACT_STATUSES)})),
    updated_at TEXT NOT NULL DEFAULT ({_NOW}),
    UNIQUE (profile_output_id, fact_key)
)
"""


def _profile_outputs_table(table: str, kinds: tuple[str, ...], column: str) -> str:
    return f"""
CREATE TABLE {table} (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(kinds)})),
    version INTEGER NOT NULL CHECK (version >= 1),
    claude_job_id INTEGER REFERENCES claude_jobs(id) ON DELETE SET NULL,
    {column} TEXT NOT NULL,
    input_sha256s TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW}),
    UNIQUE (kind, version)
)
"""


def _profile_files_table(table: str, kinds: tuple[str, ...]) -> str:
    return f"""
CREATE TABLE {table} (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(kinds)})),
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT ({_NOW}),
    extraction_status TEXT CHECK (
        extraction_status IS NULL OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})
    ),
    extraction_message TEXT,
    extracted_text TEXT
)
"""


# Migration 13 (D-101): job_applications and status_history both have a status CHECK, so renaming
# the value needs a rebuild of both, same as the profile_files/profile_outputs kind renames above.
_V13_JOB_APPLICATIONS_NEW = f"""
CREATE TABLE job_applications_new (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Identified' CHECK (status IN ({_in_list(STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V13_STATUS_HISTORY_NEW = f"""
CREATE TABLE status_history_new (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

# The pre-D-101 shape, for migration 13's down step.
_V13_JOB_APPLICATIONS_OLD = f"""
CREATE TABLE job_applications_old (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ({_in_list(_V2_STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V13_STATUS_HISTORY_OLD = f"""
CREATE TABLE status_history_old (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(_V2_STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

# Migration 30 (D-223): widens the status CHECK again, to add "Expired". job_applications has
# grown many columns since migration 13's own rebuild (all added via ALTER TABLE ADD COLUMN, never
# another rebuild), so this rebuild's shape is the table's full current column list.
_V30_JOB_APPLICATIONS_NEW = f"""
CREATE TABLE job_applications_new (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Identified' CHECK (status IN ({_in_list(STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    description TEXT,
    requirements TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    master_cv_profile_file_id INTEGER REFERENCES profile_files(id) ON DELETE SET NULL,
    fit TEXT NOT NULL DEFAULT '[]',
    gaps TEXT NOT NULL DEFAULT '[]',
    strategy TEXT,
    unclear TEXT NOT NULL DEFAULT '[]',
    positioning_scores TEXT NOT NULL DEFAULT '[]',
    interview_prep TEXT NOT NULL DEFAULT '[]'
)
"""

_V30_STATUS_HISTORY_NEW = f"""
CREATE TABLE status_history_new (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

# The pre-D-223 shape, for migration 30's down step.
_V30_JOB_APPLICATIONS_OLD = f"""
CREATE TABLE job_applications_old (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Identified' CHECK (status IN ({_in_list(_V29_STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    description TEXT,
    requirements TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    master_cv_profile_file_id INTEGER REFERENCES profile_files(id) ON DELETE SET NULL,
    fit TEXT NOT NULL DEFAULT '[]',
    gaps TEXT NOT NULL DEFAULT '[]',
    strategy TEXT,
    unclear TEXT NOT NULL DEFAULT '[]',
    positioning_scores TEXT NOT NULL DEFAULT '[]',
    interview_prep TEXT NOT NULL DEFAULT '[]'
)
"""

_V30_STATUS_HISTORY_OLD = f"""
CREATE TABLE status_history_old (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(_V29_STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

_V14_REVISE_TURNS = f"""
CREATE TABLE revise_turns (
    id INTEGER PRIMARY KEY,
    output_kind TEXT NOT NULL CHECK (output_kind IN ({_in_list(PROFILE_OUTPUT_KINDS)})),
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    message TEXT NOT NULL CHECK (message <> ''),
    created_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""

# Agent/specs/files.md: a Job Application's own files (the listing, CVs, cover letters, the
# positioning breakdown document, filed emails), stored under
# %LOCALAPPDATA%\LlmJobTracker\files\<company>\<role_title>\<name>.
_V15_JOB_FILES = f"""
CREATE TABLE job_files (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(JOB_FILE_KINDS)})),
    name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    date TEXT,
    created_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""

# D-136, Agent/specs/job-revise-steps.md: one shared table for all five chat-revised sections
# (section_kind column), the same single-table-many-kinds shape revise_turns already uses for
# the three profile documents - kept separate from revise_turns itself since that table's
# output_kind CHECK and lack of a job_application_id column are profile-specific by design.
# attachment_job_file_id is unused until Application history's own batch wires an upload into a
# turn, but the column is added now so that batch doesn't need its own table-rebuild migration.
_V18_JOB_REVISE_TURNS = f"""
CREATE TABLE job_revise_turns (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    section_kind TEXT NOT NULL CHECK (section_kind IN ({_in_list(_V18_JOB_REVISE_SECTION_KINDS)})),
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    message TEXT NOT NULL CHECK (message <> ''),
    attachment_job_file_id INTEGER REFERENCES job_files(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""

# Migration 22 (D-169): widens section_kind's CHECK to add "interview_prep" - a table rebuild,
# since SQLite can't ALTER a CHECK. Nothing else references job_revise_turns as a parent, so this
# doesn't need migration 13's FK-toggling (rebuild=True): dropping a table only matters for FK
# enforcement when something else points at it, and nothing does here.
_V22_JOB_REVISE_TURNS_NEW = f"""
CREATE TABLE job_revise_turns_new (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    section_kind TEXT NOT NULL CHECK (section_kind IN ({_in_list(JOB_REVISE_SECTION_KINDS)})),
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    message TEXT NOT NULL CHECK (message <> ''),
    attachment_job_file_id INTEGER REFERENCES job_files(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""

# migration 22's down step: back to migration 18's own five-kind shape.
_V22_JOB_REVISE_TURNS_OLD = f"""
CREATE TABLE job_revise_turns_old (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    section_kind TEXT NOT NULL CHECK (section_kind IN ({_in_list(_V18_JOB_REVISE_SECTION_KINDS)})),
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    message TEXT NOT NULL CHECK (message <> ''),
    attachment_job_file_id INTEGER REFERENCES job_files(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="create jobs",
        up=(_V1_JOBS,),
        down=("DROP TABLE jobs",),
    ),
    Migration(
        version=2,
        name="rename jobs to job_applications, add table fields and status history",
        up=(
            _V2_JOB_APPLICATIONS,
            """
            INSERT INTO job_applications
                (id, company, role_title, lane, status, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, status, next_action, due_date, created_at
            FROM jobs
            """,
            "DROP TABLE jobs",
            _V2_STATUS_HISTORY,
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
            """
            INSERT INTO status_history (job_application_id, status, changed_at)
            SELECT id, status, created_at FROM job_applications
            """,
        ),
        down=(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                lane TEXT,
                status TEXT NOT NULL DEFAULT 'Not Started',
                next_action TEXT,
                due_date TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            INSERT INTO jobs
                (id, company, role_title, lane, status, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, status, next_action, due_date, created_at
            FROM job_applications
            """,
            "DROP TABLE status_history",
            "DROP TABLE job_applications",
        ),
    ),
    Migration(
        version=3,
        name="add Claude Jobs, profile files, profile outputs and facts",
        up=(
            _V3_CLAUDE_JOBS,
            _V3_CLAUDE_JOB_PROMPTS,
            _V3_PROFILE_FILES,
            _V3_PROFILE_OUTPUTS,
            _V3_FACTS,
        ),
        down=(
            "DROP TABLE facts",
            "DROP TABLE profile_outputs",
            "DROP TABLE profile_files",
            "DROP TABLE claude_job_prompts",
            "DROP TABLE claude_jobs",
        ),
    ),
    Migration(
        version=4,
        name="one master CV kind, and kinds for the user's own outputs",
        rebuild=True,
        up=(
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id,
                   CASE WHEN kind IN ('master_cv_en', 'master_cv_fr')
                        THEN 'master_cv' ELSE kind END,
                   original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
        ),
        down=(
            # The English/French split cannot be recovered, so master CVs go back to English.
            # The user's own outputs have no place in the older kinds, so their rows are removed,
            # along with any fact that cites one of them.
            "DELETE FROM facts WHERE source_file_id IN "
            "(SELECT id FROM profile_files WHERE kind LIKE 'own_%')",
            "DELETE FROM profile_files WHERE kind LIKE 'own_%'",
            _profile_files_table("profile_files_old", _V3_FILE_KINDS),
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, CASE WHEN kind = 'master_cv' THEN 'master_cv_en' ELSE kind END,
                   original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
        ),
    ),
    Migration(
        version=5,
        name="add the user's own Fact Sheet as an upload kind",
        rebuild=True,
        up=(
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
        ),
        down=(
            # Facts that cite the user's own Fact Sheet go with it.
            "DELETE FROM facts WHERE source_file_id IN "
            "(SELECT id FROM profile_files WHERE kind = 'own_fact_sheet')",
            "DELETE FROM profile_files WHERE kind = 'own_fact_sheet'",
            _profile_files_table("profile_files_old", _V4_FILE_KINDS),
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
        ),
    ),
    Migration(
        version=6,
        name="add the cover letter template as an upload kind",
        rebuild=True,
        up=(
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
        ),
        down=(
            "DELETE FROM facts WHERE source_file_id IN "
            "(SELECT id FROM profile_files WHERE kind = 'cover_letter_template')",
            "DELETE FROM profile_files WHERE kind = 'cover_letter_template'",
            _profile_files_table("profile_files_old", _V5_FILE_KINDS),
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
        ),
    ),
    Migration(
        version=7,
        name="record the model each prompt ran on",
        up=("ALTER TABLE claude_job_prompts ADD COLUMN model TEXT",),
        down=("ALTER TABLE claude_job_prompts DROP COLUMN model",),
    ),
    Migration(
        version=8,
        name="record when a paused job resumes by itself",
        up=("ALTER TABLE claude_jobs ADD COLUMN resume_at TEXT",),
        down=("ALTER TABLE claude_jobs DROP COLUMN resume_at",),
    ),
    Migration(
        version=9,
        name="mark a profile file as generated, not uploaded",
        up=("ALTER TABLE profile_files ADD COLUMN generated INTEGER NOT NULL DEFAULT 0",),
        down=("ALTER TABLE profile_files DROP COLUMN generated",),
    ),
    Migration(
        version=10,
        name="drop the Fact Sheet: three documents, not four (D-85, D-86)",
        rebuild=True,
        up=(
            "DROP TABLE facts",
            "DELETE FROM profile_files WHERE kind = 'own_fact_sheet'",
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            # The table builder predates migration 9's column; add it here too (as 9 itself did).
            "ALTER TABLE profile_files_new ADD COLUMN generated INTEGER NOT NULL DEFAULT 0",
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text, generated)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text, generated
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
            "DELETE FROM profile_outputs WHERE kind = 'fact_sheet'",
            _profile_outputs_table("profile_outputs_new", PROFILE_OUTPUT_KINDS, "document"),
            """
            INSERT INTO profile_outputs_new
                (id, kind, version, claude_job_id, document, input_sha256s, created_at)
            SELECT id, kind, version, claude_job_id, body_json, input_sha256s, created_at
            FROM profile_outputs
            """,
            "DROP TABLE profile_outputs",
            "ALTER TABLE profile_outputs_new RENAME TO profile_outputs",
        ),
        down=(
            # The Fact Sheet's own rows and every fact cannot be recovered (same as migrations 4
            # and 5's irreversible splits): they were deleted going up, not merely hidden.
            _profile_outputs_table("profile_outputs_old", _V9_OUTPUT_KINDS, "body_json"),
            """
            INSERT INTO profile_outputs_old
                (id, kind, version, claude_job_id, body_json, input_sha256s, created_at)
            SELECT id, kind, version, claude_job_id, document, input_sha256s, created_at
            FROM profile_outputs
            """,
            "DROP TABLE profile_outputs",
            "ALTER TABLE profile_outputs_old RENAME TO profile_outputs",
            _profile_files_table("profile_files_old", _V9_FILE_KINDS),
            "ALTER TABLE profile_files_old ADD COLUMN generated INTEGER NOT NULL DEFAULT 0",
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text, generated)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text, generated
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
            _V3_FACTS,
        ),
    ),
    Migration(
        version=11,
        name="record whether a document was generated or copied from your own file",
        up=(
            "ALTER TABLE profile_outputs ADD COLUMN source TEXT NOT NULL DEFAULT 'generated' "
            "CHECK (source IN ('generated', 'imported'))",
        ),
        down=("ALTER TABLE profile_outputs DROP COLUMN source",),
    ),
    Migration(
        version=12,
        name="add a settings table for the user's display name",
        up=(
            "CREATE TABLE settings ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "user_name TEXT NOT NULL DEFAULT 'YourName'"
            ")",
            "INSERT INTO settings (id, user_name) VALUES (1, 'YourName')",
        ),
        down=("DROP TABLE settings",),
    ),
    Migration(
        version=13,
        name="rename the Not Started status to Identified (D-101)",
        rebuild=True,
        up=(
            _V13_JOB_APPLICATIONS_NEW,
            """
            INSERT INTO job_applications_new
                (id, company, role_title, lane, location, work_mode, contract_type,
                 portal_name, portal_url, status, match_score, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, location, work_mode, contract_type,
                   portal_name, portal_url,
                   CASE WHEN status = 'Not Started' THEN 'Identified' ELSE status END,
                   match_score, next_action, due_date, created_at
            FROM job_applications
            """,
            "DROP TABLE job_applications",
            "ALTER TABLE job_applications_new RENAME TO job_applications",
            _V13_STATUS_HISTORY_NEW,
            """
            INSERT INTO status_history_new (id, job_application_id, status, changed_at)
            SELECT id, job_application_id,
                   CASE WHEN status = 'Not Started' THEN 'Identified' ELSE status END,
                   changed_at
            FROM status_history
            """,
            "DROP TABLE status_history",
            "ALTER TABLE status_history_new RENAME TO status_history",
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
        ),
        down=(
            _V13_JOB_APPLICATIONS_OLD,
            """
            INSERT INTO job_applications_old
                (id, company, role_title, lane, location, work_mode, contract_type,
                 portal_name, portal_url, status, match_score, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, location, work_mode, contract_type,
                   portal_name, portal_url,
                   CASE WHEN status = 'Identified' THEN 'Not Started' ELSE status END,
                   match_score, next_action, due_date, created_at
            FROM job_applications
            """,
            "DROP TABLE job_applications",
            "ALTER TABLE job_applications_old RENAME TO job_applications",
            _V13_STATUS_HISTORY_OLD,
            """
            INSERT INTO status_history_old (id, job_application_id, status, changed_at)
            SELECT id, job_application_id,
                   CASE WHEN status = 'Identified' THEN 'Not Started' ELSE status END,
                   changed_at
            FROM status_history
            """,
            "DROP TABLE status_history",
            "ALTER TABLE status_history_old RENAME TO status_history",
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
        ),
    ),
    Migration(
        version=14,
        name="add revise_turns for the Revise (LLM) chat (D-106)",
        up=(
            _V14_REVISE_TURNS,
            "CREATE INDEX revise_turns_by_kind ON revise_turns (output_kind, id)",
        ),
        down=("DROP TABLE revise_turns",),
    ),
    Migration(
        version=15,
        name="add description/requirements/notes and job_files (Agent/specs/domain.md, files.md)",
        up=(
            "ALTER TABLE job_applications ADD COLUMN description TEXT",
            "ALTER TABLE job_applications ADD COLUMN requirements TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE job_applications ADD COLUMN notes TEXT",
            _V15_JOB_FILES,
            "CREATE INDEX job_files_by_job ON job_files (job_application_id, kind)",
        ),
        down=(
            "DROP TABLE job_files",
            "ALTER TABLE job_applications DROP COLUMN notes",
            "ALTER TABLE job_applications DROP COLUMN requirements",
            "ALTER TABLE job_applications DROP COLUMN description",
        ),
    ),
    Migration(
        version=16,
        name="add master_cv_profile_file_id and manual positioning fields (D-116)",
        up=(
            "ALTER TABLE job_applications ADD COLUMN master_cv_profile_file_id INTEGER "
            "REFERENCES profile_files(id) ON DELETE SET NULL",
            "ALTER TABLE job_applications ADD COLUMN fit TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE job_applications ADD COLUMN gaps TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE job_applications ADD COLUMN strategy TEXT",
            "ALTER TABLE job_applications ADD COLUMN unclear TEXT NOT NULL DEFAULT '[]'",
        ),
        down=(
            "ALTER TABLE job_applications DROP COLUMN unclear",
            "ALTER TABLE job_applications DROP COLUMN strategy",
            "ALTER TABLE job_applications DROP COLUMN gaps",
            "ALTER TABLE job_applications DROP COLUMN fit",
            "ALTER TABLE job_applications DROP COLUMN master_cv_profile_file_id",
        ),
    ),
    Migration(
        version=17,
        name="add extraction columns to job_files (D-122, Agent/specs/job-llm-steps.md)",
        up=(
            "ALTER TABLE job_files ADD COLUMN sha256 TEXT",
            "ALTER TABLE job_files ADD COLUMN extraction_status TEXT CHECK ("
            f"extraction_status IS NULL OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})"
            ")",
            "ALTER TABLE job_files ADD COLUMN extraction_message TEXT",
            "ALTER TABLE job_files ADD COLUMN extracted_text TEXT",
        ),
        down=(
            "ALTER TABLE job_files DROP COLUMN extracted_text",
            "ALTER TABLE job_files DROP COLUMN extraction_message",
            "ALTER TABLE job_files DROP COLUMN extraction_status",
            "ALTER TABLE job_files DROP COLUMN sha256",
        ),
    ),
    Migration(
        version=18,
        name="add job_revise_turns for the job page's chat-revise sections (D-136)",
        up=(
            _V18_JOB_REVISE_TURNS,
            "CREATE INDEX job_revise_turns_by_section "
            "ON job_revise_turns (job_application_id, section_kind, id)",
        ),
        down=("DROP TABLE job_revise_turns",),
    ),
    Migration(
        version=19,
        name="add positioning_scores, the structured per-requirement breakdown (D-139)",
        up=(
            "ALTER TABLE job_applications ADD COLUMN positioning_scores TEXT NOT NULL DEFAULT '[]'",
        ),
        down=("ALTER TABLE job_applications DROP COLUMN positioning_scores",),
    ),
    Migration(
        version=20,
        name="add source_url to job_files, for Add Job's duplicate detection (D-146)",
        up=("ALTER TABLE job_files ADD COLUMN source_url TEXT",),
        down=("ALTER TABLE job_files DROP COLUMN source_url",),
    ),
    Migration(
        version=21,
        name="add interview_prep, Interview preparation's ten question/answer pairs (D-168)",
        up=("ALTER TABLE job_applications ADD COLUMN interview_prep TEXT NOT NULL DEFAULT '[]'",),
        down=("ALTER TABLE job_applications DROP COLUMN interview_prep",),
    ),
    Migration(
        version=22,
        name="widen job_revise_turns.section_kind to add interview_prep (D-169)",
        up=(
            _V22_JOB_REVISE_TURNS_NEW,
            "INSERT INTO job_revise_turns_new "
            "(id, job_application_id, section_kind, claude_job_id, message, "
            "attachment_job_file_id, created_at) "
            "SELECT id, job_application_id, section_kind, claude_job_id, message, "
            "attachment_job_file_id, created_at FROM job_revise_turns",
            "DROP TABLE job_revise_turns",
            "ALTER TABLE job_revise_turns_new RENAME TO job_revise_turns",
            "CREATE INDEX job_revise_turns_by_section "
            "ON job_revise_turns (job_application_id, section_kind, id)",
        ),
        down=(
            _V22_JOB_REVISE_TURNS_OLD,
            "INSERT INTO job_revise_turns_old "
            "(id, job_application_id, section_kind, claude_job_id, message, "
            "attachment_job_file_id, created_at) "
            "SELECT id, job_application_id, section_kind, claude_job_id, message, "
            "attachment_job_file_id, created_at FROM job_revise_turns",
            "DROP TABLE job_revise_turns",
            "ALTER TABLE job_revise_turns_old RENAME TO job_revise_turns",
            "CREATE INDEX job_revise_turns_by_section "
            "ON job_revise_turns (job_application_id, section_kind, id)",
        ),
    ),
    Migration(
        version=23,
        name="add backend selection, retry policy and token tracking (D-195, D-197, D-198, D-201)",
        up=(
            "ALTER TABLE settings ADD COLUMN backend TEXT NOT NULL DEFAULT 'claude_code' "
            f"CHECK (backend IN ({_in_list(RUNNER_BACKENDS)}))",
            "ALTER TABLE settings ADD COLUMN retry_policy TEXT NOT NULL DEFAULT 'reset_time' "
            f"CHECK (retry_policy IN ({_in_list(RETRY_POLICIES)}))",
            "ALTER TABLE settings ADD COLUMN retry_interval_minutes INTEGER NOT NULL DEFAULT 60 "
            "CHECK (retry_interval_minutes > 0)",
            "ALTER TABLE settings ADD COLUMN retry_max_attempts INTEGER NOT NULL DEFAULT 24 "
            "CHECK (retry_max_attempts > 0)",
            "ALTER TABLE claude_job_prompts ADD COLUMN input_tokens INTEGER",
            "ALTER TABLE claude_job_prompts ADD COLUMN output_tokens INTEGER",
            f"""
            CREATE TABLE model_prices (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL CHECK (provider IN ({_in_list(RUNNER_BACKENDS)})),
                model TEXT NOT NULL,
                input_price_per_token REAL NOT NULL DEFAULT 0 CHECK (input_price_per_token >= 0),
                output_price_per_token REAL NOT NULL DEFAULT 0
                    CHECK (output_price_per_token >= 0),
                pricing_url TEXT,
                updated_at TEXT NOT NULL DEFAULT ({_NOW}),
                UNIQUE (provider, model)
            )
            """,
        ),
        down=(
            "DROP TABLE model_prices",
            "ALTER TABLE claude_job_prompts DROP COLUMN output_tokens",
            "ALTER TABLE claude_job_prompts DROP COLUMN input_tokens",
            "ALTER TABLE settings DROP COLUMN retry_max_attempts",
            "ALTER TABLE settings DROP COLUMN retry_interval_minutes",
            "ALTER TABLE settings DROP COLUMN retry_policy",
            "ALTER TABLE settings DROP COLUMN backend",
        ),
    ),
    Migration(
        version=24,
        name="move pricing_url from model_prices to a per-provider table (D-198)",
        up=(
            "ALTER TABLE model_prices DROP COLUMN pricing_url",
            f"""
            CREATE TABLE provider_pricing (
                provider TEXT PRIMARY KEY CHECK (provider IN ({_in_list(RUNNER_BACKENDS)})),
                pricing_url TEXT
            )
            """,
            "INSERT INTO provider_pricing (provider) VALUES "
            + ", ".join(f"('{backend}')" for backend in RUNNER_BACKENDS),
        ),
        down=(
            "DROP TABLE provider_pricing",
            "ALTER TABLE model_prices ADD COLUMN pricing_url TEXT",
        ),
    ),
    Migration(
        version=25,
        name="add claude_jobs.retry_attempts for the fixed_interval retry policy (D-201)",
        up=(
            "ALTER TABLE claude_jobs ADD COLUMN retry_attempts INTEGER NOT NULL DEFAULT 0 "
            "CHECK (retry_attempts >= 0)",
        ),
        down=("ALTER TABLE claude_jobs DROP COLUMN retry_attempts",),
    ),
    Migration(
        version=26,
        name="add settings.claude_code_model and codex_model (D-206)",
        up=(
            "ALTER TABLE settings ADD COLUMN claude_code_model TEXT NOT NULL "
            "DEFAULT 'claude-sonnet-5'",
            "ALTER TABLE settings ADD COLUMN codex_model TEXT NOT NULL DEFAULT 'gpt-6.1-sol'",
        ),
        down=(
            "ALTER TABLE settings DROP COLUMN codex_model",
            "ALTER TABLE settings DROP COLUMN claude_code_model",
        ),
    ),
    Migration(
        version=27,
        name="add settings.llm_export_path (D-212)",
        up=("ALTER TABLE settings ADD COLUMN llm_export_path TEXT",),
        down=("ALTER TABLE settings DROP COLUMN llm_export_path",),
    ),
    Migration(
        version=28,
        name="add lanes (D-214)",
        up=(
            f"""
            CREATE TABLE lanes (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                reasoning TEXT,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({_NOW}),
                updated_at TEXT NOT NULL DEFAULT ({_NOW})
            )
            """,
        ),
        down=("DROP TABLE lanes",),
    ),
    Migration(
        version=29,
        name="seed the default Other lane (D-219)",
        up=(
            # COALESCE(MAX(position) + 1, 0): appended after any lane a database already has
            # (an upgrade), or position 0 on a brand-new, empty table.
            "INSERT INTO lanes (name, description, position) "
            "SELECT 'Other', 'Roles that don''t clearly fit any of the lanes above.', "
            "COALESCE(MAX(position) + 1, 0) FROM lanes",
        ),
        down=("DELETE FROM lanes WHERE name = 'Other'",),
    ),
    Migration(
        version=30,
        name="add the Expired status (D-223)",
        rebuild=True,
        up=(
            _V30_JOB_APPLICATIONS_NEW,
            "INSERT INTO job_applications_new SELECT * FROM job_applications",
            "DROP TABLE job_applications",
            "ALTER TABLE job_applications_new RENAME TO job_applications",
            _V30_STATUS_HISTORY_NEW,
            "INSERT INTO status_history_new SELECT * FROM status_history",
            "DROP TABLE status_history",
            "ALTER TABLE status_history_new RENAME TO status_history",
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
        ),
        down=(
            _V30_JOB_APPLICATIONS_OLD,
            # Any row actually set to Expired has no pre-30 equivalent - falls back to Identified,
            # the same default a brand-new application gets, rather than failing the rebuild.
            "UPDATE job_applications SET status = 'Identified' WHERE status = 'Expired'",
            "INSERT INTO job_applications_old SELECT * FROM job_applications",
            "DROP TABLE job_applications",
            "ALTER TABLE job_applications_old RENAME TO job_applications",
            _V30_STATUS_HISTORY_OLD,
            "DELETE FROM status_history WHERE status = 'Expired'",
            "INSERT INTO status_history_old SELECT * FROM status_history",
            "DROP TABLE status_history",
            "ALTER TABLE status_history_old RENAME TO status_history",
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
        ),
    ),
    Migration(
        version=31,
        name="add lanes.fit_gap_summary for analyze_lane (D-238)",
        up=(
            "ALTER TABLE lanes ADD COLUMN fit_gap_summary TEXT",
            "ALTER TABLE lanes ADD COLUMN fit_gap_summary_generated_at TEXT",
        ),
        down=(
            "ALTER TABLE lanes DROP COLUMN fit_gap_summary_generated_at",
            "ALTER TABLE lanes DROP COLUMN fit_gap_summary",
        ),
    ),
    Migration(
        version=32,
        name="add claude_jobs.lane_id for analyze_lane (D-238)",
        up=(
            "ALTER TABLE claude_jobs ADD COLUMN lane_id INTEGER "
            "REFERENCES lanes(id) ON DELETE CASCADE",
        ),
        down=("ALTER TABLE claude_jobs DROP COLUMN lane_id",),
    ),
    Migration(
        version=33,
        name="add the lane_overview singleton for summarize_lanes (D-245)",
        up=(
            "CREATE TABLE lane_overview ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "summary TEXT, "
            "generated_at TEXT"
            ")",
            "INSERT INTO lane_overview (id) VALUES (1)",
        ),
        down=("DROP TABLE lane_overview",),
    ),
    Migration(
        version=34,
        name="split lane_overview's summary into a short summary plus fit/gaps sections (D-245)",
        up=(
            "ALTER TABLE lane_overview ADD COLUMN overall_fit TEXT",
            "ALTER TABLE lane_overview ADD COLUMN overall_gaps TEXT",
        ),
        down=(
            "ALTER TABLE lane_overview DROP COLUMN overall_gaps",
            "ALTER TABLE lane_overview DROP COLUMN overall_fit",
        ),
    ),
    Migration(
        version=35,
        name="add Open Applications: entity, status history, research items, files, revise "
        "turns (Phase 11, D-248 to D-254)",
        up=(
            f"""
            CREATE TABLE open_applications (
                id INTEGER PRIMARY KEY,
                target_name TEXT,
                target_type TEXT
                    CHECK (target_type IS NULL OR target_type IN (
                        {_in_list(OPEN_APPLICATION_TARGET_TYPES)}
                    )),
                contact_name TEXT,
                contact_title TEXT,
                contact_email TEXT,
                angle TEXT,
                why_this_company TEXT,
                other_notes TEXT,
                master_cv_profile_file_id INTEGER
                    REFERENCES profile_files(id) ON DELETE SET NULL,
                notes TEXT,
                next_action TEXT,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'Identified'
                    CHECK (status IN ({_in_list(OPEN_APPLICATION_STATUSES)})),
                created_at TEXT NOT NULL DEFAULT ({_NOW})
            )
            """,
            f"""
            CREATE TABLE open_application_status_history (
                id INTEGER PRIMARY KEY,
                open_application_id INTEGER NOT NULL
                    REFERENCES open_applications(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK (status IN ({_in_list(OPEN_APPLICATION_STATUSES)})),
                changed_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX open_application_status_history_by_application "
            "ON open_application_status_history (open_application_id, changed_at)",
            f"""
            CREATE TABLE open_application_research_items (
                id INTEGER PRIMARY KEY,
                open_application_id INTEGER NOT NULL
                    REFERENCES open_applications(id) ON DELETE CASCADE,
                position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 5),
                source_type TEXT NOT NULL
                    CHECK (source_type IN ({_in_list(OPEN_APPLICATION_RESEARCH_SOURCE_TYPES)})),
                content TEXT NOT NULL,
                extraction_status TEXT
                    CHECK (
                        extraction_status IS NULL
                        OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})
                    ),
                extraction_message TEXT,
                extracted_text TEXT,
                UNIQUE (open_application_id, position)
            )
            """,
            f"""
            CREATE TABLE open_application_files (
                id INTEGER PRIMARY KEY,
                open_application_id INTEGER NOT NULL
                    REFERENCES open_applications(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ({_in_list(OPEN_APPLICATION_FILE_KINDS)})),
                name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                subject TEXT,
                sha256 TEXT,
                extraction_status TEXT
                    CHECK (
                        extraction_status IS NULL
                        OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})
                    ),
                extraction_message TEXT,
                extracted_text TEXT
            )
            """,
            f"""
            CREATE TABLE open_application_revise_turns (
                id INTEGER PRIMARY KEY,
                open_application_id INTEGER NOT NULL
                    REFERENCES open_applications(id) ON DELETE CASCADE,
                section_kind TEXT NOT NULL
                    CHECK (section_kind IN ({_in_list(OPEN_APPLICATION_REVISE_SECTION_KINDS)})),
                claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({_NOW})
            )
            """,
            "ALTER TABLE claude_jobs ADD COLUMN open_application_id INTEGER "
            "REFERENCES open_applications(id) ON DELETE CASCADE",
        ),
        down=(
            "ALTER TABLE claude_jobs DROP COLUMN open_application_id",
            "DROP TABLE open_application_revise_turns",
            "DROP TABLE open_application_files",
            "DROP TABLE open_application_research_items",
            "DROP TABLE open_application_status_history",
            "DROP TABLE open_applications",
        ),
    ),
)

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    conn.execute(_LEDGER)
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row[0]) for row in rows]


def _run(
    conn: sqlite3.Connection,
    statements: tuple[str, ...],
    ledger_sql: str,
    params: tuple[object, ...],
    rebuild: bool = False,
) -> None:
    if rebuild:
        # Must be set outside a transaction. It is restored below, whatever happens.
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        if rebuild and conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("The rebuild would leave rows with broken references.")
        conn.execute(ledger_sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if rebuild:
            conn.execute("PRAGMA foreign_keys = ON")


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply every migration not yet recorded. Returns the versions applied now."""
    done = set(applied_versions(conn))
    applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in done:
            continue
        _run(
            conn,
            migration.up,
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
            migration.rebuild,
        )
        applied.append(migration.version)
    return applied


def rollback(conn: sqlite3.Connection, steps: int = 1) -> list[int]:
    """Undo the newest `steps` applied migrations. Returns the versions reverted."""
    by_version = {m.version: m for m in MIGRATIONS}
    reverted: list[int] = []
    for version in sorted(applied_versions(conn), reverse=True)[:steps]:
        migration = by_version[version]
        _run(
            conn,
            migration.down,
            "DELETE FROM schema_migrations WHERE version = ?",
            (version,),
            migration.rebuild,
        )
        reverted.append(version)
    return reverted
