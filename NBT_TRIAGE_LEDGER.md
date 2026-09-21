# Bug triage ledger

Evidence-based triage of the candidate set in `nbt_audit_data/` against this
workspace. Verdicts, repro commands and patches; produced by the S0 to S5 state
machine (inventory, ingest, classify/prove, patch, verify).

## S0 - Inventory (resolved absolute paths)

| Path | Size | sha256 | What it does |
|---|---|---|---|
| `docx2pdf.sh` | 3,627 B | `565824adb4fc...` | Bash/WSL wrapper rendering one `.docx` to PDF through Word COM via `powershell.exe -EncodedCommand`; refuses an already-PDF input, clears its derived output first, verifies the PDF exists. |
| `nbt_redlines_adapter.py` | 6,653 B | `94d14a589b28...` | Adapter called by the pipeline for the `redlines` backend: probes python-redlines interfaces, clears a stale OUT first, exits 0/2/4/5/6. (Row refreshed 2026-09-19: the pre-patch 6,182 B / `08884cdd…` snapshot above the B1/B2 patches was stale.) |
| `nbt_pipeline.py` (then `nbt_round_pipeline.py`) | 706,047 B | before `fa36b10a4339...` / now `f9a9c6b7bfde...` | Round orchestrator: setup/run/status/decide/retry, sandbox materialization, postchecks, judging, aggregation, pinning, decision reports; renamed to `nbt_pipeline.py` and given the content-hash filename rule after this triage. |
| `nbt-skills/**` (18 files) | - | see `sha256sum` output in the task report | The `$nbt-review` and `$nbt-revise` skills (SKILL.md, references, 5 scripts) plus the shipped `tests/validate_skill.py` harness. |

Path resolution, per the task's own rule:

* `~/.codex/skills/nbt-skills-v03/` does not exist here; `~/.codex/skills/` holds
  `nbt-skills-v04/`, whose 18 files are byte-identical to the tracked `nbt-skills/`
  in this repo. Searching the workspace and `$HOME` for the basename therefore
  resolves the skills surface to `nbt-skills/` - the same files that are
  installed as v04, so there is no diverging copy to patch separately.
* Candidate sources are the four zip archives in `nbt_audit_data/` (the chat URLs
  listed in the prompt were mirrored into those archives by the operator; the
  archives are byte-exact and are what was ingested).

Environment: WSL2 (Linux 5.15.167.4), bash, Python 3.12.5
(`/home/zhaoxiaofei/miniconda3/envs/ralph/bin/python3`), `soffice` and
`powershell.exe` present, no network. Tests: `python3 .nbt_test/test_*.py` and
`python3 nbt-skills/tests/validate_skill.py --skill-root nbt-skills --run-dir <tmp>`.

Baseline before any edit, all green (so no pre-existing failure needed triaging
first):

| Suite | Result |
|---|---|
| `.nbt_test/test_candidates.py` | ALL CANDIDATE CHECKS PASSED |
| `.nbt_test/test_candidates2.py` | ALL ROUND-2 CANDIDATE CHECKS PASSED |
| `.nbt_test/test_fixes.py` | ALL FIX CHECKS PASSED |
| `.nbt_test/test_pipeline.py` | ALL CHECKS PASSED |
| `nbt-skills/tests/validate_skill.py` | 40 checks, 0 failed |

## S1 - Ingested candidates (deduplicated)

Sources: A = `nbt-pipeline-fix-conversation.zip`, B =
`nbt_round_pipeline_v2.2.0_fix_conversation_branchA.zip`, C =
`nbt_round_pipeline_v2.2.0_fix_conversation_branchB.zip`, D =
`revise_code_revision_bundle.zip`. The three pipeline archives carry the same
observed failure; A/B/C each propose a variant of the fix, which is why the items
below merge them.

## S2 - Verdicts

### C01 - a dropped base document hard-fails the round, three times - CONFIRMED

* Sources: A, B, C (`raw_figs/entire_pipeline.git-snapshot.txt`, `r1_a2_revise`).
* Surface: `nbt_round_pipeline.py` - `_caption_and_document_checks()` calling
  `document_set_check()`, plus `postcheck_revise()` and `postcheck_cross()`.
* Claim: the revise agent omits a base file; `document_set_check()` reports it
  missing; the check appends an unconditional error, so the run fails, the
  sandbox is rebuilt, a fresh ~45-minute session drops the same file again, and
  after the retry budget the round is left incomplete. The omission is
  name-driven (a `.txt` that reads as git metadata), so retries cannot fix it.
* Evidence, pre-fix, against a baseline copy at `/tmp/nbt_base`:
  `NBT_WS=/tmp/nbt_base python3 /tmp/nbt_repro/repro_c01.py` gives postcheck
  `ok=False` with error `document(s) present in the base are missing from the
  candidate and their content was not found under any name:
  raw_figs/entire_pipeline.git-snapshot.txt`, and 5/5 checks fail.
  `.nbt_test/test_document_recovery.py` is red on the baseline (13 failing
  checks) and green after the patch.
* Patch: new `backfill_missing_files()` (with `_candidate_corpus_files`,
  `_candidate_dest`, `_is_derived_name`, `DERIVED_BUILD_SUFFIXES`,
  `_PDF_TWIN_EXTS`) hooked into `postcheck_revise()` against `base/` and
  `postcheck_cross()` against `self/` immediately before the document-set
  comparison; a still-missing file becomes a names-first warning instead of a
  hard error.
* Comparison with the posted suggestions: ported from C's
  `backfill_missing_files` essentially verbatim where the surrounding helpers
  exist. B's `--missing-document-policy` and A's `--ask-llm-on-missing` knobs
  were not adopted: they add configuration surface this defect does not need and
  no repro required them.
* Attempts: 1/6. Tests: `.nbt_test/test_document_recovery.py` D1-D8 and D12
  (idempotent second postcheck).
* Residual risk: the PDF-twin test is name-based; a data PDF sharing a stem with
  an unrelated editable file in the same directory is left out and named in the
  warning, so it is visible and recoverable by hand.

