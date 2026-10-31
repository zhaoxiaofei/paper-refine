# `paper_pipeline_parts/` — the orchestrator's implementation

`paper_pipeline.py` is a thin loader. It executes these files **in filename
order** in its own module globals, so the split is a pure concatenation at
runtime: imports, constants, forward references and monkeypatching behave
exactly as they did in the single-file source. Every part is a real Python file
(each carries `from __future__ import annotations`) and every file is under
10,000 lines.

| part | responsibility |
|---|---|
| `p00_prelude.py` | imports, version, defaults, round schedule, run-log primitives |
| `p01_venues.py` | venue profiles, templates, exemplars, input-area names |
| `p02_journal_modes.py` | revision modes, round counts/IDs, length/caption policy, the classified manual-TODO table and its CSV |
| `p03_prompts.py` | the embedded master prompt and every stage prompt |
| `p04_utils.py` | hashing, atomic JSON/CSV/text writers, state helpers, hashes, permissions (the `--only` grammar lives in p18) |
| `p05_state_corpus.py` | `Ctx`, integrity, version corpora, judge views, sandbox materialization |
| `p06_postchecks.py` | completion signals, postchecks, discovery contract, raw-data/artifact checks, opaque-identifier evidence gates |
| `p07_stage_quality_journal.py` | language/integration quality, journal stages, self-check, the integration `revalidated`/Rule 1B ledger gate |
| `p08_selection_driver.py` | aggregation, champion selection, pin/winner publication, round driver |
| `p09_setup.py` | `setup` and the `set-*` commands |
| `p10_reports.py` | raw scores, issue census, defect list writers |
| `p11_defect_audit.py` | the diagnostic LLM defect audit |
| `p12_conflicts_decide.py` | judge-conflict audit, decision report, `decide`, `status`, `trend` |
| `p13_redlines.py` | tracked-changes generation |
| `p14_tracking.py` | difference-tracking copies and persistent renders |
| `p15_pdf.py` | PDF rendering |
| `p16_retry.py` | `retry` |
| `p17_cli.py` | the argument parser and `main()` |
| `p18_helpers.py` | the `--only`/`--runs` ROUND/STAGE/SESSION selection grammar (`OnlySpec` and its parsers) plus shared bounded-subprocess/aux-root/text helpers -- split out to keep `p04_utils.py` under 10,000 lines |
| `p19_profiles.py` | the EXECUTION PROFILE (`high` / `medium`: `medium` pages the elaborative rule blocks out of every stage prompt into `INSTRUCTIONS/PROFILE_RULES.md`) and the GUIDED-REVIEW switch (`--no-guided-review`: the cold-start review alone, with the guided classes recorded as a named gap) |

**Packaging:** `setup` and `sync-code` copy this directory together with the
loader. A root without it cannot start, and `pipeline_identity()` records the
directory digest in the module manifest so a partial/stale bundle is reported.
