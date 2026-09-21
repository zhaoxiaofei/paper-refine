# Pipeline audit findings - judge bias, retry context, visual gate, CLI safety

Audit of `nbt_round_pipeline.py` (and the `zot` CLI the `zotero-use` skill
drives) against four user-reported suspicions, plus a hunt for further issues
that could cause biased scoring, wrong scoring, data corruption, wasted
resources, inconsistent logic, or missing steps.

Method: code reading plus executable probes on the current tree. Reproductions
live in `.nbt_test/test_pipeline_audit_findings.py` (see the mapping per finding);
each check is written to PASS while the defect is present and must be inverted
when the defect is fixed.

Evidence commands used throughout (all read-only):

* `python3 .nbt_test/test_pipeline_audit_findings.py`
* `python3 - <<'PY' ... nb.copy_into(...) ; nb.sample_labels(...) ; nb.check_visual_artifact(...)`
* `sed -n '343,436p' site-packages/pyzotero_cli/item_cmds.py` (installed CLI)
* a real end-to-end stub-agent run under `/tmp/nbt_e2e2/root`

Verdict summary

| # | Claim | Verdict |
|---|---|---|
| 1 | Judges can be biased toward later versions via artifacts/findings/timestamps | TRUE (two mechanisms) |
| 2 | `zot` can corrupt data on the remote Zotero server | PARTLY TRUE - not silent corruption, but real overwrite/no-confirmation hazards |
| 3 | Retries should carry previous failures into the next prompt | TRUE (missing step) |
| 4 | Compile docx/tex to PDF first, then run the visual-inspection prompts | PARTLY TRUE - prompt already says render-first; the gate does not enforce it |
| 5 | Anything else | 3 further findings (U1-U3), 1 additional strong candidate (U4) |

## Fix status (round-4 triage, applied)

