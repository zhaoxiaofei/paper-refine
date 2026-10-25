#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OOXML style/formatting audit and safe normalizer for submission packages.

The review/revise pipeline reads DOCX text only (the corpus converters keep
`w:t`/`w:instrText`), so layout and character formatting are invisible to it:
a break-only paragraph produced a blank page after the title page, journal
italics live half in a Zotero bibliography field and half in the body, the same
GitHub URL is hyperlinked in one section and plain text in another, quotes are
mixed straight/curly, and figure legends were hand-formatted with per-figure
spacing. This tool makes those defects checkable and fixes the mechanical ones.

    python3 paper_docx_format.py scan  PACKAGE_DIR [--pdf FILE.pdf] [--json OUT.json]
    python3 paper_docx_format.py fix   FILE.docx --out FILE.fixed.docx [--json OUT.json]
    python3 paper_docx_format.py check-pdf FILE.pdf
    python3 paper_docx_format.py zotero-check   FILE.docx      # what a refresh would rewrite
    python3 paper_docx_format.py zotero-refresh FILE.docx      # repair it offline (in place)
    python3 paper_docx_format.py scan-figures   FIGURES/ [--from-docx MS.docx]
    python3 paper_docx_format.py repair-layout  FILE.docx --out FILE.fixed.docx
    python3 paper_docx_format.py xfa-export     FORM.pdf       # readable rendering of the answers
    # policy overrides:  --policy policy.json  (see POLICY_DEFAULTS)

Design rules, each one the result of an observed failure:

