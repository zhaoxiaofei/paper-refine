# `.nbt_test/` - validation harnesses for the pipeline

Self-contained repro/regression suites for `nbt_pipeline.py`,
`nbt_redlines_adapter.py` and the `nbt-skills/` pack. They need nothing but
Python 3 (standard library) and take a few seconds each; every suite prints one
`[ok ]`/`[FAIL]` line per check and exits non-zero if any check fails.

## Running them

The suites are independent (each builds its own root under `tempfile.mkdtemp`,
and the fixed `/tmp` paths are per-suite), so run them in parallel:

```bash
python3 .nbt_test/run_all.py             # GNU parallel, 8 jobs: ~110 s (sequential: ~5.5 min)
python3 .nbt_test/run_all.py -j 4        # cap the parallelism
python3 .nbt_test/run_all.py -j 1        # exactly the old sequential loop
python3 .nbt_test/run_all.py --only test_pipeline test_docx_format
python3 .nbt_test/run_all.py --engine python   # no GNU parallel on this box
python3 .nbt_test/run_all.py --logs /tmp/nbt-logs   # keep logs/status/timing
```

`run_all.py` drives every suite through `run_one.sh`, which gives it a private
`TMPDIR`, captures its output to `<logs>/<suite>.log`, and records its exit
status and wall time under `<logs>/status/`. A suite that fails is re-run ALONE
once: a timing-sensitive suite that only failed because eight others were
competing is reported as `flaky` (and named), while a suite that fails alone too
is a real failure whose `[FAIL]` lines are quoted. Exit status is 0 when nothing
really failed, 1 otherwise.

The runner is a convenience, not a wrapper: the same evidence comes from GNU
parallel directly, and every suite still runs standalone with `python3
.nbt_test/<suite>.py`.

```bash
mkdir -p /tmp/nbt-logs && export NBT_TEST_RUNDIR=/tmp/nbt-logs
ls .nbt_test/test_*.py | sed 's|.*/||' \
  | parallel -j 8 --joblog /tmp/nbt-logs/joblog '.nbt_test/run_one.sh {}'
```