### C02 - silent loss of non-editable assets (pdf/png/pptx/tsv) - CONFIRMED, same root cause as C01

* Sources: B, C (predicted sibling P2).
* Claim: the document-set check only protects `EDITABLE_DOC_EXTS`, so a candidate
  that loses figure or data assets is never flagged and never repaired.
* Evidence: on the baseline the D2 fixture drops four assets and the postcheck
  reports no error and restores nothing; after the patch all four are restored
  because C01's backfill walks every base file.
* Patch: covered by C01. Tests: D2.

### C03 - a compiled-PDF twin must not be resurrected - CONFIRMED, contract that C01 must not break

* Sources: B, C (P5).
* Claim: a naive copy-every-missing-file recovery would re-add a compiled PDF
  whose editable twin was deliberately edited and left out.
* Evidence: D4a asserts the edited-twin PDF is NOT restored, is named in a
  warning, and the run still passes; D4b and D4c assert the unchanged-twin and
  no-twin PDFs ARE restored. All three are red on the baseline, green after.
* Patch: covered by C01 via the `_PDF_TWIN_EXTS` test.

### C04 - renamed documents must not be duplicated - CONFIRMED, contract

* Sources: B, C (P3). Evidence: D5 - after renaming `...-b.docx` to `...-c.docx`
  the old name is not re-added and `document_set` reports no missing docs.
* Patch: covered by C01 via the content-digest and version-stripped-key skips.

### C05 - 0-byte candidate files are silent holes - CONFIRMED, contract

* Sources: B, C (P4). Evidence: D6 - a truncated `...git-snapshot.txt` is
  restored non-empty; the baseline neither restored it nor flagged it.
* Patch: covered by C01.

### C06 - `revise_code.py` carry_over_untouched FileNotFoundError - OUT_OF_SCOPE

* Source: D. The module exists only inside the archive's own synthetic
  `source_dir_project/`; a `find` over the workspace and `$HOME` returns no such
  file, and no in-scope file carries that routine. The nearest in-scope analogue
  is the pipeline's document-set and carry-over machinery, fixed as C01. Not
  patched.

### C07 - a second `run` is a no-op after the retry budget is spent - CONFIRMED

* Sources: B, C (P12).
* Surface: `nbt_round_pipeline.py` `run_phase()` - the failed-run gate
  `elif rec["attempts"] > retries:` (a lifetime counter) and the
  malformed-output branch's identical check.
* Claim: `attempts` is persisted, so once three attempts failed in an earlier
  invocation, re-running `run` skips the run and exits with the old error, which
  reads like a hang.
* Evidence: `NBT_WS=/tmp/nbt_base python3 /tmp/nbt_repro/probe_retry.py` starts
  no agent wave at all (`started=[]`, `attempts=3`, `status=failed`). After the
  patch the same invocation starts three attempts at `retries=2`. D9 asserts it.
* Patch: gate both checks on `failures_in_phase` (per invocation, already
  maintained for the backoff); the lifetime counter stays for the audit; the
  failure message and the `run` resume hint now say re-running grants a fresh
  budget.
* Comparison with the posted suggestion: same approach as C.
* Attempts: 1/6. Residual risk: a repeated `run` can spend agent time again by
  design, which is the operator's explicit request.

### C08 - a judge's label case/whitespace slip shrinks the panel - CONFIRMED

* Sources: B, C (P9).
* Surface: `validate_judge_sheet()`, `judge_sheet_complete()`, `aggregate_round()`.
* Claim: labels are issued as `v1...vK`; an LLM writing `"V1"` or `" v2 "` fails
  the exact-match check, so the sheet looks short, the run fails, and the panel
  can stall even though the judge scored the right opponent.
* Evidence, baseline: `/tmp/nbt_repro/probe_misc.py` shows
  `validate_judge_sheet` returning `comparisons omit 2 issued label(s):
  ['v1', 'v2']` and `judge_sheet_complete` returning False; after the patch both
  accept the sheet and warn twice. D10a-D10d assert that a genuinely omitted
  label still fails, and D11 asserts the aggregator collects the normalized
  directed score (`n=2`).
* Patch: `_norm_opponent_label()` (strip and lower) used in the three places; a
  normalization emits an informational warning.
* Comparison with the posted suggestion: same approach as C. Attempts: 1/6.
* Residual risk: two labels differing only by case would collide; labels are
  issued as `v1...vK`, so this cannot occur in a pipeline-built run.

### C09 - marker stage synonyms - NOT_A_BUG

* Sources: B, C (P7). `_marker_checks()` hard-fails `"stage": "phase 2"`.
* Why not a bug: the marker file, its path and its schema are pinned by the
  prompt contract, and the check is deliberate - a mismatched marker is the
  signal that the wrong stage wrote it. The sources propose accepting synonyms
  as a policy change with no reproduction on this tree. Unchanged by design.

### C10 - missing visual-inspection record - NOT_A_BUG

* Sources: B, C (P10). `check_visual_artifact()` fails when the record is absent.
* Why not a bug: the docstring states the contract (a missing record fails the
  run; silence is not an acceptable outcome) and the shipped audit fix record
  marks it fixed. The record may state "not visually verified" and hand the check
  to the author, which is a warning path, not a failure. Unchanged by design.

### C11 - ledger-format tolerance - NOT_A_BUG (already tolerant)

* Sources: B, C (P11). On this tree the revise ledger check already degrades to a
  warning when a human-readable ledger exists, and `.nbt_test/test_pipeline.py`
  covers the ledger surfaces and passes both before and after. No repro of a
  false failure. No patch.

### C12 - judge_review/ misplacement - NOT_A_BUG

* Source: C (P6). On this tree a missing or empty `judge_review/` is a hard error
  by design: the panel's grounding cannot be verified without it, and the judge
  session is the cheapest to re-roll. No reproduction of a false failure. No
  patch.

### C13 - read-only-bit and layout-impossible rebuild failures - CANNOT_REPRODUCE

