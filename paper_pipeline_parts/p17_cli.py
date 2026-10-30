# -*- coding: utf-8 -*-
# Part 17/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# CLI
# =====================================================================

USAGE_EXAMPLES = """usage:
  setup   --source <dir> [--root <dir>] [--rounds 3] [--judges 2] [--review-scope full,full,full]
          [--rewrites M] [--revises N] [--integrators MASK[,MASK…]]
          [--caption-limit N] [--venue ID] [--journal NAME] [--article-type ID]
          [--strict-venue]
          [--zotero off|read|edit|apply]
          copy the pristine corpus read-only, record its SHA-256 manifest, and
          create pipeline_config.json + state.json (no sandboxes are built yet).
          --venue selects the VENUE PROFILE whose submission rules every stage
          enforces (default: nature-biotechnology, this pipeline's pre-venue
          behaviour). A venue is a RULE SET, not a journal: `--journal NAME`
          names the publication the manuscript goes to, as free text. Both are
          recorded in pipeline_config.json (with a snapshot of the resolved
          profile), can be changed later with `set-venue <id>` /
          `set-journal <name>`, and are reported by `status`. `set-venue
          --list` lists the profiles this pipeline can see; a profile is a JSON
          document under <root>/venue_profiles/ (or venue_profiles/ next to
          the script), installed with `set-venue <id> --profile FILE`. A root
          created before this feature keeps working: no `venue` key means the
          default venue, with a note. `--strict-venue` refuses to start when
          the venue is unknown, the journal is missing, or the journal does not
          belong to the selected venue.
          --article-type selects WHICH of the venue's content types this
          submission is (Article, Brief Communication, Review, Resource,
          Analysis, Matters Arising, Letter to the Editor, ...), and the venue
          profile carries the table: each type has its own limits, and a type
          the profile states no numbers for is COUNTED and reported against the
          venue's own content-types table -- never measured against another
          type's caps. `setup` prints the selected type, `set-article-type
          --list` lists the table with the caps each type carries, and
          `set-article-type <id>` changes it later.
          --rewrites M and --revises N plan each round's candidate pool: M
          REWRITTEN candidates (staged first, from the round's base) and N
          REVIEWED-AND-THEN-REVISED candidates (one $paper-review pass per round
          feeding N $paper-revise sessions). Each takes either one integer (the
          same count every round) or a comma-separated list with one entry per
          round (--rewrites 2,0,0); a shorter list is extended by repeating its
          last element. Defaults: --rewrites 2,0,0, --revises 1,1,1 and the
          per-round review scope full,full,full. Every pool member (base,
          rewrites, revisions) is then reworked once by an INTEGRATION run that
          sees the WHOLE pool as donors -- in the default schedule rounds 1-2
          integrate, and round 3 is the review-audit-revise round with NO
          integration.
          --judges is a per-round list too (--judges 2,1): the number of
          independent judge sessions per version in each round, >= 1 per round
          (default 2 everywhere). --review-scope is a per-round list with the
          same rules: "full" or "formatting-writing" (default
          full,full,full).
          --integrators is a per-round 32-BIT MASK (decimal or 0x…; --integrators
          0xF,0x5) selecting which agents of the round run that integration:
          bit (k-1) belongs to the k-th member of the round's pool
          [a1, w1..wM, a2..a{1+N}], a set bit runs that member's integration arm
          i<k>, a clear bit skips it (no session, no judge panel row, no chance
          to win). The default is 0xFFFFFFFF,0xFFFFFFFF,0x0: rounds 1-2 select
          every applicable agent and round 3 stages no integration at all (0x0
          runs no integration in any round you point it at).
          --caption-limit sets the pipeline's PROXY cap for figure-legend
          length (check id M18; e.g. 300; default: the venue profile's own
          default, 0 for a venue that publishes no legend number). Every
          legend's word count is ALWAYS enumerated: with a cap an over-cap
          legend is a reported (never enforced) formatting item; with 0 the
          counts are recorded for you to compare with the venue's own limit.
          Legend length never makes a version ineligible, reorders a ranking or
          fails a decision.
          --zotero is the reference-tooling policy for every agent session
          (off|read|edit|apply; default edit). off never runs the `zot` CLI
          (pyzotero-cli); read resolves and verifies references only; edit also
          lets the revision and integration stages add, remove or relink
          citations in their revised copy (the Zotero library stays read-only);
          apply additionally allows ONE field update of ONE existing library
          item, after a written proposal and an independent re-fetch -- it
          writes to your remote Zotero account and is never the default. No
          mode creates or deletes library items, and the review, rewrite and
          judge sessions can never write.
          Abstract and main-text length are NOT exempt: the VENUE PROFILE's
          own limits apply in their relaxed form (for the default
          nature-biotechnology Article: abstract <= 150 words and main text
          <= 3,000 words excluding abstract, Methods, references and figure
          legends, relaxed by +10% -> <= 165 and +25% -> <= 3,750; another
          profile may count its main body differently, and its `counting` block
          states which sections its own limit leaves out), with words
          counted as runs of non-space characters and a newline treated as
          space. Check id M19 is always active: the review enumerates and
          reports, the revision/integration stages compress by removing
          redundancy only, and length is a formatting-tier item that never
          gates a version. A venue profile that states no limit (the shipped
          `generic` one) still enumerates the counts and names the limit the
          target journal's own guidelines give, and so does an article type the
          selected profile carries no numbers for (the shipped
          nature-biotechnology profile states numbers for its Article type
          only): declaring the type never borrows another type's caps.
  run     --root <dir> [--jobs N] [--timeout S] [--retries 2]
          [--champion-select judge|revise|integrate]
          [--retry-backoff 30] [--retry-backoff-max 600]
          [--agent codex|claude|dsh|qwen|manual] [--agent-cmd '<json argv>']
          [--judge-agent codex|claude|dsh|qwen|manual] [--judge-agent-cmd '<json argv>']
          [--poll S] [--skip-hash]
          drive rounds 1..R as a DEPENDENCY GRAPH: every session starts as soon
          as its inputs exist (the M rewrites and the round's review start
          together; a revise starts when the review marker exists; an
          integration when the WHOLE pool is done; the judge wave when the
          field is complete), keeping up to --jobs sessions in flight.
          --champion-select revise|integrate skips the judge panel and promotes
          the revised (a2) or its integrated candidate (i<M+2>) directly; the
          result is PROVISIONAL / NOT JUDGED, requires exactly one revise arm,
          and is recorded per round in plan.champion_select.
          A failed run is retried --retries times (default 2 -> three attempts)
          with exponential backoff (--retry-backoff base seconds, doubled per
          attempt, capped by --retry-backoff-max; 0 = retry immediately). If the
          judge panel is still incomplete after the retries, the round is left
          pending (reports/round<r>_panel_gaps.json) instead of being decided on
          the reduced panel.
          --judge-agent/--judge-agent-cmd override the backend for the judge
          panel only (it is the largest wave), e.g. to run judges on a cheaper
          CLI than the production stages.
          --only SELECTION runs a subset in this invocation; items are a UNION:
          a round ordinal or range (--only 1,2 = only rounds 1 and 2, every
          stage; --only 1-3), a stage name (--only review = that stage in every
          round; rewrite, review, audit, revise, integrate, judge and the
          aliases w, a/a2, i, merge, j), or ROUND:STAGE (--only 2:merge,3:judge
          = round 2's integration and round 3's judge; 'all' stands for every
          stage), or ONE AGENT SESSION instead of its whole stage: --only
          rewriter2 (only w2), --only integrator1 (only i1), --only reviser1
          (only a2, the first revise arm), --only r1_w2 / 2:rewriter2 (that
          round), --only w2 (every round that has it), --only r1_a2_revise (the
          exact run id `agents` prints); one judge session is --only
          r1_judge_w2_j1, --only w2_j1, --only judge1 or the printed run id
          --only judge_t497f106d_j1. A session item runs ONLY that step: a judge
          SESSION therefore leaves the round UNDECIDED (no winner, no pin, the
          next round is not entered) -- the judge STEP (`--only judge`, a bare
          round, `all`) also selects the round decision, running the remaining
          panel (sessions already done are kept) before pinning. Nothing else is
          started in that invocation, and a round whose other stages are still
          pending stays incomplete for a later `run`.
  run-decide --root <dir> [same options as `run`] [same options as `decide`]
          run the pending rounds and then decide, in series: the `run` phase
          holds the root lock and finishes first, then `decide` recomputes the
          decision and publishes <root>/final_clean_version_<root name>/ -- the
          champion corpus byte-for-byte (no scratch, no auxiliaries, no
          self-written reports), ready to seed the NEXT pipeline run with
          `paper_pipeline.py setup --source <root>/final_clean_version_<root name>`.
  status  --root <dir> [--skip-hash]
          integrity, per-round progress and the per-run table.
          It also prints the venue, the journal and the resolved length limits.
  trend   [--root <dir>] [--roots <dir> ...] [--out FILE.md] [--csv FILE.csv]
          the improvement chain across several runs: one row per decided round
          with the champion, its paired margins (vs_input = the version that run
          started from; vs_incumbent = the previous round's champion) and the
          champion's per-tier/per-severity issue census, plus the panel-free
          deterministic counters. READ-ONLY (no lock, no writes into any root);
          the chain order comes from each root's recorded `source`.
  set-venue --root <dir> <venue-id> [--journal NAME] [--article-type ID] [--force]
          select the venue profile this root enforces (a RULE SET, not a
          journal) and, optionally, the journal and the article type: all are written to
          pipeline_config.json and mirrored into state.json. `set-venue --list`
          lists the venues this pipeline can see; `set-venue --profile FILE`
          installs a profile of your own into <root>/venue_profiles/ and
          selects it; `set-venue --show` prints the current setting. Changing
          the venue of a root that already has run records needs --force,
          because the recorded rounds were judged under the previous rule set.
  set-article-type --root <dir> [<id>] [--list] [--show] [--json] [--force]
          select WHICH of the venue's content types this submission is; the
          type drives the M19 caps, the caption default and the prompt prose
          ("a Nature Biotechnology Brief Communication"). `--list` prints the
          venue profile's table with the caps each type carries (a type whose
          numbers the profile does not carry is counted and named from the
          venue's own content-types table instead of inheriting the Article
          caps); `--show` prints the current selection. A change on a root that
          already has run records needs --force.
  set-journal --root <dir> <name> [--force]
          set the target journal (free text, e.g. "Nature Biotechnology" or
          "Cell"). The journal names the submission the prompts work on and is
          checked against the venue profile's own journal list; it selects no
          rule set by itself. `setup --venue/--journal` sets both at creation
          time.
  agents  --root <dir> [--only SELECTION] [--pending] [--json]
          list the AGENT SESSION NAMES every round will run, without starting
          anything: the base copy, each rewrite, the review (A and, with
          --review-split, B), the auditor, each revise arm and each integration
          arm the round's --integrators mask selected, then every judge session
          the round plans (id `judge_<token>_j<k>`, the salted per-version
          token). `--only` prints exactly the sessions the equivalent `run
          --only` invocation would drive, so `agents --only r1_w2` and `agents
          --only integrator2` double as a dry-run of a filtered run. Producing
          session names are exact, and every id it prints can be fed back to
          `run --only` as printed (`--only r1_a2_revise`, `--only
          judge_t497f106d_j1`; the base copy's `a1` line is not a session).
          Judge ids are exact too, EXCEPT that a
          pending round's judge field is deduplicated by DOCUMENT CONTENT once
          every arm exists: the listing marks the candidates, and `run` prints
          the members a content-identical package drops. Computing the list
          needs no document hashing (a few sha256 calls over the plan), so it
          takes well under a second on any root.
  decide  --root <dir> [--package-winner] [--require-complete]
          [--champion-select judge|revise|integrate]
          [--require-clean-captions] [--skip-hash]
          recompute every completed round in code, verify the pinned chain,
          write reports/DECISION_REPORT.md + decision.json + raw_scores.csv,
          and publish <root>/final_clean_version_<root name>/ (the champion
          corpus without process scratch, auxiliaries or self-written reports)
          so a new pipeline can be seeded directly from it. The clean copy is
          ALWAYS written (2026-10-01), certified or not; the verdict and its
          blockers travel in the sibling final_clean_version.readme.md, so an
          uncertified copy is never silent. Only a corpus that cannot be built
          at all is skipped, with the reason.
          The round-R champion is the final answer; each round's winner is also
          published at <root>/round<R>_winner/, and --package-winner copies the
          final one to <root>/final/ (refused when the pin/winner chain, the
          pristine reference or a judge's frozen inputs changed on disk).
          --require-clean-captions is kept for CLI compatibility and only prints
          the suggested-length caption report for the final winner: caption
          length is advisory in this pipeline, so the flag deliberately no
          longer exits non-zero.
          exit codes: 2 nothing to decide | 4 incomplete (--require-complete) |
          5 broken evidence / recomputed champion differs from the stored one /
          an incomplete judge panel (never certified).
  retry   --root <dir> --run <ID> [--all-failed]
  retry   --root <dir> --runs <SELECTION>              (same grammar as --only)
          reset one run (the failed attempt's artifacts are archived under
          runs/<run>_try<N>_failed/ keeps its whole sandbox -- deliverables,
          transcript and record.json -- and the attempt's record stays in
          state.json). Resetting a run
          inside a completed round invalidates that round and every later round,
          persists the invalidation, and rebuilds sandboxes IN DEPENDENCY ORDER:
          a run whose upstream output is gone is left stale for the staging loop
          instead of being materialized out of order.
          --runs takes the SAME selection grammar as `run --only`, resolved to
          the runs it names: --runs 1:review,1:feedback resets round 1's review
          and feedback sessions, --runs 1:judge,2:feedback,2:review round 1's
          judge wave plus round 2's feedback and review, --runs r1_w2 one
          session, --runs 1 the whole round (its base, every planned session and
          its judge wave). Targets are reset in the plan's dependency order, a
          stage/session the root's plan has no runs for says so instead of
          silently resetting nothing, and --run, --runs and --all-failed are
          mutually exclusive.
  prune   --root <dir> [--keep-latest 1] [--yes]
          delete the SANDBOXES of completed rounds to reclaim disk (every judge
          session copies the whole field + original: a 2-round run can exceed
          10 GB). Pins, published winners, reports and state.json are never
          touched, and `decide` still works because the judge sheets live in
          state.json. Dry-run unless --yes is given.
  redline --root <dir> [--round R] [--version w1,a2,i1|all] [--tool TOOL]
          write tracked-changes .docx files for every candidate version, once per
          source: non_revised/<doc>.docx -> revised/<doc>.docx AND the setup
          --source copy -> revised/<doc>.docx. TOOL is auto (default) and tries
          the docx-compare MCP tool (Word's own CompareDocuments engine, when
          configured), then python-redlines[docxodus], then docx-trackdiff, then
          the built-in OOXML diff; use --redline-cmd '<json argv with {base}
          {revised} {out}>' for any other CLI. Output: <root>/redlines/ +
          manifest.json, which records every attempt, the tool that produced each
          file, and anything skipped (use `--tool none` to only write that
          report). The docxodus bridge is the companion file
          paper_redlines_adapter.py: keep it next to this script to use that
          backend (the built-in writer needs nothing).
  track   --root <dir> [--round R] [--version w1,a2,i1|all] [--tool TOOL] [--no-pdf]
          write the per-version DIFFERENCE-TRACKING copies -- beside each
          document and mirrored under <root>/tracking/ -- for .docx (the
          docx-compare MCP tool first, then the redline chain), .tex/.bib
          (latexdiff; every tracking .tex that is a compile root is also rewired
          to its tracked includes/bibliography and compiled into a sibling
          <name>.tracking-<token>.pdf -- an identical pair yields the clean
          PDF), against the pre-conformed original AND
          the version each arm was derived from, plus every published winner
          against the original and the previous round's winner. The copy's file
          name NAMES THE
          BASELINE it was compared against: <name>.tracking-<token>.<ext> with
          <token> = original / a1 / w<k> / a<k> / winner<r> (the manifest's
          baseline_note spells out what the token means for that row). A failed
          compare writes the readable <name>.logging-<token>.<ext> fallback
          instead, never a fake tracked copy. The same run compiles/converts the
          versions to PDF under
          <root>/pdfs/ (latexmk; the docx-converter chain for DOCX). Both passes
          start NO agent session and cannot change a corpus, a pin or a decision;
          a compile/conversion failure is a WARNING. `--no-pdf` skips the PDF
          pass, `run --no-track` skips both passes after each accepted stage and
          each round.

WORKED EXAMPLE — the default pipeline: THREE rounds, two from-scratch rewrites
in round 1, integration-and-judge in round 2, and a final
review-audit-revise-and-judge round 3 (full review, no rewrite, no integration)
------------------------------------------------------------------------------
  # 0. once: create the round root. Three rounds; 2 judge sessions per version;
  #    M=[2,0,0] rewrites, N=[1,1,1] revisions, review scope
  #    [full, full, full], integrators [0xFFFFFFFF, 0xFFFFFFFF, 0x0].
  #    SOURCE is your pristine submission;
  #    --root must be new or empty.
  python paper_pipeline.py setup --source ./non_revised --root ./paper_rounds \\
      --rounds 3 --judges 2

  # 1. run BOTH rounds end to end. Each round is the same dependency graph; the
  #    arrows below are DEPENDENCIES, not a schedule, so independent runs
  #    overlap (up to --jobs sessions at once):
  #    M rewrites (round 1: w1, w2) and ONE review start TOGETHER ->
  #    N revises (a2) start when the review is done ->
  #    ONE INTEGRATION RUN PER POOL MEMBER, each seeing the WHOLE pool:
  #      i1 = a1 <- (w1, w2, a2)   i3 = w2 <- (a1, w1, a2)
  #      i2 = w1 <- (a1, w2, a2)   i4 = a2 <- (a1, w1, w2)
  #    -> judge panel -> deterministic selection (every arm competes on the same
  #    ranking key and may win) -> content-addressed pin + published
  #    round<R>_winner/.
  python paper_pipeline.py run --root ./paper_rounds --jobs 255
  #    Useful variants of that one command:
  #      --agent manual                  paste each PROMPT.md yourself (staged;
  #                                      --no-wait prints every ready prompt)
  #      --judge-agent-cmd '<json argv>' run the panel on a cheaper CLI
  #      --retries 2 --retry-backoff 30  two retries per failure, exponential
  #                                      backoff (30s, 60s, ... cap 600s); also
  #                                      covers MALFORMED JSON/XML output

  # 2. check progress, integrity and per-run status at any time:
  python paper_pipeline.py status --root ./paper_rounds

  # 3. tracked-changes .docx for every round-2 candidate, one per source:
  #    non_revised/<doc>.docx -> revised/<doc>.docx and
  #    <setup --source>/<doc>.docx -> revised/<doc>.docx
  python paper_pipeline.py redline --root ./paper_rounds --round 2

  # 4. final answer + human-facing report (the round-3 champion), optionally
  #    copying the winner into <root>/final/:
  python paper_pipeline.py decide --root ./paper_rounds --package-winner

  # 5. after the human gate, run one more pass over a round if you want to:
  #    (resets that run; invalidates that round and every later round, then the
  #     next `run` rebuilds them in dependency order)
  python paper_pipeline.py retry --root ./paper_rounds --run r2_a2_revise
  python paper_pipeline.py retry --root ./paper_rounds --runs 1:judge,2:review
  python paper_pipeline.py run   --root ./paper_rounds

  What the example produces:
    ./paper_rounds/non_revised/          pristine copy (never written)
    ./paper_rounds/round1_winner/        round-1 champion (documents at top level)
    ./paper_rounds/round2_winner/        round-2 champion
    ./paper_rounds/round3_winner/        round-3 champion = the final answer
    ./paper_rounds/pinned/               content-addressed pin of every champion
    ./paper_rounds/redlines/             tracked-changes docx + manifest.json
    ./paper_rounds/reports/              DECISION_REPORT.md, decision.json,
                                       raw_scores.csv, round<r>.json
    ./paper_rounds/final/                with --package-winner

integrity verification and --skip-hash:
  every root-verifying command (status/run/decide/...; `selfcheck` and
  `adopt-sweep` are not root-verifying and do not accept it) accepts
  --skip-hash. It skips the integrity VERIFICATION
  passes for THIS invocation -- the pristine copy, the pinned champions, the
  published winners, every completed run's frozen inputs, the judge-view
  digests and the a1 base digest -- which are usually the bulk of a big root's
  status/run/decide time. Digests are still RECORDED (state.json, the pins, the
  fingerprints and every run's own corpus_digest), so a later invocation
  WITHOUT the flag verifies the same chain, and the reports say the checks were
  SKIPPED: `status` prints "not verified (--skip-hash)", decision.json carries
  integrity.hash_checks + certification.hash_checks ("verified" | "skipped")
  with a note, and final_clean_version.readme.md carries it too. NOT skipped:
  the within-invocation freshness checks that decide what an agent READS, and
  the raw_data/ + human_review_feedback/ read-only enforcement.

agent backends:
  --agent codex (default) `codex exec -`, plus a `-c` override per MCP server
  the prompts drive (an MCP call that wants approval is DENIED, not queued, in
  a non-interactive session: approval policy is `never`)   |   --agent claude
  `claude --permission-mode bypassPermissions --print`   |   --agent dsh
  the DeepSeek Harness CLI: `dsh --profile headless --json -` (prompt on
  stdin, one fresh persisted session per attempt; the harness's own home
  $DSH_HOME owns the model, the DEEPSEEK_API_KEY credential and its MCP
  servers, and a continuation adopts the session its `--json` stream named with
  `--session-id`). A gap that would fail every session -- the binary not
  installed, a build whose headless app declares neither `--json` nor the stdin
  task form, a `node` the harness cannot run under (older than 22, or one it
  was not installed for) -- is named with its fix before the wave starts
  instead of once per session.
  --agent manual: the orchestrator builds every sandbox + PROMPT.md and polls
  for each completion signal; you paste each prompt into your agent yourself,
  with cwd = that sandbox. Manual mode respects the same dependencies, and
  --no-wait prints EVERY prompt whose dependencies are already satisfied (a
  revise prompt is never printed before the round's review marker exists, and
  an integration prompt never before the whole pool is done).
  any other CLI: --agent-cmd '["your","cli","--flag"]' or PAPER_AGENT_CMD (JSON
  argv list in the environment).

completion signals (never a bare non-empty output directory):
  rewrite / review / revise / integrate -> _pipeline_done.json, matching stage
  judge -> a parseable scores.json with matching run_id/target_id/round and one
           comparison per issued opponent label (a short sheet FAILS the run;
           the judge marker alone is not a completion)
"""

