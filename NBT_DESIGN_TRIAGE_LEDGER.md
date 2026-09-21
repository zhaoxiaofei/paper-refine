# Design-issue triage ledger — 2026-09-19 (NBT pipeline)

**Task.** Ingest the bug/issue candidates in
`nbt_audit_data/2026-0919-1754-potential-design-issue-report/`, reproduce or
disprove each against this tree, patch confirmed defects only, prove each patch,
and stop.

**Sources (read-only).**

| id | file | content |
|---|---|---|
| S1 | `design_errors_audit.md` (and `design_errors_audit.pdf`) | 17 findings: C1–C6, M1–M6, m1–m5 |
| S2 | `nbt-pipeline-design-errors.md` | design classes D1–D6 (word length, grammar, formatting, overclaims, hierarchies, contract drift) |
| S3 | `NBT_Pipeline_Design_Error_Audit.pdf` | 28 findings: A1–A11, B1–B5, C1–C5, D1–D3, E1–E4 |

S1/S3 were written against commit `dd930a5`; this tree is `67d7306`
("Fix the 2026-09-19 bug-audit findings…"), so several claims were already
closed before this triage and are marked accordingly.

**Operator instruction honoured.** "Different parts of the manuscript can be
slightly over the respective length limits … the relaxed (non-strict)
enforcement of word limit is completely as intended." Every candidate that asks
to tighten the caps to the journal numbers, to make length a gate, or to add a
length term to the ranking key is therefore `NOT_A_BUG` here.

**Trees and commands.**

```bash
# repro/regression suite written for this triage (fails on the pre-patch tree)
python3 .nbt_test/test_design_audit_2026_0919.py
# the full harness, for regressions
for t in .nbt_test/test_*.py; do python3 "$t"; done
```

---

## Ledger

### C01 — Relaxed caps (172 / 3,750) replace the journal's 150 / 3,000, and length is never a gate
- Sources: S1 C3, S1 M2 (part), S2 D1.2/D1.3, S3 A1/A7
- Surface: `nbt_pipeline.py:1075-1098` (`ABSTRACT_RELAXATION`, `MAIN_TEXT_RELAXATION`, `NBT_ARTICLE_*_CAP`), `LENGTH_RULE`, `sweeps.md` M19
- Claim: a 171-word abstract / 3,700-word main text is reported "ok"; length never gates; another content type is measured with Article numbers.
- Source suggestion: enforce 150/3,000; add `--content-type`.
- Verdict: NOT_A_BUG — the operator states the relaxed enforcement is intended; `sweeps.md` M19 and the in-prompt `LENGTH_RULE` document the margins as fixed user margins, and `test_length_limits.py` asserts them. Adding a content-type knob is a feature, not a defect fix.
- Evidence: `python3 .nbt_test/test_length_limits.py` → "ALL LENGTH-LIMIT CHECKS PASSED" (caps 172/3,750 asserted as intended).
- Patch: none. vs source suggestion: DISAGREE (policy, user-owned). Attempts: 0/6. Tests: existing LT suite. Residual risk: an author relying on the pipeline number alone can exceed the journal number — documented in the M19 row (`base` + `relaxation` + `cap`).

### C02 — "Length is never a gate" / no length term in the champion ranking key
- Sources: S1 M2, S2 D1.2, S3 A1
- Surface: `sweeps.md` M19 ("Length is never a gate"), `decide` warnings, ranking key
- Claim: an over-cap champion can win and `decide` never fails on length.
- Verdict: NOT_A_BUG — documented, operator-intended policy (same instruction as C01); M19 findings still reach the author as CATEGORY-4 items.
- Evidence: `test_length_limits.py` asserts the advisory framing; `nbt_pipeline.py` `LENGTH_RULE` "LENGTH IS NEVER A GATE" asserted by LT.
- Patch: none. vs source suggestion: DISAGREE (policy). Residual risk: none beyond C01.

### C03 — Other content types / content-type detection
- Sources: S2 D1.4, S3 A7
- Surface: `length_limits()`, `setup` flags
- Claim: a Brief Communication is scored as an Article.
- Verdict: NOT_A_BUG — the pipeline documents the NBT Article as its default; the bundled script already accepts `--base-abstract/--base-main-text`; pipeline-side detection is a feature.
- Evidence: `count_words.py --base-abstract/--base-main-text` (existing); `length_limits()` docstring names the NBT Article base.
- Patch: none. vs source suggestion: DISAGREE (feature). Residual risk: non-Article packages need the script's base overrides.

### C04 — `count_words.py` cannot read LaTeX (the mandated M19 counting tool)
- Sources: S1 C4 (part), S2 D1.4, S3 A2/P5
- Surface: `nbt-skills/nbt-review/scripts/count_words.py`
- Claim: on a `.tex` manuscript the script answers `whole file … no abstract/main-text shape detected` with markup-inclusive words, while the pipeline reports abstract/main-text rows — two "authoritative" counters that disagree on the primary editable format.
- Source suggestion: delete the script or make it a thin wrapper over the pipeline's counter.
- Verdict: CONFIRMED.
- Evidence (pre-patch): `python3 count_words.py paper.tex --json` → `{"section": "whole file", "words": 133, "note": "no abstract/main-text shape detected"}` for a `.tex` with `\begin{abstract}`; pipeline on the same file → `abstract 0, main text 9`.
- Patch: `tex_lines()` pre-processes `.tex`/`.ltx` (abstract environment incl. same-line text, `\section`/`\subsection`/`\section*` with optional `[short]` arguments, `\caption`/`\captionof` groups emitted as their own lines so the line subtraction is exact, comment stripping, scaffolding removal) and `sections()` gained explicit `abstract_end` / `caption_lines`; `main()` dispatches on the suffix, and `--section whole` always answers with a whole-file row (a shaped `.tex` used to filter its own rows away). A thin wrapper was rejected because the skill ships standalone (importing `nbt_pipeline.py` is impossible there) — recorded as PATCH_DISAGREES_WITH_SOURCE.
- vs source suggestion: DISAGREE (wrapper) — resolved by (1) the repro passing, (2) no new import dependency in a standalone skill script, (3) locality to the script.
- Attempts: 1/6. Tests: `test_design_audit_2026_0919.py` D1/D2/D3 (pipeline == script on one-line and two-paragraph `.tex`), `test_bug_audit_2026_0919.py` C03/C04/C18 still pass.
- Residual risk: math/`\paragraph{}` tokens are still counted as non-space runs (see C10).

### C05 — Unanchored Methods/References/Funding regex truncates the main text
- Sources: S1 C4.2, S3 A3/P1
- Surface: `LENGTH_MAIN_END_RE`, `count_words.py` `MAIN_END`
- Claim: a body sentence starting "Funding for this work…" ends the main text.
- Verdict: FALSE_POSITIVE on this tree — both regexes now end with `\s*(?:[:.\u2014\u2013-]\s*|\s*$)`, so a trigger word followed by prose no longer matches.
- Evidence: `nbt_pipeline.py:4343-4353` and `count_words.py:42-48`; `test_bug_audit_2026_0919.py` C03 asserts pipeline/script agreement on prose-opening fixtures ("Acknowledging…", "Methods comparable to…").
- Patch: none (fixed in `67d7306`). vs source suggestion: N/A. Residual risk: a genuine heading written as "Funding." is still an end bound (intended).

### C06 — M19 subtracted captions from the whole document, not from the main-text span
- Sources: S1 C4.3 (part), S3 A4/P3
- Surface: `scan_lengths_in_sources` (caption words) + `_length_rows_for_lines`
- Claim: `caption_words` was summed over the whole document (all docx paragraphs, all `\caption` blocks, all md lines) and then subtracted from a main-text span that ends at Methods; a 20-word main text with a 25-word legend after Methods was reported as 0 words, and long out-of-span legends could launder an over-cap main text into compliance.
- Source suggestion: subtract only captions inside the span (as `count_words.py` already did).
- Verdict: CONFIRMED.
- Evidence (pre-patch): docx fixture `Abstract … Introduction <20 words> Methods … Figure 2 | <25-word legend>` → `main text 0 words` with the note "25 word(s) of figure captions subtracted".
- Patch: `_caption_units(..., with_spans=True)` / `_caption_units_from_lines(..., with_spans=True)` return line spans; `_length_rows_for_lines(..., caption_spans=…)` subtracts only the intersection of a caption span with `[start, end)`; `.tex` captions come from `_tex_length_scan`.
- vs source suggestion: MATCH. Attempts: 1/6.
- Tests: `test_design_audit_2026_0919.py` D4 (md, docx, `.tex`, in-span and out-of-span), `test_bug_audit_2026_0919.py` C18 (pipeline == script for wrapped/supplementary legends in span), `test_length_limits.py` LT4.
- Residual risk: a legend that begins inside the span and continues past the Methods heading is subtracted only for its in-span line portion (deliberate).

### C07 — A one-line LaTeX abstract was replaced by the bare heading and lost
- Sources: S3 A5/P2
- Surface: `_tex_length_lines` (old line 4322-4324)
- Claim: `\begin{abstract} TEXT \end{abstract}` on one line → abstract row `0 words`, text counted nowhere.
- Source suggestion: keep the text that follows `\begin{abstract}`.
- Verdict: CONFIRMED.
- Evidence (pre-patch): `_tex_length_lines` output `['article','document','Abstract','Introduction',…]` and rows `abstract 0 / main text 9` for a 9-word abstract.
- Patch: `_tex_length_scan()` emits "Abstract" plus the same-line remainder (with any trailing `\end{abstract}` removed).
- vs source suggestion: MATCH. Attempts: 1/6. Tests: D2 in the new suite (pipeline and script both 9 words).
- Residual risk: none found.

### C08 — A multi-paragraph LaTeX abstract was split at its first blank line
- Sources: S1 C4.1 (part), S3 A5/P2
- Surface: abstract-end scan in `_length_rows_for_lines` / `_abstract_end`
- Claim: paragraph 2 of a two-paragraph abstract leaks into the main text (50 of 100 abstract words counted).
- Verdict: CONFIRMED for `.tex` (the environment states the boundary, the code discarded it and guessed from a blank line); patched through the explicit `\end{abstract}` index.
- Evidence (pre-patch): two-paragraph `.tex` → `abstract 50 / main text 80`; post-patch `abstract 100 / main text 30` in both implementations.
- Patch: `_tex_length_scan` returns `abstract_end`; `_length_rows_for_lines(abstract_end=…)` uses it in preference to the blank-line scan.
- vs source suggestion: MATCH (end the abstract at the environment boundary). Attempts: 1/6. Tests: D3 in the new suite.
- Residual risk: for `.md`/`.docx`/`.txt` the documented blank-line rule is unchanged (see C09b) — those formats carry no explicit boundary.

### C09 — LaTeX scaffolding counted as prose; optional-argument headings not recognised
- Sources: S3 A10/P7, P9
- Surface: `_tex_length_lines` / `_strip_latex`
- Claim: `\begin{document}`, `\end{document}`, `\documentclass{article}`, `\includegraphics{fig1.pdf}` contribute literal words ("document", "article", "fig1.pdf"); `\section[Supplementary Methods]{Methods}` is not recognised, so the bracket tokens are counted and the Methods exclusion depends on luck.
- Verdict: CONFIRMED.
- Evidence (pre-patch): one-line-abstract fixture's main text was 8 (7 prose + "document" from `\end{document}`); `\section[Short]{Methods}` produced the heading line "[Short] Methods", which `LENGTH_MAIN_END_RE` cannot match.
- Patch: `TEX_ENV_TOKEN_RE` removes `\begin{…}`/`\end{…}` tokens (on their own line or sharing one with prose), `TEX_SCAFFOLD_RE` removes setup/graphics command arguments, and the section regex now skips the optional `[short]` argument (in both the pipeline and `count_words.py`).
- vs source suggestion: MATCH. Attempts: 1/6. Tests: D2 (exact 7-word main text), D1/D3 (script agreement), plus the new suite's `\section` fixtures.
- Residual risk: `$…$` math and `\paragraph{…}` run-in headings (C10) are not handled.

### C10 — Math and `\paragraph{}` tokens counted as words
- Sources: S3 A10/P8
- Surface: `_strip_latex`, section regex
- Claim: `$P(\mathrm{win}) = \frac{a}{b}$` leaves "win", "a", "b" as words; `\paragraph{…}` headings are not handled.
- Verdict: NOT_A_BUG — the pipeline's word rule is "maximal runs of non-space characters"; how many words an equation should count as is a policy choice, and this direction only *inflates* the count (conservative for an upper limit). A patch would have to invent that policy, and the agents' M19 sweep is the authoritative count.
- Evidence: `count_words()` docstring and sweeps.md M19 counting rule; probe P8 reproduced the token behaviour, not a wrong verdict.
- Patch: none. vs source suggestion: DISAGREE (policy). Residual risk: a math-heavy section can be over-counted (never under-counted).

### C11 — M18 coverage: the review prompt allowed what its own postcheck rejects
- Sources: S1 C6, S2 D6.3/D6.4, S3 C2
- Surface: `REVIEW_DIRECTIVES` bullet, header docstring, `M18_REVIEW_SWEEP_ON/_REPORT`, `check_review_contract`, `test_length_limits.py` docstring
- Claim: the prompt said "when it is not active, M18 need not appear" while another block in the same prompt says "Give M18 its own coverage row" and `check_review_contract` hard-appends `M18`; the two M18 blocks also claimed the check was "not in references/sweeps.md" although sweeps.md has defined M18/M19 since skills 0.6.
- Source suggestion: delete the permission clause; fix the docstring; add a contract test.
- Verdict: CONFIRMED.
- Evidence: pre-patch rendered prompt contained both sentences; `check_review_contract` fails a review without M18 (`coverage table is missing check id(s) ['M18']`) — asserted in the new suite.
- Patch: the prompt bullet now says M18 "ALWAYS appears … only its proxy cap is optional"; both M18 blocks and the M19 block drop the stale "not in references/sweeps.md" claim; the header docstring lists M18+M19 as always active; `test_length_limits.py`'s docstring matches.
- vs source suggestion: MATCH. Attempts: 1/6. Tests: D6 (no-cap prompt text + runtime contract failure).
- Residual risk: none found.

### C12 — The standalone fallback prompt ships the pre-0.7 rule set
- Sources: S1 C1, S2 D6.2, S3 E3
- Surface: `nbt-skills/prompts/identify_issues.prompt.md` (body)
- Claim: hard rule 4 lists only M1–M17 as mandatory; Phase 2 makes M18 conditional; the acceptance check counts "all 21 check IDs … plus M18+ once added"; "Grow the skill" numbers new sweeps from M18; the bundled-script table omits `--section cover-letter` — all contradicting SKILL.md v0.7, the prompt's own appendix, and the pipeline postcheck.
- Verdict: CONFIRMED.
- Evidence (pre-patch): grep of the body vs `SKILL.md` hard rule 4 / Phase 2 / acceptance check 1 / "as M20, M21…"; appendix (sweeps.md copy) already said M20.
- Patch: body synced to SKILL.md (mission paragraph with M18, hard rule 4, script table row, Phase 2, coverage table, M20 numbering, acceptance check 1); `SKILL.md`'s own stale coverage line fixed; the appendix's FINDING FORMAT line synced with sweeps.md (see C13).
- vs source suggestion: MATCH. Attempts: 1/6. Tests: D7 (prompt/SKILL/sweeps text) and `test_acronym_longform.py` E3 ("prompt appendices stay verbatim in sync") which caught the appendix copy.
- Residual risk: the fallback prompt is documentation; no runtime check executes it.

### C13 — `sweeps.md` FINDING FORMAT did not admit M18/M19 findings
- Sources: S2 D6.1
- Surface: `nbt-skills/nbt-review/references/sweeps.md` (FINDING FORMAT)
- Claim: the format line says `check: <M1–M17|J1–J4>`, so an M18/M19 finding is schema-invalid against the file that defines those sweeps.
- Verdict: CONFIRMED.
- Evidence: `sweeps.md:46` (pre-patch) vs the M18/M19 finding rules in the same file.
- Patch: `<M1–M19|J1–J4>` in sweeps.md and in the prompt appendix copy (kept verbatim by `test_acronym_longform.py` E3).
- vs source suggestion: MATCH. Attempts: 1/6. Tests: D8 (sweeps text), E3 (appendix sync).
- Residual risk: none.

### C14 — Cover-letter `over_limit` disagreed between the two counters and produced a false cap warning
- Sources: S1 m1, S3 A11/G1
- Surface: `_cover_letter_row` vs `count_words.py` cover-letter row; `decide` length warning
- Claim: the pipeline set `over_limit = words > 500` for a range its own row calls "the user's preference, not an NBT limit"; the row therefore entered the scan's `over_limit` list and `decide` printed "…exceed this pipeline's relaxed caps … (cap None)"; the bundled script said `over_limit = False` for the same letter.
- Verdict: CONFIRMED.
- Evidence (pre-patch): 600-word letter → pipeline `over_limit True`, script `over_limit False`; `decide` warning text at `nbt_pipeline.py:11648` formats `cap None`.
- Patch: `over_limit` is now always `False` for a cover letter, with a new `over_preference` flag; `within_preference`/`under_preference`/`length_note`/`decision.json` reporting is unchanged.
- vs source suggestion: MATCH (script semantics win; `over_preference` keeps the signal). Attempts: 1/6. Tests: D5; `test_length_limits.py` LT4 cover-letter checks unaffected.
- Residual risk: consumers that looked for a cover letter in `over_limit` find it in `over_preference`; no in-tree consumer did.

