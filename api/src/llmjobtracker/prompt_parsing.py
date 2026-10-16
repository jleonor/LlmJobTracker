"""Shared answer-parsing helpers for job_pipeline.py and job_revise_pipeline.py (D-225).

Both files parse the same `=== NAME ===\\n...\\n=== END NAME ===` block shape out of a model's
answer, and both need the same typography/whitespace tolerance before a verbatim-match check
(D-125/D-134's "exact substring" invariant) - kept here once instead of as two private,
byte-for-byte-identical copies, one per file.
"""

import re

_TYPOGRAPHIC_EQUIVALENTS = str.maketrans(
    {
        "‘": "'",
        "’": "'",  # curly apostrophe/single quotes
        "“": '"',
        "”": '"',  # curly double quotes
        "–": "-",
        "—": "-",  # en dash, em dash
    }
)


_ACCENT_SPACING_ARTIFACT = re.compile(r"\s*([éèêëîïôöûüœæçÉÈÊËÎÏÔÖÛÜŒÆÇ])\s*")


def block_text(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def block_pattern(name: str) -> re.Pattern[str]:
    """A `=== NAME ===\\n...\\n=== END NAME ===` block - tolerant of a missing closing tag, since
    a real answer sometimes drops it even when instructed to include one (observed live: a
    well-formed REQUIREMENT block with no `=== END REQUIREMENT ===`). Also ends at the next
    `=== ` marker or the end of the text, whichever comes first. No `\\n` is required right
    before `=== END NAME ===` (an empty block has none - the opening line's own `\\n` already
    sits right against it); a captured trailing newline either way is harmless, since every
    caller strips the result."""
    return re.compile(rf"=== {name} ===\n(.*?)(?:=== END {name} ===|(?=\n=== )|\Z)", re.DOTALL)


def normalize_for_match(text: str) -> str:
    """Whitespace AND common typographic variants are folded to a plain equivalent before a
    verbatim-match check (D-125/D-134's "exact substring" invariant) - a real listing (PDF, web
    page) commonly uses curly quotes or an en dash where the model's own answer, copying the same
    words, reasonably writes the plain ASCII form. Observed live: "You’ve" in a listing
    matched against the model's "You've" failed twice in a row on an otherwise faithful, correct
    answer - not a wording difference, a typography one the check wasn't tolerant of.

    The next step closes a space that directly follows a hyphen (after the collapse above, a
    line-wrapped PDF word like "scikit-\\nlearn" reads "scikit- learn", which still would not
    match a model's natural "scikit-learn"). extraction.py's own `_dehyphenate` fixes this at the
    source for a PDF extracted from now on; this is the same tolerance for a listing already
    stored before that fix existed, and for any other source with the same artifact.

    The final step drops any space immediately touching one of a fixed set of accented letters
    that is never itself a one-letter French word. Observed live: a French listing PDF's font
    encoding inserted a stray space on both sides of "é", "è", "î" and "œ" throughout the text
    (e.g. "d é butez" for "débutez", "exp é rience" for "expérience"), which broke the check
    against the model's own, correctly-spelled answer. "à" and "ù" are deliberately left out of
    the set - both are real standalone French words ("à", "où"), so removing a space next to them
    could wrongly merge two separate words. This only affects the match comparison, not the
    stored listing text or the model's own answer."""
    collapsed = re.sub(r"\s+", " ", text.translate(_TYPOGRAPHIC_EQUIVALENTS)).strip()
    tightened = re.sub(r"-\s+", "-", collapsed)
    return _ACCENT_SPACING_ARTIFACT.sub(r"\1", tightened)