* Source: B (E7, E8). Speculative permission and layout scenarios with no
  attached reproduction. `rebuild_sandbox` runs throughout the suites here
  (including under `/tmp` and in-tree) without hitting them. Not patched.

### C14 - agent-writable frozen inputs, panel completeness, evidence integrity - NOT_A_BUG

* Source: B (the deliberately-hard-failed list). These are integrity gates whose
  failure means a run's provenance or panel is unreliable; restoring bytes
  cannot un-do an agent having acted on tampered findings. Preserved unchanged.

### C15 - console truncation of the missing-file diagnostic - CONFIRMED (diagnostic only)

* Sources: A, B, C (P13).
* Evidence: the pre-patch symptom string puts the file list after 110 characters,
  so the `[:140]` console slice prints `raw_figs/entire_pipeline.git-`. The D8
  check is red on the baseline and green after: the names-first warning prints
  the full path within the first 140 characters.
* Patch: folded into C01's warning rewrite, names first.

### C16 - stochastic-LLM robustness pass - CONFIRMED (round 3)

A third pass asked what the pipeline does when an agent fails in ways the earlier
rounds did not cover: JSON wrapped in a markdown fence or prose, a UTF-8 BOM,
`null`/wrong-typed payloads where an object was asked for, a document replaced by
a symlink or a directory, a file the process cannot read, an artifact tree it
cannot walk. Probed against the real postcheck/aggregate code paths; four defects
reproduced and are fixed here:

* **Unreadable candidate file crashed the orchestrator.** After a passing
  postcheck, `recompute_corpus_digest()` read the candidate corpus outside the
  handler's try/except (`sha256_file` -> `PermissionError`), so a chmod-000 or
  locked file raised a traceback mid-round instead of failing the attempt. Fix:
  the success-path digest is guarded and reports a names-first error, and the
  recovery layer now restores an unreadable candidate file from the
  hash-verified base copy (it is not usable content). Evidence: probe shows a
  PermissionError traceback before, and `ok` with a RECOVERY warning after.
* **A base document replaced by a symlink or a directory was silently accepted.**
  `exists()` is false for a dangling symlink and true for a directory, so the
  backfill skipped the loss, the document-set check saw a name, and the round
  reported "done" with an unusable package. Fix: any non-regular destination is
  restored from the base copy with a RECOVERY warning; a NON-EMPTY directory is
  refused (never deleted: that may be real agent work) and the refusal now
  fails the attempt through `backfill["unresolved"]`.
* **A wrong-shaped ledger passed as complete.** `revision_report.json` holding
  `null`, `[]` or a one-line string satisfied the parse-only check while giving
  the author nothing to audit. Fix: the ledger must be a list of finding rows
  (bare or under findings/revisions/rows/ledger/items/entries) or a non-empty
  report object; anything else is a clean retry. An empty-but-typed ledger is
  still accepted, because a genuine all-clean run has no rows.