### C15 — `.markdown`/`.rst` manuscripts were length-scanned but never enumerated for M18
- Sources: S3 C4 (extension drift)
- Surface: `CAPTION_TEXT_EXTS` vs `LENGTH_TEXT_EXTS`
- Claim: `.markdown`/`.rst` are editable length-scanned sources, but their legends are not enumerated (and were silently absent from the M18 artifact) — two extension sets in one pipeline.
- Verdict: CONFIRMED (enumeration parity; the M19 subtraction itself already used the line-based units for those extensions).
- Evidence: pre-patch `scan_captions_in_sources` returned zero captions for a `.rst`/`.markdown` fixture whose legend was inside the main-text span.
- Patch: `CAPTION_TEXT_EXTS = (".md", ".txt", ".markdown", ".rst")` with a comment tying it to the length scan.
- vs source suggestion: MATCH. Attempts: 1/6. Tests: D8 (both extensions enumerated; the legend is not counted as main text).
- Residual risk: `PLACEHOLDER_SOURCE_EXTS` inherits the two extensions (diagnostic only).

### C16 — Separator-less caption dialect ("Figure 1 Title") invisible to the pipeline's scan
- Sources: S1 C4 (part), S3 C4 (part)
- Surface: `CAPTION_START_RE` / `CAPTION_SUSPECT_RE` vs `count_words.py` `CAPTION`
- Claim: the script treats "Figure 1 Growth of the culture…" as a caption; the pipeline requires `| : — – - .` and does not even list the form as suspected.
- Verdict: NOT_A_BUG — the strict separator is what keeps ordinary prose ("Figure 1 shows that…") out of the legend table; broadening it would import the script's false positives into the advisory M18 scan and the M19 subtraction. Two tools with different confidence is the documented design (the pipeline also has a "suspected" list for unrecognised legends).
- Evidence: probe of both regexes; the pipeline's `suspected` warning path.
- Patch: none. vs source suggestion: DISAGREE (false-positive risk). Residual risk: a separator-less legend can be missed by the code-side scan; the agents' M18 sweep remains authoritative.

### C17 — docx legend continuation paragraphs are not merged
- Sources: S1 A9 (P4)
- Surface: `_caption_units`
- Claim: a legend split over two Word paragraphs is counted as its first paragraph only (13 of 26 words), under-reporting M18 and under-subtracting in M19.
- Verdict: CANNOT_REPRODUCE — the word counts reproduce, but the correct merge rule for paragraph text is not decidable: Word paragraphs carry no indentation/shape signal, and the text path's rule (merge only while the caption does not end in sentence-final punctuation) would still refuse to merge a paragraph that ends with a period, while merging every following paragraph would swallow body prose. Fixing this needs a shape-aware extractor, i.e. a design change, not a defect repair.
- Evidence: `_docx_paragraphs()` returns text only; `_caption_units` has no continuation branch; `_caption_units_from_lines` uses indentation + sentence-final punctuation, neither available for docx paragraphs.
- Patch: none (guarded by the "less than highly confident → do not patch" rule). vs source suggestion: DISAGREE (unsafe). Residual risk: an advisory M18 count and an M19 subtraction can be off for a genuinely split Word legend; nothing gates on M18.

### C18 — `--section cover-letter` answered with zero rows
- Sources: S1 C5 (A1 probe)
- Surface: `count_words.py` `main()`
- Claim: an explicit cover-letter request on a file whose first line is "Re: NBT-2026-0912" printed no row and exited 0.
- Verdict: FALSE_POSITIVE on this tree — the explicit request now always emits a row (`cover letter` when detected, otherwise `not a cover letter … counted the whole file`) and a stderr note; fixed in `67d7306`.
- Evidence: run of `--section cover-letter` on an address-block letter → `{"section": "not a cover letter", "words": 408}`.
- Patch: none. vs source suggestion: N/A. Residual risk: none for the silent-skip claim.

