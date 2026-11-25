# Mandatory post-write auditing and workflow repair

Base commit: `660d640b4a5bd73eb2dea3701651df8684493640`.

Every LLM authoring role except bounded repair, rewrite and integration now requires an independent audit and, for a nonempty repairable plan, one separately executed bounded repair. Covered products are revised packages in every mode, reviewer response letters/maps, conformed submissions and staged venue profiles. Read/report-only roles do not recursively audit their reports. The binding policy is recorded in AGENTS.md Rule 1C.

## Findings and fixes

| Gap | Resulting behavior |
| --- | --- |
| Major/minor bypassed the post-revision audit chain | Both modes retain an actual concern-scoped revision step and now require independent revision audit, conditional bounded repair and final verification. Their audit does not become a general review. |
| Revision audit could be disabled through flags, environment or legacy state | New setup accepts only `--revision-audit on`; legacy off/skipped settings cannot bypass the gate. `--no-audit` still controls the distinct earlier review-disposition audit. |
| Response, conform and venue profile writers lacked a common post-write gate | The shared executor now runs isolated independent audit/repair/verification sessions for all three owned products, including resumed writing sessions. |
| Structural validity could hide failed or stale audits | Downstream materialization, scoped publication, journal finalization and decision certification require acceptance of the exact authored bytes and original mandate/evidence. Author-created receipt files cannot replace the orchestrator's receipt in automatic runs. |
| Repair failures could leave a nominally accepted revision | Failed repairs and residual defects block acceptance. Every planned row needs a confirmed/rejected disposition with evidence; unplanned edits, no-op confirmed repairs and malformed ledgers fail. There is no recursive repair loop. |
| Continuations could carry an author's session into auditing | Audit and bounded-repair commands remove continuation/session flags; auxiliary sessions retain their own prompt and execution records without replacing the author's identity. |
| Transfer conformance depended on Word templates/DOCX | Both init and transfer run the conformer before round 1 for native-format submissions too, using destination guidelines when no applicable Word template exists. The explicit `--no-template-stage` opt-out remains. |
| Conformance could select the legacy/default backend instead of the requested producer | The pre-round conformer and its audits now use the resolved producer command, including the harness/model and custom-endpoint selection. |
| A passed conformer could be reused for changed source or destination rules | A context receipt binds source files, venue profile, journal, format policy and official template hashes. Stale or legacy unbound sessions are preserved and require an explicit rebuild before reuse. |
| Invocations without a judge panel could require unavailable judge/audit executables | Scoped modes, automatic promotion, and `--only` selections without judging skip irrelevant judge, conflict-audit and panel-defect-audit backend discovery. |
| Registered early stop skipped transfer/resubmit finalization | Finalization uses the actual final round; transfer still produces its journal package, and resubmit still writes and audits the required response. |
| Pruning could erase the proof required for later decision replay | Explicit pruning first validates and archives the accepted revision audit receipt. Missing or arbitrary deleted output without that archive remains unacceptable. |

The new quality module is frozen with the pipeline's runtime parts. Existing postchecks remain enforced after repair, and deterministic tracking auxiliaries do not invalidate the audited manuscript bytes. Rewriters and integrators retain their existing checks and judging. Frozen roots running an older bundle need the repository's existing `sync-code` migration before these changes govern their sessions; legacy unaudited artifacts are not retroactively accepted merely because their status says done.

## Validation

The regression suite contains 198 independently runnable suites. The new `test_mandatory_write_audits.py` contains 25 tests covering audit isolation, bounded edits, blocked prerequisites, quote/path/ledger validation, stale output and inputs, continuation stripping, role exceptions, all seven mode plans, actual major/minor revision/response runs, init/transfer conformance for Markdown and LaTeX, selected producer handling, changed destinations, judge-free selections, early-stop journal finalization, and pruned decision replay.

These are deterministic stub-agent and orchestration tests. They establish routing and enforcement behavior; they do not measure the scientific quality of live model judgments.

The final per-suite results and baseline comparison are recorded in `2026-11-25-validation.json`. The broad run was interrupted by an execution-environment disconnect after 195 suites completed; the three unfinished suites and the affected backend-selection test were rerun after recovery. A prior complete broad run and focused mode/profile/structure suites were also executed during development.

Ten suites have environment failures reproduced at the unchanged base commit:

- `test_adversary_gaps_2026_1008.py`
- `test_anonymized_judging.py`
- `test_candidates.py`
- `test_candidates2.py`
- `test_difference_tracking_3_pdfs.py`
- `test_difference_tracking_5_stage_hooks.py`
- `test_discovery_parity_2026_1010.py`
- `test_docx_format_3_render_validate.py`
- `test_fix_bugs_20261108_wave2.py`
- `test_general_audit_fixes_2026_1002b.py`

The reproduced causes are unavailable LaTeX format/rendering support, hard-coded `/tmp` subprocess working directories unavailable under the sandbox, and an unavailable `dsh` helper. The changes do not report those suites as passing. The baseline comparison used the original commit in a separate worktree, the same pinned test interpreter and the same environment.

Reproduce the suite with the interpreter created by `scripts/create-test-env.sh`:

```sh
python .paper_test/run_all.py --engine python -j 2
python .paper_test/test_mandatory_write_audits.py
```

## Figures

`figures/workflows/` contains seven mode-specific workflow panels as PDF/SVG and editable Graphviz sources, plus an auxiliary venue-authoring diagram and a suggested figure caption. `render.py` regenerates the exports. The diagrams distinguish report roles, author roles and deterministic orchestration, show conditional repair branches, and keep the exceptions explicit.
