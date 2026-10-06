# Profile steps: contracts for the four profile prompts

Phase 2 (D-64, D-66). Each prompt is one Claude Job prompt, run through the `Runner` with a JSON schema. The code validates every output before it is stored as a new version in `profile_outputs`. Nothing is overwritten.

## Common rules

- **Order:** `FULL_CV_HISTORY`, then the Fact Sheet, then the questionnaire analysis, then the strategy. Each later prompt may read the earlier outputs.
- **Input:** the extracted text of the profile files that extracted with status `ok` (see Phase 2 step 6). Each file is written into the prompt in a block headed with its `file_id`, its kind and its name. The runner gives the model no tools (`--tools ""`), so a prompt never reads files itself.
- **Building:** each prompt is built when it runs, not when the job is queued, because each one uses the outputs stored before it. The built text is stored with the prompt.
- **Writing rules:** every prompt includes the writing rules in force. These are the user's own uploaded rules if there are any (their latest extracted text), otherwise `Agent/rules/honesty.md`.
- **Size:** if the built prompt is larger than 150,000 characters, the prompt is not sent. The prompt fails with a message that says the input is too large. Splitting large inputs is not part of Phase 2.
- **Schema:** each answer is requested with `--json-schema`. Code validates the answer again against the checks below, because the schema does not check the rules that link one output to another.
- **Source:** a source is always `{file_id, location}`. `file_id` is the id of an uploaded profile file, as stored. `location` says where in it the text is: a page, a section heading, a line range, or a role title with its dates.
- **Dates:** a date is `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. A range is written as its start date. A fact with no date in its source gets the date of the source file if the file's name or metadata gives one. Otherwise the prompt returns the date as `""`, and the code check fails.
- **IDs:** `H-001` for history items, `F-001` for facts, `Q-001` for questionnaire themes, `L-01` for lanes. IDs are unique within one output.
- **Honesty:** outputs follow `Agent/rules/honesty.md`. They use only what the inputs say.

## 1. FULL_CV_HISTORY

Input: every master CV (English and French), every older CV and every older cover letter, as extracted text (D-07).

Purpose: one history of the career, built from all CVs. Conflicts between sources are recorded, not resolved (D-40). The user reviews the result on the Profile page.

Output (JSON):

```json
{
  "items": [
    {
      "id": "H-001",
      "kind": "role | education | skill | achievement | other",
      "text": "string, in the wording of the source",
      "date": "YYYY | YYYY-MM | YYYY-MM-DD",
      "source": {"file_id": 0, "location": "string"},
      "conflicts": [{"with": "H-002", "note": "string, what differs"}]
    }
  ]
}
```

Code checks:
- Each item has `id`, `kind` from the list, non-empty `text`, a valid `date`, and a `source` whose `file_id` is one of the input files.
- Each `conflicts[].with` names an item in the same output, and the conflict is listed on both items.

## 2. Fact Sheet

Input: the `FULL_CV_HISTORY` output and the extracted text of the CVs (for locations).

Purpose: the non-positioned list of facts that later documents may use, once the user verifies each one (D-09). The Fact Sheet holds no lanes and no positioning.

Output (JSON):

```json
{
  "facts": [
    {
      "id": "F-001",
      "text": "string, one claim per fact",
      "date": "YYYY | YYYY-MM | YYYY-MM-DD",
      "source": {"file_id": 0, "location": "string"},
      "history_ids": ["H-001"]
    }
  ],
  "conflicts": [
    {"id": "C-01", "fact_ids": ["F-002", "F-009"], "note": "string"}
  ]
}
```

Code checks (the automated check from the Phase 2 Done-when list):
- Every fact has a `source.file_id` that is one of the input files, a non-empty `source.location`, and a valid `date`.
- Every `history_ids` entry exists in the `FULL_CV_HISTORY` output.
- Every `fact_ids` entry in `conflicts` exists, and the conflict is shown in the review screen.

Facts are stored with status `unverified`. Only verified facts are usable later (Phase 2 step 8).

## 3. Questionnaire analysis

Input: the questionnaire (extracted text), and the Fact Sheet (fact IDs and text, not the status).

Purpose: what the questionnaire says about the user's goals, preferences and limits, linked to the facts that support each point.

Output (JSON):

```json
{
  "themes": [
    {
      "id": "Q-001",
      "text": "string",
      "questionnaire_ref": "string, the question or section",
      "fact_ids": ["F-004"]
    }
  ],
  "gaps": [{"text": "string, a question the questionnaire leaves open"}]
}
```

Code checks:
- Every `fact_ids` entry exists in the Fact Sheet output.
- `questionnaire_ref` is non-empty.

## 4. Strategy overview (with lanes)

Input: the questionnaire analysis, and the Fact Sheet.

Purpose: a non-positioned overview of the user's strategy, and the lanes that group the job search (D-58, O-12). A lane is a positioning group, which the user edits on the Profile page.

Output (JSON):

```json
{
  "overview": "string, a short plain-language summary",
  "lanes": [
    {
      "id": "L-01",
      "name": "string",
      "description": "string",
      "fact_ids": ["F-001"],
      "questionnaire_ids": ["Q-001"]
    }
  ],
  "open_points": ["string"]
}
```

Code checks:
- Every `fact_ids` entry exists in the Fact Sheet. Every `questionnaire_ids` entry exists in the questionnaire analysis.
- Each lane has a non-empty `name` and at least one fact.
- Lane names are unique.

The overview and lanes are not job positioning. Positioning for a specific job is Phase 5.

## Storage

Each validated output is stored as a row in `profile_outputs` with its kind, version number, the job that produced it, the input file hashes, and the JSON. A failed check stores nothing and marks the Claude Job as failed, with the check's message.

## Own versions and what a run does (D-68, D-69)

The user can upload their own version of three outputs: the career history (`own_full_cv_history`), the questionnaire analysis (`own_questionnaire_analysis`) and the positioning strategy (`own_strategy`). These are used in place of a generated output. The Fact Sheet has no own version, because it is always checked against the sources.

Each run decides what to do for each output, in order, before the prompt is sent:

- **import**: an own file exists and either has not been converted yet, or an output it is built on was made again in this run. The prompt converts the file into the schema and keeps its wording. It is checked with the same rules as a generated answer. The file's hash is stored with the new version, so the same file is not converted twice.
- **generate**: no own file, and the output is missing, or an output it is built on was made again in this run.
- **skip**: anything else. The prompt is not sent, and it is recorded as "Skipped: already in place."

The outputs are built on each other in this order: the career history, then the Fact Sheet, the questionnaire analysis and the strategy. So a new career history makes a new Fact Sheet, and that makes a new questionnaire analysis and strategy, unless the user's own version of one of them is imported.

The run refuses to start when nothing is missing, and it says what to upload. A run needs a CV or an own career history if it has to make the career history or the Fact Sheet, and a questionnaire or an own questionnaire analysis if it has to make the questionnaire analysis.

Master CVs are one kind, `master_cv`, for English and French alike (D-67). The language is not stored.