CHAMPION_SELECT_HELP = (
    "how a round's champion is chosen. judge (default): the relative-judgment panel "
    "scores the field and the deterministic ranking selects the winner. revise: NO "
    "judge panel -- the round's single review-audit-revised candidate (a2) is promoted "
    "directly (integration arms are not run). integrate: NO judge panel -- that "
    "candidate's integration arm i<M+2> is promoted (rounds must plan that arm). Both "
    "no-judge modes need exactly one revise arm per round, and their result is marked "
    "AUTO-PROMOTED / PROVISIONAL, never certified. The flag overrides the root's "
    "persisted champion_select for this invocation only; `setup` records it as the "
    "default")



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_pipeline.py",
        description="Round-based iterative revision pipeline for a manuscript submitted to ANY "
                    "venue or journal: the rule set comes from a configurable VENUE PROFILE "
                    "(`set-venue`, `setup --venue`), the target journal is the free-text "
                    "`set-journal` value, and no stage hard-codes Nature Biotechnology. R fixed "
                    f"rounds (default {DEFAULTS['rounds']}), M REWRITTEN candidates staged first "
                    "in every round, N "
                    "reviewed-and-then-revised candidates from one shared review pass, one "
                    "INTEGRATION run per pool member (each reworking it with the whole pool as "
                    "donors), a "
                    "relative-judgment panel (2*judges*(|field|-1) directed scores per version, "
                    "eligible only when complete) and deterministic code selection with "
                    "content-addressed pinning.",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=DEFAULTS["root"],
                        help=f"pipeline root directory (default: {DEFAULTS['root']})")
    common.add_argument("--strict-venue", action="store_true",
                        help="refuse to run when the root's venue/journal configuration is "
                             "missing or inconsistent (default: report it and continue). An "
                             "unknown venue id is always an error")
    common.add_argument("--skip-hash", action="store_true",
                        help="skip the integrity VERIFICATION passes for this invocation (the "
                             "pristine copy, pinned champions, published winners, frozen run "
                             "inputs, judge-view digests and the a1 base digest) -- usually the "
                             "bulk of a big root's status/run/decide time. Digests are still "
                             "RECORDED (state.json, pins, fingerprints and every run's own "
                             "corpus_digest), a later invocation without the flag verifies the "
                             "same chain, and every report says the checks were SKIPPED. NOT "
                             "skipped: the within-invocation freshness checks that decide what "
                             "an agent reads, and the raw_data/human_review_feedback read-only "
                             "enforcement")

    ps = sub.add_parser("setup", parents=[common], help="initialize the pipeline root")
    ps.add_argument("--source", required=True,
                    help="path to your pristine 'non_revised' manuscript directory")
    ps.add_argument("--champion-select", choices=list(CHAMPION_SELECT_MODES),
                    default=None, metavar="MODE", help=CHAMPION_SELECT_HELP)
    ps.add_argument("--venue", default=None, metavar="ID",
                    help=f"the venue profile whose submission rules every stage enforces "
                         f"(`set-venue --list` shows the shipped and installed ids; "
                         f"{', '.join(sorted(BUILTIN_VENUE_PROFILES))} are always available). "
                         f"Default: "
                         f"{DEFAULTS['venue']} -- this pipeline's pre-venue behaviour, kept as "
                         f"the default for backward compatibility. A venue is a RULE SET, not a "
                         f"journal: `--journal` names the publication the manuscript goes to")
    ps.add_argument("--venue-profile", default=None, metavar="FILE",
                    help="install and use a NEW venue profile from a JSON file on a FRESH root "
                         "(no prior root needed): the file is validated, its `id` selects the "
                         "venue, it is copied into <root>/venue_profiles/, and the resolved "
                         "profile is recorded in pipeline_config.json. On an existing root use "
                         "`set-venue <id> --profile FILE` instead")
    ps.add_argument("--journal", default=None, metavar="NAME",
                    help="the target journal as free text (e.g. \"Nature Biotechnology\", "
                         "\"Cell\"); the prompts name it and the venue profile is checked "
                         "against it. Default: the venue profile's own default journal, or "
                         "unset (the prompts then say \"the target journal\")")
    ps.add_argument("--article-type", default=None, metavar="ID",
                    help="the venue's article type this submission is (e.g. article, "
                         "brief-communication, review, resource, analysis, matters-arising, "
                         "letter-to-the-editor -- the ids the selected venue profile carries; "
                         "`setup` prints them and, on an existing root, "
                         "`set-article-type --list` shows them with their caps). Each type "
                         "carries its own M19 limits: a type the profile has no numbers for is "
                         "counted and reported against the venue's own table, never against "
                         "another type's caps. Default: the venue profile's default type")
    ps.add_argument("--rounds", type=int, default=DEFAULTS["rounds"],
                    help=f"number of fixed rounds (default: {DEFAULTS['rounds']}); the round-R "
                        f"champion is the answer")
    ps.add_argument("--round-indices", type=int, nargs="+", default=None, metavar="R",
                    help="run a SUBSET of the built-in round schedule instead of its first "
                         "entries: --round-indices 2 3 implies --rounds 2 and makes pipeline "
                         "rounds 1-2 adopt the schedule's rounds 2 and 3 (no rewrites, round 2 "
                         "with and round 3 without an integration pass); --round-indices 3 (or "
                         "-1) runs only the final schedule round (no rewrites, no integrations). "
                         "Positive values are 1-based positions in the built-in schedule, "
                         "negative values count from its end (-1 = the last). The per-round "
                         "rewrites/revises/integrators/review-scope values come from the selected "
                         "schedule entries -- do not pass those flags with it; --judges still "
                         "applies")
    ps.add_argument("--pipeline-snapshot-ok", action="store_true",
                    help="allow freezing another pipeline root's SNAPSHOT of the script into "
                         "the new root. `setup` normally refuses this: running a root's own "
                         "`paper_pipeline.py` freezes THAT copy, so every later `run` in the new "
                         "root executes code that may predate the fixes in the tree you "
                         "maintain. Pass this flag only when the snapshot is what you intend to "
                         "run, then read `status` for the staleness note")
    ps.add_argument("--judges", default=None,
                    help=f"independent judge sessions per version: an integer (--judges 3 "
                         f"applies it to every round) or a comma-separated list with one entry "
                         f"per round (--judges 3,1; default: "
                         f"{brief_list(DEFAULTS['judges'])}). A shorter list is extended by "
                         f"repeating its last element, a longer one is truncated to --rounds "
                         f"entries; every entry must be >= 1. The panel of a round is complete "
                         f"only when every field member carries its own round's 2*judges*(|field|"
                         f"-1) directed scores")
    ps.add_argument("--integrators", default=None, metavar="MASK[,MASK…]",
                    help=f"which agents of each round run an INTEGRATION session, as a bitmask "
                         f"per round: an integer (--integrators 0x5 applies it to every round) "
                         f"or a comma-separated list with one entry per round (--integrators "
                         f"0xF,0x5; decimal, 0x…/0o…/0b… all accepted; default: "
                         f"0x{INTEGRATOR_ALL:X},0x{INTEGRATOR_ALL:X},0x0 -- rounds 1-2 integrate "
                         f"every applicable agent, round 3 stages no integration). Bit (k-1) belongs "
                         f"to the k-th member of the round's pool [a1, w1..wM, a2..a{{1+N}}]: "
                         f"set = that member's integration arm i<k> runs (the base arm i1 with "
                         f"bit 0, w1 with bit 1, …); clear = the arm is not planned, never "
                         f"judged and can never win. Bits beyond the pool size are ignored, so "
                         f"0x{INTEGRATOR_ALL:X} always selects the whole pool; 0x0 runs no "
                         f"integration at all. A shorter list is extended by repeating its last "
                         f"element")
    ps.add_argument("--rewrites", default=None,
                    help=f"the number M of REWRITTEN candidates per round: an integer "
                         f"(--rewrites 2 applies it to every round) or a comma-separated list "
                         f"with one entry per round (--rewrites 2,1; default: "
                         f"{','.join(str(x) for x in DEFAULTS['rewrites'])}). A shorter list is "
                         f"extended by repeating its last element, a longer one is truncated to "
                         f"--rounds entries. Each round stages its M rewrites first, from the "
                         f"round's base, before the review")
    ps.add_argument("--review-scope", default=None, metavar="SCOPE[,SCOPE…]",
                    help=f"the review's scope per round: {('|'.join(REVIEW_SCOPE_VALUES))} -- "
                         f"'full' runs the whole frozen sweep set, 'formatting-writing' runs only "
                         f"the surface checks (M1/M3/M6-M12/M17-M20/M24/M26) and the prose/"
                         f"architecture passes J3/J5 and records every other check as out of "
                         f"scope. An integer/list pair, same rules as --rewrites (default: "
                         f"{','.join(DEFAULTS['review_scope'])}). Use it (e.g. "
                         f"--review-scope full,full,formatting-writing) to make a later round a "
                         f"polish pass instead of another full review")
    ps.add_argument("--dedup-mode", default=None, metavar="MODE",
                    help="off (default) counts every judge sheet's issue rows as separate "
                         "mentions; location additionally merges rows ACROSS sheets when they "
                         "carry the same defect class (the NORMALIZED CHECK ID the sheet cites "
                         "-- M01/M02/... are examples, never a closed set: J1-J5, FMT-* (-> M20), "
                         "the writing-rubric Q ids (-> J3) and any other id all work), the SAME exact line "
                         "number and >= 7-word excerpts whose token-set Jaccard is >= 0.8. "
                         "Only rows with both a parseable line number and a long enough excerpt "
                         "are ever merged; every merge is recorded in "
                         "reports/round<r>_dedup_audit.json")
    ps.add_argument("--revision-mode", default=None, metavar="MODE",
                    help="revise against a REAL journal decision letter instead of the "
                         "pipeline's own review rounds. One of: continue (default; the "
                         "historical workflow, unchanged), "
                         "init (start a NEW submission: the venue's own Word template is filled "
                         "by the conform stage BEFORE round 1 -- or, when no template ships, "
                         "the journal's author guidelines and then academic convention -- "
                         "`--no-template-stage` opts out; then the pipeline's own rounds run "
                         "with no journal feedback and no response letter), transfer (option 1: "
                         "revise for a NEW journal; no response to reviewers; rewrites "
                         "allowed), resubmit (option 2: new submission to the SAME journal; "
                         "response to reviewers required; rewrites allowed), major (option 3: "
                         "major revision at the same journal; response required; "
                         "concern-scoped edits ONLY, no rewrites, no general "
                         "review-audit-revise), minor (option 4: as major, for a minor "
                         "revision), llm (option 5: revise against the false-positive-"
                         "filtered llm_review_feedback/ area ONLY; no journal letter, no "
                         "response letter; select it explicitly -- a non-empty area does "
                         "not select a mode by itself). The human feedback file(s) are auto-detected in "
                         "--source by name (feedback/referee/reviewer/editor/decision), or "
                         "named with --journal-feedback")
    ps.add_argument("--journal-feedback", action="append", default=None, metavar="FILE",
                    help="the decision letter / reviewer report file the revision modes read "
                         "(repeatable; a path relative to --root is resolved against it). "
                         "Without this flag the feedback is auto-detected in --source, "
                         "typically under raw_data/")
    ps.add_argument("--journal-feedback-from", default=None, metavar="JOURNAL",
                    help="the journal the feedback came from (free text, e.g. \"iScience\"); "
                         "the response letter names it. The TARGET journal is still --journal")
    ps.add_argument("--submit-code", choices=list(SUBMIT_CODE_MODES),
                    default=DEFAULT_SUBMIT_CODE,
                    help="whether the analysis-code area (`code/`) is part of the SUBMISSION "
                         "(default: off). The area is revision content either way -- a stage may "
                         "revise it and the judges evaluate it -- but with `off` the journal "
                         "submission copy strips `code/` exactly like `raw_data/` and a "
                         "to-be-submitted file (the response letter in particular) may not refer "
                         "into it; with `on` the copy carries `code/` and the letter may cite it "
                         "(`set-submit-code on` flips an existing root)")
    ps.add_argument("--author-to-complete", dest="author_to_complete",
                    choices=list(AUTHOR_TO_COMPLETE_MODES),
                    default=DEFAULT_AUTHOR_TO_COMPLETE,
                    help="where the revision stages put a missing mandatory item (default: "
                         "readme). `readme` forbids the literal \"[AUTHOR TO COMPLETE: ...]\" "
                         "marker in every document and records each item in ONE "
                         "`README-AUTHOR-TO-COMPLETE.md` in the package root, beside the cover "
                         "letter and main text (the README is never submitted; README*.md is "
                         "dropped from the submission copy). `document` keeps the old "
                         "in-document marker convention. `off` forbids the token in every file "
                         "the stages write: the item is left out of the document -- a whole "
                         "missing mandatory file is not scaffolded as a document of "
                         "instructions -- and recorded in the package's own MANUAL_STEPS.md / "
                         "CHANGELOG.md instead. Outside `document`, a marker still present in a "
                         "delivered package is a defect rather than a neutral hand-off "
                         "(`set-author-to-complete readme|document|off` flips an existing "
                         "root)")
    ps.add_argument("--placeholder-file", dest="placeholder_files", action="append",
                    default=None, metavar="GLOB",
                    help="declare a corpus file (package-relative path or glob, matched against "
                         "the path and the bare file name) that is a PLACEHOLDER standing in "
                         "for data it does not contain -- e.g. a haplotype file that is really "
                         "another sample's. Placeholder files are IGNORED as evidence: the "
                         "evidence pack lists them, no role may cite one as a producer, and a "
                         "claim resting only on one is reported as unverified. Repeatable; "
                         "`set-placeholder-file` adds or clears declarations on an existing "
                         "root. A package's own README may declare them too (a line reading "
                         "'Placeholder files: <path-or-glob>'), and identical bytes under two different "
                         "sample names are detected as placeholder copies")
    ps.add_argument("--revises", default=None,
                    help=f"the number N of REVIEWED-AND-THEN-REVISED candidates per round: an "
                         f"integer or a comma-separated list, with the same rules as --rewrites "
                         f"(default: {','.join(str(x) for x in DEFAULTS['revises'])}). One "
                         f"$paper-review pass per round feeds all N $paper-revise sessions")
    ps.add_argument("--caption-limit", type=int, default=None,
                    help=f"the pipeline's PROXY cap for figure-legend length (check id M18; "
                         f"default: the venue profile's own default -- {DEFAULT_CAPTION_LIMIT} = "
                         f"no cap for a venue that publishes no legend number, or the venue's "
                         f"published limit when its profile carries one; e.g. "
                         f"{FIGURE_CAPTION_WORD_LIMIT}). Every legend's word count is ALWAYS "
                         f"enumerated; with a cap an over-cap legend is a reported (never "
                         f"enforced) formatting item, and with 0 the counts are recorded for "
                         f"you to compare with the venue's own limit. Legend length can never "
                         f"make a version ineligible or fail a decision")
    ps.add_argument("--vs-original-rule", choices=("median", "sign"), default=VS_ORIGINAL_RULE,
                    help="the anti-regression gate's decision rule: 'median' (default) makes a "
                         "fresh arm with a negative vs_original median ineligible; 'sign' fails "
                         "only when the exact one-sided sign test over that pair's directed "
                         "scores is significant at 0.05. The pair is 2*judges scores, so both "
                         "rules are coarse -- the sign counts and p are reported either way")
    ps.add_argument("--tiebreak-defect-floor", type=int, default=DEFAULT_TIEBREAK_DEFECT_FLOOR,
                    metavar="N",
                    help=f"the adaptive defect-prefix tie-break's floor (default "
                         f"{DEFAULT_TIEBREAK_DEFECT_FLOOR}): walk the canonical "
                         f"severity_tier_category order (fatal->critical->major->minor, "
                         f"tier by "
                         f"tier in the scoring priority order, peer before own) accumulating "
                         f"each version's reported defect counts, and STOP at the first "
                         f"prefix where the version with the FEWEST defects reaches N (or when "
                         f"every cell is used). The ORDERED per-cell census at that prefix LEADS "
                         f"the ranking (each cell is a separate lexicographic rung); the panel "
                         f"median (then mean, IQR, digest) is the tie-break below it. 0 uses the "
                         f"EMPTY prefix (no census cell leads; the median/mean/IQR/digest decide); "
                         f"a value no prefix can reach (e.g. 999999) uses every cell")
    ps.add_argument("--stop-after-no-progress", type=int, default=0, metavar="K",
                    help="adaptive stop (default 0 = off): once K CONSECUTIVE rounds pin the "
                         "round's own base (no demonstrable, non-regressing progress), `run` "
                         "stops before the next round instead of paying for another pool and "
                         "judge wave; `decide` treats the last completed round as the answer and "
                         "records the stop in decision.json. The fixed --rounds count remains the "
                         "hard cap")
    ps.add_argument("--format-policy", metavar="FILE",
                    help="JSON overrides for the code-side OOXML style/formatting scan "
                         "(paper_docx_format.py). Keys: journal_italics, quote_style, caption_line, "
                         "caption_space, title_page_header, url_style, max_em_dashes_per_1000, "
                         "unlink_zotero_fields, align_heading_sizes, blank_page_tolerance. The "
                         "scan is advisory; `decide --format-gate` promotes its high-severity "
                         "findings to decision problems")
    ps.add_argument("--format-fix", choices=list(FORMAT_FIX_MODES), default=DEFAULT_FORMAT_FIX,
                    help="auto (default) repairs the mechanical OOXML formatting defects "
                         "(break-only paragraph / blank page, legend spacing, heading keepNext, "
                         "running head on the title page, unintended italics outside Zotero "
                         "fields, hyperlink-vs-plain URL treatments, proofing markers) of the "
                         "pristine copy and of every stage package BEFORE it is fingerprinted "
                         "and judged, and records a FORMAT_FIX_*.json artifact next to each run; "
                         "text identity is verified by the fixer. off keeps the copy "
                         "byte-identical to --source and reports formatting only")
    ps.add_argument("--zotero", choices=list(ZOTERO_MODES), default=DEFAULT_ZOTERO_MODE,
                    help="Zotero reference-tooling policy for every agent session. "
                         "off = never run the `zot` CLI (pyzotero-cli); live fields stay on the "
                         "skills' manual route. "
                         "read = agents may resolve/verify references with `zot` but never edit a "
                         "citation field and never write to the library. "
                         "edit (default) = also lets the revision and integration stages add, "
                         "remove or relink citations in their revised copy under the live-field "
                         "validation rules; the library itself stays read-only. "
                         "apply = also lets those stages apply ONE field update to ONE existing "
                         "library item, only after a written proposal and an independent re-fetch "
                         "(`--last-modified auto` makes a concurrent edit fail the write instead "
                         "of being overwritten); this writes to your remote Zotero account, so "
                         "choose it deliberately. No mode ever creates or deletes library items, "
                         "and targeted-review/rewrite/judge sessions can never write")
    ps.set_defaults(func=cmd_setup)
    ps.add_argument("--review-split", choices=list(REVIEW_SPLIT_MODES), default="off",
                    help="run TWO review sessions per round on complementary scopes and merge "
                         "their findings ('phases': mechanical sweeps vs judgment+discovery; "
                         "'aspects': content/scientific vs packaging/compliance); off by default")
    ps.add_argument("--audit", choices=list(AUDIT_MODES), default=DEFAULT_AUDIT,
                    help="run an INDEPENDENT AUDITOR between the reviewer and the revisers: one "
                         "session that disposes every frozen finding (confirm, or drop WITH "
                         "evidence), attacks the reviewer's boilerplate 'OK' closures WITHOUT "
                         "filing new findings (a newly noticed defect goes to "
                         "audit/UNRESOLVED.md for the next review), and hands the audited list "
                         "to the revision arms. ON by default (`--no-audit` restores the "
                         "review -> revise plan shape); it adds `r<r>_audit` between them, and "
                         "the revisers wait for it")
    ps.add_argument("--no-audit", dest="audit", action="store_const", const="off",
                    help="turn the auditor off (same as --audit off)")
    ps.add_argument("--revision-audit", choices=("on", "off"), default="on",
                    help="audit the revised package after revise and write a bounded-repair "
                         "plan. ON (default): the revision audit runs; when its plan is "
                         "non-empty, ONE bounded repair pass applies it and produces the final "
                         "revised version. OFF: both are skipped and the revised version is "
                         "final. `PAPER_REVISION_AUDIT=off` does the same on an existing root, "
                         "and `--no-audit` skips the TARGETED-REVIEW audit (the reviser then works from "
                         "the frozen findings unaudited)")
    ps.add_argument("--targeted-review", choices=list(TARGETED_REVIEW_MODES),
                    default=TARGETED_REVIEW_DEFAULT,
                    help="run the round's TARGETED review -- the general checklist pass "
                         "(M1-M36 / J1-J5 and its D0-D5 discovery round) -- beside the probe "
                         "review. ON by default, which is the pipeline's documented plan. OFF "
                         "(`--no-targeted-review`) runs the PROBE review ALONE: its X-9xx rows "
                         "become the round's frozen finding list, and every class the targeted "
                         "review owns is recorded as a NAMED GAP (in the frozen review view, in "
                         "the audit/revise prompts and in state.json) -- never as a clean "
                         "result. When the stage runs, the round records it as the run kind "
                         "`targeted_review`, the run id `r<r>_targeted_review` and the area "
                         "`targeted_review/`. Refused with a concern-scoped revision mode, "
                         "with --review-split, "
                         "with the probe off (no finding source would remain) and outside a "
                         "full-scope round")
    ps.add_argument("--no-targeted-review", dest="targeted_review", action="store_const",
                    const="off",
                    help="run the probe review alone (same as --targeted-review off); the "
                         "targeted review's classes are recorded as a named gap")
    ps.add_argument("--execution-profile", choices=list(EXECUTION_PROFILES),
                    default=EXECUTION_PROFILE_DEFAULT,
                    help="the instruction profile the stages run under. `high` (default) is "
                         "the pipeline exactly as it has always been: every rule inlined in "
                         "every session prompt, byte for byte. `medium` keeps every rule but "
                         "stops INLINING the elaborative ones: each stage prompt carries the "
                         "contract, the finding schema and the completion marker, and the long "
                         "rule sections are written to INSTRUCTIONS/PROFILE_RULES.md in the "
                         "session sandbox and referenced for a bounded read. It is for a "
                         "limited-context model (one GPU, ~100k tokens or less); the "
                         "postchecks, the coverage table and every deliverable are UNCHANGED. "
                         "Not to be confused with the model's reasoning effort (see "
                         "PAPER_QWEN_REASONING_EFFORT), which this flag does not touch")
    ps.add_argument("--probe-review", choices=list(PROBE_REVIEW_MODES),
                    default=PROBE_REVIEW_DEFAULT,
                    help="run an INDEPENDENT PROBE session in parallel with every full-scope "
                         "round's review: a cold-context INDEPENDENT discovery pass that is "
                         "given ONLY the corpus (the submission documents and the evidence "
                         "areas, raw_data/ and code/ included) -- never a finding list. It is "
                         "GENERIC on purpose: any defect class may be filed, in the standard "
                         "categories and severities, and wherever a defect can be shown by a "
                         "computation the finding declares a small re-runnable script and the "
                         "value it prints. The orchestrator re-runs every declared verifier and "
                         "FAILS the attempt when the computation does not reproduce. Its "
                         "findings are X-9xx rows of the same standing as the discovery round's "
                         "X-* findings (the reviser must resolve them, the auditor may only drop "
                         "them with evidence, the integrator must reconcile them). ON by default "
                         "(`--no-probe-review` turns it off; `set-probe-review off` does the "
                         "same on an existing root); it adds `r<r>_probe` beside `r<r>_review`, "
                         "and the audit/revision sessions wait for it. Skipped in a "
                         "formatting-writing polish round")
    ps.add_argument("--no-probe-review", dest="probe_review", action="store_const",
                    const="off", help="turn the probe review off (same as --probe-review off)")
    ps.add_argument("--placeholder-lookup", choices=list(PLACEHOLDER_LOOKUP_MODES),
                    default=DEFAULT_PLACEHOLDER_LOOKUP,
                    help="online (default) = the orchestrator resolves searchable hand-off "
                         "markers itself (`[AUTHOR TO COMPLETE: state whether this work has been "
                         "posted to a preprint server ...]`) through public APIs (Europe PMC / "
                         "OpenAlex / Crossref, NCBI E-utilities, GitHub, Zenodo, ORCID), writes "
                         "the verdicts (`found` / `absent` = a verified negative / `error`) into "
                         "work/PLACEHOLDER_LOOKUP.md and work/IDENTIFIERS.md, and requires the "
                         "package-producing stages to dispose them -- an answerable marker may "
                         "not ship. off = record the questions and check nothing (useful offline)")
    ps.add_argument("--no-placeholder-lookup", dest="placeholder_lookup",
                    action="store_const", const="off",
                    help="turn the identifier/placeholder lookups off (same as "
                         "--placeholder-lookup off)")
    ps.add_argument("--strict-artifacts", dest="artifact_policy", nargs="?", const="on",
                    choices=list(ARTIFACT_POLICIES), default=None,
                    help="what a boilerplate/unfilled decision artifact does to a stage attempt: "
                         "`on` (default) fails it; `fix` first spends ONE scoped repair session "
                         "on the failed attempt's decision tables -- it may only fill cells, from "
                         "evidence already in the rows, and may only CHANGE files the stage wrote "
                         "(a missing ledger/report/marker is never authored: that attempt fails "
                         "and the stage is re-run) -- and the SAME postcheck then judges it -- "
                         "and a repair that does not clear the problem is a failed attempt like "
                         "any other; `off` records the detector's report as a warning. The "
                         "detectors always RUN and are recorded either way. Bare "
                         "`--strict-artifacts` means `on`")
    ps.add_argument("--fix-artifacts", dest="artifact_policy", action="store_const", const="fix",
                    help="same as --strict-artifacts fix")

    decide_opts = argparse.ArgumentParser(add_help=False)  # shared by decide / run-decide
    decide_opts.add_argument("--package-winner", action="store_true",
                             help="copy the final champion's pinned corpus into <root>/final/; "
                                  "REFUSED unless every configured round is complete and every "
                                  "ranked panel is complete (a provisional or short-panel winner "
                                  "is never packaged)")
    decide_opts.add_argument("--require-complete", action="store_true",
                             help="exit non-zero unless all configured rounds are complete")
    decide_opts.add_argument("--require-clean-captions", action="store_true",
                             help="print the suggested-length caption report for the final winner; "
                                  "kept for CLI compatibility. Caption length is advisory, so this "
                                  "flag never exits non-zero (use `decide` exit codes 4/5 for real "
                                  "problems)")
    decide_opts.add_argument("--format-gate", action="store_true",
                             help="turn the code-side OOXML style/formatting scan's HIGH-severity "
                                  "findings for the final winner (break-only paragraph / blank "
                                  "page, tracked changes, unreadable package) into decision "
                                  "problems (exit 5). Off by default: the scan is reported only, "
                                  "and `python paper_docx_format.py fix FILE --out OUT` repairs the "
                                  "mechanical ones")
    decide_opts.add_argument("--residual-gate", action="store_true",
                             default=DEFAULT_RESIDUAL_GATE,
                             help="refuse to CERTIFY a champion that still carries a residual the "
                                  "pipeline itself can see: a `searchable` hand-off marker the "
                                  "lookup engine answered (`found`/`absent`), a review whose "
                                  "decision artifacts were boilerplate or unfilled, or an "
                                  "integration ledger row that would undo a resolved finding. ON "
                                  "by default (`--non-residual-gate` records them as advisory): "
                                  "the residuals are always recorded in decision.json / the "
                                  "decision report, and this gate turns the GATING ones into "
                                  "problems (exit 5). Unsourced numbers stay advisory")
    decide_opts.add_argument("--non-residual-gate", dest="residual_gate", action="store_false",
                             help="record the residual items instead of failing the decision")
    decide_opts.add_argument("--require-ready", action="store_true",
                             help="turn the published package's own findings into blockers: a "
                                  "form that renders as the Adobe shell, an unfilled required "
                                  "document, or internal working material shipped in the package "
                                  "makes the decision NOT CERTIFIED (exit 5) instead of merely "
                                  "recorded. The readiness verdict and the findings are always "
                                  "written to decision.json and the status readme; this flag only "
                                  "turns them into a gate.")
    decide_opts.add_argument("--unlink-zotero-fields", action="store_true",
                             help="OFF BY DEFAULT. Refuse rather than silently ignore a "
                                  "post-pin flatten: the "
                                  "published copy must remain the judged pin. To flatten, set "
                                  "format_policy.unlink_zotero_fields (or "
                                  "unlink_zotero_fields_at_publish) before `run`, so every "
                                  "candidate is flattened before it is scored; otherwise the "
                                  "author unlinks fields manually.")
    # Shared by run / run-decide / decide: the optional LLM cross-judge conflict
    # audit (the deterministic pass and the manual TODO files always run).  The
    # LLM pass itself is OFF by default -- the LLM defect audit covers the same
    # ground -- and runs only when asked for here or via PAPER_CONFLICT_AGENT_CMD.
    conflict_opts = argparse.ArgumentParser(add_help=False)
    conflict_opts.add_argument("--conflict-agent", choices=list(CONFLICT_AGENT_CHOICES),
                               default=None,
                               help="backend for the cross-judge conflict audit; the LLM pass "
                                    "is OFF by default (only the mechanical conflicts are "
                                    "written) and this flag (or PAPER_CONFLICT_AGENT_CMD) turns "
                                    "it on; 'manual' keeps the deterministic check only")
    conflict_opts.add_argument("--conflict-agent-cmd", default=None,
                               help="JSON argv list for the conflict audit only (wins over "
                                    "--conflict-agent)")
    conflict_opts.add_argument("--no-conflict-agent", action="store_true",
                               help="skip the LLM cross-judge conflict audit; the deterministic "
                                    "conflict check and the manual TODO files are still written")
    # Shared by run / run-decide / decide: the LLM defect audit (diagnostic).
    # ON by default when the judge backend is a real agent; it labels every
    # round<N>_defects.csv row TP/FP and writes the auditedTP_* report family.
    # It never feeds the champion selection.
    defect_audit_opts = argparse.ArgumentParser(add_help=False)
    defect_audit_opts.add_argument("--defect-audit", choices=list(CONFLICT_AGENT_CHOICES),
                                   default=None,
                                   help="backend for the LLM defect audit (ON by default with "
                                        "the judge's agent backend; 'manual' skips it)")
    defect_audit_opts.add_argument("--defect-audit-cmd", default=None,
                                   help="JSON argv list for the defect audit only (wins over "
                                        "--defect-audit)")
    defect_audit_opts.add_argument("--no-defect-audit", action="store_true",
                                   help="skip the LLM defect audit (no auditedTP_* files are "
                                        "written; the non-audited reports are unchanged)")
    run_opts = argparse.ArgumentParser(add_help=False)   # shared by run / run-decide
    run_opts.add_argument("--champion-select", choices=list(CHAMPION_SELECT_MODES),
                          default=None, metavar="MODE", help=CHAMPION_SELECT_HELP)
    run_opts.add_argument("--jobs", type=int, default=DEFAULTS["jobs"],
                    help=f"concurrent agent sessions (default: {DEFAULTS['jobs']})")
    run_opts.add_argument("--timeout", type=int, default=None,
                    help="per-run timeout seconds (default: 4h; manual mode: none)")
    run_opts.add_argument("--retries", type=int, default=DEFAULTS["retries"],
                    help=f"automatic retries for a failed run (default: "
                         f"{DEFAULTS['retries']} -> three attempts); each retry waits "
                         f"base*2^(n-1) seconds so a transient LLM/CLI failure does not shrink "
                         f"the judge panel")
    run_opts.add_argument("--retry-backoff", type=int, default=DEFAULTS["retry_backoff"],
                    help=f"base seconds of the exponential retry backoff (default: "
                         f"{DEFAULTS['retry_backoff']}, 0 = retry immediately)")
    run_opts.add_argument("--retry-backoff-max", type=int, default=DEFAULTS["retry_backoff_max"],
                    help=f"cap on a single backoff wait in seconds (default: "
                         f"{DEFAULTS['retry_backoff_max']})")
    run_opts.add_argument("--agent", choices=list(AGENT_CHOICES), default=DEFAULTS["agent"],
                    help="the session backend: codex (default) = `codex exec -`, claude = "
                         "`claude --permission-mode bypassPermissions --print`, dsh = the "
                         "DeepSeek Harness CLI (`dsh --profile headless --json -`, installed "
                         "separately), qwen = Qwen3.8-27B through an OpenAI-compatible vLLM "
                         "endpoint (the adapter wraps codex/dsh; set PAPER_QWEN_* and see "
                         "paper_qwen_agent.py --probe), manual = stage every prompt for a "
                         "human; --agent-cmd overrides any of them")
    run_opts.add_argument("--no-template-stage", action="store_true",
                          help="do NOT author the package inside the journal's Word templates "
                               "before the round (the default is to run that stage first in "
                               "the `init` AND `transfer` journal modes, since it defines the "
                               "submission the round starts from)")
    run_opts.add_argument("--agent-cmd", default=None,
                    help="JSON argv list overriding the agent command")
    run_opts.add_argument("--judge-agent", choices=list(AGENT_CHOICES), default=None,
                    help="backend for judge sessions only (default: same as --agent); the judge "
                         "panel dominates cost, so this lets it run on a different CLI/model "
                         "(dsh = the DeepSeek Harness CLI)")
    run_opts.add_argument("--judge-agent-cmd", default=None,
                    help="JSON argv list for judge sessions only (default: --agent-cmd)")
    run_opts.add_argument("--poll", type=int, default=DEFAULTS["poll"],
                    help="manual-mode completion poll interval seconds (default: 10)")
    run_opts.add_argument("--only", metavar="SELECTION",
                    help="run only a subset of the pipeline in this invocation. Items are "
                         "comma-separated and combine as a UNION: a ROUND ordinal or range "
                         "(--only 1,2 = only rounds 1 and 2, every stage; --only 1-3), a STAGE "
                         "name (--only review = that stage in every round; rewrite, review, "
                         "audit, revise, integrate, judge, and the journal modes' feedback, "
                         "concerns, response; aliases w, a/a2, i, merge, j, fb, resp), "
                         "ROUND:STAGE (--only 2:merge,3:judge = round 2's integration and round "
                         "3's judge; '.' and '/' also separate, 'all' stands for every stage), or "
                         "ONE AGENT SESSION instead of its whole stage: --only rewriter2 runs only "
                         "w2, --only integrator1 only i1, --only reviser1 only a2 (the first "
                         "revise arm), --only r1_w2 only round 1's w2, --only w2 that session in "
                         "every round that has it, --only reviewer / --only audit the review / "
                         "audit session. One JUDGE session is --only r1_judge_w2_j1 (round 1's w2, "
                         "judge 1), --only w2_j1 (no round) or --only judge1 (judge 1 of every "
                         "version). "
                         "A session item runs ONLY that step and then stops: it never continues into "
                         "a step it did not select, so a judge SESSION runs its sessions and leaves "
                         "the round UNDECIDED (no winner, no pin, the next round is not entered) -- "
                         "the judge STEP (`--only judge`, a bare round, `all`) is what also selects "
                         "the round decision, and it runs the remaining panel (sessions already done "
                         "are kept) before pinning. "
                         "Nothing else is started in this invocation; a round whose other stages are "
                         "still pending stays incomplete and is resumed by a later `run` (or "
                         "another `--only`). Use `retry --run <ID>` first when you want a "
                         "completed stage to run again. Examples: --only 1,2  |  --only review  |  "
                         "--only review,revise  |  --only 2:merge  |  --only merge  |  "
                         "--only judge  |  --only rewriter1  |  --only integrator2. "
                         "`agents --root <dir> --only <selection>` prints the session names a "
                         "selection would run without starting anything")
    run_opts.add_argument("--no-redline", action="store_true",
                    help="skip the automatic tracked-changes generation after each round "
                         "(the `redline` command still works)")
    run_opts.add_argument("--no-track", action="store_true",
                    help="skip the automatic difference-tracking copies (the stage-time hook "
                         "and the round-close pass) and the persistent PDF renders (the "
                         "`track` command still works)")
    run_opts.add_argument("--no-wait", action="store_true",
                    help="manual mode: print the prompts for runs whose dependencies are "
                         "satisfied and exit without waiting")
    pr = sub.add_parser("run", parents=[common, run_opts, conflict_opts, defect_audit_opts],
                        help="execute pending rounds")
    pr.set_defaults(func=cmd_run)

    prd = sub.add_parser("run-decide",
                         parents=[common, run_opts, decide_opts, conflict_opts, defect_audit_opts],
                         help="run the pending rounds, then decide in series")
    prd.set_defaults(func=cmd_run_decide)

    prl = sub.add_parser("redline", parents=[common],
                         help="write tracked-changes .docx (non_revised -> revised and "
                              "setup --source -> revised) for every candidate")
    prl.add_argument("--round", type=int, default=None, help="only this round (default: all)")
    prl.add_argument("--version", default="all",
                     help="one candidate version id (a1/w1/w2/a2/i1/...), a comma-separated list "
                          "of them, or all (default: every candidate of each requested round, "
                          "i.e. the round's rewrites, revisions and integrated candidates)")
    prl.add_argument("--tool", choices=list(REDLINE_TOOLS), default="auto",
                     help="auto (default): the docx-compare MCP tool (Word's own compare engine) "
                          "first, then python-redlines[docxodus], docx-trackdiff and the built-in "
                          "OOXML diff -- under auto a backend whose markup overstates the change "
                          "(see redline_fidelity) is passed over for the next, and the "
                          "least-marked result is kept; or force one backend (its result is kept "
                          "and the fidelity caveat reported); `none` writes only the "
                          "manifest/report")
    prl.add_argument("--redline-cmd", default=None,
                     help="JSON argv list for any other tool, with {base} {revised} {out} "
                          "placeholders")
    prl.set_defaults(func=cmd_redline)

    ptrk = sub.add_parser("track", parents=[common],
                          help="write the per-version difference-tracking copies "
                               "(<name>.tracking-<baseline>.<ext>, or their "
                               "logging-<baseline>.<ext> fallbacks) and the persistent "
                               "PDF renders")
    ptrk.add_argument("--round", type=int, default=None, help="only this round (default: all)")
    ptrk.add_argument("--version", default="all",
                      help="one version id (a1/w1/a2/i1/...), a comma-separated list of them, "
                           "or all (default: every version of each requested round, plus that "
                           "round's published winner)")
    ptrk.add_argument("--tool", choices=list(REDLINE_TOOLS), default="auto",
                      help="the .docx backend(s) to try: auto (default) uses the docx-compare "
                           "MCP tool (Word's own compare engine) first, then the redline chain; "
                           "`none` writes NO .docx copy at all (not even a logging "
                           "fallback); a skipped comparison row records the reason")
    ptrk.add_argument("--redline-cmd", default=None,
                      help="JSON argv list for any other .docx differ, with {base} {revised} "
                           "{out} placeholders")
    ptrk.add_argument("--no-pdf", action="store_true",
                      help="skip the PDF compile/convert pass (tracking only)")
    ptrk.set_defaults(func=cmd_track)

    pst = sub.add_parser("status", parents=[common], help="show round/run status")
    pst.set_defaults(func=cmd_status)

    psync = sub.add_parser(
        "sync-code", parents=[common],
        help="copy the maintained paper_pipeline.py/paper_docx_format.py/"
             "paper_redlines_adapter.py/paper_qwen_agent.py into a root and record "
             "their digests")
    psync.set_defaults(func=cmd_sync_code)

    ptr = sub.add_parser("trend", parents=[common],
                         help="report the improvement chain across several pipeline roots "
                              "(per round: champion, its paired margins, and the per-tier issue "
                              "census). Read-only: no root is modified, no lock is taken")
    ptr.add_argument("--roots", nargs="+", default=None, metavar="ROOT",
                     help="the roots to report; the ORDER is inferred from each root's recorded "
                          "`source` (the chain of final_clean_version inputs) when it can be, "
                          "otherwise the order given here is kept. Default: --root alone")
    ptr.add_argument("--out", default=None, metavar="FILE",
                     help="also write the markdown report to FILE")
    ptr.add_argument("--csv", default=None, metavar="FILE",
                     help="also write the per-round rows to FILE as CSV (for plotting)")
    ptr.set_defaults(func=cmd_trend)

    # The sessions' own pre-flight (see `sandbox_selfcheck`): the stage prompts
    # tell every session to run it in the sandbox BEFORE it writes the marker.
    # Deliberately root-free and read-only, so a session (or the operator) can
    # ask "what would the postcheck say about this sandbox?" at any time.
    psc = sub.add_parser("selfcheck",
                         help="print the postcheck's own paperwork verdict for one sandbox "
                              "(the marker and its location, the deliverables, the decision "
                              "tables, the audit sheet); read-only, needs no --root")
    psc.add_argument("--sandbox", required=True,
                     help="the run's sandbox (the directory holding PROMPT.md)")
    psc.add_argument("--stage", required=True,
                    choices=list(SELFCHECK_STAGES) + list(SELFCHECK_STAGE_ALIASES),
                     help="the run's stage/kind")
    psc.add_argument("--run-id", default=None,
                     help="the run id the marker must name (default: the sandbox's own name)")
    psc.add_argument("--round", type=int, default=0,
                     help="the round the marker must name (0 = do not check the round)")
    psc.set_defaults(func=cmd_selfcheck)

    psw2 = sub.add_parser("adopt-sweep",
                          help="validate a targeted_review/round2/new_sweeps.md proposal file and, with "
                               "--yes, append its proposals to the skill's references/sweeps.md "
                               "(re-syncing the standalone prompt's appendix)")
    psw2.add_argument("--proposals", required=True, metavar="PATH",
                      help="the proposal file, or a review sandbox carrying "
                           "targeted_review/round2/new_sweeps.md")
    psw2.add_argument("--sweeps", default=None, metavar="PATH",
                      help="target sweeps.md (default: paper-skills/paper-review/references/"
                           "sweeps.md beside this script)")
    psw2.add_argument("--yes", action="store_true",
                      help="append the validated proposal(s); without it this is a dry run")
    psw2.set_defaults(func=cmd_adopt_sweep, root=None)

    pag = sub.add_parser("agents", parents=[common],
                         help="list the agent session names each round will run (a dry plan)")
    pag.add_argument("--only", metavar="SELECTION",
                     help="preview the sessions an equivalent `run --only SELECTION` invocation "
                          "would drive (the same grammar, including single agents such as "
                          "`rewriter1`, `r1_w2` or `r1_judge_w2_j1`)")
    pag.add_argument("--pending", action="store_true",
                     help="hide the sessions that already finished (only what may still run)")
    pag.add_argument("--json", action="store_true",
                     help="machine-readable output: {root, only, rounds:[{round, producing:[…], "
                          "judge:[…], …]}")
    pag.set_defaults(func=cmd_agents)

    pcf = sub.add_parser("conflicts", parents=[common],
                         help="audit each round's judge panel for cross-judge conflicts and "
                              "write the manual TODO list")
    pcf.add_argument("--round", type=int, default=None, metavar="R",
                     help="audit only this round (default: every round that has judge sheets)")
    pcf.add_argument("--agent", choices=list(CONFLICT_AGENT_CHOICES), default="manual",
                     help="backend for the LLM conflict audit (default: manual = the "
                          "deterministic check only; pass codex-lite/codex/claude/dsh, or "
                          "set PAPER_CONFLICT_AGENT_CMD, to add the LLM pass)")
    pcf.add_argument("--agent-cmd", default=None,
                     help="JSON argv list overriding the agent command")
    pcf.add_argument("--conflict-agent", choices=list(CONFLICT_AGENT_CHOICES), default=None,
                     help="override --agent for the conflict audit only")
    pcf.add_argument("--conflict-agent-cmd", default=None,
                     help="JSON argv list for the conflict audit only")
    pcf.add_argument("--timeout", type=int, default=None,
                     help="LLM conflict-audit timeout seconds (default: 900, capped at 1800)")
    pcf.add_argument("--no-agent", action="store_true",
                     help="skip the LLM audit; run only the deterministic conflict check")
    pcf.add_argument("--force", action="store_true",
                     help="re-run the LLM audit even when the judge sheets are unchanged")
    pcf.set_defaults(func=cmd_conflicts)

    pd = sub.add_parser("decide",
                        parents=[common, decide_opts, conflict_opts, defect_audit_opts],
                        help="recompute rounds, verify pins, write the decision report and "
                             "publish <root>/final_clean_version_<root name>/")
    pd.add_argument("--champion-select", choices=list(CHAMPION_SELECT_MODES),
                    default=None, metavar="MODE", help=CHAMPION_SELECT_HELP)
    pd.set_defaults(func=cmd_decide)

    psv = sub.add_parser("set-venue", parents=[common],
                         help="select the venue profile this root enforces (a rule set, not a "
                              "journal) and optionally the journal")
    psv.add_argument("venue", nargs="?", default=None, metavar="VENUE",
                     help="venue profile id, e.g. nature-biotechnology, generic, or an id you "
                          "installed with --profile (`set-venue --list` shows them)")
    psv.add_argument("--journal", default=None, metavar="NAME",
                     help="also set the target journal, atomically with the venue change")
    psv.add_argument("--article-type", default=None, metavar="ID",
                     help="also select the article type (see `set-article-type`); a type the "
                          "new venue's profile does not carry falls back to that profile's "
                          "default with a note")
    psv.add_argument("--profile", default=None, metavar="FILE",
                     help=f"install a venue profile JSON into "
                          f"<root>/{VENUE_PROFILES_DIRNAME}/<id>{VENUE_PROFILE_SUFFIX} and select "
                          f"it; the profile's own 'id' must match <VENUE>")
    psv.add_argument("--list", action="store_true",
                     help="list every venue this pipeline can see (root-local, shipped, "
                          "built-in) and exit")
    psv.add_argument("--show", action="store_true",
                     help="print the root's current venue, journal and resolved limits and exit")
    psv.add_argument("--json", action="store_true",
                     help="with --list/--show: machine-readable output")
    psv.add_argument("--force", action="store_true",
                     help="change the venue although this root already has run records (the "
                          "recorded rounds were judged under the previous rule set)")
    psv.set_defaults(func=cmd_set_venue)

    psj = sub.add_parser("set-journal", parents=[common],
                         help="set the target journal (free text; selects no rule set by itself)")
    psj.add_argument("journal", nargs="?", default=None, metavar="NAME",
                     help="the target journal, e.g. \"Nature Biotechnology\" or \"Cell\"")
    psj.add_argument("--show", action="store_true",
                     help="print the root's current venue, journal and resolved limits and exit")
    psj.add_argument("--json", action="store_true",
                     help="with --show: machine-readable output")
    psj.add_argument("--force", action="store_true",
                     help="change the journal although this root already has run records")
    psj.set_defaults(func=cmd_set_journal)

    psm = sub.add_parser("set-revision-mode", parents=[common],
                         help="select the revision mode (continue / init / option 1 transfer / "
                              "2 resubmit / 3 major / 4 minor / 5 llm), or show the current one")
    psm.add_argument("mode", nargs="?", default=None, metavar="MODE",
                     help="continue (the pipeline's own targeted-review/revise rounds) | init "
                          "(conform into the venue's own "
                          "Word template before round 1, then the pipeline's own rounds; no "
                          "journal feedback) | transfer (option 1: new journal, no response "
                         "letter) | resubmit (option 2: same journal, response letter) | "
                         "major (option 3: scoped major revision + response letter) | "
                         "minor (option 4: scoped minor revision + response letter) | "
                         "llm (option 5: the false-positive-filtered llm_review_feedback/ "
                         "area only; no journal letter, no response letter). "
                          "Omit (or pass --show) to print the current mode")
    psm.add_argument("--journal-feedback", action="append", default=None, metavar="FILE",
                     help="the decision letter / reviewer report file (repeatable; relative "
                          "paths resolve against the root)")
    psm.add_argument("--journal-feedback-from", default=None, metavar="JOURNAL",
                     help="the journal the feedback came from (free text, e.g. iScience)")
    psm.add_argument("--show", action="store_true",
                     help="print the current revision mode and its feedback files")
    psm.add_argument("--force", action="store_true",
                     help="change the mode although this root already has run records")
    psm.set_defaults(func=cmd_set_revision_mode)

    psc = sub.add_parser("set-submit-code", parents=[common],
                         help="set (or show) whether the analysis-code area (`code/`) is part "
                              "of the SUBMISSION: off (default -- revision content the stages "
                              "revise and the judges evaluate, but stripped from "
                              "journal_submission/ like raw_data/, and not citeable by the "
                              "response letter) or on (the submission copy carries it and a "
                              "letter may cite it)")
    psc.add_argument("mode", nargs="?", default=None, choices=list(SUBMIT_CODE_MODES),
                     metavar="MODE",
                     help="on or off. Omit, or pass --show, to print the current policy")
    psc.add_argument("--show", action="store_true",
                     help="print whether `code/` is part of the submission and exit")
    psc.set_defaults(func=cmd_set_submit_code)

    pac = sub.add_parser("set-author-to-complete", parents=[common],
                         help="set (or show) where the revision stages put a missing mandatory "
                              "item: readme (default -- no document carries the marker; each "
                              "item goes to README-AUTHOR-TO-COMPLETE.md beside the cover letter "
                              "and main text, never submitted), document (the literal "
                              "\"[AUTHOR TO COMPLETE: ...]\" marker inside the document), or "
                              "off (no marker anywhere: the item goes to the package's "
                              "MANUAL_STEPS.md, and a shipped marker is a defect)")
    pac.add_argument("mode", nargs="?", default=None,
                     choices=list(AUTHOR_TO_COMPLETE_MODES),
                     metavar="MODE",
                     help="readme, document, or off. Omit, or pass --show, "
                          "to print the current policy")
    pac.add_argument("--show", action="store_true",
                     help="print where hand-off items go and exit")
    pac.set_defaults(func=cmd_set_author_to_complete)

    phf = sub.add_parser("set-placeholder-file", parents=[common],
                         help="add, clear or show the PLACEHOLDER-FILE declarations of an "
                              "existing root: a declared file stands in for data it does not "
                              "contain (e.g. ACT haplotypes that are really HG008's) and is "
                              "IGNORED as evidence by every session")
    phf.add_argument("patterns", nargs="*", default=None, metavar="GLOB",
                     help="package-relative path(s) or glob(s) to declare (matched against the "
                          "path and the bare file name). With no operand, prints the current "
                          "declarations and the files they resolve to")
    phf.add_argument("--clear", action="store_true",
                     help="remove every placeholder-file declaration and exit")
    phf.set_defaults(func=cmd_set_placeholder_file)

    ptf = sub.add_parser("set-tiebreak-defect-floor", parents=[common],
                         help="set (or show) the adaptive defect-prefix walk's floor (the prefix "
                              "LEADS champion selection; the name is historical)")
    ptf.add_argument("floor", nargs="?", type=int, default=None, metavar="N",
                     help=f"the number of defects the CLEANEST ranked version must reach before "
                          f"the severity_tier_category walk stops (default "
                          f"{DEFAULT_TIEBREAK_DEFECT_FLOOR}; 0 = the EMPTY prefix (no census "
                          f"cell leads), a value no prefix can reach, e.g. 999999, = use every "
                          f"cell). Omit, or pass "
                          f"--show, to print the current value")
    ptf.add_argument("--show", action="store_true",
                     help="print the root's current floor and exit")
    ptf.add_argument("--force", action="store_true",
                     help="change the floor although this root already has run records")
    ptf.set_defaults(func=cmd_set_tiebreak_defect_floor)

    pdm = sub.add_parser("set-dedup-mode", parents=[common],
                         help="set (or show) the issue-census dedup mode: off (default, no "
                              "cross-sheet merging) or location (merge rows on defect class + "
                              "exact line number + a fuzzy-matched >= 7-word excerpt)")
    pdm.add_argument("mode", nargs="?", default=None, choices=list(DEDUP_MODES), metavar="MODE",
                     help="off (every sheet's rows are separate mentions) or location (merge "
                          "across sheets on the structured location key). Omit, or pass --show, "
                          "to print the current mode")
    pdm.add_argument("--show", action="store_true",
                     help="print the root's current dedup mode and exit")
    pdm.add_argument("--force", action="store_true",
                     help="change the mode although this root already has run records")
    pdm.set_defaults(func=cmd_set_dedup_mode)

    pcs = sub.add_parser("set-champion-select", parents=[common],
                         help="set (or show) how future round champions are chosen: judge "
                              "(the default relative-judgment panel), revise (no panel: promote "
                              "the review-audit-revised a2) or integrate (no panel: promote the "
                              "integration arm i<M+2> of that revised candidate)")
    pcs.add_argument("mode", nargs="?", default=None, choices=list(CHAMPION_SELECT_MODES),
                     metavar="MODE",
                     help="judge, revise or integrate. The no-judge modes are PROVISIONAL and "
                          "need exactly one revise arm (--revises 1). Omit, or pass --show, to "
                          "print the current mode")
    pcs.add_argument("--show", action="store_true",
                     help="print the root's current champion-selection mode and exit")
    pcs.add_argument("--force", action="store_true",
                     help="change the mode although this root already has run records")
    pcs.set_defaults(func=cmd_set_champion_select)

    ppr = sub.add_parser("set-probe-review", parents=[common],
                         help="set (or show) the PROBE REVIEW policy: on (one independent, "
                              "cold-context discovery session beside each full-scope round's "
                              "review; every declared verifier is re-run by the orchestrator) "
                              "or off (the documented off switch)")
    ppr.add_argument("mode", nargs="?", default=None, choices=list(PROBE_REVIEW_MODES),
                     metavar="MODE",
                     help="on or off. Omit, or pass --show, to print the current policy")
    ppr.add_argument("--show", action="store_true",
                     help="print the root's current probe-review policy and exit")
    ppr.add_argument("--force", action="store_true",
                     help="change the policy although this root already has run records")
    ppr.set_defaults(func=cmd_set_probe_review)

    pav = sub.add_parser("add-venue", parents=[common],
                         help="create/update ONE venue profile (JSON + venue_profiles/README.md) "
                              "and download its recent OA exemplars with an agent, then derive "
                              "the structure-only word/latex template pack")
    pav.add_argument("venue", metavar="ID",
                     help="the venue id (slug) whose profile and exemplars are created/updated")
    pav.add_argument("--journal", default=None, metavar="NAME",
                     help="the target journal name for the profile's `journals` list")
    pav.add_argument("--article-type", default=None, metavar="ID",
                     help="the article type the exemplar download should target (e.g. "
                          "original-research); the profile itself still carries the whole table")
    pav.add_argument("--agent", choices=list(AGENT_CHOICES),
                     default=DEFAULTS["agent"], help="the agent that writes the profile and "
                                                     "downloads the exemplars (default: codex)")
    pav.add_argument("--agent-cmd", default=None, metavar="JSON",
                     help="a custom agent argv (JSON list); overrides --agent")
    pav.add_argument("--profiles-dir", default=None, metavar="DIR",
                     help="the venue store to write (default: the venue_profiles/ directory "
                          "next to this script)")
    pav.add_argument("--timeout", type=int, default=3600, metavar="S",
                     help="the agent session's timeout in seconds (default 3600)")
    pav.add_argument("--no-download", action="store_true",
                     help="keep the prompt unchanged but skip the download section when the "
                          "agent prompt is staged for a manual operator")
    pav.add_argument("--publish-only", action="store_true",
                     help="skip the agent: publish a COMPLETED sandbox's staged `store/` tree "
                          "into the shared store, then validate and derive the pack (use after "
                          "an agent run that could only stage its work)")
    pav.add_argument("--from-sandbox", default=None, metavar="DIR",
                     help="the staging sandbox for --publish-only (default: the newest "
                          "<profiles-dir>/.add-venue/<venue>-*)")
    pav.set_defaults(func=cmd_add_venue)

    pbt = sub.add_parser("build-venue-templates", parents=[common],
                         help="derive the pinned structure-only template pack for a venue from "
                              "the OA exemplars in <venue_profiles>/<venue-id>.manuscripts/")
    pbt.add_argument("--venue", required=True, metavar="ID",
                     help="the venue id whose exemplars are summarised")
    pbt.add_argument("--profiles-dir", default=None, metavar="DIR",
                     help="the venue store holding <id>.manuscripts/ (default: search the root's "
                          "venue_profiles/, then the shipped one)")
    pbt.add_argument("--exemplars", default=None, metavar="DIR",
                     help="use this exemplar directory instead of the discovered one")
    pbt.set_defaults(func=cmd_build_venue_templates)

    pst = sub.add_parser("set-article-type", parents=[common],
                         help="select the venue's article type (Article, Brief Communication, "
                              "Review, ...), which drives the M19 caps and the prompts")
    pst.add_argument("article_type", nargs="?", default=None, metavar="ID",
                     help="the article-type id the venue profile carries (e.g. article, "
                          "brief-communication); `set-article-type --list` shows them")
    pst.add_argument("--list", action="store_true",
                     help="list the article types of this root's venue, with the caps each "
                          "one carries, and exit")
    pst.add_argument("--show", action="store_true",
                     help="print the root's current venue, article type, journal and limits")
    pst.add_argument("--json", action="store_true",
                     help="with --list/--show: machine-readable output")
    pst.add_argument("--force", action="store_true",
                     help="change the type although this root already has run records (its "
                          "prompts, caps and judgments belong to the previous type)")
    pst.set_defaults(func=cmd_set_article_type)

    prt = sub.add_parser("retry", parents=[common],
                         help="rebuild a failed/stale run's sandbox and reset it")
    prt.add_argument("--run", default=None, help="specific run id, e.g. r2_a2_review")
    prt.add_argument("--runs", metavar="SELECTION", default=None,
                     help="reset the runs an equivalent `run --only SELECTION` invocation "
                          "selects: the SAME grammar (rounds, stages, ROUND:STAGE, single "
                          "sessions, judge selectors and judge run ids), e.g. "
                          "`--runs 1:review,1:feedback` or `--runs 1:judge,2:feedback,2:review`. "
                          "Mutually exclusive with --run and --all-failed; a selection that "
                          "names no existing run says so and resets nothing")
    prt.add_argument("--all-failed", action="store_true",
                     help="reset every failed or stale run")
    prt.set_defaults(func=cmd_retry)

    pp = sub.add_parser("prune", parents=[common],
                        help="delete completed rounds' sandboxes to reclaim disk "
                             "(pins, winners, reports, state, redlines/, tracking/ and "
                             "pdfs/ are never touched)")
    pp.add_argument("--keep-latest", type=int, default=1,
                    help="keep the sandboxes of the last N rounds (default 1)")
    pp.add_argument("--yes", action="store_true",
                    help="actually delete; without it prune only reports what it would remove")
    pp.set_defaults(func=cmd_prune)

    pat = sub.add_parser("conform", parents=[common],
                         help="AUTHOR the WHOLE submission inside the venue's official Word "
                              "templates: with --agent the LLM copies the templates and "
                              "replaces their placeholders with the real content (keeping "
                              "every template style, header, footer and bullet); without "
                              "--agent the same job is done by the code-side pass")
    pat.add_argument("--source", default=None, metavar="DIR",
                     help="the package to rebuild (default: "
                          "<root>/final_clean_version_<root name>/, else "
                          "the last complete round's round<r>_winner/)")
    pat.add_argument("--dest", default=None, metavar="DIR",
                     help=f"destination package directory (default: "
                          f"<root>/{TEMPLATE_PACKAGE_DIRNAME}/)")
    pat.add_argument("--force", action="store_true",
                     help="replace a non-empty destination")
    pat.add_argument("--agent", nargs="?", const="codex", default=None, metavar="NAME",
                     help="TEMPLATE-FIRST REWRITE: stage the journal's templates read-only + the "
                          "source package + a prompt that says 'copy the template, replace its "
                          "placeholders with the source content' and run one agent session "
                          "(default name: codex; `manual` stages the prompt only). Without "
                          "--agent the command does the deterministic code-side rebuild instead")
    pat.add_argument("--agent-cmd", default=None,
                     help="JSON argv for the agent command, e.g. '[\"codex\",\"exec\"]'")
    pat.add_argument("--timeout", type=int, default=None,
                     help="agent session timeout in seconds (default: the run's timeout)")
    pat.set_defaults(func=cmd_apply_template)
    return p


