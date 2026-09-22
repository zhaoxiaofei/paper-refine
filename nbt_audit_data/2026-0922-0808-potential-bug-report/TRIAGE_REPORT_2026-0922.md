# Triage report — NBT pipeline design audit (2026-0922-0808)

Role: coding agent performing evidence-based bug/design triage and patching.
Tree: `/mnt/c/Users/zhaoxiaofei/Documents/my-nutstore/nbt-pipe` (git `7d19d80` + the
in-flight artifact-gate work described in §0.3). Scope: every text-format (non-binary) file
in this git repository. Method: read-only re-validation of every candidate against this
tree, minimal patches for confirmed defects only, failing-test-first, then a full in-scope
suite. The two `*LEDGER.md` files in the repo root and the relaxed word-limit enforcement
were explicitly excluded per the task instructions.

## 0. Inventory (S0)

### 0.1 Surfaces

| surface | sha256 (12) | bytes | what it is |
|---|---|---|---|
| `nbt_pipeline.py` | `fa1c9f5ef4e7` | 996371 | the round-based orchestrator: prompts, round DAG, judge contract, aggregation, selection, CLI, decision report |
| `nbt_docx_format.py` | `31ad8e301b67` | 150389 | the code-side OOXML scan/normalizer, the `tier_of` rule table, the fixer |
| `nbt_redlines_adapter.py` | `94d14a589b28` | 6653 | docxodus bridge for tracked-changes output |
| `docx2pdf.sh` | `752a30b95dd7` | 4015 | LibreOffice-based docx→pdf helper the prompts may use |
| `nbt-skills/nbt-review/**` | (tree) | — | the review skill: `SKILL.md`, `references/sweeps.md`, `references/discovery.md`, scripts |
| `nbt-skills/nbt-revise/**` | (tree) | — | the revision skill: `SKILL.md`, `references/edit_rules.md`, `references/ledger.md`, scripts |
| `nbt-skills/prompts/*.prompt.md` | (tree) | — | standalone prompt files with verbatim appendix copies of the reference docs |
| `nbt-skills/tests/*.py` | (tree) | — | the skill's own regression harness (incl. the appendix-sync and check-id numbering checks) |
| `.nbt_test/**` | (tree) | — | 31 end-to-end/unit suites, the stub agents and the fixture helper `xfix.py` |
| `README.md`, `mcp-docx-converter/**` | (tree) | — | operator documentation and the optional converter MCP server |

Full list (70 text files, 2,671,639 bytes) with sizes and sha256 is in §6.

### 0.2 How the surfaces are exercised

* `python nbt_pipeline.py {setup,run,run-decide,decide,status,retry,prune,redline} …` — the
  only production entry point; `setup` copies `nbt_pipeline.py` + `nbt_docx_format.py` into
  the root so a run is self-contained.
* `.nbt_test/test_*.py` — the regression suite (stub agents; `python3 .nbt_test/<test>.py`).
* `python3 nbt-skills/tests/{validate_skill,probe_regressions,probe_hardcases}.py
  --skill-root nbt-skills --run-dir <tmp>` — the skill harness (checks instruction/reference
  consistency, including the verbatim prompt-appendix sync).

### 0.3 Pre-existing in-flight work in the tree (NOT part of this triage)

The working tree already carried verified, uncommitted work from the earlier session on the
operator's live run: the markdown-table reader of the decision-artifact gate
(`markdown_table_report`, `_table_row`, `artifact_quality_notes`), the idempotent seed writer
(`_seed_write`), the stub-agent table filler, and their tests (`test_evidence_pack.py`,
`test_residual_audit_2026_0921.py`). Those hunks appear in the §7 diff; none of the verdicts
below depend on them.

## 1. Sources (S1)

All candidates come from one read-only audit delivered as a directory:

* `nbt_audit_data/2026-0922-0808-potential-bug-report/NBT_PIPELINE_DESIGN_ISSUES (1).md` —
  the full issue list (D1.1–D14, §7 residues, §8 redesign note). This is the source of
  record; every quoted line number was re-checked against this tree.
* `…/gmail--970ca9f8-…/NBT_Pipeline_Design_Audit.pdf` + cover/chart sources and
  `…/13552951474-…/NBT_Pipeline_Design_Audit_Report.pdf` — renderings of the same report
  (binary/HTML, no additional candidates).

Deduplication: the §7 table's residues (W-07, W-08, W-10, W-11, W-12) are aliases of
C17/C31/C06+C07/C20+C21/C04 and are not counted separately; §8 is one redesign proposal
(C34). The source's own "not a bug" notes were treated as hints, not verdicts.

## 2. Candidate ledger (S2–S4)

### C01 -- FMT-T8b prescribes the em-dash that M20 then discourages

* Sources: audit D1.1
* Surface: `nbt_docx_format.py:1637-1641` (`nested_parentheses_rows`), `nbt_pipeline.py` `M20_REVISE_RULE`
* Claim: the nested-paren fix text offers "comma or em dash", so the reviser inserts a dash that
  the em-dash density policy then flags — a two-cycle oscillator.
* Source suggestion: pick one dash/paren policy.
* Verdict: **FALSE_POSITIVE**
* Evidence: the fix text is `"move the inner item out (comma or em dash) or restructure the"`
  (`nbt_docx_format.py:1640-1641`), i.e. a comma is an equally prescribed option, and
  `FMT-T8b` is `editorial` (`_fix_kind`, not in `MECHANICAL_RULES`), so no code path inserts a
  dash. `M20_REVISE_RULE` ("rewrite parenthetical em-dashes as commas/parentheses") and the
  density cap are jointly satisfiable by choosing the comma; nothing in code chooses the dash.
* Patch: none.
* vs source suggestion: N/A (not the confirmed defect; the source's "one policy" change would
  delete a legitimate option).
* Attempts: 0/6
* Tests added/run: none (no defect to pin).
* Residual risk: an LLM may still prefer the dash; that is model behaviour, not a code defect.

### C02 -- The M20 dash/quote rows the skill calls "→ finding" were advisory in the scanner

* Sources: audit D1.2 (index line "FMT-P1 advisory in the scanner, finding in sweeps.md; auditor only attacks finding-tier")
* Surface: `nbt_docx_format.py:595-613` (`FINDING_TIER_RULES`, `tier_of`), consumed at
  `nbt_pipeline.py:6064` and `:11836` (M20 seed tier; stage regression scan)
* Claim: `FMT-P1` (em-dash density) is advisory in the code but a finding in the skill, so the
  reviewer can close it as "advisory — editorial preference only" and the auditor (which
  re-checks finding-tier rows only) never sees it.
* Source suggestion: align the scanner's tier with `sweeps.md`.
* Verdict: **CONFIRMED** and patched
* Evidence (pre-patch): `fmt.tier_of("FMT-P1") == "advisory"`, `fmt.tier_of("FMT-P2") ==
  "advisory"`, `fmt.tier_of("FMT-T1") == "finding"`, while `sweeps.md:637-639` says
  "mixed straight/curly quotation marks, a spaced hyphen used as a dash, or em-dash density
  above the user's cap → finding (editorial: the revision arm rewrites…)" and the pipeline's
  own M20 seed text calls "the editorial rows (em-dash density, quotation style,
  journal-italic policy) … findings for the revision/integration arms". The operator's real
  attempt-3 artifact shows the loophole in use: `| 2 | FMT-P1 | advisory | … | advisory — the
  row's own rule is advisory (not a finding tier); recorded in this run …`.
* Patch: added `FMT-P1` and `FMT-P2` to `FINDING_TIER_RULES` with a comment naming the skill
  sentence and the consequence (one sentence of the same skill rule covers both rules).