### C19 — "Only the caption's first line is subtracted" (pipeline .md path)
- Sources: S1 C4.3
- Surface: `_caption_units_from_lines`, `count_words.py caption_ranges`
- Claim: 150 continuation words stayed in the main text.
- Verdict: FALSE_POSITIVE on this tree — both implementations merge wrapped captions and subtract the merged unit inside the span; `test_bug_audit_2026_0919.py` C18 asserts they agree, and the new D4 asserts the in-span/out-of-span rule.
- Patch: none (superseded by C06's span fix). Residual risk: docx continuation (C17).

### C20 — Grammar / formatting / overclaiming have no judge tier, score 0, or are unfixable
- Sources: S1 M1, S1 M2, S1 M3, S2 D2–D4, S3 B1–B5, S3 C1, S3 D1–D3
- Surface: `BASIS_TIERS`, JUDGE_DIRECTIVES scale, `REWRITE_DIRECTIVES` hard rules, `edit_rules.md` E6, integration order (e)
- Claim: a version that fixes fifty grammatical errors scores 0 against one that fixes none; formatting is capped at ±1 and can never be decisive; overclaims are re-reported every round and can never be fixed or scored.
- Source suggestion: add a `writing`/`compliance` tier, a grammar sweep with an artifact, a claim ledger and narrower E6.
- Verdict: NOT_A_BUG — these are documented design decisions (the judge scale explicitly zeroes cosmetic-only differences; the reports themselves classify the formatting tier as "a policy decision, not a bug fix"; E6 and the rewrite claim-freeze are integrity rules). Changing the rubric, the score arithmetic, the stage authorizations and the review taxonomy is a feature redesign, explicitly outside "patch confirmed defects only".
- Evidence: `nbt_pipeline.py:1035` (`BASIS_TIERS`), `:2840-2866` (scale, formatting cap), `edit_rules.md:124-131` (E6), `REWRITE_DIRECTIVES` claim-freeze — all present and self-consistent as a policy.
- Patch: none. vs source suggestion: DISAGREE (design change, operator-owned). Residual risk: selection cannot prefer a grammatically cleaner version — documented in the reports.

### C21 — Judge grounding verified only as "one artifact"
- Sources: S1 M5, S2 D6.5
- Surface: `postcheck_judge`
- Claim: `judge_review/` non-empty passes; a judge that writes one M1 inventory and skips J1–J4 passes.
- Verdict: NOT_A_BUG — the bar is documented (`judge_review/ (inventory + sweep artifacts + the visual record) is required`) and enforced as "exists and is non-empty"; requiring a per-check coverage disposition is a new contract, not a defect repair (the same conclusion the repo's own audit recorded when it raised the bar from zero to one).
- Evidence: `nbt_pipeline.py:8655-8663`.
- Patch: none. vs source suggestion: DISAGREE (feature). Residual risk: an ungrounded judge sheet is still possible; blinding and the graded-basis contract limit the damage.

### C22 — `critical_remaining` (self-reported) is a ranking key
- Sources: S1 M6 (adjacent), S3 E1 (U3)
- Surface: `_self_report_counts` / ranking key `(-median, -mean, iqr, critical_remaining, digest, id)`
- Claim: an arm can win an exact tie by under-reporting one number; the cross-check is a warning only.
- Verdict: NOT_A_BUG — documented behaviour (`critical_remaining` breaks ties *after* the score statistics; the count is cross-checked against the frozen review's critical count and warned about), and the ledger is now also cross-checked row-by-row against the frozen findings (C23). Replacing the key is a design change.
- Evidence: `nbt_pipeline.py:9013-9060`, `:8252-8256` (warning path).
- Patch: none. vs source suggestion: DISAGREE (design). Residual risk: self-reported data still breaks exact ties by design.

### C23 — The revision ledger is never cross-checked against the frozen findings
- Sources: S1 M6, S3 E1 (U3)
- Surface: `postcheck_revise`
- Claim: a ledger that omits a finding the review lists is accepted.
- Verdict: FALSE_POSITIVE on this tree — `postcheck_revise` reads `revised/revision_report.json`, requires a typed row list, compares the row ids with `frozen_finding_ids()` and hard-fails naming the missing ids; fixed in `67d7306`.
- Evidence: runtime probe with a 1-row ledger against 2 frozen ids → `ok False`, error "does not name 1 of the frozen review's 2 finding id(s): F-002". Empty-but-typed ledgers are accepted only when the frozen review has zero findings.
- Patch: none. Residual risk: the check keys on the first id-like field of each row (documented row contract).

### C24 — The repealed standing length exemption is still shipped in every prompt
- Sources: S1 M4, S2 D1.1, S3 E2
- Surface: `ATTACHED_PHASE1` "Standing exemption (my preference…)" and the assembled prompts
- Claim: every review/revise/rewrite/integrate prompt carries both `LENGTH_RULE` ("this REPLACES the blanket exemption") and the master excerpt's "never flag abstract/main-text word limits".
- Verdict: CANNOT_REPRODUCE — the text conflict exists, but the same prompt resolves it explicitly (orchestration directives "override anything below where they conflict", and `LENGTH_RULE` names the excerpt's wording as superseded). Whether an agent still follows the stale sentence is a prompt-compliance question that cannot be executed here, and rewriting the user's governing excerpt is a prompt-engineering change without a demonstrable defect.
- Evidence: `nbt_pipeline.py:1140-1151` (`LENGTH_RULE`) + the appended excerpt; no runtime harness can measure instruction weighting.
- Patch: none. vs source suggestion: DISAGREE (unproven impact). Residual risk: an agent that weights recency over the precedence header may skip M19 in a prompt-only deployment.

### C25 — Supplementary files skipped by the name substring "supp"
- Sources: S1 m2, S3 A6 (part)
- Surface: `scan_lengths_in_sources`
- Claim: a real supplementary file whose name lacks "supp" (e.g. `SI-note.tex`) is counted against the Article main-text cap, and a main manuscript with "supp" in its name is skipped.
- Verdict: NOT_A_BUG — a documented, name-based role heuristic for an advisory scan that also reports every skipped file; switching to the converter's inventory roles is a refactor, not a defect repair.
- Evidence: probe: `SI-note.md` with an Introduction heading is counted (over-cap row, not a gate); the docstring states the rule.
- Patch: none. vs source suggestion: DISAGREE (refactor). Residual risk: mis-classified file roles in the advisory scan; the agents' M19 sweep is authoritative.

### C26 — Cover-letter detection fails for a letter opening with a recipient address block
- Sources: S3 A6 (P6)
- Surface: `_is_cover_letter_lines`, `count_words.py is_cover_letter`
- Claim: a letter opening "Dr. Jane Editor / Nature Biotechnology / …" is not recognised, so its length is never measured against the 300-500 preference.
- Verdict: NOT_A_BUG — the explicit request reports the file (row + note, see C18) and the automatic scan lists it under `skipped` rather than silently dropping it; extending detection to address blocks requires a new heuristic whose false-positive cost is unknown.
- Evidence: probe: `--section cover-letter` → `{"section": "not a cover letter", "words": 408, "note": "… counted the whole file"}`; auto scan → `skipped`.
- Patch: none. Residual risk: the preference is not applied to that shape unless the author requests it explicitly.

### C27 — `needs_manual` is suppressed when any other document produced rows
- Sources: S3 A6 (part)
- Surface: `scan_lengths_in_sources` (`"needs_manual": rendered if not rows else []`)
- Claim: a PDF-only document alongside an editable manuscript is not flagged as needing manual counting.
- Verdict: NOT_A_BUG — `needs_manual` is documented as the no-editable-copy case; the rendering is still recorded in `rendered`/`skipped` inside the scan state, and M18/M19 are advisory proxies whose findings remain the agents' job.
- Evidence: docstring at `nbt_pipeline.py:4308-4312`; the scan record carries `rendered`/`skipped`.
- Patch: none. Residual risk: the operator must read the scan record rather than one flag.

### C28 — M18 ships with no proxy cap (`DEFAULT_CAPTION_LIMIT = 0`)
- Sources: S1 C2, S2 D1.3, S3 A8
- Surface: `DEFAULT_CAPTION_LIMIT`, M18 prompt blocks, `caption_gate`
- Claim: by default no legend can be reported as over-length.
- Verdict: NOT_A_BUG — documented opt-in (`--caption-limit N`, default 0 = no cap); M18 still enumerates every legend and records the count with the disposition "the journal's per-type limit is not published"; inventing a default cap is the policy decision the source report itself lists under "policy decisions for the operator".
- Evidence: `sweeps.md` M18, `CAPTION_RULE_REPORT`, CLI help; `test_length_limits`/`test_pipeline` assert the no-cap state.
- Patch: none. vs source suggestion: DISAGREE (policy). Residual risk: the legend-length rule has no operative threshold unless a cap is configured.

### C29 — No caps for display items (≤ 6), reference count (~50), or abstract citations
- Sources: S2 D1.3, S3 A7 (part)
- Surface: M2/M3/M5 sweeps
- Claim: only word counts are mechanically capped; display-item and reference counts are not.
- Verdict: NOT_A_BUG — new finding rules/sweeps are feature work; the operator's instruction covers the length policy and scope forbids adding checks that no confirmed defect requires.
- Patch: none. Residual risk: those guideline limits remain agent-judged (J1/J2).

### C30 — Duplicated length constants with no sync guard
- Sources: S1 m3
- Surface: `nbt_pipeline.py` caps/regexes vs `count_words.py`
- Claim: the two implementations are maintained by hand and had already diverged once (C14).
- Verdict: NOT_A_BUG — after C14 the semantics agree; a shared module/JSON is a refactor the scope forbids, and the new D1–D5 tests pin the agreement on the shared fixtures.
- Patch: none. Residual risk: future drift is caught only by the tests that compare the two implementations.

### C31 — `adress_issues` filename typo
- Sources: S1 m4
- Surface: `nbt-skills/prompts/adress_issues.prompt.md`, skill trigger list
- Claim: the public trigger name misspells "address".
- Verdict: NOT_A_BUG — naming/hygiene, explicitly out of scope ("do not fix style, naming"); renaming a public trigger would break the documented interface.
- Patch: none. Residual risk: cosmetic.

### C32 — The rewrite stage carries no M18 output mandate
- Sources: S1 m5
- Surface: `REWRITE_DIRECTIVES`
- Claim: review/revise/judge/integrate name an M18 artifact, the rewrite does not.
- Verdict: NOT_A_BUG — the generic caption rule reaches every stage and the rewrite mandate is to leave captions alone; no observable failure follows from the missing stage-specific sentence.
- Patch: none. Residual risk: cosmetic prompt asymmetry.

### C33 — The redline writer omits table-cell edits (warning only)
- Sources: S3 C3 (repo F18)
- Surface: `nbt_redlines_adapter.py` / `non_paragraph_changed`
- Claim: a table-cell edit produces no tracked change; the fix is a warning.
- Verdict: NOT_A_BUG — documented limitation with an explicit warning (recorded in the repo's own findings); emitting real `w:ins`/`w:del` inside table cells is a feature.
- Evidence: `test_fixes.py:230-231` asserts the warning text.
- Patch: none. Residual risk: the human reviewing the redline must check tables manually.

### C34 — Judge blinding is prompt-only, with exact-name strip lists
- Sources: S3 C5
- Surface: `CORPORA_STRIP_BOOKKEEPING`, blinded views
- Claim: a self-report saved under another name travels into judge views; prose provenance is unscrubbed.
- Verdict: NOT_A_BUG — the limit is documented in-tree ("The blinding still relies on the agent obeying its prompt"), and the mitigations (salted permutations, neutralized metadata, unified mtimes) are deliberate.
- Patch: none. Residual risk: documented.

### C35 — `test_length_limits.py` has no LaTeX fixture
- Sources: S3 E4
- Surface: `.nbt_test/test_length_limits.py`
- Claim: the length path's LaTeX code is untested, which is where the audited defects live.
- Verdict: NOT_A_BUG as a defect claim (a test-coverage gap, not a defect) — and closed here: `test_design_audit_2026_0919.py` adds `.tex` fixtures for the one-line abstract, the multi-paragraph abstract, `\section`/optional-argument headings, in-span/out-of-span `\caption` legends, and `count_words.py` parity.
- Patch: new suite (see the diff). Residual risk: math/`\paragraph` handling stays untested by design (C10).

### C36 — Two source hierarchies (skill order vs master-prompt order)
- Sources: S2 D5
- Surface: `REVISE_DIRECTIVES` + `sweeps.md` conflict-priority note
- Claim: one paragraph cites the skill's order for update order and the master hierarchy for value conflicts, so a number conflict can be "resolved" two ways.
- Verdict: NOT_A_BUG — the paragraph states exactly which order applies to what (which occurrences to update first vs which source decides a value); it reads as a deliberate two-rule design, and the report's own evidence is the coexistence of both orders, not a wrong outcome.
- Patch: none. Residual risk: an agent can misapply the wrong order — a prompt-clarity concern, not a demonstrated defect.

### C37 — OOXML layout is dropped and formatting is the lowest judge tier
- Sources: S1 M2, S2 D3, S3 C1
- Claim: justification/spacing/font evidence never reaches the review or the score.
- Verdict: NOT_A_BUG — the conversion scope, the visual-inspection record (PDF render + look) and the explicit priority order are documented design; a layout sweep or a compliance tier is a feature the operator must choose.
- Patch: none. Residual risk: a layout-perfect package cannot outrank a content-perfect one — documented.

---

## Second-pass review before commit

Every changed hunk was re-read and re-run. Two defects were found in the first
version of the LaTeX patch and fixed (both are now pinned by section D9 of the
suite, `test_tex_caption_boundaries`):

1. **The caption span was the whole source line.** `\caption{A legend.} This
   sentence is prose.` was emitted as one line, so the trailing prose was
   subtracted as if it were legend text (mixed fixture: 20 words instead of the
   correct 24 — i.e. 4 prose words silently excluded from the main text, the
   dangerous direction for a cap). Fixed by emitting the caption group as its
   own line and the surrounding text as separate lines, in both the pipeline and
   `count_words.py`; a multi-line caption group is collected by brace balancing
   and a `\begin{…}`/`\end{…}` token sharing a line no longer leaks a word.
2. **`tex_lines()` returned caption spans where `sections()` expected line
   indices**, so `count_words.py` crashed with `TypeError: '<=' not supported
   between instances of 'int' and 'tuple'` on any `.tex` that carried a
   `\caption`. The first version of the suite never exercised that path (its
   `.tex` fixtures had no captions). Fixed by returning indices, and D9 now runs
  every caption fixture through the script as well as the pipeline.
3. **`--section whole` on a `.tex` printed an empty result.** Before the patch
   a `.tex` was never "manuscript-shaped", so the mode returned a whole-file
   row; once the script understands LaTeX, the shaped rows were filtered away
   by the `--section whole` filter. `main()` now always emits the requested
   whole-file row (for every format), and D1 asserts it for `.tex` and `.md`
   alike — the same "never answer with silence" rule the cover-letter mode
   already follows.

After the fixes: 40/40 checks in the new suite, 20/20 suites green.

## Follow-up (2026-09-20): the ledger-shape gate false-failed complete ledgers

Found while diagnosing a live run (`cnb-11to12-091918-1ff6d70`) whose
`r2_a2_revise` failed all three attempts with "revised/revision_report.json does
not name 28 of the frozen review's 28 finding id(s)". The frozen review was
fine (28 well-formed findings — the failing stage's input was never the
problem); the ledger was complete too, but the cross-check read rows only from
the key list `findings | revisions | rows | ledger | items | entries` and ids
only from `id | finding | finding_id | check_id`. Real agents name the row list
the way the revise skill does — "the coverage table" — so `coverage`,
`coverage_table`, a mapping keyed by finding id and a bare id list were all
invisible to the check, and a complete ledger was reported as naming none of the
ids. Round 1 failed the same way on its first attempt (`coverage`, 42/42) and
passed the second only because that attempt happened to name the key `ledger`.

Fix: `ledger_named_ids()` asks the only question the gate is about — does the
payload name every frozen finding id as structured data (a row's id field, a
mapping key, or an id list, at any nesting level)? Prose that merely mentions an
id still does not count, so a report that names nothing still fails. The revise
prompt now states the contract explicitly. Pinned by
`.nbt_test/test_llm_stochastic_failures.py` A8b (all four shapes accepted),
A8c (prose-only still fails) and A8d (a partially named ledger still fails and
names the missing id).

Verified on the real artifacts: the round-2 payload shape the agent wrote
(`finding_ids` + `coverage_table` with 28 real ids) goes from 0/28 named under
the old rule to 28/28 under the fix, and the real round-1 ledger that passed
still names 42/42.

## Follow-up (2026-09-20): OOXML style/formatting audit, scanner and fixer

The published `final_clean_version/` was inspected as OOXML (zipfile +
ElementTree, read-only) and as rendered PDFs (LibreOffice 7.3 and Microsoft Word
through `docx2pdf.sh`). Beyond the four issues the operator reported, the audit
found:

| # | Finding (evidence) | Class |
|---|---|---|
| 1 | main text page 2 is blank: paragraph 9 is an empty paragraph whose only content is `w:br w:type="page"` (rendered PNG: header + page number only; 33 pages) | structural |
| 2 | the running head prints on the title page (`w:headerReference` with no `w:titlePg`) | structural |
| 3 | the "final clean" file carries 1 Word tracked deletion (paragraph mark, author/date attributes) and 450 `w:proofErr` markers | structure/hygiene |
| 4 | figure-legend spacing drifts: the Fig. 1 legend has no `before`/`after`, Fig. 2-5 use 200/200 (all correctly single-spaced at `line=240`) | typography |
| 5 | 25 headings carry no `keepNext`; heading runs are directly sized 28/22 half-points while the Heading1/2 styles define 32/28 (style drift) | typography |
| 6 | the title-page correspondence block is italic, emails included (`color=333333`, no underline) | typography |
| 7 | 29 references italicise `et al.`; 2 references have no italic journal title (one is a legitimate arXiv preprint). All of it lives inside one `ADDIN ZOTERO_BIBL` field result (+122 `ZOTERO_ITEM` citation fields) -- Word cannot restyle it persistently, which is why the operator had to cut/paste with "keep text only" | style/field |
| 8 | URLs/emails use three treatments: 5 `w:hyperlink` runs (Hyperlink style = blue+underline), 17 plain URL runs with no styling, 2 dark-italic email runs; the same GitHub URL appears both hyperlinked and plain | typography |
| 9 | mixed quotation marks (20 straight vs 2 curly in the main text; 2 curly + 2 straight in the cover letter) | punctuation |
| 10 | em-dash density 19 per 9,851 words (1.9/1000) in the main text plus 4 in the 698-word cover letter (5.7/1000), cap set to 2.0/1000 by policy | punctuation |

Implemented:

* **`nbt_docx_format.py`** -- a stdlib companion tool with three commands:
  `scan` (rule rows `FMT-S*` structural, `FMT-T*` typography, `FMT-P*`
  punctuation, each with severity/fix-kind/field-protection), `fix` (writes a
  repaired copy) and `check-pdf` (blank-page detection from a rendered PDF).
  Every write is a byte-level splice of `word/document.xml` applied
  back-to-front, because re-serializing with ElementTree drops namespace
  declarations that `mc:Ignorable` references and Word then refuses the file
  ("the file appears to be corrupted" -- reproduced). `fix` self-verifies:
  other parts byte-identical, document text unchanged (quote-normalisation
  excepted), `docx validate` clean when that CLI is installed, mechanical
  findings re-scanned to zero. Findings inside Zotero fields are reported
  `protected` (fix the CSL style or `unlink_zotero_fields: true` for a
  submission copy) instead of being silently rewritten.
* **Pipeline wiring** -- `setup` copies the companion module next to the
  pipeline script and records `state["original_format"]` + a
  `[setup] OOXML formatting scan:` line; `decide` scans the pinned winner and
  puts `format_note`/`format`/`format_problems`/`format_gate` into
  `decision.json` and the decision report; `decide --format-gate` promotes
  high-severity findings (break-only paragraph, blank page, tracked changes,
  unreadable package) to decision problems; `setup --format-policy FILE` stores
  JSON overrides (journal italics, quote style, legend spacing, title-page
  header, URL style, em-dash cap, unlink fields, blank-page tolerance).
* **Tests** -- `.nbt_test/test_docx_format.py`: a fixture DOCX carrying every
  defect above, asserting detection, the fixer's invariants (parts, text,
  namespaces, schema, idempotency), the extended policy (unlink fields, align
  heading sizes, curly quotes), the CLI contract and - where soffice/pdftotext
  exist - a real render showing the blank page before and none after.

Verification on the real package (copies in `/tmp`, originals untouched):

```
scan  final_clean_version/                     100 findings (3 high, 91 medium, 6 low)
fix   cnb-12-2-mainText-...docx    -> 32 mechanical findings -> 0; text identical; parts intact;
                                       docx validate: valid; 33 pages (page 2 blank) -> 32 pages, none blank
fix   cnb-12-1-coverLetter-...docx -> 1 -> 0; text identical; valid
Word  (docx2pdf.sh) on the fixed main text: 32 pages, no blank page, title page without the
      running head, Introduction on page 2
```

## Follow-up (2026-09-20, part 2): formatting artifacts in every stage, `--only`, README

The first formatting commit added the scanner/normalizer and reported it at
`setup`/`decide`, but a re-run of the pipeline
(`cnb-12to13-092013-48478ff`) still shipped the same defects: the stage prompts
never mentioned formatting, no stage produced a formatting artifact and nothing
ever invoked the fixer. Diagnosis on that root: `state.original_format` existed
(2 high / 91 medium / 6 low) yet the review/revise/integrate/rewrite PROMPTs
contained **zero** mentions of OOXML, the packages still scanned at 97-971
findings (the 971 figure also counted `work/` scratch and `*.tracked.docx`
auxiliaries, now filtered), and no `M20`/`FORMAT_*` artifact existed anywhere.

What changed:

* **Deterministic normalization in the pipeline, not only in the tool**:
  `normalize_formatting_in_dir()` + `_format_fix_stage_package()` repair the
  corpus `.docx` of every package-producing stage *inside its postcheck*, i.e.
  before the corpus digest, the pin, the judge views and the next round's base
  are built (so "the pin equals what was judged" stays true), and
  `publish_final_clean()` normalizes + verifies the published copy. Each call
  writes `runs/<id>/FORMAT_FIX_<run>.json` (per-file changes + verification) and
  raises a `FORMAT-FIX: …` warning. `setup --format-fix {auto,off}` controls it
  (auto = default); `off` keeps the pristine copy byte-identical.
* **`setup` normalizes the pristine copy** before any manifest is recorded, so
  round 1's base (a1), the original's judge view, later rounds and
  `final_clean_version/` all start from the same repaired bytes; the operator's
  `--source` directory is untouched.
* **M20 is a pipeline-mandated sweep**: `materialize_review` seeds
  `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md` (the
  scan IS the enumeration), the review prompt requires every row to be disposed,
  `check_review_contract` requires the M20 coverage row, and the
  rewrite/revise/integrate/judge prompts carry M20 mandates. Discovery
  proposals now start at M21 (M18/M19/M20 reserved); sweeps.md, SKILL.md,
  discovery.md and the standalone prompt were re-synced, and the prompt
  appendix stays verbatim-equal to sweeps.md.
* **`run --only <stages>`** (aliases `w`, `a`/`a2`, `i`/`merge`, `j`; `all` =
  default): start or adopt only the listed stage types in one invocation;
  everything else stays pending and the round stays incomplete until it runs.
  `retry --run <ID>` remains the way to force a completed stage to re-run.
* **`README.md`** added at the repo root (install, quick start, round model,
  `--only`, formatting policy/artifacts, layout, tests, exit codes).

Evidence on a copy of the re-run package (`runs/r1_i1/integrated`):

```
BEFORE: 97 findings (2 high) -- incl. FMT-S1 (break-only paragraph/blank page),
        mixed hyperlink-vs-plain URL/email treatments
normalize: 2 documents, 11 mechanical changes, findings 97 -> 59, text identity verified,
        artifact FORMAT_FIX_demo_i1.json
AFTER : every URL/email run in both documents has ONE treatment shape (plain black);
        FMT-S1 gone; the remaining rows are editorial (em-dash density, heading-size
        drift, literal tabs) or manual (tracked changes: never auto-accepted)
```

Tests: new `.nbt_test/test_stage_subset.py` (parser, aliases, stage-by-stage
end-to-end `--only review` -> `revise` -> `merge` -> `judge`, multi-stage,
unknown-stage failure, `--help`), new pipeline-level checks in
`test_docx_format.py` (setup normalization + `--format-fix off`, stage
normalization + artifact + text identity + `work/` scratch untouched, seeded
M20 artifact, M20 coverage-row contract, prompt mandates), and the stub agent
now writes an M20 coverage row. All 22 `.nbt_test` suites pass.

## Follow-up (2026-09-20, part 3): one code-side evidence pack for every session

Generalizing the formatting fix: any measurement the orchestrator can make
itself was being made in ONE place and re-estimated by agents elsewhere. The
pipeline now builds a single **evidence pack** per session —
`CODE_SCANS.json` (M18 legend counts, M19 length rows, M20 formatting rows,
hand-off placeholder count, corpus identity: digest/files/revision token) plus a
human-readable `EVIDENCE_PACK.md` — with the M18/M19/M20 tables seeded as
`artifacts/*.md` rows (empty disposition column) for the review and the judge:

| session | pack location | scanned from |
|---|---|---|
| review | `review/work/` + `review/artifacts/{M18,M19,M20}.md` | `base/` |
| rewrite / revise | `work/` at the sandbox root | the package the stage edits (`base/`) |
| integrate (merge) | `work/` at the sandbox root | `self/` |
| judge | **nothing is seeded (blinding)** — the judge derives its own rows and the orchestrator verifies them afterwards | that session's own blinded `target/` |

The four non-judge prompts carry the block: use the pack instead of
re-estimating, dispose/reconcile every seeded row in your own artifact, and
state before → after numbers when your work changes one of them. The seeded
paths are declared as inputs, so the "sandbox already contains work" guard treats
a freshly materialized review sandbox as unstarted. Every package-producing stage
also records `CODE_SCANS_before.json` / `CODE_SCANS_after.json` and an
`evidence_delta` (over-cap sections, placeholders, formatting rows) on its run,
warning when a stage leaves MORE over-cap sections (or a changed placeholder
count) than it started with.

**Correction (same day): the judge must receive none of this.** The first
version of this change also seeded the pack into judge sandboxes (scanned from
the judge's own blinded `target/`). That was wrong: even a self-derived
pre-computed scan is an artifact outside the submission content (it carries a
digest, a revision token, a sandbox path and pre-digested rows), which is
exactly what blinded judging must exclude. Reverted: `materialize_judges` seeds
nothing, `leftovers_present` keeps its original judge semantics, and the judge
prompt now carries a BLINDING RULE instead of a pack -- derive every measurement
yourself from `target/`, `field/<label>/` and `original/` with the same public
tool, and record the rows in `judge_review/artifacts/`. Consistency is verified
from the orchestrator's side: `postcheck_judge` re-scans the blinded target
itself, stores it in `reports/judge_evidence_<run>.json` + the run record, and
warns (never fails) when the judge produced no corresponding artifact table.

Pinned by `.nbt_test/test_evidence_pack.py` (layouts, input-vs-work guard, prompt
blocks, stub-round materialization of every session type, a judge sandbox proved
to contain NOTHING but the blinded views + prompt, the orchestrator-side judge
verification, stage delta). All 23 `.nbt_test` suites pass.

## Follow-up (2026-09-20, part 4): judges see submission content only

The requirement: the judge panel must score the submission CONTENT and nothing
else -- no file names, timestamps, auxiliary files, document metadata or
provenance (was this package rewritten, revised, integrated? which round?). The
judge may still derive its own findings from the material it is given. The
structural work was already in place (per-view salted name permutations, opaque
tokens, one mtime/mode, OOXML/PDF metadata neutralization, no orchestrator
artifacts seeded into a judge sandbox); this pass closed the remaining
channels, all reproduced against the local tree and the user's real package.

**1. The judge run id named the round.** `rid_judge()` returned
`r<r>_judge_<token>_j<k>`, so the judge's own sandbox name, `PROMPT.md` and
`scores.json` all said which round it belonged to (and the pipeline's sibling
directories said it too). Now `judge_<token>_j<k>`: no round, no arm, not
recomputable without the per-root salt.

**2. The judge prompt carried provenance vocabulary.** Reproduced with
`judge_prompt()`: `round` (1 hit), `arm` (3), `rewrite` (2), `revised` (2),
`revision` (2), plus the `docx`-CLI block's stage list "(review, rewrite,
revise, integration, judging)" and the hand-off marker token
`[AUTHOR TO COMPLETE`. Every one was reworded provenance-neutrally: the docx
block now says "*you* may call it" and "every agent, including the judges, and
no stage is forbidden from using it"; the auxiliary rule no longer names "the
revision skill"; the M19 sentence is passive ("it is compressed by removing
redundancy ...") instead of naming the revision stages; the judge gets a
separate `PLACEHOLDER_RULE_JUDGE` ("PLACEHOLDER TEXT IN A PACKAGE") instead of
the pipeline hand-off wording; and the three "which arm" sentences became
"which process". `test_judge_blinding.py` now fails on any of those words.

**3. Build by-products reached the judge view verbatim -- with the author's
machine path and the build date inside.** The corpus filter dropped revision
auxiliaries and pipeline bookkeeping, but not the build by-products of an
editable source, and `_transform_view_file()` only rewrites *references* inside
them. On the user's real package
(`.../cnb-12to13-092013-48478ff/non-revised/`) the view therefore carried
`cnb-12-3-suppAll-d19f2ce.log`, whose first lines are
`This is XeTeX ... (MiKTeX 23.10.12)  20 SEP 2026 11:11` and
`(C:\Users\zhaoxiaofei\AppData\Local\Programs\MiKTeX\tex/latex/base/article.cls)`
-- the author's user name, toolchain, absolute paths and build date, none of
which the metadata pass can reach. The PRESENCE of the set was provenance too:
the rewrite/revise/integrate prompts order agents to leave by-products out of a
version, so a package an agent went over loses them while the untouched
original keeps them.

New rule (`_is_view_excluded_file()`, used by `corpus_dir_view_files()`):
a judge view drops revision auxiliaries, bookkeeping, `work/` scratch, Word's
`~$name.docx` owner file (its content names the author) and the build
by-products (`.aux .blg .bcf .log .out .fls .fdb_latexmk .synctex.gz .run.xml
.toc .lof .lot .nav .snm .vrb .idx .ilg .ind`). The single exception is a
compiled `.bbl`: with no editable `.bib` it is the only copy of the reference
list (the DERIVED rule lets a package ship exactly that) and it carries no build
date, tool path or machine name. The user's real package therefore goes from 38
files to 31 in the view, with the `.bbl` kept and `C:\Users\zhaoxiaofei` present
in no view byte. Pins, published winners and the next round's base are NOT
touched: their digests are recorded in `state.json`, so changing the corpus
rule would make every existing root fail its own integrity check.

**4. A judge sheet or marker that invented a round was a hard failure.** Since a
judge is never told the round, a value it cannot know cannot be a contract
breach: `validate_judge_sheet()` and `_marker_checks()` now warn (the run record
holds the real round; the opaque `target_id` still ties the sheet to its
target). The stub judge/agent and the scheduling/id harnesses were updated for
the new opaque ids.

Pinned by the new `.nbt_test/test_judge_blinding.py` (sanitizer invariants, a
Word-saved package vs its pipeline-processed twin, the by-product/owner-file
rule including the `.bbl` exception, and the prompt/id vocabulary), a new
`test_anonymized_judging.py` section that materializes REAL judge sandboxes from
a package carrying those by-products, and the updated `test_pipeline.py`,
`test_change_requests.py`, `test_evidence_pack.py`,
`test_pipeline_audit_findings.py`, `test_parallel_scheduling.py` suites. All 25
`.nbt_test` suites pass.

**Correction (same day): a judge is given the SOURCES, not what can be compiled
from them.** Item 3 kept a compiled `.bbl` and kept every submitted PDF; the
operator's rule is the opposite -- "bib file instead of files derived from bib,
docx file instead of files derived from docx file". A view now also drops any
derived output whose editable source ships in the same directory: a `.bbl` next
to its `.bib`, and a `.pdf` next to the `.docx`/`.doc`/`.tex`/`.ltx`/`.rtf`/`.md`
it was rendered from (same stem, version tokens ignored; `.txt` is deliberately
NOT treated as a source, since a text file beside a figure PDF is not a
source/derived pair). A derived file with no source in the package still stays,
because it is then the only copy of the content. On the operator's real package
the view goes 38 -> 29 files: the compiled supplementary PDF, its `.bbl`, the
`.aux/.bcf/.blg/.log/.out/.run.xml/.synctex.gz` and Word's `~$` file are gone,
while the standalone `nr-reporting-summary-filled-b.pdf` and all
`raw_figs/*.pdf` figures (no editable twin) stay, as do the `.docx`, `.tex` and
`.bib` sources. Consequence to state plainly: a stale submitted PDF is no
longer a JUDGE finding (it remains one for review/revise/integrate, which still
see every rendering).

**5. `setup` now survives its own failure.** The operator's run died with
`OSError: [Errno 5] Input/output error` while `setup` hashed the fresh copy on
`/mnt/c` (WSL drvfs returned EIO on a readable file -- the same transient error
class this session hit while reading the repository), and because `setup`
refuses to re-run on a non-empty root (a guard that exists to protect real
roots) it left a half-built directory to delete by hand. `setup` now writes
`_setup_in_progress` into the root it is building and removes it once
`state.json` exists; a root carrying that marker with no `state.json` is printed
as an INTERRUPTED setup and rebuilt from the source, while a root without the
marker (a complete run, or a directory setup did not create) is still refused.
The EIO itself is environmental: nothing in the pipeline can make a drvfs read
succeed, so the recovery path -- re-run the same command -- is the fix.

Pinned by `test_candidates.py` C2b (an interrupted root restarts; a complete
root is still refused) and the derived-output checks in `test_judge_blinding.py`
plus the extended `test_anonymized_judging.py` section.

Residual risk (documented, unchanged): there is no OS-level jail, so a judge
that disobeys its prompt could read outside its sandbox; the prompt forbids it
explicitly and the panel's evidence is re-derived outside the sandbox by
`postcheck_judge`. Consequence of the by-product rule for an EXISTING root:
judge views are rebuilt and the affected judge sessions are marked stale and
re-run (their scores were produced from a corpus that still carried the
by-products).

## Follow-up (2026-09-20, part 6): the warnings in a real root, and one defect vocabulary

The operator pointed at `state.json` of a live root and asked whether its
warnings can be avoided. Six were recorded for the review+revise round; two of
them were false and one was pure noise:

| warning | verdict | action |
|---|---|---|
| a1 `no agent run: A1 copied from orig` | noise -- the round base IS a byte-for-byte copy by construction | removed (the record's `kind` already says it) |
| `EVIDENCE: this stage left MORE over-cap section(s) (0 -> 7)` | FALSE | fixed, see below |
| `EVIDENCE: hand-off placeholders 4 -> 73 (+69)` | FALSE | fixed, see below |
| `RECOVERY: 3 base file(s) were MISSING ... restored` | REAL -- the agent dropped three `raw_figs/` files; the recovery layer restored them and recorded it | kept (that is the invariant working) |
| `compiled PDF(s) left out ... deliberate per the derived-output rule` | informational, by design | kept |
| `N pipeline hand-off placeholder(s) await the author` | informational, by design | kept |

**Root cause of the two false ones.** A stage writes its process scratch INSIDE
its output directory (`revised/work/`), and `code_side_evidence()` walked that
directory raw: the agent's own snapshots, `.txt` renderings, re-scan corpora and
`STATE.md` notes were counted as manuscript documents. So the after-scan saw
9000-word text conversions (7 phantom over-cap sections) and 69 quoted
`[AUTHOR TO COMPLETE: ...]` markers from the agent's notes, while the before-scan
walked a clean `base/` -- the delta then reported a regression that never
happened. The same walk also gave the pack a corpus digest (`bea68e0f…`) that no
other part of the pipeline used.

Fix: `code_side_evidence()` now scans the SAME sources the corpus digest uses
(`corpus_sources()`: the run's `code/` directory under the `code/` prefix plus
the output directory with `CORPUS_EXCLUDE_TOP` applied), the scanners take that
source list, and the pack's identity is computed by the same
`manifest_for_sources()` helper that defines `corpus_manifest()`. Re-measured on
the operator's live root: the pack digest is now `9e6928aabcd1601d` -- byte-equal
to the recorded `corpus_digest` -- the over-cap rows go 7 -> 0 and the
placeholders 73 -> 4 (the four real ones), so neither warning can fire again for
that package. A1's postcheck records no warning either.

**One defect vocabulary (the consistency request).** A reviewer's "category 2"
and a judge's "formatting" could describe the same edit: the review taxonomy is
six categories (`nbt-review/references/sweeps.md` -> CLASSIFICATION) while the
panel scores five classes (`BASIS_TIERS`), and no bridge existed anywhere in the
tree -- the earlier design audit recorded this as C20 and declined it as a rubric
redesign. The operator now asks for consistent scoring functions, so the bridge
is added WITHOUT touching the rubric, the scale or the arithmetic: a shared
`DEFECT_CLASS_RULE` block (generated from `BASIS_TIERS`, so it cannot drift) is
inserted verbatim into all five prompts, and the same table is added to
`nbt-review/references/sweeps.md`, its verbatim mirror
`nbt-skills/prompts/identify_issues.prompt.md`, and
`nbt-revise/references/ledger.md`. It states the five classes in priority order,
the category -> class mapping (splitting categories by the concrete defect),
the shared CRITICAL/MAJOR/MINOR scale, the rule that an improvement claim must
name its class and item, and what stays cosmetic (0) -- with the one deliberate
exception (formatting is capped at ±1 and never decisive). Wording-only fixes
are explicitly NOT cosmetic when systematic: the same convention applied
unevenly is a `consistency`-class defect, which the judge already treats as
second-priority.

Pinned by `test_pipeline.py` (the block is byte-identical in all five prompts,
its class order equals `BASIS_TIERS`, it names all six categories and the
severity scale, and both skill files carry the same table) and
`test_evidence_pack.py` (the pack ignores `work/` scratch; a stage's pack
identity equals the corpus digest the run records under the same sources).
All 25 `.nbt_test` suites pass. Out of scope, reported: the *installed* skill
copy (`~/.codex/skills/nbt-skills-2026-0920-48478ff/nbt-review/...`) is older
than the repo's (`M20` is missing from its sweeps.md), so the operator must
refresh it from `nbt-skills/` for the agents to read the new table; the prompts
carry the block themselves in the meantime.

## Follow-up (2026-09-20, part 7): the category-2 writing tie-break (integer key, not epsilon)

The operator asked for category-2 (writing quality / logic / repetition) to
matter, and proposed `score + epsilon * category_2_grade` (epsilon = 1e-6). The
mechanism was rejected and the goal implemented differently; the reasons are
worth keeping:

  * a judge sheet's score MUST be an integer (`comparisons[i].score must be an
    integer in -4..+4`), so epsilon inside the sheet fails the contract and burns
    a session;
  * epsilon applied orchestrator-side would break the `(median, mean, IQR) ==`
    test that keeps the incumbent base on an exact tie -- a style-different
    challenger would silently replace an incumbent the panel cannot distinguish
    from it, which is exactly the anti-churn rule the pipeline pre-registered;
  * floats cannot be a lexicographic key: the recorded numbers would no longer be
    the judges' integers, and the ranking would depend on summation order.

Implemented instead: an integer tie-break key. `writing_remaining` (the number of
the frozen review's CATEGORY-2 findings still open in the package) is reported by
each package-producing session in its completion marker -- the same channel as
`critical_remaining`, symmetrically for rewrites, revisions and integrations --
validated as a non-negative integer (+inf sentinel otherwise, so an absent or
nonsensical count never wins), cross-checked against the frozen review for the
revision arm (warn when it claims 0 while the review lists category-2 findings),
frozen in the round record (`tiebreak_inputs`) so `decide` re-derives the same
ranking after pruning, and added to the ranking key after the critical count:

    (-median, -mean, IQR, critical_remaining, writing_remaining, digest, id)

Severity outranks style; style outranks nothing but the digest. The incumbent
retention rule is untouched (strictly `median/mean/IQR`): a better writing count
separates challengers, it never retires an incumbent the panel cannot
distinguish. The number is never a score, a gate or a reason to make a version
ineligible, and the judge is never asked for it (blinding holds: the judge prompt
contains no `writing_remaining`). `DECISION_REPORT.md` (and the console table)
now carry `critical` and `writing` columns, and `decision.json` lists the key in
`score_model.tiebreaks` with the self-report/cross-check notes.

Pinned by `test_grading_scheme.py` section B2 (the five-way exact tie is now
decided by the writing count instead of the digest; a negative/absent count is
the +inf sentinel and never wins; a writing count never dethrones the incumbent
on an exact tie; `writing_findings_input` counts category 2 only -- including a
string `"2"` -- while `critical_findings_input` still counts Critical severity
only), the updated D4/D5 checks (the score model's key list; the three
package-producing prompts ask for the field; the review and judge prompts do
not), plus C2/E in `test_audit_bugs.py` and CR1d in `test_change_requests.py`.
All 25 `.nbt_test` suites pass.

## Follow-up (2026-09-21, part 8): font/style consistency — character-style italics and journal emphasis

The operator reported a real defect the scanner called CLEAN: in
`/home/.../cnb-12to13-092023--ba40ef0/runs/r1_a2_revise/revised/cnb-12-1-coverLetter-e46bc9d.docx`
"Nature Biotechnology" was italic in two sentences and roman in the others, and
"Nature Methods and other leading journals" was emphasised as one unit.

**Root cause.** The italics lived in Word's `Emphasis` CHARACTER STYLE
(`w:rStyle w:val="Emphasis"` -> `styles.xml` -> `<w:rPr><w:i/></w:rPr>`), and
the italics checks read only the run's own `<w:i/>`. Two gaps followed: italics
from any style were invisible (`FMT-T6c` never fired), and there was no rule at
all for "the same name is formatted two ways" or for an emphasis span that runs
on past the title. `FMT-T6c`/`T6d` were also classified `style-field`, so even a
detected row was never repaired.

**Fix.**

  * `parse_styles()` now captures `w:i`/`w:iCs` tri-states (including explicit
    `val="0"` off-switches) and the `w:docDefaults` run properties, and
    `effective_emphasis()` resolves Word's precedence — direct rPr > character
    style chain > paragraph style chain > document defaults.
  * New rules, with the run offsets kept so scan and fix cannot disagree:
    `FMT-T6c` (italic journal outside the reference list), `FMT-T6f` (emphasis
    continuing past the title onto ordinary lowercase prose), `FMT-T6e` (the
    same journal name italic in one place and roman in another, per region) and
    `FMT-T6g` (reference-list title left roman). `T6c/T6f/T6g` are MECHANICAL
    under a decided `journal_italics` policy; `T6e` is the report that ties them
    together (and remains non-mechanical when a run mixes title and volume).
  * The fixer pins the affected runs with a direct `w:i w:val="0"` (roman) or
    `<w:i/>` (italic) inserted in schema order, which beats the character style
    without touching `styles.xml`; a title-only guard means a reference run that
    also carries volume/pages is reported, never re-styled, and field-protected
    runs stay untouched unless `unlink_zotero_fields` is set.
  * Guard rails against over-reach (found while scanning the operator's own
    package): journal matches now need real token boundaries and are not read
    out of URLs/DOIs, so `Cell-line`, `(Single-Cell)` and
    `github.com/.../single-Cell-...` are not titles; the run-on rule requires a
    lowercase prose word, so abbreviated titles (`Cell Syst.`, `Cell Rep.
    Methods`) are not eaten; and a legitimate italic (`de novo`) is untouched.
  * New STYLE artifact: `style_survey()` (fonts and sizes in use, paragraph
    styles, character styles, and italic runs by mechanism — direct vs character
    style vs paragraph style) is embedded in every scan result, so it reaches
    `FORMAT_SCAN.json`, `CODE_SCANS.json` and the M20 table.

**Evidence on the operator's files.** Scan of the revised package before: 3x
`FMT-T6c`, 2x `FMT-T6f`, 2x `FMT-T6e`, all in the cover letter (the earlier
`refs: cell` row was a URL false positive and is gone). `fix` on the cover
letter: 5 runs normalized, 7 mechanical findings -> 0, `text_identical: true`,
`parts_intact: true`, `docx validate` clean, idempotent. Rendered with
LibreOffice: the before-PDF embeds `LiberationSerif-Italic`, the after-PDF has
only `LiberationSerif` and `-Bold` — the visual symptom is gone. `setup` on the
operator's pristine source now reports `FORMAT-FIX: 1 document(s) normalized …
normalized journal emphasis on 5 run(s)` and the re-scanned pristine copy has no
journal-emphasis row at all. `publish_final_clean` runs the same fixer, so a
`decide` repairs the published `final_clean_version/` too.

Residual limits (documented, deliberate): a reference run that mixes journal
title with volume/pages is reported (`FMT-T6e`) but not auto-restyled;
field-protected runs need `unlink_zotero_fields`; the extension list of known
journals is the one in `JOURNAL_RE` (unknown journals are still caught by the
per-region mixed-treatment report whenever another mention of the same name is
found). Pinned by `test_docx_format.py::test_journal_emphasis` (character-style
detection, the three rules, the false-positive guards, the fix, the untouched
`styles.xml`, the preserved `de novo` italic, the style survey, idempotency) and
the full 25-suite run.

## Follow-up (2026-09-21, part 9): package-wide style/consistency discovery + deliverable validation

The operator asked for ALL style/consistency problems of the cover-letter kind to
be found, validated and solved across the whole submission, and for the editing
sessions to validate their DOCX/LATEX output. What was done:

**Discovery over the real package** (cover letter original + revised, main text,
supplementary .tex, a generated stats .tex): a script extracted the paragraph
text and measured citation shapes, parentheses, repeated n-grams, term variants,
punctuation hygiene, reference-style labels and dash/spelling usage.

  * VALIDATED: the cover letter mixes three citation formats (3x
    `(Author, YEAR, Journal)`, 2x `(Author, Journal, YEAR)`, 2x
    `(Author, YEAR)`); the main text carries 4 real nested parentheses
    (`(… (DNTR-seq)…)`, `(… frequency (BAF))`, `(… (scWGS) …)`); the cover-letter
    paragraph repeats "Nature Biotechnology" 4x in 178 words (and 10 further
    paragraphs repeat a content word 5-9x); the supplementary .tex mixes
    attributive `copy-number` with `copy number`.
  * REFUTED (checked, not real): `Table S1` vs `Supplementary Table S1` (the
    shorter string only ever appears inside the longer one -- consistent);
    "doubled punctuation" (all hits were `al.,` and `Ph.D.,`); tumour/tumor,
    analyse/analyze, single-cell/single cell and copy number/copy-number variants
    in prose (every hit sat in a REFERENCE TITLE: quotations, which must not be
    touched); `SI Fig`/`Extended Data` (absent).

**Implemented** (rules FMT-T8a..e, one definition for scan and fix):
`citation_format_row` (mixed formats + whether the odd forms are fixable),
`nested_parentheses_rows` (mathematical calls excluded), `term_repetition_rows`
(narrow: proper names 2-3 capitalized words used >=4x in the document, or one
long content word >=5x in a paragraph of >=40 and <=300 words; URLs masked;
reference lists skipped), `variant_rows` (US/UK spellings; attributive
hyphenation). The rules run over the docx paragraphs AND the LaTeX/markdown
sources (`text_source_paragraphs`), so the whole package is covered, and the
rows flow into the pack/M20 artifact.

Fixes are policy-driven and prove themselves: `citation_journal_names="drop"`
deletes the redundant journal segment from the citation (crossing runs -- the
journal sits in its own italic run), `term_spelling="dominant"` and
`term_hyphenation="dominant"` normalize the minority form in body text only.
`rewrite_text_spans()` is the new in-depth DOCX text surgery (rewrites `<w:t>`
contents across runs, drops runs left empty, touches nothing else); every edit is
recorded and `verified.text_diff_only_recorded_edits` proves the document text
changed by exactly those edits. On the operator's cover letter: 3 mixed-format
rows -> journal segments deleted, citations now all `(Author et al., YEAR)`,
6 mechanical findings -> 0, schema valid, idempotent. Nested parentheses and
repetition stay REPORT-ONLY (they are wording decisions for the agents), which is
why they remain in the M20 table after the fix.

**Deliverable validation** (the second request): `nbt_docx_format.py validate
<paths>` checks every DOCX (zip readable, every XML/rels part parses, `docx
validate` when available) and compiles every standalone `.tex` in a scratch copy
(`\input` fragments SKIP with a reason; a missing engine is SKIP, not a failure).
The three editing prompts now carry a validation rule (run it after every edit,
iterate at most three times, then record file+command+error in the manual-steps
list and never "fix" an error by deleting content). The orchestrator does not
trust that loop: `_validate_stage_package()` runs the same validator in the
postcheck, records `rec["validation"]`, fails the attempt on a malformed DOCX,
and fails on a LaTeX compile error only when the package the stage started from
compiled (an author's pre-existing breakage is reported, not punished) -- so the
existing `--retries` policy is the hard cap. The stateless module is now copied
next to PROMPT.md in every session sandbox (the prompts call it by name); the
judge's copy is stamped with the view timestamp and carries no per-run data, and
the blinding test whitelists exactly that file. On the operator's revised
package the validator reports 2 valid DOCX, the supplementary compiles, and the
four `\input` fragments SKIP.

Pinned by `test_docx_format.py::test_text_consistency_rules` (all five rules,
the guards, the citation/spelling/hyphenation fixes, the recorded-edit proof, the
untouched reference list) and `::test_deliverable_validation` (valid/invalid
DOCX, fragment SKIP, compiling and non-compiling .tex), the prompt checks in
`test_grading_scheme.py` (the three editing prompts carry the rule; review/judge
do not) and the `rec["validation"]` check in `test_evidence_pack.py`. All 25
`.nbt_test` suites pass.

Residual limits (documented): nested parentheses and repetition are reported,
never auto-rewritten; citation normalization only matches author-year forms
(narrative citations like "Song et al. (2025)" are a legitimate style and are
left alone); the spelling allowlist is deliberately short ("analyses" is also a
noun, so analyse/analyze is not normalized); LaTeX fragments are only validated
through their parent document; and the compile gate needs a TeX engine on PATH.

## Summary

- Ingested: 37 deduplicated candidates (S1 17 findings + S2 6 classes + S3 28 findings, merged by surface/symptom).
- Confirmed: 10 — C04, C06, C07, C08, C09, C11, C12, C13, C14, C15 (C06/C07/C08/C09 are the LaTeX/span-counting group; each is separately reproduced and asserted).
- Patched: all 10 confirmed items, with the new suite plus the existing suites re-run green.
- Unfixed: none in scope. `CANNOT_REPRODUCE`: C17, C24. `FALSE_POSITIVE`: C05, C18, C19, C23.
- NOT_A_BUG (documented design, policy or feature-sized): C01, C02, C03, C10, C16, C20, C21, C22, C25, C26, C27, C28, C29, C30, C31, C32, C33, C34, C35, C36, C37.
- OUT_OF_SCOPE: none (every cited path exists inside this repository).
- Process exit: **0** — S5 green: the new suite (D1–D9, 40 checks) plus all 19 pre-existing `.nbt_test` suites pass, and no confirmed in-scope item is left unfixed.

## Verification evidence

```text
$ python3 .nbt_test/test_design_audit_2026_0919.py
all design-audit checks passed                      (exit 0; 40 checks; exit 1 pre-patch with 25 failures)

$ for t in .nbt_test/test_*.py; do python3 "$t"; done
test_acronym_longform.py            rc=0  ALL ACRONYM LONG-FORM CHECKS PASSED
test_anonymized_judging.py          rc=0  ALL ANONYMIZED-JUDGING CHECKS PASSED
test_audit_bugs.py                  rc=0  ALL AUDIT-BUG CHECKS PASSED
test_bug_audit_2026_0919.py         rc=0  ALL AUDIT-REGRESSION CHECKS PASSED
test_candidates.py                  rc=0  ALL CANDIDATE CHECKS PASSED
test_candidates2.py                 rc=0  ALL ROUND-2 CANDIDATE CHECKS PASSED
test_change_requests.py             rc=0  ALL CHANGE-REQUEST CHECKS PASSED
test_design_audit_2026_0919.py      rc=0  all design-audit checks passed
test_document_recovery.py           rc=0  ALL DOCUMENT-RECOVERY CHECKS PASSED
test_docx_converter.py              rc=0  ALL DOCX-CONVERTER CHECKS PASSED
test_final_clean_version.py         rc=0  ALL FINAL-CLEAN-VERSION CHECKS PASSED
test_fixes.py                       rc=0  ALL FIX CHECKS PASSED
test_grading_scheme.py              rc=0  ALL GRADING-SCHEME CHECKS PASSED
test_hash_cache.py                  rc=0  ALL HASH-CACHE CHECKS PASSED
test_length_limits.py               rc=0  ALL LENGTH-LIMIT CHECKS PASSED
test_llm_stochastic_failures.py     rc=0  ALL STOCHASTIC-FAILURE CHECKS PASSED
test_parallel_scheduling.py         rc=0  ALL SCHEDULING CHECKS PASSED
test_pipeline.py                    rc=0  ALL CHECKS PASSED
test_pipeline_audit_findings.py     rc=0  (F1–F5 asserted as FIXED)
test_revision_token.py              rc=0  ALL REVISION-TOKEN CHECKS PASSED
test_zotero_integration.py          rc=0  ALL ZOTERO-INTEGRATION CHECKS PASSED
```

End-to-end `setup` sanity check on a `.tex` + cover-letter package:

```text
[setup] abstract/main-text length: 3 section(s) [cover letter 600 words OUTSIDE-PREFERENCE,
        abstract 9 words, main-text 41 words] (caps: abstract 172, main text 3750; all within
        the relaxed caps; 1 cover letter(s) outside the user's 300-500-word preference
        (not an NBT limit, never a gate))
state.json: cover-letter.txt | cover letter | 600 | over_limit False | within_pref False | over_pref True
            paper.tex        | abstract     |   9 | over_limit False
            paper.tex        | main text    |  41 | over_limit False
```

## In-scope changes (unified diff)

Tracked files: `git diff`. New files: `.nbt_test/test_design_audit_2026_0919.py`
(added-file diff below) and this ledger itself (the report, not part of its own diff).

```diff
diff --git a/.nbt_test/README.md b/.nbt_test/README.md
index 933d9dc..6864265 100644
--- a/.nbt_test/README.md
+++ b/.nbt_test/README.md
@@ -9,6 +9,7 @@ Python 3 (standard library) and take a few seconds each; every suite prints one
 |---|---|
 | `test_pipeline.py` | The design-fix suite: prompts (render-then-look, visual artifacts), caption/placeholder gates, corpus rules, ranking and champion reporting. |
 | `test_bug_audit_2026_0919.py` | Regression checks for the confirmed findings of the 2026-09-19 bug audit (`nbt_audit_data/2026-0919-1336-potential-bug-report/`): Python-3.9 syntax, the MCP visual gate, length/caption/cover-letter counting, the revision token, the stale-lock reclaim race, citation/number/acronym/occurrence extractor defects and the state/probe/materializer fixes. |
+| `test_design_audit_2026_0919.py` | Regression checks for the confirmed findings of the 2026-09-19 design audit (`nbt_audit_data/2026-0919-1754-potential-design-issue-report/`): the shared M19 counter reads `.tex`/`.ltx` sources (one-line and multi-paragraph abstracts, `\caption` spans, LaTeX scaffolding), M19 subtracts only the legends inside the main-text span, the cover-letter row is a preference never a cap, M18's coverage row is mandatory in every caption state, the standalone fallback prompt matches SKILL.md/sweeps.md, and every length-scanned text format is enumerated for M18. |
 | `test_fixes.py` | Asserts the fixed behaviour of every finding in `nbt_round_pipeline_issue_findings.md` (wrong-corpus, missing-artifact, prompt-sync, ranking). |
 | `test_candidates.py` | Round-1 candidate repros: prune-then-run, setup script copy, `mc:Ignorable` declarations, stale redline output, manual-step counting. |
 | `test_candidates2.py` | Round-2 candidate repros (the audit archives): skill-script regressions R1-R11, judge/agent-command handling, xlsx/corpus fixes. |
@@ -35,6 +36,7 @@ Python 3 (standard library) and take a few seconds each; every suite prints one
 ```bash
 python3 .nbt_test/test_pipeline.py
 python3 .nbt_test/test_bug_audit_2026_0919.py
+python3 .nbt_test/test_design_audit_2026_0919.py
 python3 .nbt_test/test_fixes.py
 python3 .nbt_test/test_candidates.py
 python3 .nbt_test/test_candidates2.py
diff --git a/.nbt_test/test_length_limits.py b/.nbt_test/test_length_limits.py
index 77161de..f4af1bf 100644
--- a/.nbt_test/test_length_limits.py
+++ b/.nbt_test/test_length_limits.py
@@ -22,8 +22,9 @@ Asserts:
     main text at Methods/References, skips supplementary-named files and
     renderings, reports unparseable sources as "unparsed", and refuses to count
     a document that has no manuscript shape at all;
-  * the review postcheck requires an M19 coverage row (always, unlike M18), and
-    `setup` records the source length scan in state.json and prints it.
+  * the review postcheck requires both the M19 and the M18 coverage row
+    (both always active), and `setup` records the source length scan in
+    state.json and prints it.
 
 `NBT_WS` retargets the suite at another copy of the tree.
 """
diff --git a/nbt-skills/nbt-review/SKILL.md b/nbt-skills/nbt-review/SKILL.md
index 2351a85..86fd1d0 100644
--- a/nbt-skills/nbt-review/SKILL.md
+++ b/nbt-skills/nbt-review/SKILL.md
@@ -72,7 +72,7 @@ Truncation silently drops exactly the tail-end mechanical findings, so append ea
 2. All sweep artifacts as titled appendix tables (or pointers to `OUT/artifacts/`).
 3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M19, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
 4. Per-document index of finding IDs.
-5. Coverage table: every check ID (M1–M17, J1–J4, plus M19 — and M18 when the caption suggestion is active) → `N findings` / `clean — basis` / `unable — <reason>`.
+5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts) and M19 (abstract/main-text/cover-letter lengths)) → `N findings` / `clean — basis` / `unable — <reason>`.
 6. Summary note: counts by category/severity; unresolved gaps; missing-citation issues; ambiguous context; unresolvable contradictions; the manual-verification list (incl. Zotero fields); guidelines source/version; items to re-check against the current author guide.
 
 `OUT/findings.json` (machine-readable, consumed by nbt-revise):
diff --git a/nbt-skills/nbt-review/references/sweeps.md b/nbt-skills/nbt-review/references/sweeps.md
index adabee5..197088d 100644
--- a/nbt-skills/nbt-review/references/sweeps.md
+++ b/nbt-skills/nbt-review/references/sweeps.md
@@ -43,7 +43,7 @@ Every finding is ONE instance, formatted:
 
 ```
 F-NNN | location: <doc>/<section>/<paragraph|line|figure|table> | category: <0–5>
-check: <M1–M17|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
+check: <M1–M19|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
 evidence: "<short verbatim quote of the exact word/number/phrase>"
 problem: <1–2 sentence explanation>
 ```
diff --git a/nbt-skills/nbt-review/scripts/count_words.py b/nbt-skills/nbt-review/scripts/count_words.py
index 664d478..0a305b9 100644
--- a/nbt-skills/nbt-review/scripts/count_words.py
+++ b/nbt-skills/nbt-review/scripts/count_words.py
@@ -1,5 +1,5 @@
 #!/usr/bin/env python3
-"""Word counts for the abstract/main-text length rule (check id M19).
+r"""Word counts for the abstract/main-text length rule (check id M19).
 
 Stdlib-only, like the other bundled scripts. The counting rule is the
 pipeline's: a word is a maximal run of NON-SPACE characters with a newline
@@ -13,7 +13,10 @@ has a manuscript shape (an "Abstract" heading, or an Introduction/Main-text
 heading); otherwise it reports the whole file and says so. The main text stops
 at the first Methods / References / Figure-legends / Acknowledgements heading
 (those are excluded from the journal's main-text limit) and subtracts detected
-figure captions, which the journal also excludes.
+figure captions INSIDE that span, which the journal also excludes. `.tex`/`.ltx`
+sources are read as LaTeX: the abstract environment's own `\end{abstract}` ends
+the abstract (paragraph breaks inside it do not), and `\caption`/`\captionof`
+text is a legend even though its "Figure N" label is added at typesetting time.
 
 The default caps are the pipeline's relaxed NBT Article caps: abstract <= 172
 words (150 +15%) and main text <= 3,750 words (3,000 +25%). Use --base-abstract
@@ -59,6 +62,20 @@ COVER_DISCLOSURE = re.compile(
     r"excluded reviewers?|reviewers?|double-anonymized|orcid|competing interests?|"
     r"data availability|word counts?)\s*[:.\u2014\u2013-]", re.I)
 
+# LaTeX sources state two boundaries that plain text leaves implicit: the
+# abstract environment and the captions. Both are tracked explicitly below, so
+# a `.tex` manuscript is counted with the same rule as a .md/.docx one instead
+# of being answered with a markup-inclusive "whole file" row.
+TEX_EXTS = (".tex", ".ltx")
+TEX_SECTION = re.compile(r"^\\(?:sub)*section\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
+TEX_CAPTION = re.compile(r"\\caption(?:of)?\*?\s*(?:\{[^{}]*\}\s*)?(?:\[[^\]]*\]\s*)?\{")
+TEX_ENV_TOKEN = re.compile(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\[[^\]]*\])?")
+TEX_SCAFFOLD = re.compile(
+    r"\\(?:documentclass|usepackage|RequirePackage|bibliography|bibliographystyle|"
+    r"includegraphics|includesvg|input|include|vspace|hspace|setlength|geometry|"
+    r"graphicspath|hypersetup|newcommand|renewcommand)\*?(?:\[[^\]]*\])?"
+    r"(?:\{[^{}]*\})*")
+
 ABSTRACT_RELAXATION = 1.15
 MAIN_TEXT_RELAXATION = 1.25
 COVER_LETTER_MIN = 300
@@ -75,6 +92,116 @@ def lenient_cap(base: int, factor: float) -> int:
     return int(float(base) * float(factor))
 
 
+def _strip_latex(text: str) -> str:
+    """Prose of a LaTeX line: commands removed, braces treated as spaces."""
+    text = re.sub(r"\\(?:cite[a-zA-Z]*|ref|label|url|href)\s*\{[^{}]*\}", " ", text)
+    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
+    return re.sub(r"\s+", " ", text.replace("{", " ").replace("}", " ")).strip()
+
+
+def _brace_delta(text: str) -> int:
+    """Unescaped ``{`` minus unescaped ``}`` in `text`."""
+    delta, esc = 0, False
+    for ch in text:
+        if esc:
+            esc = False
+        elif ch == "\\":
+            esc = True
+        elif ch == "{":
+            delta += 1
+        elif ch == "}":
+            delta -= 1
+    return delta
+
+
+def _split_group(text: str):
+    """(inside, after) for the rest of a ``{...}`` group whose ``{`` was consumed.
+
+    `text` starts INSIDE the group (the caller matched up to and including the
+    opening brace), so the depth starts at 1; an unclosed group returns the
+    whole text as ``inside`` and an empty remainder.
+    """
+    depth, esc = 1, False
+    for i, ch in enumerate(text):
+        if esc:
+            esc = False
+        elif ch == "\\":
+            esc = True
+        elif ch == "{":
+            depth += 1
+        elif ch == "}":
+            depth -= 1
+            if depth == 0:
+                return text[:i], text[i + 1:]
+    return text, ""
+
+
+def _line_text(line: str) -> str:
+    """Prose of one LaTeX line: environment tokens and command arguments gone."""
+    return _strip_latex(TEX_SCAFFOLD.sub(" ", TEX_ENV_TOKEN.sub(" ", line)))
+
+
+def tex_lines(text: str):
+    """(lines, abstract_end, caption_lines) for a LaTeX source.
+
+    `lines` are heading/paragraph lines; `abstract_end` is the line index the
+    abstract's text stops at (`\\end{abstract}`, so paragraph breaks inside the
+    environment stay inside the abstract); `caption_lines` are the indices of
+    the single lines holding a `\\caption`/`\\captionof` text (each such group
+    becomes its own line, so subtracting that line removes exactly the legend's
+    words), which the main-text count subtracts.
+    """
+    lines, captions, abstract_end = [], [], None
+    raw_lines = (text or "").splitlines()
+    i, n = 0, len(raw_lines)
+    while i < n:
+        raw = raw_lines[i]
+        i += 1
+        line = re.sub(r"(?<!\\)%.*$", "", raw).strip()
+        if re.match(r"\\begin\{abstract\}", line):
+            rest = re.sub(r"^\\begin\{abstract\}", "", line)
+            rest = re.sub(r"\\end\{abstract\}.*$", "", rest).strip()
+            lines.append("Abstract")
+            if rest:
+                lines.append(_line_text(rest))
+            if "\\end{abstract}" in line:
+                abstract_end = len(lines)
+            continue
+        if re.match(r"\\end\{abstract\}", line):
+            abstract_end = len(lines)
+            rest = re.sub(r"^\\end\{abstract\}", "", line).strip()
+            if rest:
+                lines.append(_line_text(rest))
+            continue
+        m = TEX_SECTION.match(line)
+        if m:
+            lines.append(m.group(1).strip())
+            continue
+        cap = TEX_CAPTION.search(line)
+        if cap:
+            before = _line_text(line[:cap.start()])
+            if before:
+                lines.append(before)
+            group = line[cap.end():]
+            depth = 1 + _brace_delta(group)
+            while depth > 0 and i < n:
+                nxt = re.sub(r"(?<!\\)%.*$", "", raw_lines[i]).strip()
+                i += 1
+                group = f"{group}\n{nxt}"
+                depth += _brace_delta(nxt)
+            cap_text, after = _split_group(group)
+            captions.append(len(lines))
+            lines.append(_strip_latex(cap_text))
+            after = _line_text(after)
+            if after:
+                lines.append(after)
+            continue
+        stripped = _line_text(line)
+        if stripped:
+            lines.append(stripped)
+    return lines, abstract_end, captions
+
+
 def _abstract_end(lines, start):
     j = start
     seen_text = False
@@ -119,14 +246,21 @@ def caption_ranges(lines: list) -> list:
     return ranges
 
 
-def sections(text: str) -> list:
-    """[(section, words, note)] for a document's text lines."""
+def sections(text: str, abstract_end=None, caption_lines=None) -> list:
+    """[(section, words, note)] for a document's text lines.
+
+    `abstract_end` and `caption_lines` are the explicit LaTeX boundaries from
+    `tex_lines()`: the abstract stops there whatever blank lines it contains,
+    and only captions inside the counted main-text span are subtracted.
+    """
     lines = (text or "").splitlines()
     n = len(lines)
     abs_start = abs_end = None
     for i, raw in enumerate(lines):
         if ABSTRACT_HEAD.match(raw.strip()):
-            abs_start, abs_end = i + 1, _abstract_end(lines, i + 1)
+            abs_start = i + 1
+            abs_end = (max(abs_start, min(int(abstract_end), n)) if abstract_end is not None
+                       else _abstract_end(lines, abs_start))
             break
     main_start = None
     for i, raw in enumerate(lines):
@@ -151,8 +285,19 @@ def sections(text: str) -> list:
                     or KEYWORDS.match(ln.strip()))]
     offset = start or 0
     segment = lines[offset:end]
-    captions = sum(count_words(" ".join(segment[a:b]))
-                   for a, b in caption_ranges(segment))
+    if caption_lines is None:
+        cap_ranges = caption_ranges(segment)
+    else:
+        cap_ranges = []
+        for i in sorted(set(caption_lines)):
+            if not (offset <= i < end):
+                continue                       # outside the counted span
+            rel = i - offset
+            if cap_ranges and rel == cap_ranges[-1][1]:
+                cap_ranges[-1][1] = rel + 1
+            else:
+                cap_ranges.append([rel, rel + 1])
+    captions = sum(count_words(" ".join(segment[a:b])) for a, b in cap_ranges)
     words = max(0, count_words(" ".join(body)) - captions)
     notes = []
     if abs_start is None:
@@ -213,7 +358,18 @@ def main(argv=None) -> int:
             print(f"error: cannot read {name}: {e}", file=sys.stderr)
             failed = True
             continue
-        rows = sections(text)
+        if p.suffix.lower() in TEX_EXTS:
+            lines, abstract_end, caption_lines = tex_lines(text)
+            prepared = "\n".join(lines)
+            rows = ([("whole file", count_words(prepared),
+                      "the whole file (requested with --section whole)")]
+                    if args.section == "whole"
+                    else sections(prepared, abstract_end=abstract_end,
+                                  caption_lines=caption_lines))
+        else:
+            rows = ([("whole file", count_words(text),
+                      "the whole file (requested with --section whole)")]
+                    if args.section == "whole" else sections(text))
         if (args.section in ("auto", "cover-letter")) and is_cover_letter(text, p.name):
             rows = [("cover letter", cover_letter_words(text),
                      f"persuading part only; the {COVER_LETTER_MIN}-{COVER_LETTER_MAX}-word range "
diff --git a/nbt-skills/prompts/identify_issues.prompt.md b/nbt-skills/prompts/identify_issues.prompt.md
index 9cbeafa..fb6701d 100644
--- a/nbt-skills/prompts/identify_issues.prompt.md
+++ b/nbt-skills/prompts/identify_issues.prompt.md
@@ -21,7 +21,7 @@ say where they went.
 
 ## Mission
 
-Diagnose, do not fix. Produce a findings report + artifacts that the revision skill (`nbt-revise`) can consume mechanically. Length rule (user-set, replaces the former blanket exemption): **the journal's abstract/main-text limits apply, relaxed by fixed margins** — for an NBT Article, abstract ≤ 150 words +15% (≤ 172) and main text ≤ 3,000 words +25% (≤ 3,750, excluding abstract, Methods, references and figure legends); another content type uses its own base numbers with the same margins. Words are maximal runs of non-space characters with a newline treated as space. Sweep **M19** reports over-cap sections as formatting findings; never cut content to meet a limit and never flag under-length text. All output in English.
+Diagnose, do not fix. Produce a findings report + artifacts that the revision skill (`nbt-revise`) can consume mechanically. Length rule (user-set, replaces the former blanket exemption): **the journal's abstract/main-text limits apply, relaxed by fixed margins** — for an NBT Article, abstract ≤ 150 words +15% (≤ 172) and main text ≤ 3,000 words +25% (≤ 3,750, excluding abstract, Methods, references and figure legends); another content type uses its own base numbers with the same margins. Words are maximal runs of non-space characters with a newline treated as space. Sweep **M19** reports over-cap sections as formatting findings; never cut content to meet a limit and never flag under-length text. Sweep **M18** always enumerates every figure legend's word count (the journal requires legends to respect the article type's limit but publishes no number; an optional proxy cap only changes the disposition). The cover letter's persuading part is measured against the master prompt's own **300-500-word preference** — NBT's official guidance states no cover-letter word limit (checked 2026-09-19) — and is a Minor formatting item, never a journal requirement. All output in English.
 
 Guidelines source: prefer a local copy of the author guidelines if present in the directory; otherwise the current Nature Biotechnology "Information for Authors" / Nature Portfolio author guide; **name the source/version you relied on in the summary.** Label every guideline-dependent finding `[required at initial submission]`, `[required at revised-submission stage — prepare now]`, or `[recommended]`. Nature Portfolio initial submissions are format-flexible: never present convenience conventions as blocking requirements.
 
@@ -34,7 +34,7 @@ A plain "review my manuscript" prompt reliably misses low-salience mechanical is
 1. **Identification only** — findings, never edits. Never modify any file in SUBMISSION_DIR.
 2. **Never invent.** Unresolvable value → status `unresolvable — manual verification required`. Guideline rule you cannot verify → `guideline-dependent`. Missing data → note a placeholder may be needed; never fabricate.
 3. **No silent skips.** Every check ID must end up in the coverage table with a real disposition (`N findings` / `clean — basis: <artifact/locations>` / `unable — <reason>`). "Not checked" is not an allowed value.
-4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY.** Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to M1–M17.
+4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths) and M19 (abstract/main-text length plus the cover-letter preference) always run with them.** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to a mechanical sweep.
 5. **One finding per instance.** "Several acronyms are undefined" is not a finding; each undefined acronym is its own finding with its own ID, quote, and location.
 6. **Sweep pattern for every mechanical check:** ENUMERATE (script preferred; scripts live in `WORK/`) → ARTIFACT (`OUT/artifacts/<ID>.md` for the M1/M2/M4–M17 tables; term/value occurrence enumerations are written to `WORK/occurrences_<slug>.md`, which is M8's artifact — pass `--out OUT/artifacts` if you prefer them alongside the others; every instance gets a row, including rows later judged OK; the artifact spans the whole corpus, not one file) → AUDIT (each row gets: a finding ID, `OK`, or `unable — <reason>`) → REPORT (findings derived only from artifact rows, never from general impression).
 7. **A sweep with zero findings is INVALID unless its artifact exists and every row is disposed.**
@@ -50,7 +50,7 @@ All stdlib-only Python, runnable anywhere Python 3.8+ exists. Copy them into `WO
 | `scripts/extract_citations.py` | M2: every call-out vs every reference entry; orphans, uncited, duplicates, order |
 | `scripts/extract_numbers.py` | M4: labeled metrics, accessions, versions; auto-flags same-label conflicts |
 | `scripts/extract_occurrences.py` | M8 term variants; also reused by nbt-revise for propagation. Writes `WORK/occurrences_<slug>.md` (multi-target runs get a hash suffix so runs cannot overwrite each other). `--term`, `--value` and `--variants-file` are repeatable, so every corrected number can be enumerated in one run: `--value 0.021 --value 0.031` |
-| `scripts/count_words.py` | M19: counts a document's abstract and main text with the pipeline's word rule (maximal runs of non-space characters, newline = space) and the relaxed caps; `--json` for the artifact rows and `--base-abstract`/`--base-main-text` for another content type |
+| `scripts/count_words.py` | M18/M19: counts a document's abstract, main text and cover letter with the pipeline's word rule (maximal runs of non-space characters, newline = space); reads `.tex`/`.ltx` sources (abstract environment, section headings, `\caption` lines) like the other formats; `--section cover-letter` counts the persuading part (salutation/signature/disclosures excluded) against the user's 300-500-word preference; `--json` for the artifact rows and `--base-abstract`/`--base-main-text` for another content type |
 
 If a script misses a case class (e.g., a citation style it can't parse), **extend it in `WORK/`** rather than falling back to eyeballing.
 
@@ -58,7 +58,7 @@ If a script misses a case class (e.g., a citation style it can't parse), **exten
 
 **Phase 1 — Setup.** Run `convert_corpus.py` on SUBMISSION_DIR. Review the inventory: role classification, editable vs read-only, conversion status. Every conversion failure is recorded, never skipped. Images are marked `visually unverifiable` unless OCR/VLM is available; when a renderer exists, render and LOOK. Zotero live fields: the converter marks them `[[FIELD: ...]]`; check the rendered text; an unreadable or incomplete field goes to the manual-verification list (tell the user to verify it in Word). Resolve citations READ-ONLY with `ZOT_CLI` / `$ZOTERO_SKILL` (parent bibliographic item keys, never attachment keys; confirm title, creators, year, DOI) and never write to the library: a suspected metadata error becomes a finding with the proposed correction.
 
-**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M19 (M18 only when the pipeline's caption suggestion is active) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in the appendix below — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.
+**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated) and M19 (abstract/main-text length plus the cover-letter preference) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in the appendix below — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.
 
 **Phase 3 — Discovery round.** D0–D5 per `references/discovery.md`: hunt issue classes OUTSIDE the checklist; outputs `OUT/round2/findings_extra.{md,json}` and `OUT/round2/new_sweeps.md`. If the user passes `discover` as the argument, run ONLY this phase against existing findings and stop.
 
@@ -71,7 +71,7 @@ Truncation silently drops exactly the tail-end mechanical findings, so append ea
 2. All sweep artifacts as titled appendix tables (or pointers to `OUT/artifacts/`).
 3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M19, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
 4. Per-document index of finding IDs.
-5. Coverage table: every check ID (M1–M17, J1–J4, plus M19 — and M18 when the caption suggestion is active) → `N findings` / `clean — basis` / `unable — <reason>`.
+5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts) and M19 (abstract/main-text/cover-letter lengths)) → `N findings` / `clean — basis` / `unable — <reason>`.
 6. Summary note: counts by category/severity; unresolved gaps; missing-citation issues; ambiguous context; unresolvable contradictions; the manual-verification list (incl. Zotero fields); guidelines source/version; items to re-check against the current author guide.
 
 `OUT/findings.json` (machine-readable, consumed by nbt-revise):
@@ -91,11 +91,11 @@ Truncation silently drops exactly the tail-end mechanical findings, so append ea
 - One sweep at a time; artifact complete before the next begins.
 - Prefer scripts over attention for all enumeration; judgment only classifies rows.
 - Long sessions: maintain `WORK/STATE.md` (current sweep, pending steps, open questions) so the workflow resumes without loss.
-- Grow the skill: after the discovery round, validate the proposals in `OUT/round2/new_sweeps.md` with the user and append them to `references/sweeps.md` as M18, M19… — the checklist converges toward exhaustiveness over successive runs instead of pretending to be exhaustive on day one. If the skill directory is read-only (common for an installed skill), do not fight it: keep the accepted text in `OUT/round2/new_sweeps.md` and hand the user the exact block to append.
+- Grow the skill: after the discovery round, validate the proposals in `OUT/round2/new_sweeps.md` with the user and append them to `references/sweeps.md` as M20, M21… (M18 and M19 are reserved by the pipeline — see `references/sweeps.md`) — the checklist converges toward exhaustiveness over successive runs instead of pretending to be exhaustive on day one. If the skill directory is read-only (common for an installed skill), do not fight it: keep the accepted text in `OUT/round2/new_sweeps.md` and hand the user the exact block to append.
 
 ## Acceptance checks (for the human, after the run)
 
-1. `findings.md` coverage table lists all 21 check IDs (M1–M17, J1–J4; plus M18+ once added).
+1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J4, M18 (legend counts) and M19 (abstract/main-text/cover-letter lengths), plus M20+ once proposals are adopted.
 2. Every sweep with findings has a matching artifact file in `review/artifacts/` (M8's occurrence enumerations live in `review/work/occurrences_*.md`). A sweep with findings but no artifact means it worked from impression — re-run that sweep.
 3. Each finding points to a specific word/number/phrase with a verbatim quote, not a whole passage.
 4. `findings.json` exists and every finding has all eight fields.
@@ -147,7 +147,7 @@ Every finding is ONE instance, formatted:
 
 ```
 F-NNN | location: <doc>/<section>/<paragraph|line|figure|table> | category: <0–5>
-check: <M1–M17|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
+check: <M1–M19|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
 evidence: "<short verbatim quote of the exact word/number/phrase>"
 problem: <1–2 sentence explanation>
 ```
diff --git a/nbt_pipeline.py b/nbt_pipeline.py
index 6850962..fa02f4d 100644
--- a/nbt_pipeline.py
+++ b/nbt_pipeline.py
@@ -381,8 +381,8 @@ CODE-SIDE CHECKS (in addition to what the prompts ask the agents to do)
                           impossible with a manual step. Reading a .docx is not
                           a visual inspection (text carries no layout).
     * review contract     submission_dir must resolve to base/, every check id
-                          M1-M17/J1-J4 (+M18 only when the caption suggestion is
-                          active) must carry a real coverage disposition,
+                          M1-M17/J1-J4 plus M18 and M19 (both always active)
+                          must carry a real coverage disposition,
                           review/artifacts/ must exist, finding ids must be
                           unique, and every prior-round finding must be carried
                           forward or recorded as gone.
@@ -765,7 +765,10 @@ CORPUS_EXCLUDE_TOP = ("work",)
 # One source of truth for "which files does each code-side scan read?".
 CAPTION_DOCX_EXTS = (".docx",)
 CAPTION_TEX_EXTS = (".tex", ".ltx")
-CAPTION_TEXT_EXTS = (".md", ".txt")
+# The same editable text formats the length scan reads (LENGTH_TEXT_EXTS): a
+# manuscript whose legends are counted as main text must also have them
+# enumerated, or M18 reports nothing for a document M19 measures.
+CAPTION_TEXT_EXTS = (".md", ".txt", ".markdown", ".rst")
 CAPTION_SOURCE_EXTS = CAPTION_DOCX_EXTS + CAPTION_TEX_EXTS + CAPTION_TEXT_EXTS
 # The placeholder diagnostic also looks at bibliography/data/prose tables.
 PLACEHOLDER_SOURCE_EXTS = CAPTION_SOURCE_EXTS + (".bib", ".csv", ".rtf")
@@ -1267,9 +1270,9 @@ M18_REVIEW_SWEEP_ON = """3. The PIPELINE-MANDATED caption sweep M18 (see the cap
    with its document, caption id, word count, and disposition (OK / over @@CAPTION_LIMIT@@ words ->
    finding id / over the SUGGESTED length but not compressible without losing content -> manual
    verification item), then audit the table row by row. Give M18 its own coverage row, exactly
-   like the skill's sweeps. This check is mandatory here even though it is not in
-   references/sweeps.md. An M18 row is a formatting-tier item and never makes a version
-   ineligible: the orchestrator reports caption lengths, it never gates on them.
+   like the skill's sweeps. This check is mandatory in every run (the skill's
+   references/sweeps.md defines the same sweep). An M18 row is a formatting-tier item and never
+   makes a version ineligible: the orchestrator reports caption lengths, it never gates on them.
    M18 is RESERVED by this pipeline for the caption sweep: if your discovery round proposes new
    sweeps, number them from M20 upwards in review/round2/new_sweeps.md. (The discovery guide says
    proposals start at M18, and this pipeline always reserves M18 for its caption sweep and M19 for
@@ -1281,8 +1284,8 @@ M18_REVIEW_SWEEP_REPORT = """3. The PIPELINE-MANDATED legend-length sweep M18 (s
    word count, and the disposition "recorded — the journal's per-type limit is not published;
    author to compare" (or a finding id when the legend is defective for an independent reason,
    for example it explains methods or is unclear). Give M18 its own coverage row, exactly like
-   the skill's sweeps. This check is mandatory here even though it is not in
-   references/sweeps.md, and it never makes a version ineligible: with no cap configured the
+   the skill's sweeps. This check is mandatory in every run (the skill's references/sweeps.md
+   defines the same sweep), and it never makes a version ineligible: with no cap configured the
    word count alone is not a defect, is never scored and is never "fixed" by cutting text.
    M18 is RESERVED by this pipeline for the legend sweep: if your discovery round proposes new
    sweeps, number them from M20 upwards in review/round2/new_sweeps.md (M18 and M19 are
@@ -1357,10 +1360,11 @@ M19_REVIEW_SWEEP = f"""3b. The PIPELINE-MANDATED length sweep M19 (see the lengt
    a newline is a space) and say in the artifact which text you counted as the main text (the
    abstract, Methods, references and figure legends are excluded, exactly as the journal excludes
    them). Give M19 its own coverage row, exactly like the skill's sweeps, and report every
-   over-cap section as a CATEGORY-4 (technical formatting) finding. M19 is mandatory here even
-   though it is not in references/sweeps.md, and it is NEVER a gate: an over-cap section never
-   makes a version ineligible. The cover-letter row adds a MINOR formatting finding only when the
-   persuading part falls outside the {M19_CAPS['cover letter']['min']}-{M19_CAPS['cover letter']['max']}-word user preference -- never as a journal
+   over-cap section as a CATEGORY-4 (technical formatting) finding. M19 is mandatory (the skill's
+   references/sweeps.md defines the same sweep as always-on) and it is NEVER a gate: an over-cap
+   section never makes a version ineligible. The cover-letter row adds a MINOR formatting finding
+   only when the persuading part falls outside the
+   {M19_CAPS['cover letter']['min']}-{M19_CAPS['cover letter']['max']}-word user preference -- never as a journal
    requirement, and never a reason to delete content."""
 M19_REVISE_RULE = f"""Abstract/main-text length (check id M19; see the length rule): bring EVERY over-cap abstract
      or main text within the cap (abstract <= {M19_CAPS['abstract']['cap']} words; main text <= {M19_CAPS['main text']['cap']} words for an NBT
@@ -2008,9 +2012,8 @@ Skill discipline that the orchestrator will check for:
   * No silent skips: every check ID M1-M17 and J1-J4 appears in the coverage table with a real
      disposition (N findings / clean — basis: <artifact> / unable — <reason>); M19 (the pipeline's
      abstract/main-text length sweep) ALWAYS appears there too, and M18 (the pipeline's caption
-     sweep) appears when the caption suggestion is active -- when it is not active, M18 need not
-     appear, but its number stays reserved for the pipeline. Number your discovery proposals from
-     M20 upwards.
+     sweep) ALWAYS appears as well: legends are always enumerated, and only its proxy cap is
+     optional. Number your discovery proposals from M20 upwards.
   * Never invent content, citations, numbers, or accession IDs. Anything unresolvable becomes
     "unresolvable — manual verification required" and is listed in the manual-verification list.
   * Findings are reported, never fixed: identification only.
@@ -4047,18 +4050,25 @@ def _tex_captions(text: str) -> list:
     return out
 
 
-def _caption_units(texts) -> list:
-    """(label, text) for paragraph-style captions (docx paragraphs)."""
+def _caption_units(texts, with_spans: bool = False) -> list:
+    """(label, text) -- or (label, text, start, end) -- for docx paragraph captions.
+
+    The paragraph index span is what lets the M19 subtraction stay inside the
+    main-text span: a legend that sits after the Methods heading is not part of
+    the text the main-text count is measuring, so subtracting it there would
+    under-report the main text.
+    """
     units = []
-    for t in texts:
+    for i, t in enumerate(texts):
         t = (t or "").strip()
         m = CAPTION_START_RE.match(t)
         if m:
-            units.append((f"Figure {m.group(1)}", t))
+            label = f"Figure {m.group(1)}"
+            units.append((label, t, i, i + 1) if with_spans else (label, t))
     return units
 
 
-def _caption_units_from_lines(lines) -> list:
+def _caption_units_from_lines(lines, with_spans: bool = False) -> list:
     """(label, text) for line-oriented captions (md/txt); continuation lines merged.
 
     A caption that wraps over several lines has to be counted in full: counting
@@ -4068,20 +4078,24 @@ def _caption_units_from_lines(lines) -> list:
     0 with further prose (that is usually the next paragraph; merging it made a
     short legend look far longer than it is). An INDENTED continuation is always
     kept, because indentation is how a wrapped legend usually continues.
+
+    In ``with_spans`` mode each unit carries its (start, end) line span, which
+    the M19 subtraction intersects with the main-text span.
     """
-    units, cur = [], None
-    for raw in lines:
+    units, cur, start = [], None, None
+    for idx, raw in enumerate(lines):
         line = (raw or "").strip()
         if not line:
             if cur:
-                units.append(cur)
+                units.append((cur[0], cur[1], start, idx) if with_spans else cur)
                 cur = None
             continue
         m = CAPTION_START_RE.match(line)
         if m:
             if cur:
-                units.append(cur)
+                units.append((cur[0], cur[1], start, idx) if with_spans else cur)
             cur = (f"Figure {m.group(1)}", line)
+            start = idx
             continue
         indented = bool(raw) and raw[:1].isspace()
         sentence_done = bool(re.search(r"[.!?]\s*$", cur[1])) if cur else False
@@ -4091,10 +4105,10 @@ def _caption_units_from_lines(lines) -> list:
             cur = (cur[0], cur[1] + " " + line)
             continue
         if cur:
-            units.append(cur)
+            units.append((cur[0], cur[1], start, idx) if with_spans else cur)
             cur = None
     if cur:
-        units.append(cur)
+        units.append((cur[0], cur[1], start, len(lines)) if with_spans else cur)
     return units
 
 
@@ -4286,7 +4300,8 @@ def caption_gate(info) -> tuple:
 #   * the abstract is counted only when an "Abstract" heading (or a LaTeX
 #     abstract environment) is found, and it ends at the abstract's own
 #     paragraph (blank-line boundary), a Keywords line, or the next heading --
-#     whichever comes first;
+#     whichever comes first. In a .tex source the abstract environment's own
+#     \end{abstract} is the boundary and wins over any blank line inside it;
 #   * a document is only counted as a manuscript when it has an Abstract heading
 #     or an Introduction/Main-text heading -- a supplementary table dump or a
 #     Methods-only file is skipped rather than counted as a "main text" it is
@@ -4300,8 +4315,10 @@ def caption_gate(info) -> tuple:
 #   * the main text runs from the end of the abstract (or from the start of the
 #     document when there is no abstract heading) to the first Methods /
 #     References / Figure-legends / Acknowledgements heading, minus the figure
-#     captions, and the row says which text was counted. When no end heading is
-#     found the count runs to the end of the document and the row says so.
+#     captions INSIDE that span (a legend after Methods is not part of the text
+#     the count already stopped at), and the row says which text was counted.
+#     When no end heading is found the count runs to the end of the document
+#     and the row says so.
 # Nothing here gates a version: over-cap rows are reported, never enforced.
 # ---------------------------------------------------------------------
 
@@ -4343,23 +4360,145 @@ LENGTH_COVER_DISCLOSURE_RE = re.compile(
     r"data availability|word counts?)\s*[:.\u2014\u2013-]", re.I)
 
 
-def _tex_length_lines(text: str) -> list:
-    """LaTeX source as heading/paragraph lines for the length scan."""
-    out = []
-    for raw in (text or "").splitlines():
+TEX_CAPTION_TOKEN_RE = re.compile(
+    r"\\caption(?:of)?\*?\s*(?:\{[^{}]*\}\s*)?(?:\[[^\]]*\]\s*)?\{")
+# LaTeX scaffolding the length scan must not count as prose: environment tokens
+# (\begin{document}, \end{figure}) and the arguments of setup/graphics commands
+# used to leak literal words ("document", "article", "fig1.pdf") into the
+# main-text count.
+TEX_ENV_TOKEN_RE = re.compile(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\[[^\]]*\])?")
+TEX_SCAFFOLD_RE = re.compile(
+    r"\\(?:documentclass|usepackage|RequirePackage|bibliography|bibliographystyle|"
+    r"includegraphics|includesvg|input|include|vspace|hspace|setlength|geometry|"
+    r"graphicspath|hypersetup|newcommand|renewcommand)\*?(?:\[[^\]]*\])?"
+    r"(?:\{[^{}]*\})*")
+
+
+def _tex_brace_delta(text: str) -> int:
+    """Unescaped ``{`` minus unescaped ``}`` in `text`."""
+    delta, esc = 0, False
+    for ch in text:
+        if esc:
+            esc = False
+        elif ch == "\\":
+            esc = True
+        elif ch == "{":
+            delta += 1
+        elif ch == "}":
+            delta -= 1
+    return delta
+
+
+def _tex_split_group(text: str):
+    """(inside, after) for the rest of a ``{...}`` group whose ``{`` was consumed.
+
+    `text` starts INSIDE the group (the caller matched up to and including the
+    opening brace), so the depth starts at 1; an unclosed group returns the
+    whole text as ``inside`` and an empty remainder.
+    """
+    depth, esc = 1, False
+    for i, ch in enumerate(text):
+        if esc:
+            esc = False
+        elif ch == "\\":
+            esc = True
+        elif ch == "{":
+            depth += 1
+        elif ch == "}":
+            depth -= 1
+            if depth == 0:
+                return text[:i], text[i + 1:]
+    return text, ""
+
+
+def _tex_line_text(line: str) -> str:
+    """Prose of one LaTeX line: environment tokens and command arguments gone."""
+    return _strip_latex(TEX_SCAFFOLD_RE.sub(" ", TEX_ENV_TOKEN_RE.sub(" ", line)))
+
+
+def _tex_length_scan(text: str):
+    """(lines, caption_spans, abstract_end) for a LaTeX source.
+
+    ``lines`` are the heading/paragraph lines the length scan works on. LaTeX
+    states two boundaries that plain text leaves implicit, so they are tracked
+    here instead of being guessed from blank lines:
+
+      * a ``\\caption``/``\\captionof`` group is a legend even though its text
+        carries no "Figure N" label (the label is generated at typesetting
+        time): its text becomes its own line, so the span-subtraction equals the
+        legend's word count and text sharing that source line still counts;
+      * ``\\end{abstract}`` ends the abstract, whatever paragraph breaks it
+        contains, and any text on the ``\\begin{abstract}`` line belongs to it
+        (a one-line abstract used to be replaced by the bare heading and lost).
+    """
+    out, captions, abstract_end = [], [], None
+    raw_lines = (text or "").splitlines()
+    i, n = 0, len(raw_lines)
+    while i < n:
+        raw = raw_lines[i]
+        i += 1
         line = re.sub(r"(?<!\\)%.*$", "", raw).strip()
         if re.match(r"\\begin\{abstract\}", line):
+            rest = re.sub(r"^\\begin\{abstract\}", "", line)
+            rest = re.sub(r"\\end\{abstract\}.*$", "", rest).strip()
             out.append("Abstract")
+            if rest:
+                out.append(_tex_line_text(rest))
+            if "\\end{abstract}" in line:
+                abstract_end = len(out)
             continue
         if re.match(r"\\end\{abstract\}", line):
+            abstract_end = len(out)
+            rest = re.sub(r"^\\end\{abstract\}", "", line).strip()
+            if rest:
+                out.append(_tex_line_text(rest))
             continue
-        m = re.match(r"\\(?:sub)*section\*?\{([^{}]*)\}", line)
-        out.append(m.group(1).strip() if m else _strip_latex(line))
-    return out
+        m = re.match(r"\\(?:sub)*section\*?(?:\[[^\]]*\])?\{([^{}]*)\}", line)
+        if m:
+            out.append(m.group(1).strip())
+            continue
+        cap = TEX_CAPTION_TOKEN_RE.search(line)
+        if cap:
+            # Text before the caption stays prose; the caption's own group
+            # (which may wrap over several source lines) becomes one line, so
+            # subtracting its span never removes a neighbouring word.
+            before = _tex_line_text(line[:cap.start()])
+            if before:
+                out.append(before)
+            group = line[cap.end():]
+            depth = 1 + _tex_brace_delta(group)
+            while depth > 0 and i < n:
+                nxt = re.sub(r"(?<!\\)%.*$", "", raw_lines[i]).strip()
+                i += 1
+                group = f"{group}\n{nxt}"
+                depth += _tex_brace_delta(nxt)
+            cap_text, after = _tex_split_group(group)
+            captions.append((len(out), len(out) + 1))
+            out.append(_strip_latex(cap_text))
+            after = _tex_line_text(after)
+            if after:
+                out.append(after)
+            continue
+        stripped = _tex_line_text(line)
+        if stripped:
+            out.append(stripped)
+    return out, captions, abstract_end
+
+
+def _tex_length_lines(text: str) -> list:
+    """LaTeX source as heading/paragraph lines for the length scan."""
+    return _tex_length_scan(text)[0]
+
 
+def _length_rows_for_lines(lines: list, doc: str, caption_spans=None,
+                           abstract_end: int = None) -> list:
+    """M19 rows (abstract and/or main text) for one document's text lines.
 
-def _length_rows_for_lines(lines: list, doc: str, caption_words: int = 0) -> list:
-    """M19 rows (abstract and/or main text) for one document's text lines."""
+    ``caption_spans`` are (start, end) line spans of the document's captions and
+    ``abstract_end`` an explicit end index (LaTeX's ``\\end{abstract}``); only
+    the captions inside the main-text span are subtracted, because only those
+    words are inside the text this row counts.
+    """
     limits = length_limits()
     n = len(lines)
 
@@ -4369,19 +4508,22 @@ def _length_rows_for_lines(lines: list, doc: str, caption_words: int = 0) -> lis
     abs_start = abs_end = None
     for i in range(n):
         if LENGTH_ABSTRACT_HEAD_RE.match(clean(lines[i])):
-            j = i + 1
-            seen_text = False
-            while j < n:
-                line = clean(lines[j])
-                if LENGTH_SECTION_BOUND_RE.match(line) or LENGTH_KEYWORDS_RE.match(line):
-                    break
-                if not line:
-                    if seen_text:
-                        break               # the abstract's paragraph ended
-                    j += 1                  # leading blanks right after the heading
-                    continue
-                seen_text = True
-                j += 1
+            if abstract_end is not None:
+                j = max(i + 1, min(int(abstract_end), n))
+            else:
+                j = i + 1
+                seen_text = False
+                while j < n:
+                    line = clean(lines[j])
+                    if LENGTH_SECTION_BOUND_RE.match(line) or LENGTH_KEYWORDS_RE.match(line):
+                        break
+                    if not line:
+                        if seen_text:
+                            break           # the abstract's paragraph ended
+                        j += 1              # leading blanks right after the heading
+                        continue
+                    seen_text = True
+                    j += 1
             abs_start, abs_end = i + 1, j
             break
     main_start = None
@@ -4414,7 +4556,11 @@ def _length_rows_for_lines(lines: list, doc: str, caption_words: int = 0) -> lis
             if not (LENGTH_SECTION_BOUND_RE.match(clean(ln))
                     or LENGTH_MAIN_START_RE.match(clean(ln))
                     or LENGTH_KEYWORDS_RE.match(clean(ln)))]
-    words = max(0, count_words(" ".join(body)) - max(0, int(caption_words)))
+    span_start = start or 0
+    caption_words = sum(count_caption_words(" ".join(lines[max(a, span_start):min(b, end)]))
+                        for a, b in (caption_spans or [])
+                        if a < end and b > span_start)
+    words = max(0, count_words(" ".join(body)) - caption_words)
     notes = []
     if abs_start is None:
         notes.append("no Abstract heading found; the count starts at the beginning of the document "
@@ -4469,7 +4615,12 @@ def _cover_letter_row(lines: list, doc: str) -> dict:
             "base": None, "relaxation": None, "cap": None,
             "min": COVER_LETTER_MIN_WORDS, "max": COVER_LETTER_MAX_WORDS,
             "within_preference": COVER_LETTER_MIN_WORDS <= words <= COVER_LETTER_MAX_WORDS,
-            "over_limit": words > COVER_LETTER_MAX_WORDS,
+            # NOT over_limit: the 300-500-word range is the user's preference,
+            # not a journal cap. Marking it over_limit put cover letters into
+            # the scan's cap-violation list and made `decide` warn about a
+            # "relaxed caps (cap None)" breach for a merely long letter.
+            "over_limit": False,
+            "over_preference": words > COVER_LETTER_MAX_WORDS,
             "under_preference": words < COVER_LETTER_MIN_WORDS,
             "source": COVER_LETTER_SOURCE,
             "note": (f"persuading part only (salutation, signature and required disclosures "
@@ -4501,29 +4652,29 @@ def scan_lengths_in_sources(sources: list) -> dict:
             if "supp" in p.name.lower():
                 skipped.append(doc)         # supplementary text is not under the article caps
                 continue
-            lines, caption_words = None, 0
+            lines, caption_spans, abstract_end = None, [], None
             if ext in LENGTH_DOCX_EXTS:
                 paras = _docx_paragraphs(p)
                 if paras is None:
                     unparsed.append(doc)
                     continue
                 lines = paras
-                caption_words = sum(count_caption_words(t) for _, t in _caption_units(paras))
+                caption_spans = [(a, b) for _, _, a, b
+                                 in _caption_units(paras, with_spans=True)]
             elif ext in LENGTH_TEX_EXTS:
                 try:
                     text = p.read_text(encoding="utf-8", errors="replace")
                 except OSError:
                     text = ""
-                lines = _tex_length_lines(text)
-                caption_words = sum(count_caption_words(c) for c in _tex_captions(text))
+                lines, caption_spans, abstract_end = _tex_length_scan(text)
             elif ext in LENGTH_TEXT_EXTS:
                 try:
                     text = p.read_text(encoding="utf-8", errors="replace")
                 except OSError:
                     text = ""
                 lines = text.splitlines()
-                caption_words = sum(count_caption_words(t)
-                                    for _, t in _caption_units_from_lines(lines))
+                caption_spans = [(a, b) for _, _, a, b
+                                 in _caption_units_from_lines(lines, with_spans=True)]
             elif ext in LENGTH_UNPARSED_EXTS:
                 unparsed.append(doc)
                 continue
@@ -4537,7 +4688,8 @@ def scan_lengths_in_sources(sources: list) -> dict:
                 docs.add(doc)
                 rows.append(_cover_letter_row(lines, doc))
                 continue
-            found = _length_rows_for_lines(lines, doc, caption_words=caption_words)
+            found = _length_rows_for_lines(lines, doc, caption_spans=caption_spans,
+                                           abstract_end=abstract_end)
             if not found:
                 skipped.append(doc)
                 continue

diff --git a/.nbt_test/test_design_audit_2026_0919.py b/.nbt_test/test_design_audit_2026_0919.py
new file mode 100755
index 0000000..f52371e
--- /dev/null
+++ b/.nbt_test/test_design_audit_2026_0919.py
@@ -0,0 +1,406 @@
+#!/usr/bin/env python3
+"""Design-audit regression suite (2026-09-19, potential-design-issue-report).
+
+Run:  python3 .nbt_test/test_design_audit_2026_0919.py
+
+Every check below failed on the tree that the audit reviewed (or, for the items
+already closed by the previous bug-audit round, is asserted here so the fix
+cannot regress). Covered surface, one section per confirmed defect:
+
+  * D1 LaTeX counting: count_words.py must read `.tex`/`.ltx` sources (abstract
+    environment, section headings, \\caption lines) instead of answering with a
+    markup-inclusive "whole file" row;
+  * D2 a one-line `\\begin{abstract} ... \\end{abstract}` must not be counted as
+    zero words (the text used to vanish from both implementations);
+  * D3 a multi-paragraph LaTeX abstract ends at `\\end{abstract}`, not at the
+    first blank line (paragraph 2 used to leak into the main-text count);
+  * D4 M19 caption subtraction must stay inside the main-text span: a legend
+    after Methods is not part of the text the count already excluded it from;
+  * D5 the cover-letter row is a user PREFERENCE, so it must not be reported as
+    an over-cap section (the decide warning named it as a cap breach, cap None);
+  * D6 M18 is mandatory in every caption state: the review prompt used to say
+    "M18 need not appear" while its own postcheck hard-fails without the row;
+  * D7 the standalone fallback prompt must carry the same check-ID contract as
+    SKILL.md / sweeps.md (M18+M19 always, proposals from M20, cover-letter mode);
+  * D8 caption dialects/extensions: `.markdown`/`.rst` manuscripts are length
+    scanned, so their legends must be enumerated too.
+
+`NBT_WS` retargets the suite at another copy of the tree.
+"""
+from __future__ import annotations
+
+import importlib.util
+import json
+import os
+import re
+import shutil
+import subprocess
+import sys
+import tempfile
+import zipfile
+from pathlib import Path
+
+WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
+spec = importlib.util.spec_from_file_location("nbt_design_audit", str(WS / "nbt_pipeline.py"))
+nb = importlib.util.module_from_spec(spec)
+sys.modules["nbt_design_audit"] = nb
+spec.loader.exec_module(nb)
+
+COUNT_WORDS = WS / "nbt-skills/nbt-review/scripts/count_words.py"
+FAILS = []
+TMPDIRS = []
+
+
+def check(name, cond, detail=""):
+    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
+    if not cond:
+        FAILS.append(name)
+
+
+def scratch(prefix: str) -> Path:
+    tmp = Path(tempfile.mkdtemp(prefix=prefix))
+    TMPDIRS.append(tmp)
+    return tmp
+
+
+def write(p: Path, data: str):
+    p.parent.mkdir(parents=True, exist_ok=True)
+    p.write_text(data, encoding="utf-8")
+
+
+def cleanup():
+    for tmp in TMPDIRS:
+        shutil.rmtree(tmp, ignore_errors=True)
+
+
+def make_docx(path: Path, paragraphs) -> None:
+    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
+    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
+           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
+           f'<w:body>{body}</w:body></w:document>')
+    with zipfile.ZipFile(path, "w") as z:
+        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
+        z.writestr("word/document.xml", xml)
+
+
+def scan_rows(tmp: Path, name: str) -> dict:
+    info = nb.scan_lengths_in_sources([(tmp, "", ())])
+    return {(r["document"], r["section"]): r for r in info["rows"] if r["document"] == name}
+
+
+def script_rows(path: Path, *args) -> list:
+    proc = subprocess.run([sys.executable, str(COUNT_WORDS), str(path), "--json"] + list(args),
+                          capture_output=True, text=True, timeout=300)
+    if proc.returncode != 0:
+        return []
+    return json.loads(proc.stdout)["rows"]
+
+
+# =====================================================================
+# D1-D3 -- the bundled M19 counter must read LaTeX
+# =====================================================================
+
+TEX_ONE_LINE = (
+    "\\documentclass{article}\n"
+    "\\begin{document}\n"
+    "\\begin{abstract} We show that the compact abstract survives the count. \\end{abstract}\n"
+    "\\section{Introduction}\n"
+    "This body has eight words in total.\n"
+    "\\end{document}\n"
+)
+TEX_ONE_LINE_ABSTRACT_WORDS = 9      # "We show that the compact abstract survives the count."
+TEX_ONE_LINE_MAIN_WORDS = 7          # "This body has eight words in total."
+
+
+def tex_multi_paragraph(abstract_words=50, para2_words=50, body_words=30) -> str:
+    para1 = " ".join(["alpha"] * abstract_words)
+    para2 = " ".join(["beta"] * para2_words)
+    body = " ".join(["gamma"] * body_words)
+    return ("\\documentclass{article}\n\\begin{document}\n"
+            f"\\begin{{abstract}}\n{para1}\n\n{para2}\n\\end{{abstract}}\n"
+            f"\\section{{Introduction}}\n{body}\n"
+            "\\end{document}\n")
+
+
+def test_latex_counting():
+    print()
+    print("== D1-D3: LaTeX sources are counted by the shared M19 rule ==")
+    tmp = scratch("nbt_de_tex_")
+    # D2: one-line abstract
+    write(tmp / "one-line.tex", TEX_ONE_LINE)
+    rows = scan_rows(tmp, "one-line.tex")
+    abs_row, main_row = rows.get(("one-line.tex", "abstract")), rows.get(("one-line.tex", "main text"))
+    check("D2 the pipeline counts a one-line LaTeX abstract",
+          abs_row is not None and abs_row["words"] == TEX_ONE_LINE_ABSTRACT_WORDS,
+          f"{abs_row and abs_row['words']} != {TEX_ONE_LINE_ABSTRACT_WORDS}")
+    check("D2 ... and keeps it out of the main text",
+          main_row is not None and main_row["words"] == TEX_ONE_LINE_MAIN_WORDS,
+          f"{main_row and main_row['words']} != {TEX_ONE_LINE_MAIN_WORDS}")
+    srows = {(r["section"]): r for r in script_rows(tmp / "one-line.tex")}
+    check("D1 count_words.py counts the one-line LaTeX abstract too",
+          srows.get("abstract", {}).get("words") == TEX_ONE_LINE_ABSTRACT_WORDS
+          and srows.get("main text", {}).get("words") == TEX_ONE_LINE_MAIN_WORDS,
+          str(srows))
+    check("D1 count_words.py reports a LaTeX manuscript shape, not 'whole file'",
+          "abstract" in srows and "whole file" not in srows, str(list(srows)))
+    # --section whole must answer with a whole-file row for every format: a
+    # shaped document used to filter its own rows away and print nothing.
+    wrows = [r for r in script_rows(tmp / "one-line.tex", "--section", "whole")
+             if r["section"] == "whole file"]
+    check("D1 --section whole on a .tex reports the whole file (18 counted words)",
+          len(wrows) == 1 and wrows[0]["words"] == 18, str(wrows))
+    write(tmp / "plain.md", "Abstract\n\n" + " ".join(["word"] * 12) + "\n")
+    wrows = [r for r in script_rows(tmp / "plain.md", "--section", "whole")
+             if r["section"] == "whole file"]
+    check("D1 --section whole on a shaped .md also reports the whole file",
+          len(wrows) == 1 and wrows[0]["words"] == 13, str(wrows))
+
+    # D3: multi-paragraph abstract
+    write(tmp / "two-para.tex", tex_multi_paragraph())
+    rows = scan_rows(tmp, "two-para.tex")
+    abs_row = rows.get(("two-para.tex", "abstract"))
+    main_row = rows.get(("two-para.tex", "main text"))
+    check("D3 the pipeline keeps a two-paragraph LaTeX abstract whole",
+          abs_row is not None and abs_row["words"] == 100,
+          f"{abs_row and abs_row['words']} != 100")
+    check("D3 ... and the main text starts after \\end{abstract}",
+          main_row is not None and main_row["words"] == 30,
+          f"{main_row and main_row['words']} != 30")
+    srows = {r["section"]: r for r in script_rows(tmp / "two-para.tex")}
+    check("D1/D3 count_words.py agrees with the pipeline on the same .tex",
+          srows.get("abstract", {}).get("words") == 100
+          and srows.get("main text", {}).get("words") == 30, str(srows))
+
+
+# =====================================================================
+# D4 -- caption subtraction stays inside the main-text span
+# =====================================================================
+
+def test_caption_span():
+    print()
+    print("== D4: M19 subtracts only the legends inside the main-text span ==")
+    tmp = scratch("nbt_de_cap_")
+    body = " ".join(["maintext"] * 20)
+    in_span = "Figure 1 | A legend with words in it here."
+    out_span = "Figure 2 | Another legend with different words here."
+    md = (f"Abstract\n\n{'abs ' * 10}\n\nIntroduction\n\n{body}\n\n{in_span}\n\n"
+          f"Methods\n\nx y z\n\n{out_span}\n")
+    write(tmp / "ms.md", md)
+    rows = scan_rows(tmp, "ms.md")
+    main_row = rows.get(("ms.md", "main text"))
+    # the 20-word body plus the in-span legend, minus that legend = 20; the
+    # legend after Methods is outside the span and must not be subtracted.
+    want = 20
+    check("D4 a .md legend after Methods is not subtracted from the main text",
+          main_row is not None and main_row["words"] == want,
+          f"{main_row and main_row['words']} != {want}")
+    srows = {r["section"]: r for r in script_rows(tmp / "ms.md", "--section", "main-text")}
+    check("D4 count_words.py agrees (both subtract only the in-span legend)",
+          srows.get("main text", {}).get("words") == want, str(srows))
+
+    make_docx(tmp / "ms.docx",
+              ["Abstract", "abs " * 10, "Introduction", body, in_span, "Methods", "x y z",
+               out_span])
+    rows = scan_rows(tmp, "ms.docx")
+    main_row = rows.get(("ms.docx", "main text"))
+    check("D4 a .docx legend after Methods is not subtracted from the main text",
+          main_row is not None and main_row["words"] == want,
+          f"{main_row and main_row['words']} != {want}")
+
+    # LaTeX: the legend is a \caption, and only the in-span one is subtracted
+    tex_head = ("\\begin{abstract}\n" + " ".join(["abs"] * 10) + "\n\\end{abstract}\n"
+                "\\section{Introduction}\n" + body + "\n")
+    write(tmp / "in.tex", tex_head
+          + "\\begin{figure}\n\\caption{A legend inside the main text span.}\n\\end{figure}\n"
+          + "\\section{Methods}\nWe worked.\n")
+    write(tmp / "out.tex", tex_head + "\\section{Methods}\nWe worked.\n"
+          + "\\begin{figure}\n\\caption{A legend after the methods heading.}\n\\end{figure}\n")
+    rows = scan_rows(tmp, "in.tex")
+    main_row = rows.get(("in.tex", "main text"))
+    check("D4 the .tex legend inside the span is subtracted",
+          main_row is not None and main_row["words"] == 20,
+          f"{main_row and main_row['words']} != 20")
+    rows = scan_rows(tmp, "out.tex")
+    main_row = rows.get(("out.tex", "main text"))
+    check("D4 the .tex legend after Methods is not subtracted",
+          main_row is not None and main_row["words"] == 20,
+          f"{main_row and main_row['words']} != 20")
+
+
+# =====================================================================
+# D5 -- the cover-letter preference is not a cap
+# =====================================================================
+
+def test_cover_letter_preference():
+    print()
+    print("== D5: the 300-500-word cover-letter range is a preference, not a cap ==")
+    tmp = scratch("nbt_de_cover_")
+    write(tmp / "cover-letter.md",
+          "Dear Editor,\n\n" + " ".join(["persuade"] * 600)
+          + "\n\nSincerely,\nA. Author\n")
+    info = nb.scan_lengths_in_sources([(tmp, "", ())])
+    row = [r for r in info["rows"] if r["section"] == "cover letter"][0]
+    check("D5 a long cover letter is surfaced as outside the preference",
+          row["within_preference"] is False and row.get("over_preference") is True, str(row))
+    check("D5 ... and not as an over-cap section",
+          row["over_limit"] is False, str(row))
+    check("D5 the scan's over_limit list carries no cover letter",
+          not any(r["section"] == "cover letter" for r in info["over_limit"]), str(info["over_limit"]))
+    srow = [r for r in script_rows(tmp / "cover-letter.md") if r["section"] == "cover letter"][0]
+    check("D5 the bundled script keeps the same semantics",
+          srow["over_limit"] is False and srow["within_preference"] is False, str(srow))
+    note = nb.length_note(info)
+    check("D5 the note still names the preference, not a cap breach",
+          "OUTSIDE-PREFERENCE" in note and "not an NBT limit" in note, note)
+
+
+# =====================================================================
+# D6 -- M18 is mandatory in the review contract (prompt == postcheck)
+# =====================================================================
+
+def test_m18_coverage_contract():
+    print()
+    print("== D6: the M18 coverage row is always required ==")
+    tmp = scratch("nbt_de_m18_")
+    sb = tmp / "runs" / "r1_a2_review"
+    write(sb / "base" / "ms.md", "text\n")
+    write(sb / "review" / "artifacts" / "M1_acronyms.md", "| row |\n|---|\n")
+    ctx = type("C", (), {"cfg": {}})()
+    cov = ([{"check": f"M{i}", "disposition": "clean -- basis: x"} for i in range(1, 18)]
+           + [{"check": f"J{i}", "disposition": "clean -- basis: x"} for i in range(1, 5)]
+           + [{"check": "M19", "disposition": "0 findings"}])
+    fj = {"submission_dir": "./base", "findings": [{"id": "F-001", "check": "M1"}],
+          "artifacts": {}, "coverage": cov}
+    errs, warns = [], []
+    nb.check_review_contract(ctx, sb, fj, errs, warns)
+    check("D6 a review without an M18 coverage row fails the contract",
+          any("M18" in e for e in errs), str(errs))
+
+    prompt = nb.review_prompt(tmp, "r1_review", 1)
+    flat = re.sub(r"\s+", " ", prompt)
+    check("D6 the no-cap review prompt no longer says M18 may be omitted",
+          "M18 need not appear" not in flat, flat[flat.find("M18 need not appear") - 120:][:200]
+          if "M18 need not appear" in flat else "")
+    check("D6 ... and it still demands M18's own coverage row",
+          "Give M18 its own coverage row" in flat)
+    check("D6 the prompt does not claim M18 is absent from references/sweeps.md",
+          "not in references/sweeps.md" not in flat)
+    check("D6 the header docstring matches the postcheck",
+          "M1-M17/J1-J4 (+M18 only when the caption" not in
+          (WS / "nbt_pipeline.py").read_text(encoding="utf-8"))
+
+
+# =====================================================================
+# D7 -- the standalone fallback prompt carries the same contract
+# =====================================================================
+
+def test_fallback_prompt_contract():
+    print()
+    print("== D7: identify_issues.prompt.md matches SKILL.md / sweeps.md ==")
+    prompt = (WS / "nbt-skills/prompts/identify_issues.prompt.md").read_text(encoding="utf-8")
+    skill = (WS / "nbt-skills/nbt-review/SKILL.md").read_text(encoding="utf-8")
+    sweeps = (WS / "nbt-skills/nbt-review/references/sweeps.md").read_text(encoding="utf-8")
+    check("D7 the fallback hard rule makes M18 and M19 mandatory",
+          "M1–M17 are EXHAUSTIVE and MANDATORY, and M18" in prompt, "")
+    check("D7 the fallback no longer defers M18 to 'when the caption suggestion is active'",
+          "M18 only when the pipeline's caption suggestion is active" not in prompt)
+    check("D7 the fallback acceptance check lists the 23 defined check IDs",
+          "all 21 check IDs" not in prompt
+          and "M1–M17, J1–J4, M18 (legend counts) and M19" in prompt)
+    check("D7 the fallback numbers discovery proposals from M20",
+          "as M18, M19" not in prompt and "M20" in prompt)
+    check("D7 the fallback documents the cover-letter counting mode",
+          "--section cover-letter" in prompt)
+    check("D7 SKILL.md's coverage table requires M18 in both caption states",
+          "plus M19 — and M18 when the caption suggestion is active" not in skill
+          and "M18 (legend counts) and M19" in skill)
+    check("D8 the sweeps FINDING FORMAT admits M18/M19 findings",
+          "check: <M1–M19|J1–J4>" in sweeps)
+
+
+# =====================================================================
+# D8 -- every length-scanned text format is enumerated for M18 too
+# =====================================================================
+
+def test_caption_extension_parity():
+    print()
+    print("== D8: caption enumeration covers every length-scanned text format ==")
+    tmp = scratch("nbt_de_ext_")
+    md = ("Introduction\n\n" + " ".join(["body"] * 30)
+          + "\n\nFigure 1 | A legend for the rst manuscript.\n\nMethods\n\nx\n")
+    write(tmp / "ms.markdown", md)
+    write(tmp / "ms.rst", md)
+    caps = nb.scan_captions_in_sources([(tmp, "", ())])
+    files = {c["document"] for c in caps["captions"]}
+    check("D8 a .markdown legend is enumerated",
+          any(f.endswith("ms.markdown") for f in files), str(sorted(files)))
+    check("D8 a .rst legend is enumerated",
+          any(f.endswith("ms.rst") for f in files), str(sorted(files)))
+    rows = scan_rows(tmp, "ms.rst")
+    main_row = rows.get(("ms.rst", "main text"))
+    check("D8 ... and its legend is not counted as main text",
+          main_row is not None and main_row["words"] == 30,
+          f"{main_row and main_row['words']} != 30")
+
+
+# =====================================================================
+# D9 -- a \caption group is subtracted exactly; neighbouring prose is not
+# =====================================================================
+
+def test_tex_caption_boundaries():
+    print()
+    print("== D9: LaTeX captions subtract their own words only ==")
+    tmp = scratch("nbt_de_texcap_")
+    body = " ".join(["maintext"] * 20)
+    head = ("\\begin{abstract}\n" + " ".join(["abs"] * 10) + "\n\\end{abstract}\n"
+            "\\section{Introduction}\n" + body + "\n")
+    tail = "\\section{Methods}\nWe worked.\n"
+    # A caption group sharing its line with trailing prose: the 4 prose words
+    # belong to the main text; the 2 caption words do not.
+    write(tmp / "mixed.tex",
+          head + "\\caption{A legend.} This sentence is prose.\n" + tail)
+    # The same, with the caption group wrapping over two source lines.
+    write(tmp / "wrapped.tex",
+          head + "\\caption{A legend that wraps over\ntwo source lines.} "
+                 "This sentence is prose.\n" + tail)
+    # An environment token sharing its line with prose contributes no word.
+    write(tmp / "env.tex", head + "\\begin{figure} See the four panels below.\n" + tail)
+    for name, want in (("mixed.tex", 24), ("wrapped.tex", 24), ("env.tex", 25)):
+        rows = scan_rows(tmp, name)
+        main_row = rows.get((name, "main text"))
+        check(f"D9 {name}: main text counts the prose, not the caption",
+              main_row is not None and main_row["words"] == want,
+              f"{main_row and main_row['words']} != {want}")
+        srows = {r["section"]: r for r in script_rows(tmp / name, "--section", "main-text")}
+        check(f"D9 {name}: count_words.py agrees",
+              srows.get("main text", {}).get("words") == want, str(srows))
+
+
+def main() -> int:
+    sections = (("latex", test_latex_counting),
+                ("caption-span", test_caption_span),
+                ("cover-letter", test_cover_letter_preference),
+                ("m18-contract", test_m18_coverage_contract),
+                ("fallback-prompt", test_fallback_prompt_contract),
+                ("caption-exts", test_caption_extension_parity),
+                ("tex-caption-boundaries", test_tex_caption_boundaries))
+    try:
+        for name, fn in sections:
+            try:
+                fn()
+            except Exception as e:                                  # noqa: BLE001
+                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
+    finally:
+        cleanup()
+    print()
+    if FAILS:
+        print(f"FAILED {len(FAILS)} check(s):")
+        for f in FAILS:
+            print(f"  - {f}")
+        return 1
+    print("all design-audit checks passed")
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())
```
