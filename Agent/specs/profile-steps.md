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

Input: every master CV, every older CV, every older cover letter and the user's own career history, as extracted text.

Purpose: one history of the career. Conflicts between sources are recorded, not resolved (D-40). The user reviews the result on the Profile page.

Output: an object with `items`. Each item has every field, using an empty string where the source does not state it:

- `id` (`H-001`), `kind` (role, education, skill, achievement or other), `text` (the wording of the source)
- `employer`, `title`
- `date`: the start date (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`)
- `end`: empty, `present`, or a date
- `source`: `{file_id, location}`
- `conflicts`: `[{with, note}]`

Code checks: ids are unique, `kind` is from the list, `text` is not empty, `date` is valid, `end` is empty, `present` or a date, the source file is one of the inputs, and each conflict is listed on both items.

## 2. Fact Sheet

Input: the `FULL_CV_HISTORY` output and the extracted text of the CVs and letters (for locations). An uploaded Fact Sheet is converted from its own file alone (see below).

Purpose: the list of facts that later documents may use, once the user verifies each one (D-09). Each fact is one claim, with a category, so the facts can be picked by kind.

Output: `facts`, each with `id` (`F-001`), `category` (role, responsibility, achievement, skill, tool, education, language, certification or other), `text`, `date`, `source` (`{file_id, location}`) and `history_ids`. Then `conflicts`: `[{id, fact_ids, note}]`, each naming at least two facts.

Code checks: ids are unique, `category` is from the list, every source file is an input, every `history_ids` entry exists, and every conflict names known facts.

Facts are stored unverified. Only verified facts are usable later (Phase 2 step 8).

## 3. Questionnaire analysis (the questionnaire report)

Input: the questionnaire (extracted text), and the Fact Sheet (fact ids and text).

Purpose: the report on what the questionnaire says. Its sections follow the report the user writes (D-73):

- `how_the_material_reads`: a text on how the answers read as a whole
- `career_narrative`: a text on the reasons behind the career choices
- `patterns`: recurring themes, each `{id (Q-001), title, text, questionnaire_ref, fact_ids}`
- `independent_work`: projects or products made outside a job, each `{title, text, fact_ids}`
- `cv_support`: points that support the patterns, reframed for the CV, each `{text, fact_ids}`
- `nuance`: what a first reading would miss, each `{text, questionnaire_ref}`
- `cv_implications`: a list of text
- `open_items`: a list of text

Code checks: the first two texts are not empty, pattern ids are unique, every pattern has a title, text and questionnaire reference, and every fact id exists.

## 4. Strategy (the positioning strategy)

Input: the questionnaire analysis, and the Fact Sheet.

Purpose: the positioning strategy. Its sections follow the strategy the user writes (D-73):

- `differentiator`: one paragraph
- `primary_lanes` and `secondary_lanes`: each lane is `{id (L-01), role, fit, why, fact_ids, questionnaire_ids}`. A fit is a rating from 0.5 to 5 in steps of 0.5.
- `avoid`: roles not to target as primary, each `{role, why}`
- `geography`, `comp_anchor` (empty if the material does not state it), `effort_allocation`
- `open_questions`: a list of text

Code checks: lane ids are unique, a lane has a role, a fit in steps of 0.5 between 0.5 and 5, a reason, and at least one known fact. Lane roles are unique, and every questionnaire id exists.

## Own versions and what a run does (D-68, D-69)

The user can upload their own version of each output: the career history (`own_full_cv_history`), the Fact Sheet (`own_fact_sheet`), the questionnaire analysis (`own_questionnaire_analysis`) and the positioning strategy (`own_strategy`). These are used in place of a generated output. An uploaded Fact Sheet is the Fact Sheet (D-72). It is converted from its own file alone: the CVs, the history and the other outputs are not inputs to it, and every fact's source is the uploaded file. Its facts are unverified until the user verifies them (D-09). It is not rebuilt when the history changes. The outputs built on it (the questionnaire analysis and the strategy) are rebuilt when it changes.

Each run decides what to do for each output, in order, before the prompt is sent:

- **import**: an own file exists and either has not been converted yet, or an output it is built on was made again in this run. The prompt converts the file into the schema and keeps its wording. It is checked with the same rules as a generated answer. The file's hash is stored with the new version, so the same file is not converted twice.
- **generate**: no own file, and the output is missing, or an output it is built on was made again in this run.
- **skip**: anything else. The prompt is not sent, and it is recorded as "Skipped: already in place."

The outputs are built on each other in this order: the career history, then the Fact Sheet, the questionnaire analysis and the strategy. So a new career history makes a new Fact Sheet, and that makes a new questionnaire analysis and strategy, unless the user's own version of one of them is imported.

The run refuses to start when nothing is missing, and it says what to upload. A run needs a CV or an own career history if it has to make the career history or the Fact Sheet, and a questionnaire or an own questionnaire analysis if it has to make the questionnaire analysis.

Master CVs are one kind, `master_cv`, for English and French alike (D-67). The language is not stored.