def main() -> None:
    parser = build_parser()
    # Usage output (`-h`/`--help` and an argparse error) is NOT a run log: it is
    # something an operator reads, pipes into documentation or diffs, so it stays
    # un-stamped. Everything a COMMAND prints afterwards is the run's own console
    # and keeps its datetime prefix (year-month-day hour-minute-second) so a long
    # run's log is readable.
    args = parser.parse_args()
    install_timestamped_streams()
    cmd = getattr(args, "cmd", "")
    # A path is a pipeline root only when it is an existing directory carrying
    # one of the root's OWN files. `Ctx.load` creates `runs/` and `reports/` on
    # success, and `start_run_log` creates `reports/` with parents=True, so any
    # code that opens/loads a path BEFORE this check manufactures a root out of a
    # typo: `redline`/`track` then wrote empty manifests and exited 0. Both the
    # foreign-driver guard (which calls `load`) and the run log are therefore
    # gated on this test; a command's own validation still sees the path as the
    # operator wrote it.
    _root_arg = getattr(args, "root", None)
    _log_root = Path(_root_arg) if _root_arg else None
    if _log_root is not None and (
            not _log_root.is_dir()
            or not ((_log_root / "pipeline_config.json").is_file()
                    or (_log_root / "state.json").is_file())):
        _log_root = None
    # A root freezes the pipeline script that produced it. Refuse EVERY mutator
    # driven by a different copy before even opening its run log; otherwise the
    # same stale driver that corrupted a root through `run` can still change it
    # through `retry`, `conform`, `prune`, or a `set-*` command.
    if cmd in FOREIGN_GUARD_COMMANDS and _log_root is not None:
        guard_ctx = Ctx(
            Path(args.root).resolve(),
            strict_venue=bool(getattr(args, "strict_venue", False)),
        )
        # Loading a root can print informational notes. Keep the guard silent
        # and JSON-safe; it speaks only when it refuses the command.
        with contextlib.redirect_stdout(io.StringIO()):
            guard_ctx.load(need_cfg=False)
        refuse_foreign_pipeline(guard_ctx, cmd)
    # The commands that drive or mutate a root keep their console in the root
    # (`reports/<cmd>-<stamp>.log`, and `state.json` -> `run_logs`): the attempt
    # history holds each attempt's diagnostics, this holds the INVOCATION --
    # retry/backoff decisions, judge advisories, repair decisions, panel news.
    # (`setup` starts its own log once the root exists -- see cmd_setup: writing
    # into a not-yet-created root would make it non-empty and fail its own check.)
    if getattr(args, "cmd", "") in LOGGING_COMMANDS \
            and getattr(args, "cmd", "") != "setup" and _log_root is not None:
        begin_run_log(args.cmd, _root_arg, sys.argv)
    # The digest cache is enabled only for a quiescent READ-ONLY audit (and only
    # when no other pipeline process holds the root lock); see the block comment
    # above sha256_file(). The emitted note warns when a live run forced it off.
    note = configure_hash_cache_for_command(getattr(args, "cmd", ""),
                                            getattr(args, "root", None))
    if note:
        print(f"[{args.cmd}] note: {note}")
    # `--skip-hash`: the verification passes are per INVOCATION (the global is
    # process-wide, so `run-decide` keeps it across both phases).
    skip_note = configure_hash_checks(bool(getattr(args, "skip_hash", False)))
    if skip_note:
        print(f"[{args.cmd}] WARNING: {skip_note}")
    args.func(args)
