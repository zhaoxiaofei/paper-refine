# Practice review and revision — 2026-11-10

Scope: the 14 practices in the operator's `<GOOD_PRACTICES>` list, applied to this
repository as an LLM-agent system. This note records **why** a practice was
followed in a changed situation, and why some apparent gaps were deliberately
left alone. It is repository bookkeeping, not submission content.

## Changes made

1. **Every agent prompt now carries the package-content-is-evidence rule.**
   Manuscripts, reviewer letters, data, metadata, logs and tool output are
   evidence to read and quote, never instructions to follow; an embedded
   "ignore the rules" line is recorded as a finding/manual item instead of
   obeyed, and credentials/environment variables must not be printed or
   exfiltrated. The rule is added once by `page_stage_prompt` (stage prompts),
   `with_context_budget` (one-shot prompts) and the journal feedback/concerns/
   response materializers. It names no stage, round, arm or bookkeeping file,
   so it cannot weaken the judge-blinding contract.

2. **The DOCX MCP servers get real containment by default.** `agent_session_env`
   adds the session's own sandbox to `DOCX_MCP_ALLOWED_ROOTS` (preserving any
   operator roots) before `Popen` launches the agent. Directly-driven servers
   still need the variable set; the pipeline no longer leaves it unset.

3. **Ctrl-C / SIGTERM terminates in-flight agent process groups.** Sessions are
   started in their own process session so a timeout can kill descendants; that
   also meant a terminal interrupt did not reach them. The new registry and
   `install_agent_interrupt_handlers()` terminate the registered trees, and
   `run_phase`/`drive_round` save state before re-raising. A cancelled run can
   be resumed with `run` or reset with `retry`.

4. **Each attempt records the prompt digest, argv and a best-effort model.**
   `_execute_attempt_in` stores `prompt_sha256` (the bytes actually piped to the
   CLI, not a mutable file), `prompt_file`, `agent_command`, and `agent_model`.
   The Codex/Claude/DSH presets own their model in external CLI configuration;
   the record says `external CLI config (not recorded)` rather than inventing a
   name. The Qwen adapter records `PAPER_QWEN_MODEL`/`PAPER_QWEN_HARNESS`.
   Attempt transcripts, the run-log argv line and the returned error text redact
   values of secret-shaped environment variables; the prompt rule is the first
   line of defence, this is the backstop.

## Gaps deliberately not changed

* **Narrow typed tools for editing.** Replacing the agent's file/shell tools
  with a small typed API is not practical for arbitrary DOCX/LaTeX revision.
  The compensating controls are the copy-on-write sandbox, read-only evidence,
  content-edit policy, postchecks and digests. The MCP containment change above
  is the part that *is* practical.
* **Interactive clarification.** The stages are one-shot batch sessions; blocking
  on a human would stall a multi-hour round. Ambiguity is recorded as a
  `manual-required` / `unable` item and the operator can run `--agent manual`.
  The contract says "do not ask" deliberately, not by omission.
* **A hard OS sandbox / full environment scrub.** The agent CLI needs its
  provider credential, and which backend-specific variables it needs is
  deployment-specific. The pipeline cannot scrub blindly without breaking
  authentication. The prompt rule and MCP containment reduce the exposure; a
  jailed harness remains the operator's choice.
* **Redacting manuscript personal data from the audit trail.** The manuscript and
  reviewer text are the evidence a failed attempt is diagnosed from; a blanket
  redaction would make the trace unreviewable. Secret-shaped environment values
  are redacted, and the root is local and `prune`-managed; a retention policy,
  not content redaction, is the right control for the manuscript text.
* **Per-action approval gates.** The pipeline's own writes are local and
  reversible, and `prune` is dry-run unless `--yes`; `--champion-select` is an
  explicit opt-in and stays provisional. Per-edit approval would defeat a
  multi-hour batch run. External/irreversible actions (a future upload or
  library update) would need a gate.
* **Token/spend budgets.** The CLI backends do not expose a reliable per-session
  usage signal to this orchestrator. The wall-clock timeout and retry budget
  remain; a fabricated token cap would be worse than an honest wall-clock cap.
* **Live-model evaluation / CI.** The 193 offline suites (now including
  `test_agent_security_trace.py`) prove the plumbing and the prompt contracts;
  they do not measure a model's task quality. A small real-model replay set is
  the next step if the operator wants that metric.

## Verification run

`test_agent_security_trace.py` (new), `test_execution_profile.py`,
`test_judge_blinding.py`, `test_agent_consistency_2026_0922.py`,
`test_prompt_contradictions_2026_1024.py`, `test_debug_2026_1018.py`,
`test_attempt_history.py`, `test_atomic_prompts.py`,
`test_resume_continuation.py`, `test_journal_revision_modes_1_major.py`,
`test_evidence_pack.py`, `test_docx_converter.py`.