* vs source suggestion: MATCH (code aligned to the skill's explicit tier statement).
* Attempts: 1/6
* Tests added/run: `.nbt_test/test_docx_format.py::test_scan` gained "the M20 dash/quote rows
  the skill calls `→ finding` carry the finding tier" (failed pre-patch, passes post-patch);
  `test_docx_format.py`, `test_residual_audit_2026_0921.py`, `test_pipeline.py` and the full
  suite pass.
* Residual risk: the two rules now count as finding-tier families in
  `scan_regression_problems`, so a stage that introduces an em-dash flood (or the first spaced
  hyphen) where the input had none fails instead of warning — the strictness the skill asks
  for. Related same-class drift for `FMT-T6b`/`FMT-T6d`/`FMT-T2b`/`FMT-T3b`/`FMT-T7a`/`FMT-T7b`/
  `FMT-S5` is recorded in §4 (not patched: unreported and a wider strictness change).

### C03 -- L9 "make it flow" vs rewrite "report only" vs judge Q11 ±1

* Sources: audit D1.3
* Surface: `nbt_pipeline.py` `LANGUAGE_PASS_RULE` L9, `M20_REWRITE_RULE`, `WRITING_RUBRIC` Q11
* Claim: the rewrite arm is told not to fix M20 editorial rows while the language pass is
  told to make prose flow, and the judge can only score the difference ±1.
* Source suggestion: one dash policy for all roles.
* Verdict: **CANNOT_REPRODUCE**
* Evidence: the three texts exist as claimed, but there is no runtime harness for "which
  instruction an LLM weights more", and the ±1 cap is a documented, pre-registered design
  (`MINOR_ONLY_TIERS`). No code path contradicts another here; the claim is about model
  behaviour under competing prose.
* Patch: none.
* vs source suggestion: N/A
* Attempts: 0/6
* Tests added/run: none.
* Residual risk: a real-run measurement (judge sheets where the only difference is a dash)
  would be needed to promote this to a defect.

### C04 -- Writing-rubric Q1–Q3 (premise/logic) sit on the minor-only writing tier

* Sources: audit D1.4 (first half)
* Surface: `nbt_pipeline.py:11745-11766` (`WRITING_RUBRIC`), `BASIS_TIERS`, `TIER_CAPS`
* Claim: a factual contradiction (Q1) or a logic error (Q2/Q3) parked on `writing` is capped at
  ±1 while the skill files the same sentence as correctness.
* Source suggestion: move Q1–Q3 onto correctness.
* Verdict: **NOT_A_BUG**
* Evidence: the rubric opens "use it to justify every `writing`-tier row", i.e. it constrains
  what may be filed AS writing; a judge that finds a contradicted premise may still file it as
  `correctness` (uncapped) — `judge_basis_problems` accepts any `BASIS_TIERS` value and only
  requires the ledger arithmetic to match. No code forces a contradiction into `writing`.
* Patch: none.
* vs source suggestion: N/A (documented rubric scope).
* Attempts: 0/6
* Tests added/run: none.
* Residual risk: judges may read the rubric as exhaustive; the shared block's tier list is the
  operative vocabulary and already includes `correctness`.

### C05 -- Q12 (segmentation) has no L12 in the language pass

* Sources: audit D1.4 (second half)
* Surface: `nbt_pipeline.py:11758-11766` (`WRITING_RUBRIC`), `language_pass_report`
* Claim: the judge scores a 12th check the producers never run.
* Source suggestion: add L12 or drop Q12.
* Verdict: **FALSE_POSITIVE**
* Evidence: the rubric itself documents the asymmetry in the same paragraph: "Q1-Q11
  correspond one-to-one to the eleven checks of the language pass …; **Q12 is the segmentation
  check**, and a difference that cannot be named in this rubric is cosmetic". `language_pass_report`
  requires `L1..L11` by design. A judge may legitimately find a segmentation difference
  between two packages that no producer repaired; nothing claims Q12 is a producer check.
* Patch: none.
* vs source suggestion: N/A
* Attempts: 0/6
* Tests added/run: none.
* Residual risk: none identified.

### C06 -- Auditor drops are deleted from the list the reviser sees

* Sources: audit D2.1
* Surface: `nbt_pipeline.py:3092-3181` (`AUDIT_DIRECTIVES`), `apply_audit_to_findings`, `revise_prompt`
* Claim: a dropped `F-*` disappears for the reviser while a promoted `AU-*` appears — the
  auditor and reviewer run different agendas.
* Source suggestion: keep the reviewer's list authoritative.
* Verdict: **NOT_A_BUG**
* Evidence: this is the documented purpose of the stage ("disposes every frozen finding
  (confirm, or drop WITH evidence)"), the reviser prompt states the contract ("a dropped
  finding is NOT yours to re-litigate (re-opening one requires new evidence …); every `AU-*`
  finding is a normal finding you must resolve"), and every drop keeps its evidence in
  `audit/audit.json` so the human can re-open it. `revise → audit` plan wiring is asserted by
  `test_residual_audit_2026_0921.py`.
* Patch: none.
* vs source suggestion: N/A (source proposes a control-flow redesign).
* Attempts: 0/6
* Tests added/run: none.
* Residual risk: an auditor that over-drops is caught only by its own artifact-quality
  detectors; that is the designed check.

### C07 -- The judge's own scope sentence capped the frozen set below its own contract

* Sources: audit D2.2 + D9 (judge row)
* Surface: `nbt_pipeline.py` `JUDGE_DIRECTIVES` task 1 (`FROZEN SWEEP SET`), `PRIOR_ROUND_RULE`
* Claim: the judge is told to run "M1-M17 and J1-J4 ONLY" (+ an M18 clause) while contract v3
  requires a `checks` disposition for `JUDGE_COVERAGE_CHECKS` = M1-M17, M18-M24, J1-J4, and the
  same prompt's adopted-checks block lists M21–M24.
* Source suggestion: one checklist for judge and reviser.
* Verdict: **CONFIRMED** and patched
* Evidence (pre-render): `JUDGE_COVERAGE_CHECKS` contains M21–M24
  (`nbt_pipeline.py:10468-10469`); the rendered judge prompt's contract section lists "M1-M17,
  M18, M19, M20, M21, M22, M23, M24, J1-J4"; yet its task-1 sentence read
  "…mechanical sweeps M1-M17 and judgment passes J1-J4 ONLY, @@M18_JUDGE_SWEEP@@". A judge
  obeying the sentence cannot honestly fill the M21–M24 dispositions, and the same stale
  enumeration appeared in `PRIOR_ROUND_RULE` ("run the complete M1-M17 + J1-J4 set").
* Patch: task-1 sentence now reads "… judgment passes J1-J4, plus the adopted M18-M24 checks,
  …"; `PRIOR_ROUND_RULE` now adds "plus the pipeline-mandated M18-M24 checks (the caption check
  among them)". Text-only; no code path changed.
* vs source suggestion: MATCH (the pipeline's own contract is authoritative).
* Attempts: 1/6
* Tests added/run: `test_agent_consistency_2026_0922.py::test_judge_tier_and_sweep_scope`
  (new; failed pre-patch) plus the existing per-id checks; `test_redesign_v3.py`,
  `test_anonymized_judging.py`, `test_judge_blinding.py` pass.
* Residual risk: the judge now has four more sweeps in scope; they were already required in
  its `checks` map, so this costs no new contract.

### C08 -- The judge's PRIORITY ORDER omitted the `writing` tier

* Sources: audit D2.3
* Surface: `nbt_pipeline.py` `JUDGE_DIRECTIVES` priority order (`@@WRITING_RUBRIC@@` context)
* Claim: the order lists five tiers while the graded basis has six, and the rubric in the same
  prompt scores `writing` rows.
* Source suggestion: make the tier vocabulary one list.
* Verdict: **CONFIRMED** and patched
* Evidence: `BASIS_TIERS == ("correctness", "consistency", "preservation", "completeness",
  "formatting", "writing")` (`nbt_pipeline.py:1399-1400`) and contract v3 requires the `basis`
  of every score to be one of them, while the rendered priority line read
  "correctness  >  consistency  >  preservation  >  completeness  >  formatting" — a judge with
  a writing-only difference had no position in the order it is told to use for every comparison.
* Patch: the line now ends "> writing" and the following sentence names "formatting and writing
  (micro-formatting and wording rows, each capped at one point)".
* vs source suggestion: MATCH
* Attempts: 1/6
* Tests added/run: `test_judge_tier_and_sweep_scope` asserts every `BASIS_TIERS` member appears
  in the order, in order (failed pre-patch).
* Residual risk: none (documentation of an existing tier; caps unchanged).

### C09 -- Writing/formatting are capped at ±1

* Sources: audit D3.1
* Surface: `nbt_pipeline.py:1404-1413` (`TIER_CAPS`, `MINOR_ONLY_TIERS`), `judge_basis_problems`
* Claim: grammar can never decide a comparison.
* Source suggestion: drop the cap.
* Verdict: **NOT_A_BUG**
* Evidence: the cap is the documented measurement design ("minor-only, so it can separate two
  otherwise equal packages by at most one point"), it is pre-registered in `score_model_doc()`,
  and the seed/decision reports state it. Raising it would change the ranking function, i.e. a
  policy change, not a defect fix.
* Patch: none.
* vs source suggestion: N/A
* Attempts: 0/6
* Tests added/run: `test_redesign_v3.py` pins the cap and passes.
* Residual risk: the operator may still want a policy knob; that is a feature request.

### C10 -- Shared defects score 0 in a pairwise panel

* Sources: audit D3.2
* Surface: `aggregate_round` / judge prompt ("0 is a real and EXPECTED answer")
* Claim: a defect present in every member is invisible (both ledgers empty ⇒ 0).
* Source suggestion: give the judge the defect inventory and score its change.
* Verdict: **NOT_A_BUG**
* Evidence: relative scoring is the stated design ("pairwise", "relative-judgment panel"),
  documented in the judge prompt and `score_model_doc()`; the audit's fix is the §8 redesign
  (C34).
* Patch: none.
* Attempts: 0/6
* Residual risk: shared defects can persist; that is the documented limit of a relative panel.

### C11 -- J3 is optional and `unable` satisfies coverage

* Sources: audit D3.3
* Surface: `SKILL.md` hard rule 4, `judge_coverage_problems`, `JUDGE_DISPOSITIONS`
* Claim: a judge under token pressure skips J3 (the only grammar sweep) and still passes.
* Source suggestion: require a J3 artifact.
* Verdict: **NOT_A_BUG**
* Evidence: `SKILL.md` explicitly allows prioritizing judgment passes ("Only judgment passes
  J1–J4 may be prioritized") and contract v3 defines `unable` as a legitimate disposition that
  must state why (`JUDGE_DISPOSITIONS = ("clean", "findings", "unable")`). The code enforces
  that a disposition exists and is well-formed, not that it is "clean".
* Patch: none.
* Attempts: 0/6
* Residual risk: a judge can skip J3 honestly; the residual gate reports `unable` rows.

### C12 -- Judge private rule: "wording preferences that do not change meaning" are 0

* Sources: audit D3.4
* Surface: `nbt_pipeline.py:3849-3851` (judge directives), `SHARED_DECISION_BLOCK`, `WRITING_RUBRIC`
* Claim: the private rule zeroes the grammar/punctuation/flow rows the rubric and shared block
  count.
* Source suggestion: delete the private rule.
* Verdict: **FALSE_POSITIVE**
* Evidence: the private sentence is scoped to "Cosmetic-only differences (spacing, font choice,
  ordering of identical content, wording preferences that do not change meaning)" and the
  shared block defines the operative bar — "A difference that cannot be named in this
  vocabulary is COSMETIC" — while the rubric names the counted writing rows (Q1–Q12, including
  typography). Nothing in code zeroes a named row; `judge_basis_problems` accepts any
  ledger-backed score. The same prompt scores Q10–Q12 explicitly.
* Patch: none.
* vs source suggestion: N/A
* Attempts: 0/6
* Residual risk: prompt-level emphasis is a judgment call; no reproducible failure.

### C13 -- Overclaiming: J3 files it as correctness, Q7 as writing

* Sources: audit D3.5
* Surface: `sweeps.md` J3, `WRITING_RUBRIC` Q7
* Claim: two honest judges score the same overclaim differently.
* Source suggestion: one classification per construct.
* Verdict: **CANNOT_REPRODUCE**
* Evidence: both readings are defensible under the current vocabulary (hype is a correctness
  claim AND prose quality); no code contract is violated, and no runtime harness exists for
  judge interpretation. `judge_basis_problems` accepts either tier when the ledger supports it.
* Patch: none.
* Attempts: 0/6
* Residual risk: inter-judge variance on mixed constructs; the panel median absorbs single
  sheets, and the diagnostics report direction flips.

### C14 -- Default integrator mask includes `i1 = a1 ← (donors)`

* Sources: audit D4.1
* Surface: `DEFAULTS["integrators"] = [0xFFFFFFFF]`, `round_run_plan`, `integrate_prompt`
* Claim: integrating into the unrevised incumbent is expensive and biased toward it.
* Source suggestion: default mask should skip bit 0.
* Verdict: **NOT_A_BUG**
* Evidence: the pool model is documented ("EVERY fresh arm is a CANDIDATE on equal terms"; each
  pool member runs exactly one integration), and the control the audit asks for exists and is
  per-round (`setup --integrators 0xFFFFFFFE` skips bit 0; `--integrators 0` runs none). The
  class-(c)/(d) rules in `INTEGRATE_DIRECTIVES` are the documented porting policy, not an
  accident.
* Patch: none.
* Attempts: 0/6
* Residual risk: the default costs one integration session per round; the operator can change
  it per round.

### C15 -- Integrator class (d) freezes shared defects

* Sources: audit D4.2
* Surface: `INTEGRATE_DIRECTIVES` (c)/(d)
* Claim: a defect present in the base and in any donor is left untouched, so grammar/dashes
  survive every round.
* Source suggestion: forbid class (d).
* Verdict: **NOT_A_BUG**
* Evidence: the rule is explicit and purposeful ("d) a defect present in the base AND in at
  least one donor → LEAVE UNTOUCHED"), because a merge must not turn a shared property into a
  donor-specific change; `test_change_requests.py` asserts the ledger contract. Changing it is
  a policy redesign (C34).
* Patch: none.
* Attempts: 0/6
* Residual risk: known design limit, documented in the decision report.

### C16 -- Integrators receive no `review/`

* Sources: audit D4.3
* Surface: `INTEGRATE_DIRECTIVES` carve-out
* Claim: integrators port differences, not findings, so a repaired finding competes with a
  rewrite reorg under "prefer the base".
* Source suggestion: hand integrators the audited list.
* Verdict: **NOT_A_BUG**
* Evidence: the carve-out is explicit and reasoned in the prompt ("There is NO review/
  directory here … do NOT build an A1 ledger keyed to finding IDs"), and the revisit A2's
  repairs reach the integrator as diffs by design.
* Patch: none.
* Attempts: 0/6
* Residual risk: same as C15; the redesign in C34 would change it deliberately.

### C17 -- Regression scan fails only a NEW rule family

* Sources: audit D4.4 (residue W-07)
* Surface: `nbt_pipeline.py:11825-11856` (`scan_regression_problems`)
* Claim: growth *inside* an existing family is a warning, so a merge that adds more nested
  parens to a document that already had one still ships.
* Source suggestion: fail any in-family growth / counter-change artifact.
* Verdict: **NOT_A_BUG**
* Evidence: the function deliberately separates the two cases: a new family is an error
  ("introduces a NEW finding-tier defect family … fix it"), in-family growth is a warning
  ("rows grew X -> Y"), which keeps a legitimate repair of a few of many tolerated rows from
  failing a stage. Turning warnings into errors changes what the pipeline accepts (policy),
  not a broken contract.
* Patch: none.
* Attempts: 0/6
* Residual risk: a stage can add instances of an already-present family; the warning is
  recorded in the run record and decision report.

### C18 -- Language pass stops after two iterations

* Sources: audit D4.5
* Surface: `LANGUAGE_PASS_RULE`
* Claim: L9/L11 fight FMT-T8b/T9c inside two iterations, then freeze.
* Source suggestion: more iterations / a different operator.
* Verdict: **NOT_A_BUG**
* Evidence: the cap is written into the rule ("iterate at most TWICE, then stop and report")
  precisely to bound oscillation; the postcheck requires the L1–L11 coverage artifact, not a
  convergence proof.
* Patch: none.
* Attempts: 0/6
* Residual risk: documented; the reviewer/judge still see the surviving rows.

### C19 -- Incumbent lock in selection

* Sources: audit D4.6
* Surface: `select_champion` (base always eligible; exact tie keeps the base), `score_model_doc`
* Claim: hill-climbing with a trust region of radius 0 around A1.
* Source suggestion: rank on `vs_base` / a frozen test set.
* Verdict: **NOT_A_BUG**
* Evidence: the ranking key and the tie rule are pre-registered and documented
  (`score_model_doc()["tiebreaks"]`, "an exact tie on median, mean and IQR keeps the incumbent
  base"), and the anti-regression gate exists to prevent backwards steps; the audit's change is
  a redesign (C34).
* Patch: none.
* Attempts: 0/6
* Residual risk: a round may pin the base; that is the documented no-progress outcome and it
  is reported honestly.

### C20 -- Session mix: judging dominates and the known list is not an input

* Sources: audit D5.1
* Surface: `DEFAULTS`, `round_run_plan`, `materialize_judges`
* Claim: ~58 sessions, ~42 of them judges, and the panel re-derives what the review already
  found.
* Source suggestion: invert the session mix; score the changed inventory in code.
* Verdict: **NOT_A_BUG**
* Evidence: cost follows from the documented plan (M, N, K, judges, and the relative-judgment
  design); the counts quoted in the audit are consistent with the plan. (Its arithmetic claim
  about the *docstring* is C33, which was a real documentation defect and is patched.) The
  session-mix change is the §8 redesign.
* Patch: none.
* Attempts: 0/6
* Residual risk: wall-clock cost is the operator's main lever via `--judges`,
  `--rewrites`, `--revises`, `--integrators`.

### C21 -- Rewrites run before the review; round 2 forces a structural rewrite

* Sources: audit D5.2 (residue W-11)
* Surface: `round_run_plan`, `rewrite_level_of`
* Claim: rewrites cannot aim at `F-*`; the only consumer of the frozen list is the N=1 revise
  arm; with M=1 round 2 is structural-only.
* Source suggestion: review-then-rewrite, keep sentence-level search alive.
* Verdict: **NOT_A_BUG**
* Evidence: `rewrite_level_of` documents the deliberate level rule ("With a single rewrite arm
  the level is structural: organization is what a rewrite exists for") and the round plan is
  documented as "rewrites staged FIRST in every round, from the round's base". Scheduling and
  level choice are design; the operator can raise M to get a sentence arm back.
* Patch: none.
* Attempts: 0/6
* Residual risk: documented.

### C22 -- Fixed-length loop; `--stop-after-no-progress` defaults to 0

* Sources: audit D6.1
* Surface: `DEFAULTS`, `cmd_run` stop rule
* Claim: an extra round is paid even after a no-progress round.
* Source suggestion: default the stop rule to K=1.
* Verdict: **NOT_A_BUG**
* Evidence: the fixed length is the pre-registered design ("There is no early stop, no
  convergence test…"), while the opt-in adaptive stop exists (`--stop-after-no-progress K`,
  recorded in `decision.json` when it fires, asserted by `test_redesign_v3.py`). Changing the
  default is a policy decision.
* Patch: none.
* Attempts: 0/6
* Residual risk: an operator who wants the stop must pass the flag (or set it via
  `pipeline_config.json`).

### C23 -- Per-round statistics are documented as incomparable

* Sources: audit D6.2
* Surface: `score_model_doc()["cross_round_comparability"]`
* Claim: no learning curve across rounds.
* Source suggestion: reuse judges / a frozen test set.
* Verdict: **NOT_A_BUG**
* Evidence: the incomparability is stated up front with its causes (new panel, new field, new
  review) and the decision report prints only the paired statements it supports. Producing a
  comparable statistic is a new measurement design (C34).
* Patch: none.
* Attempts: 0/6
* Residual risk: none (documented limitation).

### C24 -- Tie-breaks are self-reported off the revise arm

* Sources: audit D6.3
* Surface: `candidate_tiebreak_inputs`
* Claim: an integrator that reports `writing_remaining: 0` beats an honest reviser on a median
  tie.
* Source suggestion: verify the self-reports for every arm.
* Verdict: **NOT_A_BUG**
* Evidence: the limitation is documented in the function's own docstring ("the frozen-review
  cross-check exists only for the arms that consume a `review/` directory …; a rewrite or
  integration self-report is unverified"), and those counts are the third/fourth tie-break
  keys after median, mean and IQR — an exact tie on the panel statistics is required before
  they are consulted.
* Patch: none.
* Attempts: 0/6
* Residual risk: verified in the decision report's caveat; a code-side cross-check is a
  follow-up feature.

### C25 -- `vs_base` is reported but not a ranking key

* Sources: audit D6.4
* Surface: `aggregate_round`, `select_champion`, `score_model_doc`
* Claim: the only paired statistic is unused.
* Source suggestion: rank on `vs_base`.
* Verdict: **NOT_A_BUG**
* Evidence: the exclusion is documented and reasoned ("its 2*judges directed scores are few
  enough that one outlier session flips the sign statistic, so the decision stays on the
  field-wide list"); the number is printed for the human. Changing the ranking key would change
  the pre-registered decision rule.
* Patch: none.
* Attempts: 0/6
* Residual risk: documented.

### C26 -- Judges are blind to the defect inventory

* Sources: audit D8
* Surface: `JUDGE_DIRECTIVES` blinding rule, `build_judge_view`
* Claim: blindness to provenance is extended to blindness to the round's finding list, so the
  panel re-discovers defects instead of scoring the repairs.
* Source suggestion: hand every judge the id-stripped audited list.
* Verdict: **NOT_A_BUG**
* Evidence: blinding is a deliberate anti-anchoring design ("BLINDING RULE … the judge gets NO
  orchestrator artifact"), enforced by `test_judge_blinding.py` and `test_evidence_pack.py`
  (a judge sandbox holds nothing but the blinded views + prompt). The audit's proposal is the
  §8 redesign.
* Patch: none.
* Attempts: 0/6
* Residual risk: documented; a provenance-free finding list would have to be designed and
  tested before it could replace the current rule.

### C27 -- Check-id contract drift across the skill, the fallback prompts and the postcheck

* Sources: audit D9 (and the review/skill rows of D2.2)
* Surface: `nbt-skills/nbt-review/SKILL.md`, `references/sweeps.md`, `references/discovery.md`,
  `nbt-skills/prompts/identify_issues.prompt.md`, `nbt-skills/nbt-revise/references/ledger.md`,
  `nbt_pipeline.py:10590-10596` (`check_review_contract`)
* Claim: three documents, three checklists: the postcheck requires M18–M24 coverage, the skill
  lists only M1–M17/J1–J4/M18–M20, `sweeps.md`'s FINDING FORMAT caps finding ids at M20, and
  the discovery round still numbers proposals from M21 (already adopted).
* Source suggestion: one list everywhere.
* Verdict: **CONFIRMED** and patched
* Evidence (runtime, pre-patch): a review sandbox whose coverage table follows the skill's own
  list fails the postcheck —
  `nb.check_review_contract(None, sb, fj, errs, warns)` with M1–M17,M18,M19,M20,J1–J4 returns
  `"review/findings.json coverage table is missing check id(s) ['M21', 'M22', 'M23', 'M24']"`.
  The skill lines were checked literally (`SKILL.md:75/99`, `sweeps.md:67`, and the same lists
  in the fallback prompt) and the skill's own harness (`validate_skill.py` D18/D10/D10b) was
  red on the pristine tree because of the same drift.
* Patch: the adopted M18–M24 set is now named in `SKILL.md` (hard rule 4, Phase 2, output item
  3, coverage table, acceptance list, "grow the skill"), in the fallback
  `identify_issues.prompt.md` (the same five lists), in `sweeps.md` (title, numbering line,
  `check: <M1–M24|J1–J4>`), in `discovery.md` (proposals now start at M25; example ids), and in
  the revise `ledger.md` check-id field; the two prompt appendices (which are verbatim copies
  of the reference docs) were re-synced mechanically; the harness pin
  `validate_skill.py` D18 and `.nbt_test/test_design_audit_2026_0919.py` D8 were updated to the
  new contract.
* vs source suggestion: MATCH (one list, sourced from the pipeline's required set).
* Attempts: 1/6
* Tests added/run: `test_agent_consistency_2026_0922.py::test_check_id_coverage` now proves the
  postcheck requirement at runtime and asserts the skill/fallback/format lists carry
  M21–M24; `validate_skill.py` (49 checks), `probe_regressions.py`, `probe_hardcases.py`,
  `test_acronym_longform.py` (E3 appendix sync), `test_design_audit_2026_0919.py` pass.
* Residual risk: the integrate directive still abbreviates the rescan set as "(M1-M17 + J1-J4)
  + M18 clause" (no coverage postcheck there); recorded in §4. The *installed* skill copy under
  `~/.codex/skills/nbt-skills-092203-7d19d80/` is a true pre-edit copy but lies outside this
  repository, so it is OUT_OF_SCOPE and must be refreshed by the operator for the agents to
  read the fixed text.

### C28 -- Rewrite prompt appends the full Phase 1+2 excerpts

* Sources: audit D10
* Surface: `rewrite_prompt` (`ATTACHED_HEAD + ATTACHED_PHASE1 + ATTACHED_PHASE2`), `REWRITE_TAIL`
* Claim: the attached master prompt says to run the complete review including D0–D5, while the
  rewrite directives say this is not a review.
* Source suggestion: attach only the style excerpts.
* Verdict: **NOT_A_BUG**
* Evidence: the same prompt's tail scopes the attachment ("excerpts above are attached only for
  their STYLE"), and the integrate stage already has an explicit carve-out; the claim is about
  which instruction an LLM follows (no runtime harness). No code path runs a review for a
  rewrite.
* Patch: none.
* Attempts: 0/6
* Residual risk: prompt-emphasis judgement call; a real-run observation would be needed.

### C29 -- The consistency suite contained a tautological assertion

* Sources: audit D11 (first half)
* Surface: `.nbt_test/test_agent_consistency_2026_0922.py` `test_check_id_coverage`
* Claim: `"M21" in nb.__dict__.get("__doc__", "") or True` can never fail.
* Source suggestion: delete the `or True`.
* Verdict: **CONFIRMED** and patched
* Evidence: `("M21" in "") or True` evaluates to `True`; the check reported `ok` for any tree.
* Patch: replaced with a real runtime proof: a review sandbox whose coverage table stops at
  M20 is run through `nb.check_review_contract`, and the check requires the resulting errors to
  name M21–M24 (plus the skill-list assertions of C27). The later source-grep check is kept.
* vs source suggestion: MATCH (stronger: runtime instead of a string grep).
* Attempts: 1/6
* Tests added/run: the suite fails pre-patch (6 checks red) and passes post-patch.
* Residual risk: none.

### C30 -- The consistency suite is presence-only

* Sources: audit D11 (second half)
* Surface: `test_shared_blocks_everywhere`, `test_role_applicable_blocks`
* Claim: the suite cannot detect private text contradicting the shared block.
* Source suggestion: make it fail on private contradictions.
* Verdict: **NOT_A_BUG**
* Evidence: the suite's docstring states its scope ("fails if any prompt loses a block or grows
  a private rule"), and the two concrete drifts it missed are now covered by C07/C08/C27's
  checks. A general contradiction detector for free prose is not a defect fix.
* Patch: none.
* Attempts: 0/6
* Residual risk: future private contradictions need a named check, as these got.

### C31 -- Length caps block wording fixes (W-08)

* Sources: audit D12 (residue W-08)
* Surface: `LENGTH_RULE`, `M19_*` directives, `scan_lengths_in_sources`
* Claim: a manuscript pinned at the relaxed cap cannot absorb a split sentence.
* Source suggestion: prefer ≤ cap−3 so the next edit has room.
* Verdict: **NOT_A_BUG**
* Evidence: the operator's instruction for this triage states the relaxed enforcement is
  intended; the code agrees (length is advisory, never a gate: `LENGTH_RULE`, the M19 rows are
  reported, and caption/length can never make a version ineligible).
* Patch: none.
* Attempts: 0/6
* Residual risk: none per the stated policy.

### C32 -- The review skill's default `SUBMISSION_DIR` is `./non-revised`

* Sources: audit D13
* Surface: `nbt-skills/nbt-review/SKILL.md` Paths, `REVIEW_DIRECTIVES`, `check_review_contract`
* Claim: an agent following the skill's default reviews the pristine original in round 2+
  while the postcheck demands `base/`.
* Source suggestion: make the skill's default track the pipeline's.
* Verdict: **NOT_A_BUG**
* Evidence: the standalone skill's default is its documented behaviour for direct use; the
  pipeline override is explicit in the review directives ("SUBMISSION_DIR = ./base") and is
  enforced by the postcheck, which reports the exact remedy ("Re-run the review with
  SUBMISSION_DIR=./base"). `test_residual_audit_2026_0921.py` exercises the override.
* Patch: none.
* Attempts: 0/6
* Residual risk: an agent that ignores an explicit directive is caught by the postcheck and
  the run is retried.

### C33 -- The module docstring's default round-1 field arithmetic was wrong

* Sources: audit D14 (and the arithmetic part of D5.1)
* Surface: `nbt_pipeline.py:5-8`, `:150-154`
* Claim: the docstring says the default round-1 field has 7 members and 36 directed scores,
  while the plan yields 8 and 42 (the `i1 = a1 ← (donors)` arm is a distinct member).
* Source suggestion: fix the header arithmetic.
* Verdict: **CONFIRMED** and patched
* Evidence: `round_pool_ids(2,1) = [a1, w1, w2, a2]` + `round_integrated_ids(2,1) = [i1..i4]`
  with `a1` deduplicating into the original gives 8 field members and `2*3*(8-1) = 42` scores;
  the docstring's own member list already enumerated all eight
  ("{original, w1, w2, a2, i1..i4}") while saying "7".
* Patch: the two places now read "field of 8 gives 42", "42 with the 8-member round-1 field"
  and "gives 8 members in round 1".
* vs source suggestion: MATCH
* Attempts: 1/6
* Tests added/run: `.nbt_test/test_change_requests.py::test_plan_and_ids` computes the default
  field from the code and asserts the docstring matches (failed pre-patch, passes post-patch).
* Residual risk: none (documentation).

### C34 -- §8 "what a coherent redesign would have to change" (8 proposals)

* Sources: audit §8
* Surface: cross-cutting (ranking key, integrator policy, judge inputs, session mix, stopping
  rule, test philosophy)
* Claim: the pipeline would converge better with one objective used by every role.
* Source suggestion: the eight numbered redesign steps.
* Verdict: **NOT_A_BUG**
* Evidence: these are policy redesigns, several of which require new data structures (a
  code-side score delta, a shared defect inventory handed to blinded judges, a reused panel).
  The task for this triage forbids refactoring, new features and drive-by policy changes, so
  none may be applied here; the two concrete sub-items with a reproducible defect are broken
  out as C02 (tier) and C33 (arithmetic) and patched.
* Patch: none.
* Attempts: 0/6
* Residual risk: recorded as the operator's design decision list, not as defects.

## 3. Integration verification (S5)

* New/updated tests, failing before their patch and passing after:
  * `test_docx_format.py` — finding tier of the M20 dash/quote family (C02).
  * `test_agent_consistency_2026_0922.py` — the runtime coverage-contract proof + the skill
    list checks (C27, C29), the judge scope sentence and priority order (C07, C08).
  * `test_change_requests.py` — the docstring arithmetic (C33).
* Full in-scope sweep, all exit 0 (34/34):
  * 31 `.nbt_test/test_*.py` suites (acronym, agent-consistency, anonymized-judging,
    arm-levels/language, audit-bugs, bug-audit-2026-0919, candidates 1+2, change-requests,
    decide-antiregression, design-audit-2026-0919, document-recovery, docx-converter,
    docx-format, evidence-pack, final-clean-version, fixes, grading-scheme, hash-cache,
    judge-blinding, length-limits, llm-stochastic-failures, only-rounds/integrators/judges,
    parallel-scheduling, pipeline, pipeline-audit-findings, redesign-v3, residual-audit-2026-0921,
    revision-token, stage-subset, zotero-integration);
  * `nbt-skills/tests/{validate_skill,probe_regressions,probe_hardcases}.py` — 49 checks,
    0 failed; 0 probe failures. `validate_skill.py` D10/D10b/D18 were RED on the pristine tree
    (baseline recorded) and are GREEN after the C27 sync.
* Confirmed repros re-run: the pre-patch failures of the eight new checks were captured in
  `/tmp/s5` logs during the run; no confirmed item is left unpatched.

## 4. Residual observations (not patched, not counted as unfixed confirmed bugs)

1. Same-class tier drift the source did not report: `sweeps.md`'s M20 prose marks
   `FMT-T2b`/`FMT-T3b`/`FMT-T6b`/`FMT-T6d`/`FMT-T7a`/`FMT-T7b`/`FMT-S5` as "→ finding" while
   `FINDING_TIER_RULES` keeps them advisory. Aligning the whole table would tighten the review
   bar and the stage regression scan well beyond the reported dash-family defect; recommend a
   separate, explicitly scoped change.
2. The integrate directive's rescan sentence still abbreviates the sweep set as
   "(M1-M17 + J1-J4)" + an M18 clause (`nbt_pipeline.py:3352-3358`). No coverage postcheck
   consumes it, so no hard failure was reproduced; the same patch pattern as C27 would apply.
3. The installed skill copy `~/.codex/skills/nbt-skills-092203-7d19d80/` is a true copy of the
   pre-edit files but outside this repository: OUT_OF_SCOPE. Refresh it so the agents read the
   fixed check lists.
4. Baseline flakiness: this mount intermittently raises read errors ("os error 5") and stale
   `git diff` object reads; the affected runs were retried and the object contents verified
   with `git cat-file` (SHA-1 intact). No test was left red.

## 5. Summary

```
Ingested:          34  (D1.1-D14 split into their distinct claims, + the §8 redesign note)
Confirmed:          6  C02, C07, C08, C27, C29, C33
Patched:            6  (all confirmed; no confirmed item left unfixed)
Unfixed:            -
FALSE_POSITIVE:     3  C01, C05, C12
CANNOT_REPRODUCE:   2  C03, C13
NOT_A_BUG:         23  C04, C06, C09, C10, C11, C14-C26, C28, C30, C31, C32, C34
OUT_OF_SCOPE:       0  candidates (1 follow-up: the installed skill copy, §4.3)
Process exit:       0  (S5 green; every in-scope CONFIRMED item patched with passing tests)
Exit reason:        S5 green
```

"Bug-free" here means exactly: every ingested candidate is classified; all six confirmed
in-scope defects are patched with a repro that failed before and passes after; the touched
surfaces' suites and the full in-scope sweep are green. It does not claim the product is
otherwise proven correct.

## 6. Inventory appendix (all in-scope text files)

70 text files, 2671639 bytes. sha256 truncated to 12 hex chars.

```
b2e5ec79a93a        394  .gitignore
80b3a10cc860      22945  .nbt_test/README.md
7e07a751a9ed      26693  .nbt_test/stub_agent.py
14d2fc01f135       4547  .nbt_test/stub_judge.py
5d4fd95703a0       4336  .nbt_test/stub_timed.py
47bbc8a47994      18394  .nbt_test/test_acronym_longform.py
84d6f138a0cb      19450  .nbt_test/test_agent_consistency_2026_0922.py
86012f7b0cb0      28577  .nbt_test/test_anonymized_judging.py
44a223a60eee      17503  .nbt_test/test_arm_levels_and_language_2026_0922.py
1d64e993d692      29444  .nbt_test/test_audit_bugs.py
642e657137c7      40092  .nbt_test/test_bug_audit_2026_0919.py
69c5344cf033      23013  .nbt_test/test_candidates.py
30fcb1dcfd0b      27398  .nbt_test/test_candidates2.py
5bb9ac7dbfc0      39979  .nbt_test/test_change_requests.py
952322ec2f37       9057  .nbt_test/test_decide_antiregression.py
08996bb67296      19894  .nbt_test/test_design_audit_2026_0919.py
80f77c676613      20553  .nbt_test/test_document_recovery.py
c480cf784126      18920  .nbt_test/test_docx_converter.py
31200f2c4b63      52236  .nbt_test/test_docx_format.py
d537de98b16e      19770  .nbt_test/test_evidence_pack.py
5e8630c3cd5c       6004  .nbt_test/test_final_clean_version.py
3a3a76a7a1b4      12769  .nbt_test/test_fixes.py
d5871506857b      25090  .nbt_test/test_grading_scheme.py
c57597c1ecc0      14650  .nbt_test/test_hash_cache.py
c6d6cae48147      22581  .nbt_test/test_judge_blinding.py
f02a8caf4b38      16952  .nbt_test/test_length_limits.py
7a1d0d795b28      24537  .nbt_test/test_llm_stochastic_failures.py
5c20a2c18361      13660  .nbt_test/test_only_rounds_integrators_judges.py
84248192d9c0      16996  .nbt_test/test_parallel_scheduling.py
bde4d2c51231      22925  .nbt_test/test_pipeline.py
c23e15b9d464      19533  .nbt_test/test_pipeline_audit_findings.py
6f90db01da74      15217  .nbt_test/test_redesign_v3.py
ddedd1439fd1      33295  .nbt_test/test_residual_audit_2026_0921.py
8195a1b9d508       8698  .nbt_test/test_revision_token.py
cde8e234eed9      10064  .nbt_test/test_stage_subset.py
c8020c64e604      16749  .nbt_test/test_zotero_integration.py
f83af22fc0e5       2340  .nbt_test/xfix.py
89b47b629325     149012  NBT_DESIGN_TRIAGE_LEDGER.md
086bdbb67fcc      47432  NBT_RESIDUAL_ISSUE_LEDGER.md
f1b845b0f7f1      48352  NBT_TRIAGE_LEDGER.md
258408f3b1b1      37613  README.md
752a30b95dd7       4015  docx2pdf.sh
64e75facced5       3947  mcp-docx-converter/index.js
74396a163f56      43339  mcp-docx-converter/package-lock.json
c941876391a1        426  mcp-docx-converter/package.json
c9964999f52d      16888  nbt-skills/CHANGELOG.md
dea61af0008f      14183  nbt-skills/README.md
33b53ccf983d      13937  nbt-skills/nbt-review/SKILL.md
0f55af459e8e       6900  nbt-skills/nbt-review/references/discovery.md
7ca05934298e      46902  nbt-skills/nbt-review/references/sweeps.md
50d5e40e0491      23441  nbt-skills/nbt-review/scripts/convert_corpus.py
f7b11050a061      18264  nbt-skills/nbt-review/scripts/count_words.py
16283b0782f1      50124  nbt-skills/nbt-review/scripts/extract_acronyms.py
fd319ff6d28c      16854  nbt-skills/nbt-review/scripts/extract_citations.py
917fe2004629      16025  nbt-skills/nbt-review/scripts/extract_numbers.py
733ecf53f504       9510  nbt-skills/nbt-review/scripts/extract_occurrences.py
4ce57e2fa445      13465  nbt-skills/nbt-revise/SKILL.md
586dcc73535d      18368  nbt-skills/nbt-revise/references/edit_rules.md
3442f76d90e2       6338  nbt-skills/nbt-revise/references/ledger.md
44b55af05145       6660  nbt-skills/nbt-revise/scripts/revision_token.py
2052016d4711      37698  nbt-skills/prompts/adress_issues.prompt.md
0bbd5a809fad      67819  nbt-skills/prompts/identify_issues.prompt.md
43bef81e1c73       5039  nbt-skills/tests/probe_hardcases.py
21e2509b97f1      17686  nbt-skills/tests/probe_regressions.py
e2044d69fd67      25241  nbt-skills/tests/validate_skill.py
dcffb1ef01f6      13883  nbt_audit_data/PIPELINE_AUDIT_FINDINGS.md
0324419ae6d4      13610  nbt_audit_data/repros/test_audit_findings_prepatch.py
31ad8e301b67     150389  nbt_docx_format.py
fa1c9f5ef4e7     996371  nbt_pipeline.py
94d14a589b28       6653  nbt_redlines_adapter.py
```

## 7. Diff of all in-scope changes (working tree vs HEAD)

Includes the pre-existing in-flight artifact-gate work described in §0.3; the
triage's own hunks are C02 (`nbt_docx_format.py` tier table), C07/C08/C33
(`nbt_pipeline.py` prompt texts + docstring), C27 (skill/fallback/reference
check-id lists + prompt-appendix sync + the two harness pins), C29 and the new
test checks (`.nbt_test/*`), and the C02/C33 tests.

```diff
=================== .nbt_test/stub_agent.py
--- /tmp/head_version.tmp	2026-09-22 08:44:19.737594505 +0800
+++ .nbt_test/stub_agent.py	2026-09-22 08:14:23.229031000 +0800
@@ -79,6 +79,44 @@
         z.writestr("word/document.xml", doc)
 
 
+def split_table_cells(text: str) -> list:
+    """Split one table line on its UNESCAPED pipes, KEEPING `\\|` inside a cell.
+
+    The pipeline escapes a literal pipe in a cell as `\\|` (figure captions carry
+    them: "Figure 1 \\| A legend here."), so a plain `str.split("|")` shifts every
+    later cell. That is exactly how the stub used to leave a seeded row
+    undisposed: the shift made the row look filled at the disposition index.
+    Escapes are kept verbatim (this reads for read-modify-write).
+    """
+    cells, cur, i = [], [], 0
+    while i < len(text):
+        ch = text[i]
+        if ch == "\\" and i + 1 < len(text):
+            cur.append(ch)
+            cur.append(text[i + 1])
+            i += 2
+            continue
+        if ch == "|":
+            cells.append("".join(cur))
+            cur = []
+            i += 1
+            continue
+        cur.append(ch)
+        i += 1
+    cells.append("".join(cur))
+    return [c.strip() for c in cells]
+
+
+def table_cells(line: str) -> list:
+    """The cells of one `| ... |` line, without its two delimiter pipes."""
+    s = line.strip()
+    if s.startswith("|"):
+        s = s[1:]
+    if s.endswith("|") and not s.endswith("\\|"):
+        s = s[:-1]
+    return split_table_cells(s)
+
+
 def fill_seeded_tables(dirp: Path) -> None:
     """Fill the seeded decision tables the way the strict policy expects.
 
@@ -100,7 +138,7 @@
         head_i = next((i for i, l in enumerate(lines) if l.strip().startswith("|")), None)
         if head_i is None:
             continue
-        header = [c.strip().lower() for c in lines[head_i].strip("|").split("|")]
+        header = [c.lower() for c in table_cells(lines[head_i])]
 
         def cell(cells, key, default=""):
             i = header.index(key) if key in header else None
@@ -111,11 +149,18 @@
             line = lines[j]
             if not line.strip().startswith("|"):
                 continue
-            cells = [c.strip() for c in line.strip("|").split("|")]
-            if all(set(c) <= set("-: ") for c in cells):
+            cells = table_cells(line)
+            if all("-" in c and set(c) <= set("-: ") for c in cells):
                 continue
             if len(cells) < len(header):
                 cells += [""] * (len(header) - len(cells))
+            elif len(cells) > len(header):
+                # A wider row would shift the disposition index: trim stray empty
+                # cells first, then read positionally like the pipeline does.
+                while len(cells) > len(header) and not cells[0]:
+                    cells = cells[1:]
+                while len(cells) > len(header) and not cells[-1]:
+                    cells = cells[:-1]
             row_no = j - head_i
             rule = cell(cells, "rule")
             reason = (f"OK — {rule or 'row ' + str(row_no)}: reviewed against its own bar "
=================== .nbt_test/test_agent_consistency_2026_0922.py
--- /tmp/head_version.tmp	2026-09-22 08:44:19.787594491 +0800
+++ .nbt_test/test_agent_consistency_2026_0922.py	2026-09-22 08:31:12.214900200 +0800
@@ -198,13 +198,78 @@
           set(stub_judge.JUDGE_CHECK_IDS) == set(expected)
           and set(stub_agent.JUDGE_CHECK_IDS) == set(expected),
           f"{len(stub_judge.JUDGE_CHECK_IDS)} vs {len(expected)}")
-    check("the review coverage contract requires M21-M24 too",
-          "M21" in nb.__dict__.get("__doc__", "") or True)  # constant check below
+    # The review postcheck requires M18-M24 coverage, so the SKILL the reviewer
+    # actually reads must list the same ids: a coverage table built from the
+    # skill's own list (M1-M17, J1-J4, M18-M20) fails the run with "coverage
+    # table is missing check id(s) ['M21', 'M22', 'M23', 'M24']". This check is
+    # the runtime proof of the contract (the old one was `... or True`, which
+    # could never fail).
+    tmp = scratch("nbt_cov_")
+    sb = tmp / "r1_review"
+    (sb / "base").mkdir(parents=True)
+    skill_ids = ([f"M{i}" for i in range(1, 18)] + ["M18", "M19", "M20"]
+                 + [f"J{i}" for i in range(1, 5)])
+    fj = {"submission_dir": "base",
+          "coverage": [{"check": c, "disposition": "clean -- basis: x"} for c in skill_ids]}
+    errs, warns = [], []
+    nb.check_review_contract(None, sb, fj, errs, warns)
+    check("the review postcheck really requires M21-M24",
+          any(all(c in e for c in ("M21", "M22", "M23", "M24")) for e in errs),
+          str(errs)[:160])
+    skill = (WS / "nbt-skills" / "nbt-review" / "SKILL.md").read_text(encoding="utf-8")
+    sweeps = (WS / "nbt-skills" / "nbt-review" / "references" / "sweeps.md").read_text(
+        encoding="utf-8")
+    coverage_line = next((l for l in skill.splitlines() if l.startswith("5. Coverage table")), "")
+    acceptance_line = next((l for l in skill.splitlines() if "coverage table lists every" in l), "")
+    format_line = next((l for l in sweeps.splitlines() if l.startswith("check:")), "")
+    check("SKILL.md's coverage table lists the adopted M21-M24",
+          "M21–M24" in coverage_line or all(c in coverage_line
+                                            for c in ("M21", "M22", "M23", "M24")),
+          coverage_line[:160])
+    check("SKILL.md's acceptance list no longer calls M21+ 'once adopted'",
+          ("M21–M24" in acceptance_line
+           or all(c in acceptance_line for c in ("M21", "M22", "M23", "M24")))
+          and "once proposals are adopted" not in acceptance_line, acceptance_line[:160])
+    check("sweeps.md's FINDING FORMAT admits M21-M24 finding ids",
+          "M1–M24" in format_line and "M1–M20|J1–J4" not in format_line,
+          format_line[:160])
     src = (WS / "nbt_pipeline.py").read_text(encoding="utf-8")
     check("the review postcheck's required-coverage list names M21-M24",
           'wanted += ["M21", "M22", "M23", "M24"]' in src)
 
 
+def test_judge_tier_and_sweep_scope():
+    """The comparison session's own directives must carry its own contract.
+
+    Contract v3 requires a disposition for every frozen check id M1-M17,
+    M18-M24, J1-J4, and the graded basis has six tiers -- but the directive's
+    task-1 sentence stopped the frozen set at M1-M17 (+M18-M20) "ONLY", and its
+    PRIORITY ORDER listed five tiers (no `writing`, the tier the WRITING RUBRIC
+    in the same prompt scores). A judge that obeys the sentence cannot honestly
+    fill the M21-M24 dispositions, and one that obeys the priority order has no
+    place for the writing rows.
+    """
+    print()
+    print("== the judge's scope sentence and priority order match its own contract ==")
+    jp = prompts()["judge"]
+    jl = jp.splitlines()
+    start = next((i for i, l in enumerate(jl) if "FROZEN SWEEP SET" in l), None)
+    # The sentence wraps across lines, and the ids may be written as a range
+    # ("M18-M24"), exactly like the skill's own "M1-M17".
+    frozen = " ".join(jl[start:start + 4]) if start is not None else ""
+    check("the frozen-set sentence names the adopted M21-M24",
+          "M18-M24" in frozen or "M21-M24" in frozen
+          or all(f"M{i}" in frozen for i in range(21, 25)), frozen[:200])
+    priority = next((l for l in jp.splitlines() if "correctness  >" in l), "")
+    positions = [priority.find(t) for t in nb.BASIS_TIERS]
+    check("the priority order lists every graded-basis tier, in order",
+          all(p >= 0 for p in positions) and positions == sorted(positions),
+          f"{priority.strip()[:120]} vs BASIS_TIERS={nb.BASIS_TIERS}")
+    check("the prior-round sweep rule names the adopted M18-M24 too",
+          all(c in nb.PRIOR_ROUND_RULE for c in ("M18", "M24")),
+          nb.PRIOR_ROUND_RULE[:160])
+
+
 def test_judge_blind_exception():
     print()
     print("== the one allowed asymmetry: the comparison session knows no provenance ==")
@@ -303,6 +368,7 @@
         test_role_applicable_blocks()
         test_cosmetic_rule_is_one_rule()
         test_check_id_coverage()
+        test_judge_tier_and_sweep_scope()
         test_judge_blind_exception()
         test_defaults_and_flags()
         test_residual_gating_split()
=================== .nbt_test/test_change_requests.py
--- /tmp/head_version.tmp	2026-09-22 08:44:19.827594481 +0800
+++ .nbt_test/test_change_requests.py	2026-09-22 08:26:21.907342900 +0800
@@ -102,6 +102,21 @@
           [nb.arm_of_vid(v) for v in ("a1", "w3", "a2", "a7", "i5")] ==
           ["base", "rewrite", "revise", "revise", "integrate"],
           str([nb.arm_of_vid(v) for v in ("a1", "w3", "a2", "a7", "i5")]))
+    # The module docstring's panel arithmetic must match the plan the default
+    # configuration builds: a1 deduplicates into the original, so round 1 has
+    # {original, w1, w2, a2, i1..i4} = 8 members and 2*3*(8-1) = 42 directed
+    # scores per version -- not "7 members" / 36 (D14 of the design audit).
+    default_field = (["orig"] + [v for v in nb.round_pool_ids(2, 1) if v != "a1"]
+                     + nb.round_integrated_ids(2, 1))
+    n_field, n_scores = len(default_field), 2 * nb.DEFAULTS["judges"][0] * (len(default_field) - 1)
+    doc = nb.__doc__ or ""
+    check("CR1a the module docstring's default round-1 field arithmetic matches the plan",
+          f"gives {n_field} members in round 1" in doc
+          and f"field of {n_field} gives {n_scores}" in doc
+          and f"{n_scores} with the {n_field}-member round-1" in doc,
+          f"plan={n_field} members / {n_scores} scores; "
+          f"docstring claims present: "
+          f"{[s for s in ('gives 7 members in round 1', 'field of 7 gives 36') if s in doc]}")
     check("CR1a there is no pairwise 'b*' arm any more",
           not nb.is_fresh_vid("b1") and not nb.is_fresh_vid("b2")
           and nb.arm_of_vid("b1") == "pinned",
=================== .nbt_test/test_design_audit_2026_0919.py
--- /tmp/head_version.tmp	2026-09-22 08:44:19.857594474 +0800
+++ .nbt_test/test_design_audit_2026_0919.py	2026-09-22 08:30:11.748145800 +0800
@@ -314,8 +314,8 @@
     check("D7 SKILL.md's coverage table requires M18/M19/M20 in every state",
           "plus M19 — and M18 when the caption suggestion is active" not in skill
           and "M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20" in skill)
-    check("D8 the sweeps FINDING FORMAT admits M18/M19/M20 findings",
-          "check: <M1–M20|J1–J4>" in sweeps)
+    check("D8 the sweeps FINDING FORMAT admits M18-M24 findings",
+          "check: <M1–M24|J1–J4>" in sweeps and "check: <M1–M20|J1–J4>" not in sweeps)
 
 
 # =====================================================================
=================== .nbt_test/test_docx_format.py
--- /tmp/head_version.tmp	2026-09-22 08:44:20.007594432 +0800
+++ .nbt_test/test_docx_format.py	2026-09-22 08:25:55.559810500 +0800
@@ -508,6 +508,18 @@
             ("FMT-T7b", "mixed URL/email treatment"),
             ("FMT-P1", "em-dash density")):
         check(f"scan detects {label} ({rule})", rule in got, f"got {sorted(got)}")
+    # sweeps.md's M20 sweep lists the dash/quote family as `→ finding`
+    # ("mixed straight/curly quotation marks, a spaced hyphen used as a dash, or
+    # em-dash density above the user's cap → finding"), and the pipeline's own
+    # M20 seed text calls the em-dash density an editorial row that is a finding
+    # for the revision/integration arms. The tier column must say so, or a
+    # reviewer can close the row as "advisory -- editorial preference only" and
+    # the auditor (which attacks finding-tier rows) never sees it.
+    check("the M20 dash/quote rows the skill calls `→ finding` carry the finding tier",
+          fmt.tier_of("FMT-P1") == "finding" and fmt.tier_of("FMT-P2") == "finding"
+          and fmt.tier_of("FMT-T1") == "finding",
+          f"FMT-P1={fmt.tier_of('FMT-P1')} FMT-P2={fmt.tier_of('FMT-P2')} "
+          f"FMT-T1={fmt.tier_of('FMT-T1')}")
     protected = [r for r in info["rows"] if r["rule"] == "FMT-T6b"]
     check("the italic 'et al.' inside the Zotero field is field-protected",
           protected and all(r["protected"] and r["fix"] == "style-field" for r in protected),
=================== .nbt_test/test_evidence_pack.py
--- /tmp/head_version.tmp	2026-09-22 08:44:20.177594388 +0800
+++ .nbt_test/test_evidence_pack.py	2026-09-22 08:12:56.029807700 +0800
@@ -160,6 +160,38 @@
               f"{sorted(str(p.relative_to(sb)) for p in written - seeded)}")
 
 
+def test_seeded_tables_survive_a_re_materialization():
+    """Re-materializing a sandbox must not overwrite what the session wrote.
+
+    `run` re-materializes a failed (or dirty) run whose completion marker still
+    exists so its postcheck can be re-evaluated -- that is how a FIXED gate
+    adopts a finished session instead of paying for it again. The seeded tables
+    are the files the session disposes IN PLACE, so re-seeding them wiped the
+    verdicts: on the real 2026-09-22 root a complete 212-row M20 sweep came back
+    as 212 empty cells and the session could never be adopted.
+    """
+    print()
+    print("== a session's disposed artifacts survive a re-materialization ==")
+    tmp = scratch("nbt_ev_reseed_")
+    corpus = tmp / "corpus"
+    make_text_corpus(corpus)
+    ctx = type("C", (), {"cfg": {"placeholder_lookup": "off"}})()
+    sb = tmp / "run_review"
+    sb.mkdir()
+    nb.seed_evidence_pack(ctx, sb, corpus, "review")
+    m20 = sb / "review" / "artifacts" / "M20_formatting.md"
+    m20.write_text("# M20\n\n| # | rule | disposition |\n|---|---|---|\n"
+                   "| 1 | FMT-T1 | OK — disposed by the session |\n", encoding="utf-8")
+    deleted = sb / "review" / "artifacts" / "M18_caption_words.md"
+    deleted.unlink()
+    nb.seed_evidence_pack(ctx, sb, corpus, "review")
+    check("the session's edited table is NOT overwritten",
+          "disposed by the session" in m20.read_text(encoding="utf-8"),
+          m20.read_text(encoding="utf-8")[:120])
+    check("a missing seeded table is still (re)created",
+          deleted.is_file() and "| disposition |" in deleted.read_text(encoding="utf-8"))
+
+
 def test_prompts():
     print()
     print("== every prompt carries the evidence-pack block ==")
@@ -344,6 +376,7 @@
 def main() -> int:
     try:
         test_seeding_layouts()
+        test_seeded_tables_survive_a_re_materialization()
         test_prompts()
         test_pack_scans_the_corpus_not_the_scratch()
         test_stub_round_sessions()
=================== .nbt_test/test_residual_audit_2026_0921.py
--- /tmp/head_version.tmp	2026-09-22 08:44:20.227594374 +0800
+++ .nbt_test/test_residual_audit_2026_0921.py	2026-09-22 08:15:23.667913400 +0800
@@ -327,6 +327,72 @@
           len(probs) == 1 and "EMPTY" in probs[0], str(probs))
 
 
+def test_delivered_table_shapes():
+    """The table shapes real review sessions deliver (2026-09-22 real root).
+
+    A complete 2-round review failed three 30-minute attempts in a row on
+    "EMPTY disposition cell" messages that were the PARSER's fault: a session
+    that appends its verdict after the seeded empty cell, a session that adds a
+    second table (the M20 "classes the scan cannot see"), an escaped `\\|` inside
+    a caption, and a stray leading empty cell each made the row wider than its
+    header, and the positional zip() then read the disposition from the wrong
+    column (or read the second table's rows against the first table's header).
+    """
+    print()
+    print("== delivered table shapes: appended verdicts, added tables, escaped pipes ==")
+    tmp = scratch("nbt_shapes_")
+    art = tmp / "artifacts"
+    art.mkdir()
+    # (a) verdict APPENDED after the seeded empty disposition cell
+    (art / "M20_formatting.md").write_text(
+        "| # | rule | severity | disposition |\n|---|---|---|---|\n"
+        "| 1 | FMT-T1 | medium |  | OK — FMT-T1: covered by finding F-001 |\n"
+        "| 2 | FMT-T9c | low |  | unable — no rule recorded for this row |\n",
+        encoding="utf-8")
+    # (b) a SECOND table with its own columns (the added "classes the scan cannot see")
+    (art / "M19_length.md").write_text(
+        "| # | section | words | disposition |\n|---|---|---|---|\n"
+        "| 1 | abstract | 150 | OK — inside the 172-word cap |\n\n"
+        "## Rows added from the manual pass\n\n"
+        "| # | check | disposition |\n|---|---|---|\n"
+        "| A1 | cover letter | OK — 400 words, inside the 300-500 preference |\n",
+        encoding="utf-8")
+    # (c) an escaped pipe inside a caption cell + a stray leading empty cell
+    (art / "M18_caption_words.md").write_text(
+        "| # | document | caption | disposition |\n|---|---|---|---|\n"
+        "| | 1 | main.docx | Fig. 1 \\| Benchmarking | OK — 134 words, recorded |\n",
+        encoding="utf-8")
+    rows = nb.parse_markdown_table(art / "M20_formatting.md")
+    check("an appended verdict is read as the disposition (not dropped by zip)",
+          [r.get("disposition") for r in rows]
+          == ["OK — FMT-T1: covered by finding F-001",
+              "unable — no rule recorded for this row"], str(rows))
+    check("dispositioned appended rows are no longer an EMPTY problem",
+          not nb.disposition_artifact_problems(rows))
+    notes = nb.artifact_quality_notes(tmp)
+    check("the appended-cell shape is reported as a WARNING, never a failed run",
+          "one more cell" in (notes.get("artifacts/M20_formatting.md") or [""])[0],
+          str(notes))
+    check("a second table is parsed against ITS OWN header",
+          [r.get("disposition") for r in
+           nb.parse_markdown_table(art / "M19_length.md")] == ["OK — inside the 172-word cap"],
+          str(nb.parse_markdown_table(art / "M19_length.md")))
+    check("both tables of a file are checked for dispositions",
+          nb.artifact_quality_report(tmp) == {}, str(nb.artifact_quality_report(tmp)))
+    m18 = nb.parse_markdown_table(art / "M18_caption_words.md")
+    check("an escaped pipe stays inside its cell and the stray empty cell is dropped",
+          m18[0]["caption"] == "Fig. 1 | Benchmarking"
+          and m18[0]["disposition"] == "OK — 134 words, recorded", str(m18))
+    # (d) the gate still fails what it is FOR: an undisposed row and a shifted row
+    (art / "OUTLINE.md").write_text(
+        "| # | heading | summary | disposition |\n|---|---|---|---|\n"
+        "| 1 | Introduction | Four-step benchmark workflow |  |\n",
+        encoding="utf-8")
+    report = nb.artifact_quality_report(tmp)
+    check("a genuinely empty disposition cell is still a problem",
+          any("EMPTY" in p for p in report.get("artifacts/OUTLINE.md") or []), str(report))
+
+
 # ---------------------------------------------------------------------------
 # 4. the auditor stage: artifact contract, drop/add split, plan wiring
 # ---------------------------------------------------------------------------
@@ -531,6 +597,7 @@
         test_gene_symbol_ledger()
         test_disposition_detectors()
         test_markdown_table_roundtrip()
+        test_delivered_table_shapes()
         test_audit_contract()
         test_audit_plan_wiring()
         test_collect_residuals()
=================== nbt-skills/nbt-review/SKILL.md
--- /tmp/head_version.tmp	2026-09-22 08:44:20.437594319 +0800
+++ nbt-skills/nbt-review/SKILL.md	2026-09-22 08:34:14.816842100 +0800
@@ -35,7 +35,7 @@
 1. **Identification only** — findings, never edits. Never modify any file in SUBMISSION_DIR.
 2. **Never invent.** Unresolvable value → status `unresolvable — manual verification required`. Guideline rule you cannot verify → `guideline-dependent`. Missing data → note a placeholder may be needed; never fabricate.
 3. **No silent skips.** Every check ID must end up in the coverage table with a real disposition (`N findings` / `clean — basis: <artifact/locations>` / `unable — <reason>`). "Not checked" is not an allowed value.
-4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan) always run with them.** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to a mechanical sweep.
+4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan) always run with them, together with the adopted sweeps M21–M24 (correspondence policy, data/code-availability integrity, supplementary parity, concept/term families).** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to a mechanical sweep.
 5. **One finding per instance.** "Several acronyms are undefined" is not a finding; each undefined acronym is its own finding with its own ID, quote, and location.
 6. **Sweep pattern for every mechanical check:** ENUMERATE (script preferred; scripts live in `WORK/`) → ARTIFACT (`OUT/artifacts/<ID>.md` for the M1/M2/M4–M17 tables; term/value occurrence enumerations are written to `WORK/occurrences_<slug>.md`, which is M8's artifact — pass `--out OUT/artifacts` if you prefer them alongside the others; every instance gets a row, including rows later judged OK; the artifact spans the whole corpus, not one file) → AUDIT (each row gets: a finding ID, `OK`, or `unable — <reason>`) → REPORT (findings derived only from artifact rows, never from general impression).
 7. **A sweep with zero findings is INVALID unless its artifact exists and every row is disposed.**
@@ -59,7 +59,7 @@
 
 **Phase 1 — Setup.** Run `convert_corpus.py` on SUBMISSION_DIR. Review the inventory: role classification, editable vs read-only, conversion status. Every conversion failure is recorded, never skipped. Images are marked `visually unverifiable` unless OCR/VLM is available; when a PDF/Word renderer exists, render them and LOOK instead of marking them unverifiable. Zotero live fields: the converter marks them `[[FIELD: ...]]`; check the rendered text; an unreadable or incomplete field goes to the manual-verification list (tell the user to verify it in Word). Resolve citations READ-ONLY with `ZOT_CLI` / `$ZOTERO_SKILL` / `$zotero-use` (parent bibliographic item keys, never attachment keys; confirm title, creators, year, DOI; `zot fulltext get` for the abstract/full text). This skill never edits a field and never writes to the library: a suspected metadata error becomes a finding with the proposed correction for nbt-revise or the user to apply under their Zotero policy.
 
-**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity; the pipeline seeds `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md`, and every row must be disposed) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in `references/sweeps.md` — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.
+**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity; the pipeline seeds `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md`, and every row must be disposed), the adopted sweeps M21–M24 (see `references/sweeps.md` §M21–M24) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in `references/sweeps.md` — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.
 
 **Phase 3 — Discovery round.** D0–D5 per `references/discovery.md`: hunt issue classes OUTSIDE the checklist; outputs `OUT/round2/findings_extra.{md,json}` and `OUT/round2/new_sweeps.md`. If the user passes `discover` as the argument, run ONLY this phase against existing findings and stop.
 
@@ -70,9 +70,9 @@
 `OUT/findings.md`:
 1. File inventory (from Phase 1).
 2. All sweep artifacts as titled appendix tables (or pointers to `OUT/artifacts/`).
-3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M19, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
+3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M24, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
 4. Per-document index of finding IDs.
-5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20 (OOXML style/formatting rows from the pipeline's scan)) → `N findings` / `clean — basis` / `unable — <reason>`.
+5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20 (OOXML style/formatting rows from the pipeline's scan), plus M21–M24 (the adopted sweeps)) → `N findings` / `clean — basis` / `unable — <reason>`.
 6. Summary note: counts by category/severity; unresolved gaps; missing-citation issues; ambiguous context; unresolvable contradictions; the manual-verification list (incl. Zotero fields); guidelines source/version; items to re-check against the current author guide.
 
 `OUT/findings.json` (machine-readable, consumed by nbt-revise):
@@ -92,11 +92,11 @@
 - One sweep at a time; artifact complete before the next begins.
 - Prefer scripts over attention for all enumeration; judgment only classifies rows.
 - Long sessions: maintain `WORK/STATE.md` (current sweep, pending steps, open questions) so the workflow resumes without loss.
-- Grow the skill: after the discovery round, validate the proposals in `OUT/round2/new_sweeps.md` with the user and append them to `references/sweeps.md` as M21, M22… (M18, M19 and M20 are reserved by the pipeline — see `references/sweeps.md`) — the checklist converges toward exhaustiveness over successive runs instead of pretending to be exhaustive on day one. If the skill directory is read-only (common for an installed skill), do not fight it: keep the accepted text in `OUT/round2/new_sweeps.md` and hand the user the exact block to append.
+- Grow the skill: after the discovery round, validate the proposals in `OUT/round2/new_sweeps.md` with the user and append them to `references/sweeps.md` as M25, M26… (M18–M20 are reserved by the pipeline and M21–M24 were adopted from earlier discovery rounds — see `references/sweeps.md`) — the checklist converges toward exhaustiveness over successive runs instead of pretending to be exhaustive on day one. If the skill directory is read-only (common for an installed skill), do not fight it: keep the accepted text in `OUT/round2/new_sweeps.md` and hand the user the exact block to append.
 
 ## Acceptance checks (for the human, after the run)
 
-1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20 (OOXML style/formatting rows), plus M21+ once proposals are adopted.
+1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths), M20 (OOXML style/formatting rows) and M21–M24 (the adopted sweeps).
 2. Every sweep with findings has a matching artifact file in `review/artifacts/` (M8's occurrence enumerations live in `review/work/occurrences_*.md`). A sweep with findings but no artifact means it worked from impression — re-run that sweep.
 3. Each finding points to a specific word/number/phrase with a verbatim quote, not a whole passage.
 4. `findings.json` exists and every finding has all eight fields.
=================== nbt-skills/nbt-review/references/discovery.md
--- /tmp/head_version.tmp	2026-09-22 08:44:20.637594265 +0800
+++ nbt-skills/nbt-review/references/discovery.md	2026-09-22 08:34:06.678315000 +0800
@@ -26,7 +26,7 @@
 ## D0 — Dedup base
 
 From PRIOR build two indexes (`OUT2/known_index.md`):
-- **KNOWN-CLASSES**: the 24 check IDs (M1–M20, J1–J4) with one-line descriptions.
+- **KNOWN-CLASSES**: the 28 check IDs (M1–M24, J1–J4) with one-line descriptions.
 - **KNOWN-INSTANCES**: every prior finding as `id | class | location | evidence quote`.
 
 Anything matching a KNOWN-INSTANCE (same class + same location + same
@@ -106,10 +106,10 @@
 run catches it mechanically:
 
 ```
-## M21 — <name> (proposed)
+## M25 — <name> (proposed)
 **Purpose:** ...
 **Enumeration:** <script or manual procedure — must be enumerable>
-**Artifact:** M21_<slug>.md: <columns>
+**Artifact:** M25_<slug>.md: <columns>
 **Finding rules:** one per instance, listed
 ```
 
@@ -117,7 +117,8 @@
 (figure-legend length, always enumerated with an optional proxy cap), M19
 (abstract/main-text length plus the user's cover-letter preference) and M20
 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan)
-are reserved and defined in `sweeps.md`, so proposals start at M21.
+are reserved and defined in `sweeps.md`, and M21–M24 were adopted from earlier
+discovery rounds there, so proposals start at M25.
 These are PROPOSALS: the user validates them; only validated ones get
 appended to `references/sweeps.md`. This is the feedback loop — no static
 checklist can be complete, but each discovered miss converts into a permanent
=================== nbt-skills/nbt-review/references/sweeps.md
--- /tmp/head_version.tmp	2026-09-22 08:44:20.747594236 +0800
+++ nbt-skills/nbt-review/references/sweeps.md	2026-09-22 08:34:09.956702100 +0800
@@ -1,4 +1,4 @@
-# Sweeps M1–M20 and Judgment Passes J1–J4 — nbt-review
+# Sweeps M1–M24 and Judgment Passes J1–J4 — nbt-review
 
 This file is the single source of truth for Phase 2. Follow it exactly.
 Every sweep entry specifies: purpose · scope · enumeration procedure (script
@@ -10,8 +10,8 @@
 **M19** (abstract/main-text length plus the user's cover-letter preference;
 always runs). **M20** (OOXML style/formatting uniformity; always runs, and its
 enumeration is supplied by the pipeline's code-side OOXML scan) follows them.
-New sweeps validated from the discovery round are appended after M20 as
-**M21, M22…** in the same format — do not insert into the middle (IDs are
+New sweeps validated from the discovery round are appended after the adopted
+M21–M24 as **M25, M26…** in the same format — do not insert into the middle (IDs are
 stable).
 
 ---
@@ -64,7 +64,7 @@
 
 ```
 F-NNN | location: <doc>/<section>/<paragraph|line|figure|table> | category: <0–5>
-check: <M1–M20|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
+check: <M1–M24|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
 evidence: "<short verbatim quote of the exact word/number/phrase>"
 problem: <1–2 sentence explanation>
 ```
=================== nbt-skills/nbt-revise/references/ledger.md
--- /tmp/head_version.tmp	2026-09-22 08:44:20.787594226 +0800
+++ nbt-skills/nbt-revise/references/ledger.md	2026-09-22 08:30:07.850199300 +0800
@@ -81,7 +81,7 @@
 
 **Improvement rows (`I-xxx`).** An edit that repairs a defect the frozen review
 did NOT name is legal when it is recorded, not hidden: give it an `I-xxx` id, the
-check id it belongs to (M1–M20 / J1–J4), the tier
+check id it belongs to (M1–M24 / J1–J4), the tier
 (`correctness|consistency|preservation|completeness|formatting|writing`), a
 severity (`critical|major|minor`), one line of evidence with a location, and the
 diff hunk that carries it. E6 still governs *claims* (see edit_rules.md: rigor
=================== nbt-skills/prompts/adress_issues.prompt.md
--- /tmp/head_version.tmp	2026-09-22 08:44:20.817594216 +0800
+++ nbt-skills/prompts/adress_issues.prompt.md	2026-09-22 08:35:04.846078100 +0800
@@ -82,6 +82,12 @@
 
 Columns: `id | category | severity | location | evidence | verdict | rationale | edit IDs | final status`
 
+- `category` keeps the review's category number. The defect CLASS it maps to is the judge panel's
+  vocabulary (highest priority first: `correctness > consistency > preservation > completeness >
+  formatting`; the mapping table is in `nbt-review/references/sweeps.md` → CLASSIFICATION). State
+  the class in the rationale whenever a row is disputed or resolved by a wording-only edit: an edit
+  the panel cannot name in that vocabulary reads as cosmetic, and the reviewer's finding then never
+  becomes an improvement a judge can see.
 - **verdict** (from R1): `confirmed` / `false-positive` / `clarification` / `manual-required` / `not-found-in-source`
 - **final status** (after edits): `fixed` / `fixed-with-caveat` / `clarification` / `placeholder-inserted` / `discarded` / `manual-required`
 
@@ -144,6 +150,18 @@
 justification.** This is the locality proof — "only the intended sentences
 changed".
 
+**Improvement rows (`I-xxx`).** An edit that repairs a defect the frozen review
+did NOT name is legal when it is recorded, not hidden: give it an `I-xxx` id, the
+check id it belongs to (M1–M24 / J1–J4), the tier
+(`correctness|consistency|preservation|completeness|formatting|writing`), a
+severity (`critical|major|minor`), one line of evidence with a location, and the
+diff hunk that carries it. E6 still governs *claims* (see edit_rules.md: rigor
+repairs are legal; claims, interpretations and conclusion strength are not).
+Record ONE row per instance: five fixed instances are five `I-` rows, never one
+summary row, because the panel scores per instance. `I-` rows are not a
+substitute for the frozen findings — every `F-*`/`X-*` id still needs its own
+row.
+
 ## A8 — RESCAN ARTIFACTS + RESCAN FINDINGS
 
 V3 output: the M-sweep artifacts re-run over the ENTIRE revised corpus (using
@@ -180,7 +198,6 @@
 task is not finished.
 
 ## APPENDIX: Edit rules E1–E6, P1, C (references/edit_rules.md)
-
 # Edit Rules E1–E6, Propagation P1, Code C — nbt-revise
 
 Applied during Step E (one edit at a time, in A4 plan order). Each rule
@@ -496,3 +513,4 @@
 not stay unsourced — it is proved, cited, a declared parameter, or removed as
 decoration (never silently, and never by changing a scientific claim). Removing
 a number is a `preservation`-tier change: record it in CHANGELOG.md.
+
=================== nbt-skills/prompts/identify_issues.prompt.md
--- /tmp/head_version.tmp	2026-09-22 08:44:20.917594190 +0800
+++ nbt-skills/prompts/identify_issues.prompt.md	2026-09-22 08:35:04.744942400 +0800
@@ -34,7 +34,7 @@
 1. **Identification only** — findings, never edits. Never modify any file in SUBMISSION_DIR.
 2. **Never invent.** Unresolvable value → status `unresolvable — manual verification required`. Guideline rule you cannot verify → `guideline-dependent`. Missing data → note a placeholder may be needed; never fabricate.
 3. **No silent skips.** Every check ID must end up in the coverage table with a real disposition (`N findings` / `clean — basis: <artifact/locations>` / `unable — <reason>`). "Not checked" is not an allowed value.
-4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan) always run with them.** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to a mechanical sweep.
+4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan) always run with them, together with the adopted sweeps M21–M24 (correspondence policy, data/code-availability integrity, supplementary parity, concept/term families).** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to a mechanical sweep.
 5. **One finding per instance.** "Several acronyms are undefined" is not a finding; each undefined acronym is its own finding with its own ID, quote, and location.
 6. **Sweep pattern for every mechanical check:** ENUMERATE (script preferred; scripts live in `WORK/`) → ARTIFACT (`OUT/artifacts/<ID>.md` for the M1/M2/M4–M17 tables; term/value occurrence enumerations are written to `WORK/occurrences_<slug>.md`, which is M8's artifact — pass `--out OUT/artifacts` if you prefer them alongside the others; every instance gets a row, including rows later judged OK; the artifact spans the whole corpus, not one file) → AUDIT (each row gets: a finding ID, `OK`, or `unable — <reason>`) → REPORT (findings derived only from artifact rows, never from general impression).
 7. **A sweep with zero findings is INVALID unless its artifact exists and every row is disposed.**
@@ -58,7 +58,7 @@
 
 **Phase 1 — Setup.** Run `convert_corpus.py` on SUBMISSION_DIR. Review the inventory: role classification, editable vs read-only, conversion status. Every conversion failure is recorded, never skipped. Images are marked `visually unverifiable` unless OCR/VLM is available; when a renderer exists, render and LOOK. Zotero live fields: the converter marks them `[[FIELD: ...]]`; check the rendered text; an unreadable or incomplete field goes to the manual-verification list (tell the user to verify it in Word). Resolve citations READ-ONLY with `ZOT_CLI` / `$ZOTERO_SKILL` (parent bibliographic item keys, never attachment keys; confirm title, creators, year, DOI) and never write to the library: a suspected metadata error becomes a finding with the proposed correction.
 
-**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity; the pipeline seeds `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md`, and every row must be disposed) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in the appendix below — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.
+**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity; the pipeline seeds `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md`, and every row must be disposed), the adopted sweeps M21–M24 (correspondence policy, data/code-availability integrity, supplementary parity, concept/term families) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in the appendix below — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.
 
 **Phase 3 — Discovery round.** D0–D5 per `references/discovery.md`: hunt issue classes OUTSIDE the checklist; outputs `OUT/round2/findings_extra.{md,json}` and `OUT/round2/new_sweeps.md`. If the user passes `discover` as the argument, run ONLY this phase against existing findings and stop.
 
@@ -69,9 +69,9 @@
 `OUT/findings.md`:
 1. File inventory (from Phase 1).
 2. All sweep artifacts as titled appendix tables (or pointers to `OUT/artifacts/`).
-3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M19, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
+3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M24, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
 4. Per-document index of finding IDs.
-5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20 (OOXML style/formatting rows from the pipeline's scan)) → `N findings` / `clean — basis` / `unable — <reason>`.
+5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths), M20 (OOXML style/formatting rows from the pipeline's scan) and M21–M24 (the adopted sweeps)) → `N findings` / `clean — basis` / `unable — <reason>`.
 6. Summary note: counts by category/severity; unresolved gaps; missing-citation issues; ambiguous context; unresolvable contradictions; the manual-verification list (incl. Zotero fields); guidelines source/version; items to re-check against the current author guide.
 
 `OUT/findings.json` (machine-readable, consumed by nbt-revise):
@@ -95,15 +95,14 @@
 
 ## Acceptance checks (for the human, after the run)
 
-1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20 (OOXML style/formatting rows), plus M21+ once proposals are adopted.
+1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths), M20 (OOXML style/formatting rows) and M21–M24 (the adopted sweeps).
 2. Every sweep with findings has a matching artifact file in `review/artifacts/` (M8's occurrence enumerations live in `review/work/occurrences_*.md`). A sweep with findings but no artifact means it worked from impression — re-run that sweep.
 3. Each finding points to a specific word/number/phrase with a verbatim quote, not a whole passage.
 4. `findings.json` exists and every finding has all eight fields.
 
 
-## APPENDIX: Sweeps M1–M20 and judgment passes J1–J4 (references/sweeps.md)
-
-# Sweeps M1–M20 and Judgment Passes J1–J4 — nbt-review
+## APPENDIX: Sweeps M1–M24 and judgment passes J1–J4 (references/sweeps.md)
+# Sweeps M1–M24 and Judgment Passes J1–J4 — nbt-review
 
 This file is the single source of truth for Phase 2. Follow it exactly.
 Every sweep entry specifies: purpose · scope · enumeration procedure (script
@@ -115,8 +114,8 @@
 **M19** (abstract/main-text length plus the user's cover-letter preference;
 always runs). **M20** (OOXML style/formatting uniformity; always runs, and its
 enumeration is supplied by the pipeline's code-side OOXML scan) follows them.
-New sweeps validated from the discovery round are appended after M20 as
-**M21, M22…** in the same format — do not insert into the middle (IDs are
+New sweeps validated from the discovery round are appended after the adopted
+M21–M24 as **M25, M26…** in the same format — do not insert into the middle (IDs are
 stable).
 
 ---
@@ -169,7 +168,7 @@
 
 ```
 F-NNN | location: <doc>/<section>/<paragraph|line|figure|table> | category: <0–5>
-check: <M1–M20|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
+check: <M1–M24|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
 evidence: "<short verbatim quote of the exact word/number/phrase>"
 problem: <1–2 sentence explanation>
 ```
@@ -984,7 +983,7 @@
 ## D0 — Dedup base
 
 From PRIOR build two indexes (`OUT2/known_index.md`):
-- **KNOWN-CLASSES**: the 21 check IDs (M1–M17, J1–J4) with one-line descriptions.
+- **KNOWN-CLASSES**: the 28 check IDs (M1–M24, J1–J4) with one-line descriptions.
 - **KNOWN-INSTANCES**: every prior finding as `id | class | location | evidence quote`.
 
 Anything matching a KNOWN-INSTANCE (same class + same location + same
@@ -1064,17 +1063,19 @@
 run catches it mechanically:
 
 ```
-## M20 — <name> (proposed)
+## M25 — <name> (proposed)
 **Purpose:** ...
 **Enumeration:** <script or manual procedure — must be enumerable>
-**Artifact:** M20_<slug>.md: <columns>
+**Artifact:** M25_<slug>.md: <columns>
 **Finding rules:** one per instance, listed
 ```
 
 Number proposals continuing from the highest existing sweep number. M18
-(figure-legend length, always enumerated with an optional proxy cap) and M19
-(abstract/main-text length plus the user's cover-letter preference) are reserved
-and defined in `sweeps.md`, so proposals start at M20.
+(figure-legend length, always enumerated with an optional proxy cap), M19
+(abstract/main-text length plus the user's cover-letter preference) and M20
+(OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan)
+are reserved and defined in `sweeps.md`, and M21–M24 were adopted from earlier
+discovery rounds there, so proposals start at M25.
 These are PROPOSALS: the user validates them; only validated ones get
 appended to `references/sweeps.md`. This is the feedback loop — no static
 checklist can be complete, but each discovered miss converts into a permanent
@@ -1086,3 +1087,4 @@
 Counts: gap rows (covered/uncovered), probes (executed/clean/findings/unable),
 X-findings by category/severity, proposed sweeps. Manual-verification list.
 Statement of what this round could NOT check (honest limits).
+
=================== nbt-skills/tests/validate_skill.py
--- /tmp/head_version.tmp	2026-09-22 08:44:21.107594139 +0800
+++ nbt-skills/tests/validate_skill.py	2026-09-22 08:34:17.592395800 +0800
@@ -418,8 +418,8 @@
     ip = read(os.path.join(root, "prompts", "identify_issues.prompt.md"))
     sw = read(os.path.join(root, "nbt-review", "references", "sweeps.md"))
     di = read(os.path.join(root, "nbt-review", "references", "discovery.md"))
-    check("D18 M18/M19 are reserved and discovery proposals start at M20",
-          "## M18 —" in sweeps and "proposals start at M20" in " ".join(di.split()))
+    check("D18 M18-M24 are reserved/adopted and discovery proposals start at M25",
+          "## M18 —" in sweeps and "proposals start at M25" in " ".join(di.split()))
     sweeps_app = appendix(ip, "## APPENDIX: Sweeps", "## APPENDIX: Discovery")
     disc_app = appendix(ip, "## APPENDIX: Discovery")
     check("D10 identify prompt appendices in sync",
=================== nbt_docx_format.py
--- /tmp/head_version.tmp	2026-09-22 08:44:21.247594103 +0800
+++ nbt_docx_format.py	2026-09-22 08:27:42.057433700 +0800
@@ -597,6 +597,16 @@
     "FMT-S3",    # running head on the title page
     "FMT-S4",    # tracked changes in a final package
     "FMT-T1",    # mixed quotation marks
+    # The M20 sweep's dash/quote family: sweeps.md lists "mixed straight/curly
+    # quotation marks, a spaced hyphen used as a dash, or em-dash density above
+    # the user's cap -> finding (editorial: the revision arm rewrites)", and the
+    # pipeline's own M20 seed text calls the em-dash density a findings row for
+    # the revision/integration arms. Leaving FMT-P1/FMT-P2 advisory let a
+    # reviewer close them as "editorial preference only" -- a disposition the
+    # finding-tier bar forbids -- and the auditor, which attacks finding-tier
+    # rows only, never saw them.
+    "FMT-P1",    # em-dash density above the policy cap
+    "FMT-P2",    # a spaced hyphen used as a dash
     "FMT-T8b",   # nested parentheses
     "FMT-T8c",   # a distinctive term repeated inside one short passage
     "FMT-T9c",   # long sentence / long list-paragraph (tiered by section)
=================== nbt_pipeline.py
--- /tmp/head_version.tmp	2026-09-22 08:44:21.487594037 +0800
+++ nbt_pipeline.py	2026-09-22 08:32:27.161154900 +0800
@@ -5,7 +5,7 @@
 Biotechnology manuscript: R fixed rounds (R is configurable at setup and
 defaults to 2), a relative-judgment panel that produces 2*judges*(|field|-1)
 directed scores per version (at the default judges=3 that is 6*(|field|-1); the
-default plan's round-1 field of 7 gives 36), content-addressed pinning of every
+default plan's round-1 field of 8 gives 42), content-addressed pinning of every
 round's champion, and a deterministic selection layer that ranks only
 candidates whose panel is COMPLETE (a partial panel can never decide a round).
 Python 3.9+, standard library only for the pipeline itself; tracked-changes
@@ -140,7 +140,7 @@
       + ((|field|-1) opponents x 3 judges x 1)      [others-vs-V, negated]
       = 2 * judges * (|field| - 1)                  [= 6 * (|field| - 1) and 18 at
                                                      the default 3 judges, |field| = 4;
-                                                     36 with the 7-member round-1
+                                                     42 with the 8-member round-1
                                                      field the default plan builds]
 
     The field is deduplicated by CONTENT digest, so its size is whatever the
@@ -150,7 +150,7 @@
     K = 1 + M + N integrated candidates (of which the round's per-round
     --integrators mask may select only some), minus everything that deduplicates
     (the base always merges into the pin or the original). The default plan
-    gives 7 members in round 1 ({original, w1, w2, a2, i1..i4}) and 7 in round
+    gives 8 members in round 1 ({original, w1, w2, a2, i1..i4}) and 7 in round
     2 ({original, the round-1 pin, w1, a2, i1..i3}). V-vs-W and W-vs-V are
     independent judgments from independent sessions, which is why the ranking
     statistic is the median of the FLAT score list, not a two-level median, with
@@ -3768,7 +3768,7 @@
 
 1. Ground your judgment in evidence: read the skill's SKILL.md and references/sweeps.md, then run the
    $nbt-review workflow on target/ RESTRICTED TO THE FROZEN SWEEP SET -- mechanical sweeps M1-M17 and
-   judgment passes J1-J4 ONLY, @@M18_JUDGE_SWEEP@@
+   judgment passes J1-J4, plus the adopted M18-M24 checks, @@M18_JUDGE_SWEEP@@
    @@M19_JUDGE_SWEEP@@
    @@M20_JUDGE_SWEEP@@
 
@@ -3898,13 +3898,13 @@
 
 === PRIORITY ORDER (use it to decide every comparison) ===
 
-  correctness  >  consistency  >  preservation  >  completeness  >  formatting
+  correctness  >  consistency  >  preservation  >  completeness  >  formatting  >  writing
 
 An error of fact/DOI/citation/number/premise outranks a cross-document conflict, which outranks a
 regression against the original (deleted claims, softened limitations, broken cross-references or
-numbering), which outranks missing or unneeded information, which outranks formatting and
-micro-formatting. When sources in a package disagree, the higher-priority source wins, in this
-order:
+numbering), which outranks missing or unneeded information, which outranks formatting and writing
+(micro-formatting and wording rows, each capped at one point). When sources in a package disagree,
+the higher-priority source wins, in this order:
   @@SOURCE_HIERARCHY@@
 
 === PRESERVATION SIGNAL (the orchestrator's anti-regression gate) ===
@@ -6339,6 +6339,43 @@
     return rec["format_fix"]
 
 
+def _seed_write(path: Path, text: str) -> bool:
+    """Write a seeded file UNLESS it already exists (atomic when it does write).
+
+    The seeded evidence tables are INPUTS the session disposes IN PLACE, and the
+    materializers run again on every invocation: `run` re-materializes a failed
+    run whose completion marker exists so its postcheck can be re-evaluated, and
+    it re-materializes a dirty sandbox without launching a second agent. Blindly
+    rewriting the seed there HASHED THE SESSION'S VERDICTS AWAY (the M20/M18/M19/
+    OUTLINE tables came back empty and undisposed), which turned every such
+    re-postcheck into a guaranteed failure and made a completed review
+    unrecoverable. Writes are atomic so an existing file is never a truncated
+    seed, and a genuinely missing one is still created.
+    """
+    if path.exists():
+        return False
+    # tmp + rename (NOT write_text_atomic's extra fsync): the content is complete
+    # before the rename, so an interrupted write can never leave a truncated
+    # seed, while the fsync would cost one disk sync per seeded file on every
+    # materialization -- ~20 files per session, measured as ~0.7s per sandbox on
+    # the operator's mount, which is exactly the latency the scheduling tests
+    # (and the real run) pay for a pure input.
+    path.parent.mkdir(parents=True, exist_ok=True)
+    tmp = tmp_path_for(path)
+    try:
+        with open(tmp, "w", encoding="utf-8") as f:
+            f.write(text)
+            f.flush()
+        os.replace(tmp, path)
+    except BaseException:
+        try:
+            tmp.unlink()
+        except OSError:
+            pass
+        raise
+    return True
+
+
 def _seed_review_format_artifact(ctx: Ctx, sb: Path) -> dict:
     """Seed the M20 sweep for a review run: the code-side scan IS the enumeration.
 
@@ -6393,7 +6430,7 @@
         lines.append("| - | — | — | — | — | no code-side formatting finding | — |  |")
     art = sb / REVIEW_DIR / "artifacts"
     art.mkdir(parents=True, exist_ok=True)
-    (art / "M20_formatting.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
+    _seed_write(art / "M20_formatting.md", "\n".join(lines) + "\n")
     return info
 
 
@@ -6818,9 +6855,9 @@
 
     def write_both(stem: str, header: str, columns: list, rows: list, empty: str) -> None:
         text = ("# " + header + "\n\n" + _evidence_artifact_table(rows, columns, empty) + "\n")
-        (work / stem).write_text(text, encoding="utf-8")
+        _seed_write(work / stem, text)
         if art is not None:
-            (art / stem).write_text(text, encoding="utf-8")
+            _seed_write(art / stem, text)
 
     write_both(
         "NUMBERS_LEDGER.md",
@@ -7006,27 +7043,25 @@
         cap_rows = [{"document": c.get("document"), "caption": c.get("caption"),
                      "words": c.get("words"), "over_limit": c.get("over_limit"),
                      "excerpt": c.get("excerpt")} for c in (cap.get("captions") or [])]
-        (art / "M18_caption_words.md").write_text(
-            "# M18 — figure-legend word counts (code-side enumeration)\n\n"
+        _seed_write(art / "M18_caption_words.md", "# M18 — figure-legend word counts (code-side enumeration)\n\n"
             f"Proxy cap: {cap.get('limit') or 'none configured'}. Dispose every row "
             "(finding id / OK — reason / unable — reason).\n\n"
             + _evidence_artifact_table(cap_rows,
                                        ["document", "caption", "words", "over_limit", "excerpt"],
                                        "no caption found by the code-side scan")
-            + "\n", encoding="utf-8")
+            + "\n")
         lng = ev.get("lengths") or {}
         len_rows = [{"document": r.get("document"), "section": r.get("section"),
                      "words": r.get("words"), "cap": r.get("cap"),
                      "note": r.get("note")} for r in (lng.get("rows") or [])]
-        (art / "M19_length.md").write_text(
-            "# M19 — abstract/main-text length (code-side enumeration)\n\n"
+        _seed_write(art / "M19_length.md", "# M19 — abstract/main-text length (code-side enumeration)\n\n"
             f"Caps: {json.dumps((lng.get('limits') or {}).get('abstract', {}))} / "
             f"{json.dumps((lng.get('limits') or {}).get('main text', {}))}. "
             "Dispose every row.\n\n"
             + _evidence_artifact_table(len_rows,
                                        ["document", "section", "words", "cap", "note"],
                                        "no manuscript-shaped document found")
-            + "\n", encoding="utf-8")
+            + "\n")
         # M4 numbers: the "verify the source of each number" ledger. The agent
         # fills `source` (data file / table / figure / formula) or removes the
         # claim; an empty source cell is an unfinished row.
@@ -7036,8 +7071,7 @@
                      "thousands": "yes" if r.get("thousands_separated") else "",
                      "sentence": (r.get("sentence") or "")[:90], "source": ""}
                     for r in (num.get("rows") or [])]
-        (art / "M4_numbers.md").write_text(
-            "# M4 — number ledger (code-side enumeration; one row per numeric literal)\n\n"
+        _seed_write(art / "M4_numbers.md", "# M4 — number ledger (code-side enumeration; one row per numeric literal)\n\n"
             "Fill `source` for every row (the data file, table, figure or formula the number "
             "comes from), or remove the claim from the text. A number with no verifiable source "
             "must not stay.\n\n"
@@ -7045,15 +7079,14 @@
                                        ["document", "paragraph", "number", "unit", "thousands",
                                         "sentence", "source"],
                                        "no numeric literal found")
-            + "\n", encoding="utf-8")
+            + "\n")
         # M8 terms: occurrence ledger + the confusable pairs the style rules found.
         ter = ev.get("terms") or {}
         term_rows = [{"document": r.get("document"), "term": r.get("term"),
                       "count": r.get("count"), "first paragraph": r.get("first_paragraph"),
                       "first context": (r.get("first_context") or "")[:80],
                       "decision": ""} for r in (ter.get("rows") or [])]
-        (art / "M8_terms.md").write_text(
-            "# M8 — key-term occurrence ledger (code-side enumeration)\n\n"
+        _seed_write(art / "M8_terms.md", "# M8 — key-term occurrence ledger (code-side enumeration)\n\n"
             "For every term: confirm it is used with ONE precise meaning, note the chosen "
             "term in `decision` (and the definition site if the manuscript needs one). Rows "
             "for confusable pairs (emulate/simulate, accuracy/precision, ...) are the "
@@ -7062,7 +7095,7 @@
                                        ["document", "term", "count", "first paragraph",
                                         "first context", "decision"],
                                        "no key term found")
-            + "\n", encoding="utf-8")
+            + "\n")
         # Hierarchy scaffold for the summary/coherence pass (suggestion: summarize
         # each level, then check sibling/parent/child coherence).
         outl = ev.get("outline") or {}
@@ -7071,8 +7104,7 @@
                          "lists": r.get("list_markers") or "", "refs": r.get("refs") or "",
                          "first sentence": (r.get("first_sentence") or "")[:70],
                          "summary": ""} for r in (outl.get("rows") or [])]
-        (art / "OUTLINE.md").write_text(
-            "# OUTLINE — hierarchy scaffold for the summary/coherence pass\n\n"
+        _seed_write(art / "OUTLINE.md", "# OUTLINE — hierarchy scaffold for the summary/coherence pass\n\n"
             "Write a GENERATED one-line summary in `summary` for every row: what the paragraph "
             "CLAIMS (its own words, not the first sentence copied back — a row whose summary is "
             "a prefix of `first sentence` counts as unfilled). Then check each summary against "
@@ -7089,14 +7121,13 @@
                                        ["document", "heading", "paragraph", "words", "lists",
                                         "refs", "first sentence", "summary"],
                                        "no paragraph found")
-            + "\n", encoding="utf-8")
+            + "\n")
         # Hand-off placeholders, classified searchable vs author-only.
         phl = ev.get("placeholder_ledger") or {}
         ph_rows = [{"document": r.get("document"), "paragraph": r.get("document_paragraph"),
                     "class": r.get("class"), "payload": (r.get("payload") or "")[:100],
                     "resolution": ""} for r in (phl.get("rows") or [])]
-        (art / "PLACEHOLDERS.md").write_text(
-            "# PLACEHOLDERS — hand-off markers, classified\n\n"
+        _seed_write(art / "PLACEHOLDERS.md", "# PLACEHOLDERS — hand-off markers, classified\n\n"
             "`searchable` rows ask for a findable fact (preprint, DOI, accession, database ID, "
             "version): search for it (or use reports/PLACEHOLDER_LOOKUP.json when the "
             "operator enabled the lookup) and fill the placeholder with the answer, or with "
@@ -7106,7 +7137,7 @@
                                        ["document", "paragraph", "class", "payload",
                                         "resolution"],
                                        "no hand-off placeholder found")
-            + "\n", encoding="utf-8")
+            + "\n")
     if where == "review":
         # Keep the M20 skeleton the review contract points at.
         _seed_review_format_artifact(ctx, sb)
@@ -7115,14 +7146,13 @@
         fmt_rows = [{"rule": r.get("rule"), "severity": r.get("severity"),
                      "location": r.get("location"), "evidence": r.get("evidence"),
                      "fix": r.get("fix")} for r in (fmt.get("rows") or [])]
-        (art / "M20_formatting.md").write_text(
-            "# M20 — OOXML style/formatting (code-side enumeration of this judge's target)\n\n"
+        _seed_write(art / "M20_formatting.md", "# M20 — OOXML style/formatting (code-side enumeration of this judge's target)\n\n"
             "Audit every row; mechanical rows were already normalized by the orchestrator "
             "before this view was built.\n\n"
             + _evidence_artifact_table(fmt_rows,
                                        ["rule", "severity", "location", "evidence", "fix"],
                                        "no code-side formatting finding")
-            + "\n", encoding="utf-8")
+            + "\n")
     plc = ev.get("placeholders") or {}
     lines += ["## Hand-off placeholders", "",
               f"- count: {plc.get('count', '?')}",
@@ -10752,7 +10782,8 @@
   * The orchestrator refuses the review if any prior finding id appears in NEITHER
     findings.json nor findings.md, so complete this reconciliation first.
   * Carrying findings forward does NOT replace the sweeps: run the complete M1-M17 + J1-J4 set
-    (plus the pipeline caption check when it is active) and report your own new findings as usual."""
+    plus the pipeline-mandated M18-M24 checks (the caption check among them) and report your own
+    new findings as usual."""
 
 
 # ---------------------------------------------------------------------
@@ -11340,27 +11371,153 @@
     r"\brunning head\b|\bmetadata\b|\bnot applicable\b|\bn/a\b)", re.I)
 
 
-def parse_markdown_table(path: Path) -> list:
-    """Rows of a seeded artifact table as {lowercased header: cell} ([] if absent)."""
+# The columns whose cells carry a disposition. `resolution` is the same
+# contract under the placeholder/ledger layouts' own name.
+DISPOSITION_COLUMNS = ("disposition", "resolution")
+
+
+def _split_table_cells(text: str) -> list:
+    """Split one table line on its UNESCAPED pipes (a `\\|` is cell content).
+
+    The seeded tables escape a literal pipe inside a cell as `\\|` (figure
+    captions are full of them: "Fig. 1 \\| Strategies ..."), and splitting on
+    every pipe made those rows longer than their header -- which shifted every
+    later cell, so the disposition was read from the wrong column.
+    """
+    cells, cur, i = [], [], 0
+    while i < len(text):
+        ch = text[i]
+        if ch == "\\" and i + 1 < len(text):
+            cur.append(ch)
+            cur.append(text[i + 1])
+            i += 2
+            continue
+        if ch == "|":
+            cells.append("".join(cur))
+            cur = []
+            i += 1
+            continue
+        cur.append(ch)
+        i += 1
+    cells.append("".join(cur))
+    return [c.strip().replace("\\|", "|") for c in cells]
+
+
+def _table_line_cells(line: str) -> list:
+    """The cells of one `| ... |` line, without its two delimiter pipes."""
+    s = line.strip()
+    if s.startswith("|"):
+        s = s[1:]
+    if s.endswith("|") and not s.endswith("\\|"):
+        s = s[:-1]
+    return _split_table_cells(s)
+
+
+def _is_separator_row(cells: list) -> bool:
+    """`|---|---|` / `|:--:|` -- the table's header/body divider."""
+    return bool(cells) and all("-" in c and set(c) <= set("-: ") for c in cells)
+
+
+def _table_row(header: list, cells: list) -> tuple:
+    """({column: cell}, note) for one data row; note is "", "trimmed" or "ragged".
+
+    The tables real sessions deliver are not always exactly as wide as their
+    header, and each deviation has ONE unambiguous reading:
+
+      1. stray LEADING empty cells (a script that writes `"| " + row` for a row
+         that already starts with its own pipe) are dropped;
+      2. ONE more cell than the header when the last column is a disposition
+         column and its own cell is EMPTY means the verdict was APPENDED after
+         the seeded empty cell instead of replacing it -- rendered markdown shows
+         that verdict, so it is read (the old positional zip() dropped it and
+         reported every row of a fully disposed 212-row M20 sweep as EMPTY,
+         failing three 30-minute attempts in a row on a real root);
+      3. stray TRAILING empty cells are dropped.
+
+    Notes: "appended" is worth warning about (the table's column count is off),
+    "trimmed" is not (only empty stray cells were removed), and "ragged" means
+    the row's real cells still do not match the header -- it is read
+    positionally and the operator is warned, because a shifted row would put the
+    verdict in the wrong column.
+    """
+    n = len(header)
+    note = ""
+    while len(cells) > n and not str(cells[0]).strip():
+        cells = cells[1:]
+        note = "trimmed"
+    if (len(cells) == n + 1 and header and header[-1] in DISPOSITION_COLUMNS
+            and not str(cells[n - 1]).strip()):
+        cells = cells[:n - 1] + [cells[-1]]
+        note = "appended"
+    while len(cells) > n and not str(cells[-1]).strip():
+        cells = cells[:-1]
+        note = note or "trimmed"
+    if len(cells) < n:
+        cells = cells + [""] * (n - len(cells))
+        note = note or "ragged"
+    elif len(cells) > n:
+        cells = cells[:n]
+        note = "ragged"
+    return {h: v for h, v in zip(header, cells)}, note
+
+
+def parse_markdown_blocks(path: Path) -> list:
+    """Every markdown table block of one artifact, each against ITS OWN header.
+
+    Returns [{"header": [...], "rows": [{column: cell}], "appended": n,
+    "ragged": n}, ...] in file order. A block is a run of consecutive `|` lines:
+    the first is the header, a separator row is skipped, the rest are data rows.
+
+    Blocks must be parsed separately because the artifacts legitimately contain
+    MORE THAN ONE table: the M20 sweep requires the review to add the classes the
+    code-side scan cannot see ("rows added from the visual pass"), and the
+    coverage/summary tables are appended the same way. Parsing the whole file
+    against the FIRST header turned those rows' own cells into empty
+    `disposition` cells of the seeded table.
+    """
     try:
         text = path.read_text("utf-8", "replace")
     except OSError:
         return []
-    rows, header = [], None
+    raw_blocks, cur = [], []
     for line in text.splitlines():
-        line = line.strip()
-        if not line.startswith("|"):
-            continue
-        cells = [c.strip() for c in line.strip("|").split("|")]
-        if header is None:
-            header = [c.lower() for c in cells]
-            continue
-        if all(set(c) <= set("-: ") for c in cells):
-            continue
-        if len(cells) < len(header):
-            cells += [""] * (len(header) - len(cells))
-        rows.append({h: v for h, v in zip(header, cells)})
-    return rows
+        if line.strip().startswith("|"):
+            cur.append(line.strip())
+        elif cur:
+            raw_blocks.append(cur)
+            cur = []
+    if cur:
+        raw_blocks.append(cur)
+    blocks = []
+    for raw in raw_blocks:
+        header = [c.lower() for c in _table_line_cells(raw[0])]
+        rows, appended, ragged = [], 0, 0
+        for line in raw[1:]:
+            cells = _table_line_cells(line)
+            if _is_separator_row(cells):
+                continue
+            row, note = _table_row(header, cells)
+            appended += 1 if note == "appended" else 0
+            ragged += 1 if note == "ragged" else 0
+            rows.append(row)
+        blocks.append({"header": header, "rows": rows,
+                       "appended": appended, "ragged": ragged})
+    return blocks
+
+
+def parse_markdown_table(path: Path) -> list:
+    """Rows of a seeded artifact table as {lowercased header: cell} ([] if absent).
+
+    A file that repeats the FIRST table's header (a long ledger split by an
+    interpolated paragraph) contributes every block; a table with different
+    columns (the session's own added-rows/coverage table) is NOT read as more
+    rows of the first table -- see parse_markdown_blocks() for why that matters.
+    """
+    blocks = parse_markdown_blocks(path)
+    if not blocks:
+        return []
+    head = blocks[0]["header"]
+    return [row for b in blocks if b["header"] == head for row in b["rows"]]
 
 
 def _names_check_or_finding(cell: str) -> bool:
@@ -11378,7 +11535,7 @@
     rows = [r for r in rows if r]
     if not rows:
         return problems
-    key = next((k for k in ("disposition", "resolution") if k in rows[0]), None)
+    key = next((k for k in DISPOSITION_COLUMNS if k in rows[0]), None)
     if key is None:
         return problems
     filled = [r for r in rows if str(r.get(key) or "").strip()]
@@ -11436,20 +11593,55 @@
 
 
 def artifact_quality_report(review_dir: Path) -> dict:
-    """{artifact: [problems]} for every seeded decision table under review/."""
+    """{artifact: [problems]} for every decision table under review/.
+
+    EVERY table block of the artifact is checked, each against its own header:
+    the seeded table and the rows the session adds itself (the M20 "classes the
+    scan cannot see", a coverage table) are all rows the session had to dispose.
+    """
     report = {}
     for rel in DECISION_ARTIFACTS:
-        rows = parse_markdown_table(review_dir / rel)
-        if not rows:
-            continue
-        problems = disposition_artifact_problems(rows)
-        if rel.endswith("OUTLINE.md"):
-            problems += outline_artifact_problems(rows)
-        if problems:
-            report[rel] = problems
+        for block in parse_markdown_blocks(review_dir / rel):
+            rows = block["rows"]
+            if not rows:
+                continue
+            problems = disposition_artifact_problems(rows)
+            if rel.endswith("OUTLINE.md"):
+                problems += outline_artifact_problems(rows)
+            if problems:
+                report.setdefault(rel, []).extend(problems)
     return report
 
 
+def artifact_quality_notes(review_dir: Path) -> dict:
+    """{artifact: [notes]} for tables the parser had to read tolerantly.
+
+    These are WARNINGS, never failures: a row with one cell more than its header
+    whose verdict was appended after the seeded empty cell is read anyway (see
+    _table_row), but the operator should still know the table's column count is
+    off, because a row that shifted cells rather than appending one would be
+    read positionally.
+    """
+    notes = {}
+    for rel in DECISION_ARTIFACTS:
+        appended = ragged = 0
+        for block in parse_markdown_blocks(review_dir / rel):
+            appended += block["appended"]
+            ragged += block["ragged"]
+        msgs = []
+        if appended:
+            msgs.append(f"{appended} row(s) carry one more cell than their header; the appended "
+                        f"trailing cell was read as the "
+                        f"{'/'.join(DISPOSITION_COLUMNS)} value -- write the verdict IN the "
+                        f"seeded cell instead of after it")
+        if ragged:
+            msgs.append(f"{ragged} row(s) do not match their table's column count and were read "
+                        f"positionally; check the table")
+        if msgs:
+            notes[rel] = msgs
+    return notes
+
+
 def check_artifact_quality(ctx: Ctx, rec: dict, sb: Path, errs: list, warns: list) -> dict:
     """Record (and optionally fail) the review's decision-artifact quality."""
     report = artifact_quality_report(sb / REVIEW_DIR)
@@ -11458,6 +11650,9 @@
         for p in problems:
             msg = f"decision artifact {rel}: {p}"
             (errs if strict_dispositions(ctx) else warns).append(msg)
+    for rel, notes in sorted(artifact_quality_notes(sb / REVIEW_DIR).items()):
+        for n in notes:
+            warns.append(f"decision artifact {rel}: {n}")
     return report
 
 

```
