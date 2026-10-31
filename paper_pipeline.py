#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_pipeline.py -- ROUND-BASED iterative revision pipeline for a manuscript
submitted to ANY venue or journal (the submission rules come from a configurable
VENUE PROFILE, the target journal from `set-journal`; Nature Biotechnology is the
default profile and the pipeline's pre-venue behaviour): R fixed rounds (R is
configurable at setup and
defaults to 3), a relative-judgment panel that produces 2*judges*(|field|-1)
directed scores per version (at the default judges=2 that is 4*(|field|-1); the
default plan's round-1 field of 8 gives 28), content-addressed pinning of every
round's champion, and a deterministic selection layer that ranks only
candidates whose panel is COMPLETE (a partial panel can never decide a round).
Python 3.9+, standard library only for the pipeline itself; tracked-changes
.docx use `python-redlines[docxodus]` (or `docx-trackdiff`), and the optional
companion file `paper_redlines_adapter.py` bridges the former.
The second optional companion, `paper_docx_format.py`, is the code-side OOXML
style/formatting scanner/fixer (see scan_format_in_sources): `setup` copies it
next to this script and records the source scan, `decide` reports the winner's
scan and can gate on it with `--format-gate`, and the tool's own CLI
(`scan`/`fix`/`check-pdf`) repairs the mechanical findings.

ROUND MODEL
-----------
    for r in 1..R:                 # R = 3 by default, exactly R rounds (unless
                                   # setup pre-registered --stop-after-no-progress K)
                                   # (the default schedule: M=[2,0,0], N=[1,1,1],
                                   # review_scope [full, full, full] and round 3 a
                                   # final review-audit-revise round -- no later
                                   # rewrites, no round-3 integration arm)
        A1_r  = the round's base  (round 1: a byte-identical copy of the
                                   pristine original; round r > 1: the
                                   byte-identical pinned champion of r-1)
        W1_r..WM_r
              = M = M_r full REWRITTEN candidates, each from its own agent
                                   session, staged FIRST, before the review:
                                   alternative organizations of the SAME content
                                   (diversity, and more pairs of eyes on
                                   ambiguity/perspective).
        A2_r..A(1+N)_r
              = N = N_r REVIEWED-AND-THEN-REVISED candidates. ONE $paper-review
                                   pass per round produces the frozen finding
                                   list; each of the N $paper-revise sessions then
                                   consumes its own read-only copy of that same
                                   guided_review/ and produces one revised candidate.
        I1_r..IK_r
              = K = 1 + M + N INTEGRATION runs: every pool member is reworked
                                   ONCE, in its own session, with that member as
                                   the base (self/) and ALL the OTHER pool
                                   members as donors (others/<version-id>/):
                                     I1 = A1 <- (W1..WM, A2..A(1+N))
                                     I2 = W1 <- (A1, W2..WM, A2..A(1+N))
                                     ... and so on for every pool member.
                                   There are NO pairwise arms.
        judges score every field member against every other field member,
        one direction each, 2 independent judge sessions per member
        champion_r = deterministic code selection (Section D); it is pinned
    into pinned/<r>_<champion_id>/ and joins every later round's field
    the round-R champion is the final answer.

    SCHEDULING: the runs of a round are a DAG, not a sequence of barriers. The
    M rewrites and the round's single review both depend only on the base, so
    they run CONCURRENTLY; each of the N revise sessions starts the moment the
    review marker exists (independently of the rewrites); the K integration
    runs start once the whole pool is done; the judge wave starts once the field
    is complete. Up to `jobs` sessions are in flight at any moment, so wall-clock
    time is the critical path through the DAG, not the sum of the stages.

    EVERY fresh arm is a CANDIDATE on equal terms: rewrites, revised candidates
    and integrated candidates each get their own judge panel and their own row
    in the ranking; each may win the round, become the next round's base and
    replace any other version under the published ranking key. Nothing in the
    selection layer privileges or penalises an arm beyond that key.
    M AND N ARE PER-ROUND COMMAND-LINE PARAMETERS: `setup --rewrites`,
    `setup --revises` and `setup --judges` each take either one integer (the
    same count every round) or a comma-separated list with one entry per round;
    a list shorter than --rounds is extended by repeating its last element. The
    defaults are R = 3 rounds, M = [2, 0, 0] (the two from-scratch rewrites are
    staged in round 1 only), N = [1, 1, 1], `--judges 2` everywhere and the
    per-round review scope [full, full, full]. WHICH
    integrations run is a per-round 32-bit mask (`setup --integrators`,
    default [0xFFFFFFFF, 0xFFFFFFFF, 0x0] -- rounds 1-2 integrate every
    applicable agent, the final review-audit-revise round integrates none): bit
    (k-1) belongs to the k-th
    member of the round's pool [a1, w1..wM, a2..a{1+N}], and a clear bit means
    that member's integration arm does not exist at all (no session, no judge
    panel row, no chance to win). `run --only` selects a subset per invocation,
    by round (`--only 1,2`), by stage (`--only judge`) or both
    (`--only 2:merge,3:judge`).

    The loop is FIXED-LENGTH: there is no convergence test, no implicit "stop
    when unchanged", and no early exit on a round whose score did not improve.
    The one deliberate exception is the pre-registered `--stop-after-no-progress
    K` (a setup-time operator decision, never an automatic exit). A killed
    process resumes at the next incomplete round from state.json.