| Finding | Status | Commit |
|---|---|---|
| 1a timestamps reach the judge (C01) | FIXED - one timestamp per view, one shared stamp per session; the prompt now names metadata as an unusable signal | `f6512ff` |
| 1b label mapping recomputable (C02) | FIXED - the permutation is seeded with the per-root salt (`judge_salt_of`) | `0999ad3` |
| 3 retry drops the failure (C03) | FIXED - a PREVIOUS ATTEMPT FAILED block is injected into the regenerated prompt | `dec6af2` |
| 4 visual claim unenforced (C06) | FIXED - a "visually inspected" claim needs rendered pages when a renderer exists; the not-verified escape hatch is preserved | `829d7e5` |
| U1 self-written bookkeeping in judged/pinned corpora (C04) | FIXED - stripped from target/, field/*, pins and winners; corpus identity uses the same rule | `f6512ff` |
| U2 MANUAL_STEPS.md judged/pinned | FIXED by the same change (it no longer ships to the author) | `f6512ff` |
| 2 `zot` hazards | NOT PATCHED - third-party CLI outside the target list (OUT_OF_SCOPE) | - |
| U3 ledger vs frozen review | NOT PATCHED - reported only; see the note below | - |
| U4 pin bookkeeping drift | CLOSED as not reproducible - the pin rule now excludes bookkeeping on both sides | `f6512ff` |

Rejections from the triage: claim 4 as a *missing* step is FALSE_POSITIVE - the
prompt already instructs CONVERT-first with the detected converters; only the
enforcement half was real (C06). The "predicted siblings" the audit considered
earlier (marker synonyms, missing visual artifact, judge_review placement) stay
NOT_A_BUG as deliberate contract gates.

Reproduction record: `repros/test_audit_findings_prepatch.py` is the audit suite
as it ran against 1903b34, where every check passes because the defect is
present. The live suite (`.nbt_test/test_pipeline_audit_findings.py`) now
asserts the fixed behaviour for C01/C04 (F1, F5) and C02/C03/C06 (F2, F4, F3).

---

## 1. Judge bias toward later versions - TRUE, two independent mechanisms

### 1a. Version timestamps reach the judge

`build_corpus_dir()` materializes every judge view through
`copy_into()`, which uses `shutil.copy2`/`shutil.copytree(dirs_exist_ok=True)`
(`nbt_round_pipeline.py:2551-2573`) - both preserve mtimes.

Reproduction (`.nbt_test/test_pipeline_audit_findings.py`, F1):

* a2 (revise stage) is written first, b1/b2 (cross stage) later; the observed
  spread between version corpora is thousands of seconds;
* `copy_into` into `target/`/`field/*` preserves that mtime to the second,
  including nested files.

Consequence: a judge can order all field members by "last modified" and use
recency as a proxy for "later round = better", which is exactly what the blind
protocol is meant to prevent. The judge prompt explicitly forbids inferring
provenance from file names, tokens, run ids and directory names
(`nbt_round_pipeline.py:1555-1560`, `1598-1601`) but never mentions timestamps
(grep: 0 hits for mtime/modification time/timestamp in `JUDGE_DIRECTIVES`).

Severity: high for scoring validity (it can move a close comparison), moderate
in practice (it requires the judge to go looking for metadata).

### 1b. The label -> version mapping is recomputable from inside the sandbox

`sample_labels(r, vid, j, k)` seeds `random.Random` from
`sha256("nbt-round-field|{r}|{vid}|{j}")` (`nbt_round_pipeline.py:3027-3038`).
Round, version id and judge index are all small/enumerable values, and the judge
is told its round, its judge index and its own opaque token. Only 4 version ids
exist (a1/a2/b1/b2) and 3 judge indices per root, so a judge that knows the
pipeline can reproduce the permutation for each label and recover which corpus
is which - or simply learn which label is the previous champion.

The session token gets this right: `judge_token_for()` mixes in the per-root
random salt, so the same (round, version, judge) yields different tokens in
different roots. `sample_labels()` does not take `ctx` at all.

Reproduction: F2 shows the permutation is a pure function of public inputs
(identical across roots) while the token differs across roots.

Severity: high if any judge agent ever reasons about the pipeline (the
permutation is also stable across re-runs, so a retried judge sees the same
mapping again).

---

## 2. `zot` (pyzotero-cli) corrupting the remote Zotero server - PARTLY TRUE

Not verifiable end-to-end here: it needs a live Zotero API key and network, and
the local API is read-only. What the installed CLI source (v1.0.0) does show:

* `zot items update` fetches the item first and sends `If-Unmodified-Since-Version`
  with the fetched (or `--last-modified`) version (`item_cmds.py:343-436`), so a
  concurrent remote edit is refused by the server rather than silently
  overwritten. That rules out the "lost update" corruption story.
* `--field` assignments REPLACE a field value (`item_to_update['data'][key] = value`),
  and `--from-json` merges a user payload over the freshly fetched item. A wrong
  value overwrites good data with no preview and no backup.
* `zot fulltext set ITEM_KEY --from-json ...` overwrites an attachment's stored
  full text with no confirmation step at all.
* `zot items delete` / `tags delete` / `collections delete|remove-item` require
  explicit keys/tags and prompt for confirmation, but `--force` (and
  `--no-interaction`, which skips the prompt entirely) removes that protection,
  and no command offers a dry-run/preview.

Verdict: the claim is real in the sense that the CLI can destroy remote data
when an operator or agent passes the wrong key/value, and there is no dry-run
safety net - but it is operator/agent error, not silent corruption, and no
mechanism in this repository can produce it automatically. The `zotero-use`
skill already restricts library writes to explicit user requests; a preview
step (print the current value, require `--yes`) would close the remaining gap.

Scope note: this concerns a third-party CLI outside this repository
(`pyzotero-cli` 1.0.0, installed in the active conda env), so no patch is
proposed here.

---

## 3. Retries do not carry the previous failure - TRUE (missing step)

`rebuild_sandbox()` deletes the sandbox and re-materializes it
(`nbt_round_pipeline.py:3352-3384`); the prompt is regenerated from the same
static template, so attempt N's prompt is byte-identical to attempt 1's. The
failure IS recorded on the run (`rec["last_error"]`, `rec["postcheck"]["errors"]`)
but never handed to the agent.

Reproduction: F4 - two `revise_prompt()` calls are identical, contain no
previous-failure text, while the recorded error names the exact file and reason
("revised/revision_report.json is EMPTY/unfinished ... lists no revision row").

Consequence: a deterministic mistake is repeated at full cost. With the
observed configuration (~45 minutes per revise session, 24-job waves, 3
attempts) an avoidable repeat costs hours of agent time per run - the same
economics that motivated the per-invocation retry budget fix (C07) and the
document-recovery layer (C01). The cheapest fix is to append the previous
attempt's error lines (and, for marker/schema failures, the exact path and
offending value) to the regenerated prompt, clearly labelled as the previous
attempt's failure.

Severity: moderate-high for resource waste, low risk of harm.

---

## 4. Compile docx/tex to PDF before visual inspection - PARTLY TRUE

What already exists: `VISUAL_INSPECTION_RULE` (injected into all four prompts via
`visual_inspection_block()`) already tells the agent to CONVERT first - it names
`docx2pdf.sh`, LibreOffice, Word COM and `pandoc` in a preferred order, tells it
to render every page with `pdftoppm`, and says in as many words: "Never write
'visually inspected' without having seen rendered pages."
`visual_tools_available()` detects renderers on this machine and the prompt lists
them, so the machinery the user asks for is present at the instruction level.

What is missing: enforcement. `check_visual_artifact()`
(`nbt_round_pipeline.py:3694-3720`) only requires that the artifact FILE exists
and does not contain "not visually verified". A file that claims "all 12 pages
rendered and looked at" passes with no PDF, no PNG and no renderer invocation
anywhere (F3). The judge gate has the same shape
(`judge_review/artifacts/VIS_visual.md`).

Consequence: the pipeline cannot distinguish a real visual pass from a
plausible sentence, so visual claims in the decision report and the final
package are unverified. A mechanical check is available: when a renderer exists
(`visual_tools_available()`), require at least one rendered artifact (a PDF/PNG
produced during the run, or a named converter with its recorded output) before
accepting a "verified" claim; "not visually verified" plus a MANUAL_STEPS entry
should stay the documented escape hatch.

Severity: moderate (quality gate, not a scoring error), but it makes an
explicitly required step unverifiable.

---

## Further findings (U1-U3 true positives, U4 candidate)

### U1 - Self-written bookkeeping reaches the judge corpora (bias + prompt-injection)

`build_corpus_dir()` excludes only `revised/work/`; the pipeline's own
bookkeeping files are copied into `target/` and `field/*`. Observed in a real
run: one field label carried `CHANGELOG.md`, `MANUAL_STEPS.md`,
`REVISION_REPORT.md`, `revision_report.json`, `DIFF_LEDGER.md`, `VISUAL_CHECK.md`
while another carried none.

Two consequences:

* bias: the prompt says presence/absence "is also not a difference to score",
  but an LLM judge may still read a polished CHANGELOG as evidence of care;
* injection: `CHANGELOG.md`/`REVISION_REPORT.md` are produced by the SAME agent
  that produced the version, so self-serving claims ("all critical findings
  fixed") sit inside the package the judge inspects. Only the *prohibition* in
  the prompt keeps them out of the score.

The asymmetric presence of these files between labels is itself a provenance
signal of the kind 1b describes.

### U2 - `MANUAL_STEPS.md` is both a hand-off and a deliverable

MANUAL_STEPS.md is copied into every judge corpus and into the pinned winner
(`copy_into(..., skip_aux=True)` skips only `*.tracked.docx`/`*.before-after.docx`).
The author is therefore told to complete steps that were already resolved in the
revision, and the file is scored as package content. It is a hand-off to the
human gate, not a submission deliverable, and should be excluded from the
judged/pinned corpus like the other bookkeeping files.

### U3 - Nothing enforces the revision ledger's consistency with the frozen review

`critical_findings_input()` recomputes the count in the frozen review and
`postcheck_revise` only WARNS when the marker's `critical_remaining` is 0 while
the review lists critical findings. The ledger itself is only required to exist
and carry rows; a ledger that omits a finding the review lists is accepted.

### U4 (candidate, not reproduced) - the pinned corpus keeps regenerated bookkeeping

`meta.json` in a pin records the document digest of the corpus, and the corpus
contains the revised bookkeeping files. If a later stage regenerates
`CHANGELOG.md`, the pinned corpus no longer matches what it claims to be
independent of the agent's own reports. This needs the pin-verification path to
be traced before it is claimed as a defect; it is recorded here as a candidate,
not as confirmed.

---

## Not raised

Considered and rejected as not reproducible or not defects: marker stage/round
synonyms (deliberate contract gate, see NBT_TRIAGE_LEDGER.md C09),
missing visual artifact as a hard failure (intended, C10), `judge_review/`
placement rules (C12), and the already-fixed digest/filename/ledger issues
(C16). Per-instruction "re-run the whole agent session" behaviour is intended;
only the *missing context* in the regenerated prompt is reported (3).

## Reproduction

```
python3 .nbt_test/test_pipeline_audit_findings.py
```

prints one `[ok ]` line per check above (F1a-F1d, F2a-F2c, F3a-F3c, F4a-F4c,
F5a-F5c) and exits 0 only while every fix still holds. The prepatch reproduction
record (`repros/test_audit_findings_prepatch.py`, as run against 1903b34) is the
copy whose checks pass while the defects are present; this live suite asserts
the fixed behaviour for all five findings (F1-F5).