* reading uses ElementTree; WRITING never re-serializes the XML. Re-serializing
  `word/document.xml` drops namespace declarations that `mc:Ignorable` still
  references and Word then refuses the file ("the file appears to be
  corrupted"). Every edit is a byte-level splice of the original text, so all
  untouched bytes stay untouched.
* every edit is collected against one parse of the current XML and applied from
  the END of the document backwards, so earlier offsets stay valid.
* `fix` verifies itself: `w:t` text is unchanged unless the policy asks for
  punctuation normalization, the parts stay byte-identical, the package still
  parses (plus `docx validate` when that CLI is installed), and a re-scan shows
  every mechanical finding gone. The LIVE-FIELD FENCE additionally requires
  every Zotero field signature (kind, citationID, instruction, begin/separate/
  end balance) to come through the repair unchanged -- a fix that would add,
  remove or unbalance a field fails its own verification and the original file
  is kept -- unless the policy explicitly asks to unlink fields for a
  submission copy. Anything the fixer cannot repair is reported with
  `fix=style-field|policy|editorial|manual` instead of being "fixed" by
  guesswork.
* a finding inside a Zotero field (`w:fldChar begin ... end` + `ADDIN ZOTERO_*`
  instruction) is a field RESULT: Word cannot restyle it persistently because a
  refresh regenerates it. Such rows carry `protected=true`; the fix is the CSL
  style, or `unlink_zotero_fields: true` in the policy for a submission copy.

The module also carries the text-side ledgers the pipeline seeds for its
sessions (`number_ledger`, `key_term_rows`, `identifier_rows`,
`concept_family_rows`, `outline_rows`, `placeholder_ledger`). One of them is
two-sided on purpose: `claim_strength_rows` (check id J3) enumerates the `under`
(hedge) AND `over` (maximal claim) directions of every claim-bearing paragraph,
so a review cannot report the loud direction and leave the quiet one unexamined.

The scan also applies the VENUE's own display-item rules when the policy
declares them: `policy["tables"]` / `policy["figures"]` state where those items
belong and which side carries their caption (a venue profile's rules, rendered
into `format_policy.json` by the pipeline), and the scan reports
`FMT-TB1..FMT-TB3` for a table and `FMT-FG1..FMT-FG3` for a figure -- no
caption / caption on the wrong side / item before its area -- with
`policy[...].special` naming the items the venue itself treats differently
(a key-resources table inside the methods, a graphical abstract). A policy that
declares no rule for a kind reports nothing for it.

A display item's caption is ONE paragraph with ONE spacing and ONE style, and
the scan and the fixer read the same CAPTION BLOCK definition (a figure/table
label -- `Fig. 2 |`, `Figure S1.`, `Table 3 ...` -- plus the paragraphs that
continue it, inside the venue's own figures/tables area): `FMT-T2a`/`FMT-T2b`
check every paragraph of the block (a continuation left without direct spacing
renders one caption at two line spacings), `FMT-T2c` reports a caption split
across paragraphs and the fixer MERGES it into the label paragraph (runs
verbatim, the verifier told the join via `verified.caption_joins`; a block
carrying a drawing, a text box, a tracked change or a section break is left for
the revision arms), and `FMT-T2d` aligns a caption carrying a paragraph style
its sibling captions in the same area do not.

The text-level rules include the "lone division" pair: a narrative paragraph
built from ONE sentence is `FMT-T9k` and a section holding exactly ONE
subsection is `FMT-T10f` -- the same shape rule at two levels of the outline
(a container that divides at all divides into more than one part), both
finding-tier, with end-matter statements, acronym lists, captions and table
cells exempt by construction.

The same policy carries the VENUE TEMPLATE's own blank-line slots
(`policy["empty_paragraph_slots"]`, derived from the journal's official Word
template by the pipeline): an empty paragraph whose (own, previous, next) style
signature is one of them is template chrome (a spacer before the title, a
placeholder between two headings) and is never reported or deleted. Stray empty
paragraphs that are NOT prescribed -- a lone blank line between a section head
and its first subsection, a run longer than `max_empty_paragraph_run` -- are
`FMT-S8`/`FMT-S6` and the fixer deletes them. The text-hygiene family catches
what a text-only corpus cannot see: a space that renders at the start or end of
a visual line (the correspondence e-mail one space to the right, a dangling
trailing space) is `FMT-P4` and mechanical; doubled spaces, bracket spacing and
zero-width marks are `FMT-P3`; a doubled word is `FMT-G1`; a possible lowercase
sentence start is `FMT-G2`; a missing space after punctuation is `FMT-G3`. The
style-convention family (`FMT-T10a`..`FMT-T10e`) reports mixed direct fonts,
spacing/indent/alignment drift inside one style, and heading numbering/level
anomalies for the editing arms. Embedded images are checked against their own
pixels: a figure rescaled without its aspect ratio is `FMT-IM1` and the fixer
restores the ratio in `wp:extent`/`a:ext` (and the VML size). `policy
["cover_letter"]` carries the venue MANUSCRIPT template's front-matter style
ids and its header/footer part hashes plus the venue's cover-letter template
when one ships: a cover letter that uses those styles or carries those parts
while the venue ships no cover-letter template is `FMT-CL1` -- a letter
formatted as a manuscript, cleared only by the journal's own template/guideline
text quoted that REQUIRES the formatting.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_PARTS_DIRNAME = "paper_docx_format_parts"


def _parts_dir() -> _Path:
    """The ordered implementation parts that live beside this loader."""
    return _Path(__file__).resolve().with_name(_PARTS_DIRNAME)


def _load_parts() -> None:
    """Execute every part, in order, in THIS module's globals."""
    parts = _parts_dir()
    if not parts.is_dir():
        raise SystemExit(
            f"{_Path(__file__).name}: missing {_PARTS_DIRNAME}/ beside this loader. "
            "A pipeline root must freeze the parts directory together with the "
            "loader (setup/sync-code copy the whole bundle).")
    files = sorted(parts.glob("p[0-9][0-9]_*.py"))
    if not files:
        raise SystemExit(f"{_PARTS_DIRNAME}/ carries no implementation parts")
    for part in files:
        code = compile(part.read_text(encoding="utf-8"), str(part), "exec")
        exec(code, globals(), globals())


_load_parts()



if __name__ == "__main__":
    _sys.exit(main())