| Suite | Covers |
|---|---|
| `test_pipeline.py` | The design-fix suite: prompts (render-then-look, visual artifacts), caption/placeholder gates, corpus rules, ranking and champion reporting. |
| `test_bug_audit_2026_0919.py` | Regression checks for the confirmed findings of the 2026-09-19 bug audit (`nbt_audit_data/2026-0919-1336-potential-bug-report/`): Python-3.9 syntax, the MCP visual gate, length/caption/cover-letter counting, the revision token, the stale-lock reclaim race, citation/number/acronym/occurrence extractor defects and the state/probe/materializer fixes. |
| `test_design_audit_2026_0919.py` | Regression checks for the confirmed findings of the 2026-09-19 design audit (`nbt_audit_data/2026-0919-1754-potential-design-issue-report/`): the shared M19 counter reads `.tex`/`.ltx` sources (one-line and multi-paragraph abstracts, `\caption` spans, LaTeX scaffolding), M19 subtracts only the legends inside the main-text span, the cover-letter row is a preference never a cap, M18's coverage row is mandatory in every caption state, the standalone fallback prompt matches SKILL.md/sweeps.md, and every length-scanned text format is enumerated for M18. |
| `test_fixes.py` | Asserts the fixed behaviour of every finding in `nbt_round_pipeline_issue_findings.md` (wrong-corpus, missing-artifact, prompt-sync, ranking). |
| `test_candidates.py` | Round-1 candidate repros: prune-then-run, setup script copy, restarting a setup that died part-way (the `_setup_in_progress` marker, while a complete root stays protected), `mc:Ignorable` declarations, stale redline output, manual-step counting. |
| `test_candidates2.py` | Round-2 candidate repros (the audit archives): skill-script regressions R1-R11, judge/agent-command handling, xlsx/corpus fixes. |
| `test_document_recovery.py` | The document-recovery layer: a dropped base file is restored with a warning instead of failing the round, plus the per-invocation retry budget and judge-label normalization. |
| `test_llm_stochastic_failures.py` | The stochastic-LLM contract: fenced/prose/BOM JSON, wrong-typed or half-written markers and ledgers, documents replaced by symlinks or directories, unreadable files/directories, judge sheets with null entries or fractional scores. Asserts every case either repairs with a warning or fails the attempt cleanly -- never a crash, never a silent accept. |
| `test_change_requests.py` | The pool/integration change requests: every round stages `M` REWRITTEN candidates first and `N` reviewed-and-then-revised candidates from ONE shared review pass, then reworks EVERY pool member once with the WHOLE pool as donors (`i1 = a1 <- (w1..wM, a2..)`, ... -- no pairwise arms); `--rewrites` / `--revises` accept an integer or a per-round list (short lists repeat their last element); the optional `docx` CLI (including `docx diff`) is probed and documented in every prompt; the defaults are `--rounds 2` / `--jobs 255` / `--rewrites 2,1` / `--revises 1,1`. Ends with two real stub-agent rounds (default plan and a custom plan). |
| `stub_agent.py` | Deterministic offline stand-in for an LLM session, used by the end-to-end runs. |
| `test_docx_converter.py` | The `docx-converter` MCP tool is the FIRST-choice .docx->.pdf converter: the Codex-config probe (`[mcp_servers.docx-converter]`, CODEX_HOME aware, refuses a deleted server script), the probe list/summary order (MCP tool first, then docx2pdf.sh, `docx render`, LibreOffice, ...), every prompt demanding `convert_docx_to_pdf` before any other converter plus the "render into a writable work dir, never into a read-only view" rule, the `-c mcp_servers.docx-converter.default_tools_approval_mode="approve"` override that makes the call legal in a non-interactive `codex exec` session (approval policy `never` denies an unapproved MCP call; no bypass flag is used, only installed servers are named, and an explicit `--agent-cmd` is never rewritten), and a live MCP handshake (tools/list); the real conversion runs only with `NBT_TEST_DOCX_MCP=1`. |
| `test_acronym_longform.py` | The M1b acronym long-form fix (the "copy-number (CN) defined, but the main text keeps spelling it out" bug): `extract_acronyms.py`'s reverse-direction audit finds residues after a definition that lives in ANOTHER context/file, is variant-tolerant (space/hyphen/case/plural), exempts each context's own first use and the definition site, counts quoted titles instead of flagging them, treats `CN, copy number` key entries as definitions, excludes bibliographies, annotates repeated page furniture; the spec (sweeps.md rule (k), edit_rules.md P1a), both prompt appendices, the pipeline's revise/judge directives and the orchestrator's "M1b rows were audited" gate are asserted; the suite closes the loop by re-sweeping after the P1a substitution (zero rows). Red on the pre-fix tree. |
| `test_grading_scheme.py` | The judging/grading redesign: panel integrity (a superseded judge sheet or one whose judge index is outside the configured range can no longer poison a panel into a false "PANEL INCOMPLETE" fallback), the tie-break (an exact statistical tie is decided by the CONTENT DIGEST, never by the arm's name -- `a2 < i1 < w1` silently favoured the revise arm), and judge contract v2's graded basis (every comparison carries the tier it is about plus a `resolved`/`introduced` ledger; a non-zero score needs an item on its own side, |score| >= 3 needs a MAJOR/CRITICAL item outside formatting, |score| = 4 needs a CRITICAL item; legacy sheets are accepted with an UNCALIBRATED warning instead of silently mixing in), plus the calibration diagnostics, `raw_scores.csv` columns, the decision.json score model and the judge prompt itself. Red on the pre-change tree. |
| `test_redesign_v3.py` | The 2026-09-21 redesign pass (judge contract v3): `writing` is the sixth scored class and `formatting`/`writing` rows are MINOR-only; the integer a judge writes is DERIVED from its own `resolved`/`introduced` rows (minor 1 / major 2 / critical 3, net capped per tier at correctness +-4, consistency/preservation +-3, completeness +-2, formatting/writing +-1) and a sheet whose number contradicts its ledger fails its run; every comparison must carry a `checks` map with one `clean|findings|unable` disposition per frozen check id (M1-M17, M18-M20, J1-J4), so a session that never examined an opponent cannot look calibrated; the incumbent margin (`vs_base` median + wins/losses/ties over the pair's 2*judges directed scores) is printed and stored but stays OUT of the ranking key; the three TEXT-level consistency rules (citation dialect, US/UK spelling, attributive hyphenation) are no longer pre-normalized before judging (`pre_judge_format_policy`) while the published copy still is; the split-review merge deduplicates session B's rows against session A's by (location, evidence prefix); half the panel reads `field/` before `target/`; and `setup --vs-original-rule median|sign` plus `--stop-after-no-progress K` are asserted end-to-end (an all-zero panel pins the incumbent, `run` stops early, `decide` treats the last completed round as the answer). Red on the pre-redesign tree. |
| `test_decide_antiregression.py` | `decide` refuses to certify a FINAL champion the panel judged WORSE than the pristine original: the anti-regression gate exempts the round's own base (the no-progress fallback has to be able to crown it), so this suite builds the round-2 base-champion scenario (`vs_original=-2.0`, `anti_regression_ok=False`) and asserts that the problem is recorded in `decision.json` and the decision exits 5 instead of certifying the regression. |
| `test_anonymized_judging.py` | Console timestamps (every stdout/stderr line carries `YYYY-MM-DD HH:MM:SS `), anonymized judge views (placeholder `d01/`/`f0001<ext>` paths, a per-view permutation, one mtime/mode, no xattrs, no original name anywhere, extension and tree shape preserved, tampering detected by content), the view TRANSFORM (references inside .tex/build files are rewritten to the anonymous names so the package still compiles -- asserted with a real `pdflatex` run; OOXML core/app/custom properties, tracked-change/comment authors and zip timestamps are sanitized; PDF /Info//ID/XMP values are blanked in place) and metadata preservation for every file no judge sees (sandbox, pin, published winner, pristine copy). |
| `test_final_clean_version.py` | `decide`/`run-decide` publishes `<root>/final_clean_version/` with the user's generation counter INCREMENTED by one (`int(filename.split("-")[1]) + 1`: `cnb-11-*` -> `cnb-12-*`; a missing or non-numeric second field keeps the name), the references inside the text files repointed to the new names, decision.json carrying the renamed count plus the pre-rename pin digest and the final digest, byte-stable repeat runs (no `.tmp`/`_superseded` churn) and a direct `setup --source` of the incremented package. |
| `test_parallel_scheduling.py` | The round's dependency graph: the M rewrites and the round's review run CONCURRENTLY, each revise starts when the review marker exists (without waiting for the rewrites), the integrations start when the whole pool is done, the judge wave when the field is complete -- measured with a timestamping stub (`stub_timed.py`), plus the `--jobs` cap, the per-run retry budget and the "permanent failure leaves the round undecided" rule. |
| `test_audit_bugs.py` | The follow-up bug audit: judge-view timestamps (one mtime across `target/`, `field/*` and `original/`), self-healing repair of partially copied inputs, the atomic-write and multi-process-lock races, `decide` reproducibility against a config edit, negative tie-break counts, judge-token collisions, same-second archive names, the oversized-agent-JSON cap and damaged-`state.json` validation. |
| `test_attempt_history.py` | The attempt-history layer: EVERY attempt is kept, not just the last one. Attempts are numbered monotonically across `retry` (`attempts_done`), every postcheck AND every process-level failure appends an entry (errors, warnings, artifact quality, marker summary, timing, source, sandbox) to the run record, a re-postcheck of the same attempt replaces its entry, and the log is capped at 25 attempts per run. The message lists are COMPLETE (no count cap -- `_attempt_messages` keeps 2000 test messages -- with only a total-size guard that names what it left out). A failed attempt's sandbox is archived before the rebuild (`runs/_attempts/<run>/attempt-<n>/`, hardlinked, input corpora and `work/corpus` skipped, self-describing `record.json`) with its transcript moved to `runs/_logs/<run>.attempt-<n>._agent.log` and referenced from the record; the console prints every problem one per line; `status`/DECISION_REPORT.md list the history; `prune` reclaims the archives while state.json keeps the records; and each invocation's console is teed into `reports/<cmd>-<stamp>.log` (recorded in `state.json` -> `run_logs`). |
| `test_artifact_repair.py` | `--strict-artifacts fix` (the scoped ARTIFACT-REPAIR session), per stage: the three-valued policy (`on`/`fix`/`off`, bare `--strict-artifacts`, `--fix-artifacts`, `--non-strict-artifacts`, and an old root's boolean config); a repairable bookkeeping problem for EVERY stage (review audit rewrite revise integrate judge) against a content/contract failure that must stay a plain failure; the byte-level scope and the pinned-evidence guard of each profile (decision-table rows; an auditor's dispositions and `adds`; a judge's resolved/introduced ledger, comparison set and existing coverage entries; a package's manuscript files; a package's bookkeeping and `work/` scratch; the frozen review from any other stage); every stage's prompt (problems verbatim, writable scope, the honest `unable — manual verification required` escape, no unresolved token); and end-to-end runs with `stub_repair_agent.py` for all six stages -- a broken audit sheet, deleted rewrite report, dropped revision-ledger row, deleted integration ledger and stripped judge `checks` map are each repaired and the run completes, a repair that edits the package's manuscript is rejected by the guard, every error of the failed attempt appears in the record/console/run log, and `on`/`off` never and always repair, respectively. |
| `test_zotero_integration.py` | The `zot` CLI (pyzotero-cli) wiring: `setup --zotero {off,read,edit,apply}` (default `edit`) and its persistence in `pipeline_config.json`; the Zotero block in every prompt with the availability line filled in and no unresolved `@@TOKEN@@`; policy propagation (off never names the CLI, read resolves without field edits, edit adds the citation-edit clause, only `apply` reaches the propose-then-verify library-update protocol); the write path is unreachable from review/rewrite/judge even under `--zotero apply`; unknown stored values fall back to the default, never to a more permissive mode; the live-field guardrails (the $zotero-use DOCX reference + bundled validator, parent keys, unique citationIDs, preserved baseline, snapshot-then-prove, no automatic Zotero Refresh) and the apply-mode hard limits (one field on one item, no create/delete, no bulk edit, `--last-modified auto`); plus one real stub round asserting the on-disk PROMPT.md files. |
| `test_length_limits.py` | The abstract/main-text length rule (M19): the Nature Biotechnology Article base limits (abstract <= 150 words; main text <= 3,000 words excluding abstract, Methods, references and figure legends) relaxed by +15%/+25% (caps 172 and 3,750, floored so the margin is never exceeded); the counting definition (maximal runs of non-space characters, newline = space; `state-of-the-art` and `2026` are one word each); the rule and its stage mandate in every prompt (review sweep + mandatory M19 coverage row, revise compression, integration porting, rewrite surfacing, judge formatting tier) with the blanket exemption gone and discovery proposals starting at M20; the code-side proxy scan (abstract/body split, Keywords and blank-line boundaries, Methods/References exclusion, caption subtraction, supplementary/renderings skipped, legacy .doc unparsed, non-manuscript files never counted); and `setup` recording the source scan. |
| `test_docx_format.py` | The OOXML style/formatting audit and normalizer (`nbt_docx_format.py`, wired into `setup`/`decide`): a fixture DOCX carries a break-only paragraph (the blank page), a running head on the title page, tracked changes/proofing markers/literal tabs, per-figure legend spacing, heading style drift without keepNext, an italic correspondence block, an italic `et al.` inside a Zotero bibliography field (field-protected: style/unlink, never a silent run edit), a reference without an italic journal, the same URL hyperlinked and plain, mixed straight/curly quotes and an em-dash flood. Asserts detection, the byte-level fixer (all other parts byte-identical, document text unchanged, `mc:Ignorable` namespaces preserved, `docx validate` clean, mechanical findings 0, idempotent), the extended policy (unlink Zotero fields, align heading sizes, curly quotes), the CLI (`scan --strict`, `fix` refusing to overwrite its input) and - when soffice/pdftotext exist - a real render showing the blank page before and none after. `test_journal_emphasis` adds the 2026-09-21 real-world class: italics that live in Word's `Emphasis` CHARACTER STYLE (invisible to a direct-rPr check), the same journal name italic in one sentence and roman in the next, an emphasis span running on over "other leading journals", and a roman reference-list journal title - plus the false-positive guards (`Cell-line`, `(Single-Cell)`, a URL, an abbreviated `Cell Syst.` title, a legitimate `de novo` italic) and the font/paragraph-`style_survey` artifact. `test_text_consistency_rules` covers FMT-T8a-e (mixed citation formats with the fix that deletes the redundant journal segment across runs, nested parentheses, repetition of a proper name, US/UK spelling, attributive hyphenation) with the guards (reference titles untouched, `T(·,·)` not a nesting, URL/github text ignored) and the `text_diff_only_recorded_edits` proof; `test_deliverable_validation` covers the `validate` command (valid/malformed DOCX, `\input` fragment SKIP, compiling vs failing `.tex`). |
| `test_stage_subset.py` | `run --only <stages>`: the stage-name parser and aliases (`merge`=integrate, `a`/`a2`=revise, `w`, `j`, plurals, `all`), then a real stub-agent end-to-end run that is driven stage by stage - `--only review` (and nothing else starts; the round stays incomplete and says so), `--only revise`, `--only merge`, `--only judge` (which completes the round and pins the champion), `--only review,revise` in one invocation, an unknown stage failing fast with the accepted choices, and `run --help` documenting the flag. |
| `test_only_rounds_integrators_judges.py` | The round-scoped `--only` and the two per-round plan knobs: `--only 1,2` / `--only 1-3` run named rounds in full, `--only 2:review` one stage of one round (a later round asked for before its predecessor is finished reports the unmet dependency instead of "repair the upstream output"), out-of-range rounds and unknown stages fail fast, and the untouched round is neither started nor adopted; `--integrators 0x5` plans exactly the mask's arms (i1/i3 of `[a1, w1, w2, a2]`), the skipped arms get no session/judge row/chance to win and are named in the run log and `DECISION_REPORT.md`, `0x0` runs no integration at all, a pool wider than the 32 bits is refused at setup; `--judges 1,2` gives each round its own panel expectation (`2*judges_r*(|field|-1)`, judge sessions = judges_r x field members, recorded on the round plan), and a zero count is refused. |
| `test_evidence_pack.py` | The code-side evidence pack (M18 counts, M19 lengths, M20 formatting rows, placeholder count, corpus digest/token) and the BLINDING rule: unit checks for the review and stage layouts (JSON + human-readable pack + the seeded M18/M19/M20 tables, and every seeded file declared as an input so the "sandbox already has work" guard ignores it), the four non-judge prompts carrying the pack block, and a stub round asserting that the rewrite, review, revise and integration sandboxes each hold their pack; that a freshly materialized judge sandbox contains NOTHING but the blinded views + prompt (no `CODE_SCANS.json`, no `review/`, no seeded tables) and carries the BLINDING RULE in its prompt; that the orchestrator's own scan of the judge's blinded target is recorded OUTSIDE the sandbox (`reports/judge_evidence_<run>.json`) with a warning when the judge produced no artifact table; and that a stage records its before/after `evidence_delta`. |
| `test_hash_cache.py` | The cached/parallel hashing that makes `decide` fast stays exact: the digest is standard SHA-256; the cache is OFF by default (the `run` path, where agents may still be writing) and ON only for a quiescent `decide`/`status` (a live root lock disables it and warns); a cache hit really avoids `hashlib` and a changed stat key re-hashes; same-size edits and edits that restore the mtime are still detected on the default path; `sha256_files` preserves order, raises by default and honours `on_error`; serial and parallel manifests are identical; two consecutive `decide` runs on one stub root produce identical `decision.json`/`DECISION_REPORT.md` (minus the generation timestamp); `decide` publishes `<root>/final_clean_version/` (champion corpus only, no bookkeeping/auxiliaries, no `action` in the certificate) and `run-decide` runs both phases in series. |
| `test_revision_token.py` | The 7-character content-hash version token that replaced the letter/digit increments: the bundled `nbt-revise/scripts/revision_token.py` and the pipeline's `revision_token_for_dir()` compute the same token; the token is stable across applying it (renaming `-a` names to `-<token>` and repointing a LaTeX reference) and `--verify` proves it; a content change changes the token and fails `--verify`; self-written reports, `.tracked.docx` auxiliaries and `work/` scratch never enter it; `_doc_key()` strips 7-hex tokens like legacy letter tokens while a plain trailing number (`SI-Table-1.csv`) stays distinct; a filename token that contradicts the content is recorded and warned about, never fatal; the revise/rewrite/integration prompts state the rule and no longer carry a live increment instruction. |
| `test_judge_blinding.py` | Blind judging, attacked from every side: the OOXML sanitizer (canonical zip, no thumbnail, no rsid/paraId/textId/proofing/last-rendered-page/attachedTemplate/docVars/track-changes markers, core+app+custom properties neutralized, tracked changes accepted, marker prefix neutralized, idempotent); a Word-saved package and its pipeline-processed twin (revision token in the name, CHANGELOG/MANUAL_STEPS/REVISION_REPORT/revision_report/DIFF_LEDGER/VISUAL_CHECK, `work/`, `*.tracked.docx`, a `.log`/`.aux` build by-product) reduce to views with the SAME tree shape, file types, timestamp, modes and canonical DOCX surface; a view is handed the SOURCES, never what can be compiled from them (a `.bbl` beside its `.bib` and a PDF beside its `.docx`/`.tex` are dropped, a `.bbl` with no `.bib` and a figure PDF with no editable source stay); the build by-products and Word's `~$` owner file are gone; the judge run id carries no round prefix; and the judge prompt contains no round/arm/stage/provenance word, no bookkeeping file name, no marker token, while stating the blinding rule and the neutral placeholder rule. |
| `stub_timed.py` | Wraps `stub_agent.py` with per-stage sleeps and start/end timestamps (and an optional fail-once / always-fail switch) for the scheduling tests. |
| `stub_judge.py` | Deterministic offline judge for the rewrite-arm end-to-end run: one explicit, documented preference (the rewrite's organization, with no later edits stacked on it) so the panel's outcome does not depend on hash ordering. |

## Running

```bash
python3 .nbt_test/test_pipeline.py
python3 .nbt_test/test_bug_audit_2026_0919.py
python3 .nbt_test/test_design_audit_2026_0919.py
python3 .nbt_test/test_fixes.py
python3 .nbt_test/test_candidates.py
python3 .nbt_test/test_candidates2.py
python3 .nbt_test/test_document_recovery.py
python3 .nbt_test/test_llm_stochastic_failures.py
python3 .nbt_test/test_change_requests.py
python3 .nbt_test/test_decide_antiregression.py
python3 .nbt_test/test_audit_bugs.py
python3 .nbt_test/test_parallel_scheduling.py
python3 .nbt_test/test_redesign_v3.py
python3 .nbt_test/test_anonymized_judging.py
python3 .nbt_test/test_docx_converter.py
python3 .nbt_test/test_docx_format.py
python3 .nbt_test/test_stage_subset.py
python3 .nbt_test/test_only_rounds_integrators_judges.py
python3 .nbt_test/test_evidence_pack.py
python3 .nbt_test/test_judge_blinding.py
python3 .nbt_test/test_acronym_longform.py
python3 .nbt_test/test_grading_scheme.py
python3 .nbt_test/test_zotero_integration.py
python3 .nbt_test/test_length_limits.py
python3 .nbt_test/test_hash_cache.py
python3 .nbt_test/test_revision_token.py
python3 .nbt_test/test_final_clean_version.py
```

## Pointing a suite at a baseline copy

`NBT_WS` redirects a suite's workspace (default: the repo this directory sits
in), so the same file doubles as a repro script - it fails on the pre-fix tree
and passes here:

```bash
cp nbt_pipeline.py /tmp/nbt_baseline/           # or copy the whole tree
NBT_WS=/tmp/nbt_baseline python3 .nbt_test/test_document_recovery.py   # red
python3 .nbt_test/test_document_recovery.py                            # green
```

`test_candidates2.py` additionally accepts `NBT_SKILLS` for the skills pack
(default: `nbt-skills/` next to the workspace it is testing).

## End-to-end with the stub agent

```bash
python3 nbt_pipeline.py setup --source <MANUSCRIPT_DIR> --root <ROOT> \
    --rounds 2 --rewrites 2,1 --revises 1,1
python3 nbt_pipeline.py run --root <ROOT> \
    --agent-cmd '["python3","<ABS>/.nbt_test/stub_agent.py"]' \
    --judge-agent-cmd '["python3","<ABS>/.nbt_test/stub_judge.py"]'   # optional
python3 nbt_pipeline.py run-decide --root <ROOT> \
    --agent-cmd '["python3","<ABS>/.nbt_test/stub_agent.py"]' \
    --judge-agent-cmd '["python3","<ABS>/.nbt_test/stub_judge.py"]'
# run-decide = run, then decide; decide also publishes <ROOT>/final_clean_version/
# (the champion corpus with no scratch/auxiliaries/reports), which can seed the
# next pipeline directly: setup --source <ROOT>/final_clean_version --root <NEW>
```

The stub rewrites each stage's artifacts deterministically (rewrites write a
full `rewritten/` package with a `REWRITE_REPORT.md`, revisions a `revised/`
package, integrations an `integrated/` package whose ledger names every donor;
version tokens increment and revised prose gains a marker line), so the whole
round - rewrites, review, revises, integrations, judging, aggregation, pinning
- runs offline in seconds. Without `--judge-agent-cmd` the panel is driven by
`stub_agent.py` too (scores by whole-tree digest, so the winner depends on hash
ordering); `stub_judge.py` scores on one explicit, documented preference
instead.