A2 PRODUCTION -- REVIEW -> REVISE AS TWO CHAINED SESSIONS (A4)
-------------------------------------------------------------
    Phase 1 (guided review): its own sandbox, runs $paper-review on base/,
                      writes guided_review/*, sees nothing about revision.
    Phase 2 (revise): a SEPARATE sandbox, materialized only once Phase 1's
                      _pipeline_done.json (stage="guided_review") exists. It
                      receives a READ-ONLY copy of Phase 1's guided_review/
                      directory, reads guided_review/findings.json as the frozen
                      authoritative finding list, starts at R0, and writes revised/.
    Why the split: Phase 1's context (sweep artifacts, coverage table,
    discovery output) is the largest in the pipeline; Phase 2 needs bounded
    context for targeted edits; a failure in either phase is retryable without
    re-paying the other; and the two skills already communicate through
    findings.json, so the split merely exposes an interface that already
    exists. Cross-pollination has no review phase (its agent reads self/ and
    other/ directly), and judge runs are Phase-1-only: neither is split.

RETRY POLICY / PANEL INTEGRITY
------------------------------
    A failed agent run (non-zero exit, timeout, missing/invalid completion
    signal, failed postcheck) is retried automatically -- TWICE by default, i.e.
    up to three attempts per run, configurable with `run --retries N`. Between
    attempts the orchestrator waits an exponential backoff
    `--retry-backoff * 2**(failures so far, counting from 0)` seconds (default
    base 30s -> 30s, 60s, 120s, ... capped by `--retry-backoff-max`, default
    600s; base 0 retries immediately -- see `backoff_delay`). The wait applies
    to the automated waves. In MANUAL mode a
    failed attempt is NEVER rebuilt automatically: the operator owns that
    sandbox, so its work product is preserved and the failure is reported with
    the two supported next steps (`retry --run <ID>` to reset it, or fix the
    artifacts and re-run `run`). This exists because a lost judge session
    shrinks the panel, and a shrunk panel must not decide a round.
    MALFORMED STRUCTURED OUTPUT COUNTS AS A FAILED RUN: a truncated or empty
    scores.json / findings.json / revision_report.json / _pipeline_done.json, an
    agent-written .xml that does not parse, or a .docx it wrote that is not a
    readable OOXML package is reported with its parse error and retried like any
    other failure. In manual mode the file must stop changing for one poll
    interval first, so a still-writing agent is never interrupted; and files that
    are merely COPIED from a read-only input are never blamed on the agent.
    Belt and braces: after the judge wave, the round is decided ONLY when every
    field member's directed-score panel is complete. If any member is short (a
    sheet that dropped a comparison, a stale judge run, a whole version's
    sheets), the round stops BEFORE selecting or pinning anything, its record is
    left `pending` with `panel_gaps` diagnostics, and
    `reports/round<r>_panel_gaps.json` is written so the operator can
    `retry --run <judge id>` and re-decide with the full panel.

THE SCORE SET (2*judges*(|field|-1) DIRECTED SCORES PER VERSION; 4*(|field|-1)
AND 28 AT |field| = 8 WITH THE DEFAULT 2 JUDGES)
---------------------------------------------------------------------------
    Each round has a field of versions. For version V, `judges` independent
    sessions each score V against EVERY other field member in V's own
    direction only (one integer per opponent, -4..+4, plus the GRADED BASIS that
    makes the integer checkable: the tier it is about and a short ledger of the
    items on each side -- see JUDGE_CONTRACT_VERSION). The reverse direction of
    a pair (V,W) comes from W's own judges, negated into V's frame:

        (2 judges x (|field|-1) opponents)          [V-vs-others]
      + ((|field|-1) opponents x 2 judges x 1)      [others-vs-V, negated]
      = 2 * judges * (|field| - 1)                  [= 4 * (|field| - 1) and 12 at
                                                     the default 2 judges, |field| = 4;
                                                     28 with the 8-member round-1
                                                     field the default plan builds]

    The field is deduplicated by CONTENT digest, so its size is whatever the
    pinning history and the per-round plan yield (never hardcoded): round r has
    at most r + 1 + 2*(M_r + N_r) members -- {original}, {pins from earlier
    rounds}, the round's fresh arms (base, M rewrites, N revisions) and the
    K = 1 + M + N integrated candidates (of which the round's per-round
    --integrators mask may select only some), minus everything that deduplicates
    (the base always merges into the pin or the original). The default plan
    gives 8 members in round 1 ({original, w1, w2, a2, i1..i4}), 5 in round 2
    ({original, the round-1 pin, a2, i1, i2} -- M = 0, so the pool is the base
    plus the revised candidate). Round 3 has M = 0 and integrators 0x0: no
    integration arm exists, and its field is only the incumbents (the original
    and the earlier pins, after content dedup) plus the revised candidate.
    V-vs-W and W-vs-V are
    independent judgments from independent sessions, which is why the ranking
    LEADS on the round's reported DEFECT PREFIX (the issue census accumulated in
    severity_tier_category order until the cleanest version reaches the
    configured floor, or every cell is used); below it come the median of the
    FLAT score list (not a two-level median), then the ARITHMETIC MEAN of the
    same list, the IQR and the CONTENT DIGEST as the final provenance-free
    fallback (the arm's NAME never decides a tie). The self-reported
    critical_remaining/writing_remaining values are reported and cross-checked
    but never rank, and an exact (median, mean, IQR) tie keeps the incumbent base.
    ELIGIBILITY requires the full
    panel (and, for a fresh arm, both directions against the original): a version
    whose panel is short -- because a judge sheet omitted a comparison or a judge
    run failed -- is reported as a panel gap and cannot win the round, because
    the median of a one-sample list must never outrank a complete panel. The
    round's own base competes too, through the content-identical field member
    whose judges scored it, so a round can never crown a version the panel ranks
    below the version it started from: when no fresh arm measurably beats the
    base, the base is the champion and the round reports no progress.

STAGING DEPENDENCY ORDER (a DAG: every run starts as soon as its inputs exist)
-----------------------------------------------------------------------------
    (i)   runs/r<R>_a1/         base copy only, no agent run. Everything else
          depends on it.
    (ii)  the WRITES: runs/r<R>_w1..wM/ (M rewrites: base/ + non_revised/ +
          rewritten/) and runs/r<R>_guided_review/ (ONE guided review pass;
          skipped when --revises is 0) both depend only on a1, so they START
          TOGETHER. Each run's sandbox is materialized the moment its
          dependencies are done.
    (iii) runs/r<R>_a2_revise..A(1+N)_revise/ (the N reviewed-and-then-revised
          candidates): each consumes its OWN read-only copy of the SAME frozen
          guided_review/, so a revise session starts as soon as the review
          marker exists -- it does NOT wait for the rewrites (or for its sibling
          revise sessions).
    (iv)  runs/r<R>_i1..iK/     the integration runs selected by the round's
          --integrators mask (default [0xFFFFFFFF, 0xFFFFFFFF, 0x0]: every pool
          member in rounds 1-2, none in the final review-audit-revise round;
          self/ = one pool member, others/<id>/ = every other member). They
          start once the WHOLE pool
          (a1, every rewrite, every revision) is done, and run in parallel with
          each other.
    (v)   build field_r, materialize `judges` judge sandboxes per field member,
          execute them in parallel, aggregate in code, select, pin, mark the
          round done.
    The scheduler (`run_round_runs`) keeps up to `--jobs` sessions in flight and
    gives every run the same per-invocation retry budget and exponential backoff
    as before; a run whose dependencies are still failing is simply never
    started. Manual mode follows the same dependency order but is operator-paced
    (`--no-wait` prints EVERY currently-runnable prompt at once).

RULES CARRIED INTO EVERY PROMPT (AND WHERE THEY COME FROM)
----------------------------------------------------------
    * FIGURE LEGENDS -- ALWAYS ENUMERATED, NEVER A GATE (check id M18): the
      VENUE PROFILE's legend policy applies (the default nature-biotechnology
      profile: a legend may not exceed the article type's word limit, but the
      venue publishes no number, and the master prompt and both skills state
      none either). Every stage therefore COUNTS every legend's words:
      `setup --caption-limit N` lets the operator configure a proxy cap; without
      one the venue profile's own default applies (0 for the default profile =
      counts only, no cap). An over-cap legend is REPORTED and compressed only
      by removing redundancy, never by deleting scientific content, and with no
      cap the counts are recorded for the author to compare with the venue's
      own limit.
      Nothing is ever enforced on a word count: legend length cannot make a
      version ineligible, cannot reorder a ranking, and cannot fail a decision.
      The orchestrator also scans the corpora itself (code-side proxy over .docx
      OOXML paragraphs, LaTeX \\caption, and Markdown/plain-text caption lines)
      and reports the final winner's caption state and any caption-looking line
      the pattern did NOT recognise ("suspected").
      `decide --require-clean-captions` is kept for CLI compatibility and prints
      that report; it deliberately does not exit non-zero.
    * ABSTRACT / MAIN-TEXT LENGTH -- THE JOURNAL'S LIMITS, RELAXED BY THE
      PIPELINE (check id M19): the master prompt's blanket exemption ("never
      flag abstract or main-text word limits") is REPLACED here, because an
      abstract or main text over the journal's own limit is something the
      editor will raise even though no pipeline rule ever mentioned it. The
      numbers come from the configured VENUE PROFILE (`set-venue`; see the
      VENUES AND JOURNALS section below): for the DEFAULT nature-biotechnology
      Article profile the base limits are abstract <= 150 words and main text
      <= 3,000 words (excluding abstract, Methods, references and figure
      legends), relaxed by the operator's margins -- +10% on the abstract
      (<= 165 words) and +25% on the main text (<= 3,750 words). A profile may
      carry different numbers and its own main-text COUNTING CONVENTION (which
      sections its limit leaves out: Frontiers counts Methods, NBT's Brief
      Communication counts abstract/references/legends), or none at all (the
      stages then count and name the limit the target journal's guidelines
      state). Words are counted as
      maximal runs of NON-SPACE characters with a newline treated as space
      (so "state-of-the-art" is one word and "2026" is one word). An over-limit
      section is a formatting-tier item (M19): reported by the review,
      compressed by the revision/integration stages only by removing
      redundancy, and NEVER a gate -- no version becomes ineligible, fails, is
      rejected or is ranked down as a whole on a word count, and text that is
      within the cap is never cut for length. The orchestrator also counts the
      abstract and the main text itself (code-side proxy) and reports the
      winner's counts next to the caption report.
    * HAND-OFF PLACEHOLDERS -- a PIPELINE CONVENTION THAT MUST NOT BE SCORED:
      because the revision stages may never invent content, a missing mandatory
      item is scaffolded with the literal token "[AUTHOR TO COMPLETE: ...]" and
      listed for the author. The review's M6 hygiene sweep and the judges'
      frozen sweeps would otherwise read that token as leftover template text
      and penalise the very version that obeyed the pipeline, so every prompt
      disposes it as a manual item: the marker is never scored, never counted as
      a defect, never a difference between versions, and never a reason to lose a
      ranking. The orchestrator counts the markers itself and reports them
      (`author_placeholders`), and the count is a diagnostic that ranks nothing.
    * AUXILIARY FILES -- the difference-tracking copies ARE NOT SUBMISSION
      CONTENT: every "<name>.tracking-<token>.<ext>" (and its
      "<name>.logging-<token>.<ext>" fallback log) is excluded from every
      judged/pinned corpus rule (corpus_manifest/build_corpus_dir), so the
      copies never reach a judge, a pin or the next round's base, and the M6
      sweep's "residual tracked changes" row never fires on the pipeline's own
      output. The pipeline's own tracked-changes copies live under
      <root>/redlines/ (per source pair) and <root>/tracking/ (one copy per
      baseline: the pre-conformed original, the version an arm was derived
      from, or a published round winner -- the token names which).
    * DERIVED BUILD OUTPUTS -- NOT CARRIED, NOT SCORED: ".aux/.blg/.bcf/.log/
      .out/.synctex.gz/.run.xml/.fls/.fdb_latexmk" and friends are by-products of
      a build, not submission content. The revision stage is told to leave them
      out of revised/ (copying them unchanged after a rename leaves stale file
      names behind and makes the package look broken), a derived file that
      cannot be regenerated is shipped only when it still matches the revised
      sources, and otherwise the recompile becomes a MANUAL_STEPS.md item. The
      judge prompt makes the same point from the other side: a stale by-product
      is reported as a packaging note, never scored as a correctness,
      preservation or completeness defect, and never decisive. A JUDGE VIEW
      additionally drops the by-products outright (`_is_view_excluded_file()`):
      a .log/.fls/.synctex.gz names the build machine's absolute paths and the
      build date, and a version an agent went over loses the whole by-product
      set, so their very presence would say which package was worked on. The one
      exception is a compiled ".bbl", kept because with no editable ".bib" it is
      the only copy of the reference list.
    * MANUAL_STEPS.md IS REPORTED, NOT RANKED: the number of manual items
      measures how much work the pipeline hands to the author, not how good the
      package is; ranking on it would reward under-reporting and would punish a
      package for reporting its hand-offs honestly, so it is reported in the
      decision report and deliberately kept out of the ranking key.
    * WINNER PUBLICATION: each round's champion is written to
      <root>/round<R>_winner/ (documents at the top level) in addition to its
      content-addressed pin, and both copies are digest-verified against each
      other on every `run`/`decide`. `decide` additionally publishes the FINAL
      champion as <root>/final_clean_version_<root name>/ (zipped beside it):
      the same corpus byte-for-byte
      without process scratch, auxiliaries or self-written reports, ready to
      seed a new pipeline run (`setup --source
      <root>/final_clean_version_<root name>`).
      It is written on EVERY decide, certified or not, and is idempotent; the
      certification verdict (and why a package is not signed) is stated in the
      sibling <root>/final_clean_version.readme.md.
    * ONE CONTENT-HASH VERSION TOKEN PER PACKAGE (replaces the old letter/digit
      increments): every producing stage names all of its editable documents
      with the SAME 7-character token, the first 7 hex of SHA-256 over the
      package's sorted payload-content digests (the tool is shipped as
      `paper-revise/scripts/revision_token.py`; reports, auxiliaries and `work/`
      are excluded, file NAMES do not enter the hash, and version-token
      references inside contents are normalized before hashing, so applying the
      token never changes it -- `--verify` proves that). The orchestrator
      recognises 7-hex tokens when matching documents (legacy letter/digit
      names keep working), records each producing run's token, warns when a
      filename token contradicts the content, and reports the final winner's
      token. The judge views remain ANONYMIZED (placeholder names): a content
      hash identifies a package but does not hide a document's real basename,
      which is where author/project identity lives.
    * EVERY ARM IS AN ORDINARY CANDIDATE: rewrites (alternative organizations
      of the base's content, created before the review, never revisions of the
      frozen finding list), reviewed-and-revised candidates and integrated
      candidates all compete on exactly the same terms -- same field, same
      judges, same anti-regression gate, same ranking key, same pin/winner
      machinery. No prompt is told to favour one, and the selection layer
      never treats one differently from another.
    * INTEGRATION, NOT PAIRWISE CROSS-POLLINATION: the stage after the review
      and the revisions reworks EVERY pool member ONCE, with the whole pool
      visible in one sandbox (self/ = the member being reworked,
      others/<version-id>/ = every other member). "A1 <- (A2, W1)" is one
      session, not two pairwise arms; a donor-set ledger row names the donor
      each port came from, and every donor must appear in the ledger.
    * THE `docx` CLI IS AVAILABLE TO EVERY AGENT, AND OPTIONAL: every prompt
      states that the `docx` command (bun-docx: read/outline/wc/render/diff/
      validate/track-changes/comments/... , including `docx diff FILE
      --against SNAPSHOT`) may be used by any agent in any stage when it helps,
      that using it is never required and never scored, and -- for the stages
      whose contract says "read the packages in full" -- that it is an aid, not
      a substitute for that reading. `docx render` is also probed as a
      layout-faithful visual renderer (it drives Word/LibreOffice internally).
    * THE `docx-converter` MCP TOOL IS THE FIRST-CHOICE DOCX->PDF CONVERTER: the
      pipeline probes the operator's Codex config (~/.codex/config.toml,
      `[mcp_servers.docx-converter]`, CODEX_HOME aware) and, when the server is
      configured with its script still on disk, every prompt tells the agents to
      call `convert_docx_to_pdf(docxPath)` BEFORE `docx2pdf.sh`, `docx render`,
      LibreOffice or any other converter -- it renders through Microsoft Word
      via WSL/PowerShell interop, the highest-fidelity renderer available. The
      prompts also insist that the conversion target is a COPY inside the
      stage's writable work directory, never a hash-verified read-only view
      (`target/`, `field/*`, `base/`, `non_revised/`), because
      every converter writes its output next to the file it is handed.
      A prompt to call the tool is not by itself enough: `codex exec` is
      non-interactive and therefore runs with approval policy `never`, which
      DENIES an MCP tool call that wants approval rather than queueing it for a
      human, so the orchestrator hands every codex session the per-server
      override `-c mcp_servers.docx-converter.default_tools_approval_mode=
      "approve"` (see MCP_APPROVALS and codex_mcp_overrides()). Without that
      override the agents can see the tool and still never be allowed to call
      it, which is what happened to the first-choice renderer.
    * THE `zot` CLI (pyzotero-cli) IS THE REFERENCE ROUTE: every prompt documents
      the read route (`zot --local ... items list/get/citation/bib`, full text,
      collections, tags), the live-field rules for editing a DOCX citation
      (parent item keys, one unique field per citation location, baseline-
      preserving validation, no invented keys), and the fact that the operator's
      Zotero library is not the agents' to edit at will. `setup --zotero`
      chooses how far they may go: off (never run zot), read (resolve/verify),
      edit (default: also add/remove/relink citations in the revised copy) and
      apply (also apply ONE guarded field update to ONE existing library item
      under the propose-then-verify protocol, with `--last-modified auto` as the
      concurrency guard). The pipeline never creates or deletes library items,
      and a suspected metadata error defaults to a proposal row plus a manual
      step the author applies.
    * A candidate's corpus is its stage package -- revised/ for a revised
      candidate, rewritten/ for a rewritten one, integrated/ for an integrated
      one -- plus code/; the process scratch (revised/work/,
      rewritten/work/, integrated/work/) is excluded from judging, hashing,
      pinning and from the next round's base. The report files the skill
      mandates INSIDE revised/ (CHANGELOG.md, MANUAL_STEPS.md, REVISION_REPORT.md,
      revision_report.json, DIFF_LEDGER.md) cannot be excluded without breaking
      the pin == judge-target invariant, so instead they stay in the corpus
      digest but are excluded from the caption scan and the document-set
      comparison, and every prompt tells the agents that they are pipeline
      bookkeeping, not manuscript content.

CODE-SIDE CHECKS (in addition to what the prompts ask the agents to do)
---------------------------------------------------------------------
    * caption check       extractable captions over the SUGGESTED length are
                          REPORTED (advisory, never a gate: no version is made
                          ineligible and no decision fails on a word count);
                          unparseable formats (.doc/.pdf/slides) are reported as
                          "not verified" and rely on the M18 rows.
    * length check (M19)  the abstract and the main text are counted with the
                          operator's definition (runs of non-space characters,
                          newline = space) at setup over the source corpus and
                          at `decide` over the pinned winner, and compared with
                          the SELECTED article type's limits, relaxed by the
                          profile's margins (the default nature-biotechnology
                          Article: +10%/+25% -> 165 / 3,750 words; the profile's
                          other article types, and a profile with no limits,
                          record counts only -- see `set-article-type`).
                          Reported next to the caption
                          check, advisory in exactly the same way: the agents'
                          M19 sweep is authoritative, an over-cap section is a
                          formatting-tier item, and no version is ever made
                          ineligible on a word count.
    * hand-off markers    the "[AUTHOR TO COMPLETE: ...]" token the revision
                          stages must write instead of inventing content is
                          counted and reported per version, and is never scored,
                          never a defect and never a ranking input.
    * auxiliary files     the difference-tracking copies
                          ("*.tracking-<token>.<ext>" and their
                          "*.logging-<token>.<ext>" fallbacks) are left out of every
                          judged/pinned corpus (the pipeline writes its own
                          tracked-changes copies under <root>/redlines/ and
                          <root>/tracking/).
    * visual inspection   "visually inspect the document" is enforced as a
                          RENDER-THEN-LOOK rule: convert Word files to PDF by
                          calling the `docx-converter` MCP tool
                          (`convert_docx_to_pdf`, the FIRST choice, probed from
                          the operator's ~/.codex/config.toml and pre-approved
                          for the agent with the `-c` override above, because
                          an unapproved MCP call is denied outright under
                          `codex exec`) and falling back
                          to docx2pdf.sh, the `docx render` command, LibreOffice,
                          ... only when that tool is unavailable,
                          render pages to images (pdftoppm/gs) and inspect them;
                          the pass must be recorded (guided_review/artifacts/VIS_visual.md,
                          judge_review/artifacts/VIS_visual.md,
                          revised/VISUAL_CHECK.md, rewritten/VISUAL_CHECK.md,
                          integrated/VISUAL_CHECK.md) or explicitly declared
                          impossible with a manual step. Reading a .docx is not
                          a visual inspection (text carries no layout). When the
                          venue ships an official Word template, the orchestrator
                          renders it ONCE per root (the `docx-converter` MCP
                          tool first -- driven by the orchestrator's own tiny
                          stdio client -- then docx2pdf.sh, then LibreOffice)
                          into each session's `visual_template/` (PDF + page
                          images + renderer/page manifest) so every agent
                          compares its own render side by side with the
                          template's, and the recorded pass must name each
                          template document and its rendered page count.
    * review contract     submission_dir must resolve to base/, every check id
                          M1-M17, J1-J5 plus M18-M36 (the always-active length/
                          caption/formatting checks, the adopted rewrite-parity
                          checks and the source-hierarchy reconciliation) must
                          carry a real coverage disposition,
                          the M25-M30 artifacts and guided_review/ARCHITECTURE.md
                          must exist with a disposition column,
                          guided_review/artifacts/ must exist, finding ids must be
                          unique, and every prior-round finding must be carried
                          forward or recorded as gone.
    * ledger contract     revised/revision_report.json is required from revise
                          runs, integrated/DIFF_LEDGER.md from integration runs
                          (one row per donor, every donor named), and
                          rewritten/REWRITE_REPORT.md from rewrite runs.
    * judge grounding     judge_review/ (inventory + sweep artifacts + the visual
                          record) is required before a sheet is accepted.
    * derived outputs     build by-products (.aux/.log/.out/.synctex.gz/.run.xml/
                          .bbl/PDFs) are not editable documents, so leaving a
                          stale one out of the package never trips the
                          document-set check; the prompts make the same rule
                          explicit for the agents and the judges.
    * document set        a rewrite/revise/integration run FAILS if a base
                          document disappears.
                          Base and candidate documents are matched ONE-TO-ONE
                          (same stripped name + same bytes, then same stripped
                          name, then same bytes anywhere), so numbered sibling
                          families ("Supplementary-Table-1/2.csv") can no longer
                          mask a lost file; possible pre/post-rename twins are
                          reported as warnings.
    * evidence integrity  `decide` re-hashes every completed run's frozen inputs,
                          the pristine original and the pin/winner copies, and
                          refuses to certify a decision whose evidence changed on
                          disk (exit 5). `--package-winner` refuses to package a
                          broken chain.
    * panel completeness  a candidate whose directed-score panel is short (a
                          judge sheet omitted a comparison, a judge run failed,
                          or a whole version's sheets are missing) is INELIGIBLE
                          to win; the gap is listed in the round record and the
                          decision report, and `run` retries judge runs whose
                          sheets omit issued opponent labels.
    * panel guard         a round whose judge panel is incomplete for ANY field
                          member is never decided at all: `run` stops before
                          selection/pinning, keeps the round pending, writes
                          reports/round<r>_panel_gaps.json, and tells the
                          operator which judge session to `retry`.
    * structured output   the JSON/XML a run was supposed to write is parsed
                          before it is trusted: a truncated scores.json, an
                          empty findings.json, a malformed .xml artifact, or a
                          .docx that is not a readable OOXML package fails the
                          run (with the parse error) and is retried by the policy
                          above. Files copied unchanged from a read-only input
                          are exempt.
    * tracked changes     every candidate gets tracked-changes .docx against the
                          round's base, the pristine original and the setup
                          --source directory (the `docx-compare` MCP tool -- the
                          Word-native compare engine -- first, then
                          python-redlines[docxodus] -> docx-trackdiff ->
                          --redline-cmd -> built-in OOXML writer), with a
                          manifest that names the backend that actually produced
                          each file.
    * difference tracking every candidate ALSO gets, beside each document,
                          "<name>.tracking-<token>.<ext>" (docx/tex/bib) for the
                          comparison against the pristine original (`original`),
                          the version it was derived from (`a1`, or the
                          integration's own `w<k>`/`a<k>` base) or, for a
                          PUBLISHED winner, the previous round's winner
                          (`winner<r-1>`); the sibling
                          "<name>.logging-<token>.<ext>" is the fallback log
                          written when the tool failed. `.tex`/`.bib` pairs go
                          through `latexdiff`. The copies are auxiliaries, never
                          submission content, and the pass uses no agent. The
                          same round-close pass compiles the
                          LaTeX sources (`latexmk`) and converts the .docx files
                          into PDFs under <root>/pdfs/ (persistent; a failure is
                          a warning, never a failed round).
    * blind judging       a judge's run id and the sheet's target_id are opaque
                          tokens mixed with a per-root random salt, so the token
                          cannot be recomputed from (round, version id); the
                          token -> version-id map lives only in the run record.
                          What a judge can SEE is anonymous too: every view
                          (target/, field/*) is materialized with
                          placeholder paths ("d01/", "f0001<ext>"), a per-view
                          random permutation (so the same document has a
                          different name in every view), one mtime, one mode and
                          no xattrs -- nothing in a path, timestamp, permission
                          bit or attribute can order the packages or reveal
                          provenance. Extensions are kept (the judge needs the
                          file type) and the tree shape is kept (grouping is
                          package structure, not provenance); the judge prompt
                          states this and tells judges never to score internal
                          filename references as broken (the orchestrator
                          verifies the real file set mechanically).
                          A view carries SUBMISSION CONTENT only: revision
                          auxiliaries, pipeline bookkeeping/report files, the
                          process scratch and every derived output whose
                          editable source is in the package never reach it.
                          That covers the build by-products of an editable
                          source (.aux/.log/.toc/... -- their content names the
                          build machine, its paths and the build date, and their
                          very presence says whether an agent went over the
                          package) and the renderings a judge can produce
                          itself: a compiled .bbl next to its .bib, a compiled
                          PDF next to its .docx/.doc/.tex/.ltx. A derived file
                          with no source in the package stays -- with no .bib
                          shipped, a .bbl is the only copy of the bibliography.
                          The blinding still relies on the agent obeying its
                          prompt (there is no OS-level jail), which the report
                          states rather than hides.
    * metadata preservation  files NO judge sees keep their identity: sandbox
                          inputs, pins, published winners, the integration views
                          and the pristine copy are copied with names, mtimes,
                          modes and attributes intact (shutil.copy2/copytree), so
                          the author's/agent's own metadata survives the
                          pipeline. Only judge views are anonymized and
                          normalized (build_judge_view).
    * judge backend       --judge-agent / --judge-agent-cmd let the judge panel
                          run on a different (e.g. cheaper) CLI than the
                          production stages.

CONTENTS OF THIS FILE
---------------------
    ATTACHED_HEAD / ATTACHED_PHASE1 / ATTACHED_PHASE2 are the master revision
    prompt, reused VERBATIM (the orchestration logic around it is what this
    file rewrites). If you start from a stripped copy of this file, paste your
    master prompt into those three constants before first use; every prompt
    builder appends the excerpts it needs by concatenation, never by editing
    the prose.

USAGE
-----
    python paper_pipeline.py setup --source /path/to/non_revised \\
        --root ./paper_rounds --rounds 3 --judges 2 [--rewrites 2,0,0] [--revises 1,1,1]
        [--integrators 0xFFFFFFFF] [--caption-limit N] [--strict-artifacts {on,fix,off}]
    # revise against a REAL journal decision letter (options 1-4):
    python paper_pipeline.py setup --source /path/to/submission --root ./paper_rounds \\
        --journal "Frontiers in Immunology" --revision-mode transfer \\
        --journal-feedback-from iScience [--journal-feedback FILE ...]
    python paper_pipeline.py set-revision-mode major --root ./paper_rounds
        # transfer (1) | resubmit (2) | major (3) | minor (4) | llm (5)
    python paper_pipeline.py run    --root ./paper_rounds --jobs 255
    python paper_pipeline.py run    --root ./paper_rounds --only 1,2      # only rounds 1 and 2
    python paper_pipeline.py run    --root ./paper_rounds --only 2:review,2:merge
    python paper_pipeline.py run-decide --root ./paper_rounds   # run, then decide in series
    python paper_pipeline.py status --root ./paper_rounds
    python paper_pipeline.py redline --root ./paper_rounds [--round R] [--tool auto]
    python paper_pipeline.py track   --root ./paper_rounds [--round R] [--no-pdf]
    python paper_pipeline.py decide --root ./paper_rounds   # also writes final_clean_version_<root name>/
    python paper_pipeline.py retry  --root ./paper_rounds --run r2_guided_review
    python paper_pipeline.py retry  --root ./paper_rounds --runs 1:judge,2:feedback,2:review
    python paper_pipeline.py prune  --root ./paper_rounds --keep-latest 1 [--yes]
    python paper_pipeline.py conflicts --root ./paper_rounds [--round R] [--no-agent]
        # cross-judge conflict audit -> reports/round<R>_judge_conflicts.md
        # + the cumulative reports/JUDGE_CONFLICTS_TODO.md manual TODO list

    `retry --runs <selection>` takes the SAME grammar as `run --only` (rounds,
    stage classes, ROUND:STAGE, single sessions and judge selectors), so the
    two commands select the same part of the pipeline: `--runs 1:review` resets
    round 1's review, `--runs r1_w2` one session, `--runs 1` the whole round.
    `--run`, `--runs` and `--all-failed` are mutually exclusive.

    Cross-judge conflicts: `run`/`run-decide`/`decide` also audit the round's
    judge sheets for contradictions between independent sessions -- opposite
    integers for the same comparison, a claim one judge files as `resolved` and
    another as `introduced`, different numbers quoted for the same source fact,
    or one session marking a check clean while another files findings.  Each
    conflict is written as a REQUIRED MANUAL CHECK to
    reports/round<R>_judge_conflicts.{md,json} and the cumulative
    reports/JUDGE_CONFLICTS_TODO.md.  Each round's judge wave is followed by ITS
    OWN audit (two rounds -> two audits; `decide` back-fills a round that has no
    audit yet).  The mechanical pass (origin=mechanical) always runs; the LLM
    pass is OFF by default (2026-10-06) and runs for ONE invocation only when
    the operator asks for it -- `--conflict-agent`/`--conflict-agent-cmd`, or
    PAPER_CONFLICT_AGENT_CMD, otherwise the lightweight `codex-lite` preset
    (codex at low reasoning effort).  The backend `run` records is diagnostic
    and never turns the pass back on; `--no-conflict-agent` and
    `--conflict-agent manual` keep the deterministic pass only, and the
    standalone `conflicts` command (its --agent defaults to manual) refreshes
    the audit on demand.

    Every command also accepts `--skip-hash`: it skips the integrity
    VERIFICATION passes for THIS invocation (the pristine copy, pinned
    champions, published winners, frozen run inputs, judge-view digests and the
    a1 base digest). Digests are still RECORDED, so a later invocation without
    the flag verifies the same chain; status/decision.json/the published
    readme say the checks were SKIPPED, never that they were verified.

    A completed round's sandboxes are scratch (the judge sheets are stored in
    state.json), and every judge session copies the whole field: `prune` is the
    supported way to reclaim that space (dry-run unless --yes).

    Every message a COMMAND prints to stdout/stderr is prefixed with the
    current local datetime ("YYYY-MM-DD HH:MM:SS "), so a long run's log shows
    when each step, retry and warning happened. Usage output stays plain:
    `-h`/`--help` (and an argparse usage error) is printed without a prefix, so
    it can be read, piped into documentation or diffed as-is.

    Files a JUDGE sees are anonymized (placeholder paths, one timestamp, one
    mode, no attributes); files no judge sees -- sandboxes, pins, published
    winners, integration views, the pristine copy -- keep their names,
    timestamps, modes and attributes.

    For a complete worked example of the default three-round pipeline,
    including every stage of one round and the artifacts it produces, run
    `python paper_pipeline.py -h` and read the WORKED EXAMPLE section.

AGENT BACKENDS
--------------
    --agent codex    (default) `codex exec -` (prompt piped via stdin, cwd =
                     the sandbox), plus one `-c` override per MCP server the
                     prompts drive, so that server's tools are callable without
                     an operator: `codex exec` runs with approval policy
                     `never`, and an MCP tool call that wants approval is
                     DENIED there, not queued for a human. The overrides name
                     only servers that are actually installed, and they change
                     nothing about how the CLI sandboxes shell commands.
    --agent claude   `claude --permission-mode bypassPermissions --print`
    --agent dsh      the DeepSeek Harness CLI (`dsh`): `dsh --profile headless
                     --json -` (the stage's PROMPT.md piped via stdin, cwd = the
                     sandbox, one fresh persisted session per attempt, `--json`
                     so the opening `session` line carries the id a
                     continuation adopts). The harness is a separate install
                     (node >= 22, `npm i -g @deepseek-ai/dsh@alpha`; verified
                     against dsh 0.2.1-alpha.4 and 0.2.0-rc.2) and its own home
                     ($DSH_HOME, default ~/.dsh) owns the model, the
                     DEEPSEEK_API_KEY credential and its MCP servers -- unlike
                     the codex preset this argv carries no overrides for them.
                     Prompts that tell an agent to reach an MCP tool (the
                     docx-converter renderer, the docx-compare redline engine)
                     fall back to the next converter in their list when the
                     harness has no such server configured.
    --agent qwen     Qwen3.8-27B through an OpenAI-compatible vLLM endpoint,
                     wrapped around the harness the operator already uses. The
                     adapter (`paper_qwen_agent.py`, copied beside the driver)
                     defaults to `PAPER_QWEN_HARNESS=codex`; `dsh` generates an
                     `llm-pi-ai` provider patch for its headless profile, and
                     `chat` is a text-only completion mode. The endpoint is
                     `PAPER_QWEN_BASE_URL` (default
                     http://127.0.0.1:18000/v1), model
                     `PAPER_QWEN_MODEL` (default qwen3.8-27b), key
                     `PAPER_QWEN_API_KEY` (default `dummy`). When the endpoint
                     is not already reachable the adapter starts the SSH tunnel
                     `ssh -p 52080 -N -L 18000:127.0.0.1:8000
                     zxf@101.6.31.113` (configurable with PAPER_QWEN_SSH_HOST/
                     PORT/TUNNEL_LOCAL/TUNNEL_REMOTE; PAPER_QWEN_TUNNEL=off
                     forbids starting it). `python3 paper_qwen_agent.py
                     --probe` reports endpoint/model/tool-call support, and
                     `--check-tools` exits 0/1 on whether the server accepts
                     `tool_choice=auto`: the agentic harness needs that; a
                     server started without `--enable-auto-tool-choice
                     --tool-call-parser` fails a tool-using turn.
    --agent manual   the orchestrator builds every sandbox + PROMPT.md, prints
                     each prompt's path, and polls for the completion signal;
                     you paste each prompt into your agent yourself. Staging is
                     respected: a revise prompt is never printed before its
                     review marker exists.
    any other CLI:   --agent-cmd '["your","cli","--flag"]' or the environment
                     variable PAPER_AGENT_CMD with the same JSON argv list.

COMPLETION CONTRACT / INTEGRITY
-------------------------------
    * An agent run is finished only when its completion signal exists:
      rewrite/guided_review/revise/integrate -> _pipeline_done.json with that stage;
      judge -> a parseable scores.json with matching run_id/target_id/round AND
      one comparison per issued opponent label (a sheet that omits issued labels
      FAILS the run, because a short sheet silently shrinks the panel). The
      judge's _pipeline_done.json is an auxiliary signal only: a marker with no
      scores.json is a failure, not a completion.
      A non-empty revised/ (or rewritten/, integrated/, or guided_review/) is
      NEVER completion.
    * Every read-only input in a sandbox is hashed before the run and
      re-hashed by the postcheck; any byte that moved fails the run. In
      particular a Phase 2 run that edits guided_review/ FAILS.
    * The pristine original is re-hashed at the start of every `run`/`decide`;
      `run` refuses to proceed, and `decide` records the change as a blocking
      problem and exits 5 instead of certifying the decision. Pinned round
      champions, the published winner copies and every judge's frozen inputs are
      re-verified the same way.
    * A retry inside a completed round invalidates that round and every later
      round and PERSISTS the invalidation before touching any sandbox; runs whose
      upstream output no longer exists are left stale and re-materialized by the
      staging loop in dependency order (never rebuilt out of order).
    * A failed run is retried automatically: 2 times by default
      (--retries, up to 3 attempts) with exponential backoff
      (--retry-backoff base seconds, then 2x, 4x, ... capped by
      --retry-backoff-max; 0 = retry immediately). A round whose judge panel is
      still incomplete is left pending with panel_gaps diagnostics instead of
      being decided on the reduced panel.
    * Re-materializing a round's base is content-checked, so re-running an earlier
      round can no longer leave a later round running on that round's stale
      champion copy.
    * Content is the only identity: the field is deduplicated by SHA-256
      corpus digest, so a pinned version equal to the original appears once.
    * Sandbox isolation is prompt-enforced plus post-hoc SHA-256 verification;
      it is not an OS-level jail (see ISOLATION CAVEATS in the original
      orchestrator: --permission-mode bypassPermissions grants full access).

DIRECTORY LAYOUT CREATED UNDER --root
-------------------------------------
    non_revised/                    pristine copy of --source, never written
    runs/r<R>_a1/base               the round's base A1_r (copy)
    runs/r<R>_w<k>/                 base/, non_revised/, rewritten/, PROMPT.md:
                                    the k-th rewritten candidate (k = 1..M),
                                    staged FIRST in every round
    runs/r<R>_guided_review/        base/, non_revised/, prior_round/ (r>1),
                                    guided_review/, PROMPT.md: the round's ONE
                                    guided review pass (skipped when --revises is 0)
    runs/r<R>_a<j>_revise/          base/, non_revised/, guided_review/ (read-only),
                                    revised/, PROMPT.md: the j-th reviewed-and-
                                    revised candidate (j = 2..1+N)
    runs/r<R>_i<k>/                 self/, others/<version-id>/ (EVERY other
                                    pool member), non_revised/, integrated/,
                                    PROMPT.md: the k-th integration run, i.e.
                                    the k-th pool member reworked with the whole
                                    pool as donors
    runs/r<R>_judge_<token>_j<J>/   target/, field/v1..vK, PROMPT.md
                                    (<token> is the opaque session token, never
                                    the version id; the three view roots hold
                                    ANONYMIZED packages -- placeholder paths,
                                    one mtime, one mode, no attributes -- see
                                    blind judging / build_judge_view)
    pinned/<r>_<champion_id>/       documents/, meta.json
    round<R>_winner/                the round's winner, documents at top level
                                    (digest-verified copy of the pin)
    final_clean_version_<root name>/  `decide`'s clean copy of the final champion:
                                    submission documents + code/, no scratch,
                                    auxiliaries or self-written reports -- a
                                    `setup --source` for the next run (always
                                    generated; its certification status is in
                                    the sibling final_clean_version.readme.md)
    redlines/r<R>_<version>/        tracked-changes .docx per candidate:
                                    from-base/, from-original/,
                                    from-setup-source/, plus manifest.json and
                                    README.md (tool chain + every attempt)
    tracking/r<R>_<version>/        difference copies, ONE DIRECTORY PER
                                    BASELINE TOKEN (original/, a1/, w1/, a2/,
                                    ...): "<name>.tracking-<token>.<ext>" (real
                                    Word/latexdiff copies) or the sibling
                                    "<name>.logging-<token>.<ext>" fallback log,
                                    plus manifest.json and README.md. The same
                                    copies also sit BESIDE the candidate
                                    documents in the run sandbox.
    tracking/round<R>_winner/       the published winner's copies: original/
                                    (vs non_revised/) and winner<R-1>/ (vs
                                    round<R-1>_winner/), with the same
                                    manifest.json/README.md. The copies also sit
                                    inside round<R>_winner/ itself.
    pdfs/r<R>_<version>/            the compiled .tex (latexmk) and converted
                                    .docx (Word/MCP first) PDFs of the version,
                                    beside pdfs/original/ for the pristine
                                    original, plus manifest.json and README.md
                                    (persistent: prune never touches them)
    _superseded/                    displaced winner copies (archives)
    pinned/_superseded/             displaced pin copies (archives; nothing the
                                    pipeline produced is ever deleted)
    reports/                        round*.json, decision.json,
                                    DECISION_REPORT.md, raw_scores.csv
    state.json                      crash-safe run/round registry
    pipeline_config.json            knobs as set at setup
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_PARTS_DIRNAME = "paper_pipeline_parts"


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