* **Fenced/prose/BOM JSON wasted a retry.** `read_json` used a strict utf-8
  parse, so a complete marker or judge sheet wrapped in ```json (or written with
  a BOM) failed as malformed. Fix: `read_json` is BOM-tolerant and, for
  AGENT-written files only, recovers a complete JSON document from a fence or
  short prose margin via `raw_decode`; truncated payloads still fail, and the
  pipeline's own state/config stay strict.

Evidence: `.nbt_test/test_llm_stochastic_failures.py` (47 checks, red on the
pre-fix tree with 16 failures, green after) plus an end-to-end adversarial run:
after a real stub-agent round, a dangling symlink, a chmod-000 document and a
fenced marker were injected into the revise sandbox; the recheck restored both
files with RECOVERY warnings, kept the run `done`, and produced a digest.

Tests added: that suite, and `stub_agent.py` now writes one ledger row per
finding id (it previously wrote an empty `findings` list, which the corrected
ledger contract rejects - the stub was violating the contract, not the code).

## S3-S4 - Patches and local verification

Three patches, all in `nbt_round_pipeline.py`, plus one new test file, each
applied to the real tree and verified individually:

1. C01 recovery layer (backfill plus names-first warning): repro
   `/tmp/nbt_repro/repro_c01.py` flips 5/5 fail to 0/5 fail; D1-D8 green.
2. C07 per-invocation retry budget: probe flips 0 to 3 attempts; D9 green.
3. C08 judge-label normalization: probe flips errors to accepted; D10/D11 green.

Regression risks considered: callers of the touched surfaces are
`postcheck_revise` and `postcheck_cross` (postcheck), `run_phase` (the retry
loop), and the judge pipeline (`validate_judge_sheet` to `judge_sheet_complete`
to `apply_results` to `aggregate_round`). On-disk formats are unchanged;
`rec["backfill"]` is a new additive state key read elsewhere only through
`.get()`, so roots created before this patch still load. CLI flags and exit
codes are unchanged because no new flags were introduced. Re-running a postcheck
over an already repaired sandbox restores nothing a second time (D12).

## S5 - Integration verification

| Check | Result |
|---|---|
| `python3 -m py_compile nbt_round_pipeline.py nbt_redlines_adapter.py` | OK |
| `bash -n docx2pdf.sh` | OK |
| `.nbt_test/test_pipeline.py` | ALL CHECKS PASSED |
| `.nbt_test/test_fixes.py` | ALL FIX CHECKS PASSED |
| `.nbt_test/test_candidates.py` | ALL CANDIDATE CHECKS PASSED |
| `.nbt_test/test_candidates2.py` | ALL ROUND-2 CANDIDATE CHECKS PASSED |
| `.nbt_test/test_document_recovery.py` | ALL DOCUMENT-RECOVERY CHECKS PASSED (baseline: 13 failing) |
| `.nbt_test/test_llm_stochastic_failures.py` | ALL STOCHASTIC-FAILURE CHECKS PASSED (47 checks; baseline: 16 failing) |
| `nbt-skills/tests/validate_skill.py` | 40 checks, 0 failed |
| CLI smoke: `setup`, `run --agent manual --no-wait`, `status` on a synthetic root | OK (stages the run, writes `PROMPT.md`, reports) |

Not performed, stated honestly: a full four-stage agent run (review, revise,
cross, judge) needs live LLM sessions this environment does not have; the
recovery layer is exercised instead through the real `postcheck`,
`recompute_corpus_digest`, `apply_results` and `aggregate_round` code paths in
the suites above. `docx2pdf.sh`'s Word rendering path is not exercised here (it
launches Word over COM in a real Windows session); it was not part of any
confirmed defect and is unchanged.

## SUMMARY

* Ingested: 16 candidate classes (15 deduplicated from A-D plus the round-3
  stochastic-robustness pass, C16).
* Confirmed: 9 (C01-C05, C07, C08, C15, C16); C02-C05 and C15 are the recovery
  layer's own contract or diagnostics and are fixed by the C01 patch, and C16
  covers four further defects found by probing stochastic agent failures.
* Patched: 4 rounds of changes / 9 confirmed items, all in
  `nbt_round_pipeline.py` (plus tests and the stub agent under `.nbt_test/`).
* Unfixed: none in scope. C06 is OUT_OF_SCOPE (no such file in the workspace).
* FALSE_POSITIVE: 0 - NOT_A_BUG: 5 (C09-C12, C14) - CANNOT_REPRODUCE: 1 (C13) -
  OUT_OF_SCOPE: 1 (C06).
* Process exit: 0 - every in-scope confirmed item is patched with a repro that
  was red before and green after, and the integration sweep is green.

## S6 - Pool/integration round model, configurable M/N, and the follow-up bug audit

Two later change sets are recorded here for the same reason as S1-S5: each item
below has a repro that is red before and green after (the suites named next to
it), so the reasoning and the evidence stay in the repository.

### S6a - The round model (change requests)

* **Pairwise "cross-pollination" replaced by whole-pool INTEGRATION.** There are
  no `b*` arms any more. A round's POOL is `[a1, w1..wM, a2..a{1+N}]`, and every
  pool member is reworked ONCE, in its own session, with that member as the base
  (`self/`) and EVERY other pool member as a donor (`others/<version-id>/`):
  `i1 = a1 <- (w1..wM, a2..)`, `i2 = w1 <- (a1, w2.., a2..)`, ... K = 1+M+N runs.
  The integration ledger must name every donor; a donor that is absent from the
  ledger is reported (`postcheck_integrate`), and the donor directories are
  verified against the current pool corpora by the input-freshness layer.
* **M (`--rewrites`) and N (`--revises`) are command-line parameters**
  (`setup --rewrites 2,1 --revises 1`, defaults `[2,1]`/`[1,1]`). Each takes one
  integer (the same count every round) or a comma/space separated per-round list;
  a list shorter than `--rounds` is EXTENDED BY REPEATING ITS LAST ELEMENT, a
  longer one is truncated. One `$nbt-review` pass per round feeds all N
  `$nbt-revise` sessions, so N revisions share one frozen `review/` copy.
* Every arm is a first-class candidate: same field, same judges, same ranking
  key, same pin/winner machinery; the plan (`pool` + integration map) is stored
  on the round record and printed in setup and in the decision report.
* Suite: `.nbt_test/test_change_requests.py` (110 checks, including two stub-agent
  end-to-end rounds: the default plan and a custom `--rewrites 1 --revises 2`).

### S6b - Confirmed bugs found by the follow-up audit

| # | Finding (confirmed by a probe) | Fix | Repro / guard |
|---|---|---|---|
| A1 | `original/` in every judge sandbox kept the AUTHOR's real mtimes while `target/` and `field/*` were stamped with one view time, so a judge could tell the original view (and, in round 1, the field label holding the original) apart by timestamp -- contradicting the prompt's "metadata says nothing" rule. | every judge view (`target/`, `original/`, `field/*`) is re-stamped with the session's single `view_stamp` after materialization. | `test_audit_bugs.py` A |
| B1 | Materializers only copied an input when the destination was MISSING, so a sandbox killed in the middle of a copy froze the PARTIAL input in place; the truncation was then recorded as the run's frozen manifest, and the agent/candidate were compared against the truncated base -- a silent document loss that no later check could see. | `ensure_copy()` / `ensure_corpus_dir()` verify each input area against its current upstream corpus and rebuild it when it does not match (also drops donor dirs that are not in the pool, and rebuilds `prior_round/`). | `test_audit_bugs.py` B |
| B2 | A judge sandbox that already had a `PROMPT.md` and a record was reused without any check, so a damaged `target/`/`field/` view would be judged as if it were the whole corpus. | damaged views of an untouched sandbox mark the run `stale` (the staging loop rebuilds it); a damaged sandbox that already holds agent output is left to the postcheck. | `test_audit_bugs.py` B |
| C1 | `write_json_atomic()`/`write_text_atomic()` shared one fixed `<name>.tmp`: two writers could rename each other's half-written bytes into place, or crash with `FileNotFoundError` after the other had renamed the shared temporary away. | unique temporary per writer (pid + counter), `flush()` + best-effort `fsync()`, cleanup on failure. | `test_audit_bugs.py` C |
| C2 | Nothing serialised the root: two `run` processes both saw the same pending runs, both launched agents into the SAME sandbox, and each saved its own `state.json`, silently dropping the other's run records. | `Ctx.lock()` (advisory pid-file lock) held by `run`, `retry`, `prune` and `redline`; a lock whose owner is gone is reclaimed with a warning. | `test_audit_bugs.py` C |
| D1 | `decide` re-derived each round's candidate set from the MUTABLE config, so editing `--rewrites`/`--revises` (or restoring a config from a backup) made it recompute a different champion and report a bogus integrity problem about perfectly good judge sheets. | `round_counts()` prefers the plan recorded on the decided round; invalidation clears it, so a re-run re-derives it from the config. | `test_audit_bugs.py` D |
| E1 | A marker reporting a NEGATIVE `critical_remaining` sorted ahead of an honest 0 and won the statistical tie-break. | `_valid_count()` treats an impossible count exactly like a missing one (+inf sentinel) and the postchecks warn about it. | `test_audit_bugs.py` E |
| F1 | Two versions whose salted judge tokens collided (32-bit truncation) would silently share one sandbox and be judged under two labels. | token collisions are detected before any sandbox is built and refused with an explanatory error. | `test_audit_bugs.py` F |
| F2 | Superseded pin/winner/`final/` archives and stashed agent logs were named with a SECOND-resolution UTC stamp, so two operations in the same second nested one archive inside the other (or overwrote the only log of a failed attempt). | `unique_path()` suffixes `-2`, `-3`, ... for every archive/log name. | `test_audit_bugs.py` F |
| F3 | `read_json()` loaded agent-written files of unbounded size; a runaway agent writing a multi-GB `findings.json`/`scores.json` could exhaust memory (the orchestrator must never die that way). | `MAX_JSON_BYTES` (64 MiB) cap in `read_json()` plus an explicit "over the agent-output limit" problem in `structured_output_problems()`. | `test_audit_bugs.py` F |
| G1 | A `state.json` whose run record lacked `sandbox` passed `load()` and crashed later with a bare `KeyError` inside `status`/`retry`. | `load()` validates every run record (sandbox path, numeric round) and `rounds`/`pinned` types, and names the damaged record. | `test_audit_bugs.py` G |

Not defects, checked and left alone (so a later pass does not re-open them):
`docx2pdf.sh` quoting/`-EncodedCommand`/output verification, `nbt_redlines_adapter.py`
stale-OUT clearing, `convert_corpus.py`'s flattened-name collision suffix, the
judge label permutation (salt-seeded, F12), the field mtime equalization for
`target/`+`field/*` (F1e), and `prune`'s never-touch-anything-but-sandboxes rule.

Verification for S6: `.nbt_test/test_pipeline.py` (51), `test_fixes.py` (31),
`test_candidates.py` (20), `test_candidates2.py` (18), `test_document_recovery.py`
(31), `test_llm_stochastic_failures.py` (47), `test_pipeline_audit_findings.py`
(25), `test_change_requests.py` (110) and `test_audit_bugs.py` (all green;
`test_audit_bugs.py` is red on the pre-fix tree), plus
`nbt-skills/tests/validate_skill.py` (40/0) and `probe_regressions.py` (0 failed).

### S6c - The round is a dependency graph, not a sequence of barriers

Requested: "the rewrite and review-revise steps should be run in parallel, and
all other steps as much as possible". The old driver ran the stages one after
another (rewrites, then review, then revises, then integrations, then judges),
so e.g. a revise could not start until every rewrite had finished even though it
only needs the review.

`drive_round` now hands the whole round to `run_round_runs()` (plus
`round_run_plan()`, the DAG): each run's sandbox is materialized the moment its
dependencies are done, and it is submitted to a `--jobs`-bounded thread pool
immediately. The resulting order:

* the M rewrites and the round's single `$nbt-review` both depend only on the
  base, so they START TOGETHER;
* each of the N revise sessions starts the moment the review marker exists --
  independently of the rewrites and of its sibling revisions;
* the K = 1+M+N integration runs start once the WHOLE pool (base, rewrites,
  revisions) is done, and run in parallel with each other;
* the judge wave starts once the field is deduplicated and runs in parallel.

Every run keeps the per-invocation retry budget and the exponential backoff
(a failed attempt rebuilds only its own sandbox and is re-queued), a run whose
dependencies never complete is never started, and a permanently failed session
still leaves the round `pending` (exit 3) with no pin/winner instead of deciding
on a shrunk pool. Manual mode follows the same dependency order and `--no-wait`
now prints EVERY currently-runnable prompt (the rewrites and the review at
once).

Evidence: `.nbt_test/test_parallel_scheduling.py`, which runs real rounds
through a timestamping stub (`stub_timed.py`) and asserts the overlaps and the
dependency `>=` gaps from the measured start/end times, that `--jobs 1`
serialises everything (max concurrency 1), that a once-failing session is
retried to completion, and that a permanently failing session leaves the round
undecided with its dependents never started. Red on the pre-change tree (the
old driver has no `run_round_runs` and cannot overlap the review with the
rewrites).

### S6d - Timestamped console output, anonymized judge views, metadata preservation

Requested: (1) every stdout/stderr message of `nbt_round_pipeline.py` must show
the current datetime as `year-month-day hour-minute-second`, and (2) names,
timestamps, attributes and metadata must be PRESERVED for every file no judge
sees, while everything a JUDGE sees must be anonymous (paths that disclose
nothing, one timestamp, one set of attributes).

* **Console timestamps.** `install_timestamped_streams()` (called by `main()`)
  wraps `sys.stdout`/`sys.stderr` in `TimestampedStream`, which prefixes every
  LINE -- including the continuation lines of a multi-line `die()` message and
  `--help` -- with the current local time in `%Y-%m-%d %H:%M:%S` form. The
  prefix is evaluated at write time, so a long run's log shows when each step
  happened. Agent subprocess output is unaffected: it is captured into the
  sandbox's `_agent.log`, not printed.
* **Anonymous judge views.** `materialize_judges()` no longer copies a package
  under its own names. `build_judge_view()` materializes each view
  (`target/`, every `field/<label>/`, `original/`) as placeholders: directories
  become `d01`, `d02`, ... and files `f0001<ext>`, permuted per view from a seed
  of (per-root salt, session token, judge index, view) -- so the same document
  has a different name in the target and in every opponent, and no cross-view
  correlation is possible. Files are copied by CONTENT only (`shutil.copyfile`),
  so ownership, ACLs, xattrs, flags, modes and mtimes never travel; the whole
  view then gets one mtime and one mode (0o644 files / 0o755 directories).
  Extensions are kept (the judge needs the file type) and the tree shape is kept
  (grouping is package structure, not provenance), and the judge prompt now
  explains the anonymization and forbids scoring internal filename references
  ("my figure file is missing") as defects -- the orchestrator verifies the real
  file set mechanically.
* **Content-based verification everywhere a judge view is involved.**
  `content_multiset()`/`judge_view_digest()`/`_view_digest()` replace the
  path-keyed comparisons for judge inputs: the freshness revalidation, the
  damaged-view detection in `materialize_judges()` and
  `_check_pristine_copy(..., content_only=True)` for `original/` all compare the
  multiset of file digests, which still catches any edit or truncation.
* **Metadata preservation for non-judged files.** `build_corpus_dir()` no longer
  normalizes mtimes, so pins, published winners, the integration views
  (`self/`, `others/<id>/`) and the pristine copy keep the agent's/author's
  names, mtimes, modes and attributes (`shutil.copy2`/`copytree`, including
  xattrs). Only judge views are anonymized/normalized.

Evidence: `.nbt_test/test_anonymized_judging.py` -- timestamps on stdout, on the
continuation lines of a multi-line stderr error and on `--help`; no original
file name, stem or directory name in any of the 216 judge-view files of a real
round; every judge path matching `(v<k>/)?(d\d\d/)?f\d{4}<ext>`; identical
extension multiset and content multiset; a single mtime and only 0644/0755 modes
across every view entry; no xattrs; distinct per-view seeds; a one-byte edit in
a view resetting exactly that judge run; and pins/winners/pristine copies keeping
the agent's 0600 mode and old mtime. Red on the pre-change tree.

### S6e - The docx-converter MCP tool is tried FIRST for every .docx -> .pdf

Requested: use the `docx-converter` MCP service (declared in
`~/.codex/config.toml`) to convert a .docx to its PDF before trying any other
tool.

* The service (`[mcp_servers.docx-converter]`: node +
  `~/mcp-docx-converter/index.js`) exposes exactly one tool,
  `convert_docx_to_pdf(docxPath)`, which renders through Microsoft Word via
  WSL/PowerShell interop (`docx2pdf.sh`). It was exercised directly over the MCP
  stdio protocol: `initialize` -> `tools/list` (the tool is listed) ->
  `tools/call` on a sample .docx, which produced the PDF next to it
  (`sample-a.pdf`, 96,904 bytes).
* The pipeline now probes the operator's Codex config
  (`codex_config_path()`, `CODEX_HOME` aware, quoted or plain section names) and
  only reports the tool as available when the section exists AND the files it
  names are still on disk (`mcp_server_configured()`), so a deleted server
  script cannot make the prompts promise a converter that would fail.
  `probe_available()` lets one probe list mix PATH executables and `mcp:<server>`
  entries; the MCP tool is the FIRST entry of `VISUAL_TOOL_PROBES` and the first
  name in the "Converters available on this machine right now:" line of every
  prompt.
* `VISUAL_INSPECTION_RULE` now says: ALWAYS TRY THE `docx-converter` MCP TOOL
  FIRST, BEFORE ANY OTHER CONVERTER (`convert_docx_to_pdf(docxPath=<absolute
  WSL path>)`), and only fall back -- in order -- to `docx2pdf.sh`,
  `docx render`, LibreOffice, Word COM and pandoc. The optional `docx` CLI block
  repeats the rule, and `run` prints which converter the agents were told to use
  first.
* Related correctness fix: every one of those converters writes its output next
  to (or under) the file it is handed, and `target/`, `field/*`, `base/`,
  `non-revised/` and `original/` are hash-verified. The visual rule therefore
  instructs the agent to convert a COPY inside its own writable work directory
  (`judge_review/work/`, `revised/work/`, `rewritten/work/`,
  `integrated/work/`) and states that a PDF/image appearing inside a read-only
  view is treated as tampering and fails the run (the existing
  `input_mismatches` check enforces it).

Evidence: `.nbt_test/test_docx_converter.py` -- config-probe cases (valid
section, quoted section name, CODEX_HOME redirect, deleted server script,
missing config), probe ordering and summary, per-prompt assertions for all five
stages (tool named first, MCP before `docx2pdf.sh`, ordering inside the visual
rule, no unresolved tokens, the work-directory rule), and a live stdio handshake
with the configured server; the real conversion is opt-in
(`NBT_TEST_DOCX_MCP=1`) because it needs Word.

## S7 - Acronym long-form residues are now found, fixed and scored (M1b / rule (k))

Reported: "copy-number [or copy number] is abbreviated as CN at its first use,
but the manuscript main text still uses its non-abbreviated forms in the rest
of the main text — why is it never revised?" Confirmed against the production
run `cnb01-d2f-091722-ab78d4f` (`runs/r1_review/review/`): the `CN` row of the
M1 artifact read `n=238, defined at first use: Y, one expansion, consistent: Y`
— healthy in every column — while the long form appeared 50+ times after the
definition. The error class was invisible at four separate stages, so no
finding was ever produced and nothing could be revised:

| Stage | Why the residue stayed invisible | Fix |
|---|---|---|
| Detection (M1) | `extract_acronyms.py` enumerated acronym-like TOKENS only; long-form occurrences were counted nowhere, and rules (a)–(j) had no rule for "expansion re-used after its first use" (rule (c) fires only when the acronym is used exactly once, and its conventional remedy — delete the definition — is the wrong direction). | the M1b reverse-direction audit: for every acronym with a recorded definition, every un-abbreviated long form after that context's first long-form occurrence becomes an instance row in `M1_acronyms.md` (variant-tolerant: case/hyphen/plural; definition site and quoted titles exempt; page furniture annotated; family-aware `short_form_uses` so (c) no longer misfires). |
| Spec | the M1 finding rules had no (k) and M8's variant rule is position-unaware, so a reviewer could not express "long form is fine up to first use, short form required after". | `references/sweeps.md`: new rule **(k)** (one finding per M1b row), rule (c) amended, M8 carve-out, artifact-column spec; prompts re-synced verbatim (D10/D10b green). |
| Revision | `edit_rules.md` had no fix direction; E-rules push toward locality, so an editor facing "copy-number" reverts to the long form. | new rule **P1a**: substitute the acronym per flagged occurrence, never expand a short form or delete the definition, pluralise/compound correctly, manual-required for quotes and generated renderings, and the V3 rescan must show zero M1b rows for the edited contexts. |
| Selection | the judge prompt filed "wording preferences that do not change meaning" as cosmetic (0 points), so a version that fixed the convention earned nothing. | `JUDGE_DIRECTIVES`: systematic consistency failures are NOT cosmetic; the M1b table is named as the evidence surface. The revise prompt gains the same recipe plus the rescan gate, and the review postcheck now FAILS a review whose M1b table has rows while `findings.json` raises no M1 finding and the M1 coverage row does not account for them. |

Two bugs in the first cut of the matcher were found by the new tests and fixed:
a hyphenated long form that the strict token detector also matched
(`Copy-Number`) was dropped as "another acronym" — silently killing the whole
CN audit on corpora with one capitalised slip — and definition spans were
recorded lowercase while the token kept its case, so an acronym's OWN
definition site was misread as another term's and its first-use slot was
handed to a later, genuine residue. A third, pre-existing defect surfaced on
the way: `classify_context()` ran the `supp`/`fig` heuristics before the
reference patterns, so a supplement's `.bib` was swept as supplementary text
and its reference titles/abstracts fed the M1 inventory (64 phantom tokens on
the production corpus).

Evidence (all red before this change, green after):

* `.nbt_test/test_acronym_longform.py` — 30 checks: the reported case
  (abstract definition -> main-text residues, 4/4 rows with the definition site
  and each context's first use exempt), variant tolerance, capitalized-token
  regression, per-context first use, cross-context definition, abbreviation-key
  definitions (`CN, copy number;`), quoted titles counted not flagged,
  another term's definition site, page-furniture annotation, bibliography
  exclusion, the closed loop (P1a substitution -> zero rows), spec/prompt/
  directive wiring and the orchestrator's M1b gate.
* `nbt-skills/tests/probe_regressions.py` R15–R20 (`FAIL R15..R20` on the
  pre-fix tree) and `tests/validate_skill.py` C25–C26 (42 checks total).
* Production corpus: `/mnt/c/.../cnb01-d2f-091722-ab78d4f/runs/r1_review/review/work`
  -> `M1 artifact: 600 unique tokens; M1b: 117 long-form re-use rows across 11
  acronyms` (94 for `CN`, 28 of them in the main text; the same run reported
  0 such rows before this change), and after substituting the acronym for the
  flagged occurrences (P1a-style, on a /tmp copy) the re-scan reports
  `CN rows before: 94 -> after: 0` with the `CN` token count rising 238 -> 340
  — the residue becomes the defined acronym, and the sweep proves it.

## S8 - Grading scheme: a checkable basis, a provenance-free tie-break, a panel that cannot be poisoned

Question asked: should the judging scale be redesigned (wider range, aspect
sub-grades with weights)? The redesign below answers with the panel's own data
and fixes the defects that data exposed.

**What the production panel says about the scale.** The real run
(`cnb01-d2f-091722-ab78d4f`, 45 judge sheets, `reports/raw_scores.csv`) used the
integers -3..+3 and **never once used +-4** (round 1 histogram
{-3:13,-2:11,-1:28,0:33,1:29,2:31,3:23}; round 2 {-3:8,-2:8,-1:19,0:40,1:35,2:4,3:12};
largest |score| = 3). A -5..+5 range would therefore add rungs nobody uses.
What the panel lacks is not resolution but *anchoring*: the integer is written
without a checkable claim about which defect class it is about, so two judges
can both be "right" on different calibrations. A weighted average of absolute
aspect sub-grades is rejected for the same reason the design rejects absolute
ratings at all: weights are arbitrary, they re-compress into noise across
independent sessions, and the priority order already IS the aggregation
(correctness > consistency > preservation > completeness > formatting).

**The redesign (judge contract v2, `JUDGE_CONTRACT_VERSION = 2`).** Every
comparison now carries `basis` (the highest-priority tier in which the target
differs) plus a small `resolved`/`introduced` ledger of items
(`tier`, `severity`, <=25-word `evidence`), and the orchestrator enforces the
judge prompt's own anchors arithmetically: a non-zero score needs an item on its
own side, |score| >= 3 needs a MAJOR/CRITICAL item outside the formatting tier,
|score| = 4 needs a CRITICAL item, and a basis may not claim a lower-priority
tier than the items it cites. A sheet that contradicts its own ledger fails its
run and is retried; a legacy sheet (a sandbox materialized before the contract)
is accepted ONLY with an explicit UNCALIBRATED warning and is counted as such in
the decision record -- never silently mixed into a calibrated panel. The judge
prompt also now requires the `reason` to be written in the TARGET's frame (the
production reasons were often written from the opponent's side, e.g. "v1 fixes
the SI overclaim" under a negative score, which is unreadable in the audit
trail).

| # | Issue found by reading the aggregation against the real panel | Fix | Repro |
|---|---|---|---|
| G1 | A second done judge sheet for the same (target, judge index) -- a re-materialized session after a state repair or a prune -- pushed a version's directed-score count ABOVE the expected panel size, which the completeness test reads as "incomplete": the whole round fell back to the base with the operator told to add judges that already existed. | `aggregate_round` keeps the NEWEST valid sheet per (target, judge index) and reports the superseded ones (`diagnostics.superseded_sheets`, printed and written to the decision report). | `test_grading_scheme.py` A1 |
| G2 | A sheet whose `judge_index` is outside the configured 1..judges range (a stale `--judges` value, a ghost session) poisoned the panel the same way, and nothing in the diagnostics mentioned it. | out-of-range sheets are recorded in `diagnostics.out_of_range_sheets` and skipped; the configured panel is what counts. | `test_grading_scheme.py` A2 |
| G3 | The final tie-break was the version ID, so every exact statistical tie was decided by the arm's NAME -- `a2 < i1 < i2 < i3 < w1` silently favoured the reviewed-and-revised arm over the rewrite and integration arms, contradicting the pipeline's own provenance-blind judging. | the tie-break is the CONTENT DIGEST (provenance-free), with the id only as the last deterministic resort; the trace and the decision report state it. | `test_grading_scheme.py` B1 |
| G4 | Self-reported `critical_remaining` ranked above every remaining key, and the marker text promised it "can break a statistical tie" while the incumbent-protection rule silently overrode it whenever the base was involved. | the key is documented as (-median, -mean, IQR, critical_remaining, digest, id): the panel statistics decide, the self-reported count is next and is labelled SELF-REPORTED, the incumbent keeps an exact panel tie (a challenger must be measurably better), and `vs_base` is reported but not re-ranked (it is already one of the pairs inside the flat list). | `test_grading_scheme.py` D4, `.nbt_test/test_pipeline.py` selection checks |
| G5 | Nothing measured whether the integers were anchored: a 4 for a font difference and a 4 for a wrong DOI were the same data point, and the panel-quality diagnostics could not tell a calibrated panel from a noisy one. | contract v2 (above) + calibration diagnostics in the decision report: score histogram, largest |score| used, calibrated vs uncalibrated sheets, basis-tier counts and ledger-sign contradictions. | `test_grading_scheme.py` C1-C7, D1-D3 |

**Backward compatibility, verified on the real run.** Replaying the production
`state.json` through the redesigned `aggregate_round`/`select_champion`
(read-only, on a /tmp copy) reproduces BOTH recorded champions exactly
(round 1 `i4`, round 2 `i3`), with full panels (24/24 and 21/21 sheets) and the
legacy sheets counted as uncalibrated (24 and 21) rather than rejected. A
pre-contract run therefore keeps its decision and gains an honest note about how
calibrated its panel was. `nbt_round_pipeline.py` is bumped to 3.1.0 for the
contract change: if a stored round was decided by an earlier version and its
champion no longer recomputes (only possible when the old id tie-break decided
an exact tie), `decide` reports the mismatch, names the deciding version, and
refuses to re-derive the pinned chain silently rather than rewriting history.

Evidence: `.nbt_test/test_grading_scheme.py` (31 checks; 23 of them fail on the
pre-change tree) plus the updated stub judges, `.nbt_test/README.md`, and the
score-model/report text in `nbt_round_pipeline.py`. All fourteen `.nbt_test`
suites and the three skills harnesses (validate_skill 42/0, probe_regressions
0 failed, probe_hardcases 0 failed) pass.

## S9 - An MCP tool call needs PRE-APPROVAL to be reachable from `codex exec`

Reported: the first-choice renderer never ran. In
`cnb01-f2h-091819-e4bdc58/runs/r1_i4`, the agent's own visual-check table read
"`docx-converter` MCP tool (`convert_docx_to_pdf`, Word via PowerShell) | tool
present, but the call returns 'MCP tool call requires approval, but approval
policy is never' | **not usable in this sandbox**", and `_agent.log` line 7196
then fell through the documented converter order to `docx2pdf.sh`. It was not a
sandbox problem and not specific to that run: `codex exec` is non-interactive
and therefore runs with approval policy `never`, and `never` does not mean
"allow" -- it means "never ask, and refuse whatever would have to be asked".

* Root cause, read off the CLI the pipeline actually launches (codex-cli
  0.155.0; `codex-rs/core/src/mcp_tool_call.rs` in `openai/codex`): when an MCP
  tool call wants approval and the policy is `Never`, the call is denied with
  exactly that message. Whether a tool wants approval is a PER-SERVER/PER-TOOL
  setting -- `mcp_servers.<server>.default_tools_approval_mode`, or
  `mcp_servers.<server>.tools.<tool>.approval_mode`, values
  `auto|prompt|writes|approve` -- and is NOT governed by `--sandbox` or
  `--ask-for-approval`. The CLI default is `auto`, which still asks for any tool
  that does not declare itself read-only; `convert_docx_to_pdf` declares no
  annotations at all, so every call to it wanted approval.
* Fix: `AGENT_PRESETS` is no longer handed to the runner verbatim.
  `agent_argv()` (used by `resolve_agent_cmd()` for both the agent and the
  judge command) splices `-c
  mcp_servers.docx-converter.default_tools_approval_mode="approve"` into
  `codex exec` -- once, before the `-` prompt positional -- so the converter
  never wants approval at all. `MCP_APPROVALS` deliberately names ONE server:
  the renderer the prompts mandate first. Shell commands stay sandboxed by the
  CLI and every other MCP server keeps the operator's own policy. Only servers
  the probe finds installed are named (an override for an absent server would
  register a half-configured entry), and an operator-supplied
  `--agent-cmd`/`NBT_AGENT_CMD` is still taken verbatim. No dangerous flag is
  used or needed: neither `--dangerously-bypass-approvals-and-sandbox` (which
  would also drop the filesystem sandbox around shell commands) nor
  `--approve-for-me` (auto-review: correct for MCP in general, but it buys a
  reviewer call per render and routes every escalation through the reviewer).
  `run` now prints whether the session it is about to launch actually carries
  the override.
* Evidence, A/B on this machine with the real CLI and model: the same
  `codex exec` prompt ("call `convert_docx_to_pdf` once on the cover letter,
  then reply CONVERTED") produced, WITH the override, two `mcp_tool_call`
  events, the server's "转换成功" result and a 134,994-byte PDF; WITHOUT the
  override it produced the denial message three times and NO PDF, and the agent
  reported the conversion had not happened.
  `.nbt_test/test_docx_converter.py` gained the "codex exec: the MCP approval
  override" section (override present and `-` last, `resolve_agent_cmd()`
  carries it, no bypass/sandbox flag, only the one server approved,
  `--agent-cmd` untouched, no override when the server is absent, claude preset
  unchanged). All thirteen `.nbt_test` suites pass.
