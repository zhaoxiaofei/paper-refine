from __future__ import annotations

import argparse
import copy
import contextlib
import csv
import difflib
import fnmatch
import hashlib
import io
import itertools
import json
import math
import os
import posixpath
import queue
import random
import re
import shlex
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
from pathlib import Path

# 3.0.0 -- pool/integration release: every round is planned with M REWRITTEN
# candidates (w1..wM, staged first, before the review) and N
# REVIEWED-AND-THEN-REVISED candidates (a2..a{1+N}, one shared $paper-review pass
# feeding N $paper-revise sessions), and EVERY pool member is reworked once by an
# INTEGRATION run that takes it as the base and ALL the other pool members as
# donors (i1..iK) -- there are no pairwise "cross-pollination" arms any more.
# M and N are command-line parameters (`setup --rewrites`, `setup --revises`),
# each either a single integer or a per-round list; they default to [2, 1] and
# [1, 1]. Every prompt also documents the optional `docx` CLI (including
# `docx diff`), which the visual-tool probe includes; the cmd-line defaults are
# --rounds 3 and --jobs 255. state.json is version 3 (the arm set changed).
# Carried over from 2.1.0: the figure-caption rule is an opt-in SUGGESTION
# (default 0) that is never enforced, median ties are broken by the arithmetic
# mean of the same score list, MANUAL_STEPS.md is reported but not ranked on,
# the round's own base competes (so a round cannot move backwards), the
# pipeline's own hand-off placeholders and the difference-tracking auxiliaries
# ("*.tracking-<token>.<ext>" / "*.logging-<token>.<ext>") are
# neutralised everywhere they could be mistaken for manuscript defects, and
# copied-but-unchanged input files are exempted from structured-output
# validation by content instead of by path. (2.1.0 kept state.json at version 2.)
# 3.1.0: judge contract v2 (graded basis), panel de-duplication by
# (target, judge index), and the provenance-free digest tie-break. A round
# decided by an earlier version recomputes a champion only if its ranking key
# changed the outcome; `decide` reports that as a problem instead of silently
# re-deriving the stored chain.
# 3.2.0 -- Zotero reference tooling: `setup --zotero {off,read,edit,apply}`
# (default edit) and a `zot`-CLI block in every prompt. off keeps the old
# manual route; read adds read-only reference resolution; edit additionally lets
# the revision and integration stages add, remove or relink citations in their
# revised copy under the live-field validation rules; apply additionally lets
# those stages write ONE field of ONE existing library item, after a proposal
# row and an independent re-fetch (`--last-modified auto` makes a concurrent
# edit fail the write instead of being overwritten). Review, rewrite and judge
# sessions can never write, no mode creates or deletes items, and the library
# stays read-only unless the operator opted into apply.
# 3.3.0 -- the abstract/main-text length exemption is replaced by the journal's
# own limits relaxed by the operator's margins: abstract <= 150 words * 1.10
# (<= 165) and main text <= 3,000 words * 1.25 (<= 3,750) for a Nature
# Biotechnology Article, with words counted as runs of non-space characters
# (newline = space). The new sweep id is M19 (always active; M18 stays the
# opt-in caption sweep), an over-limit section is a formatting-tier item that
# the revision stages compress by removing redundancy only, and the
# orchestrator reports its own code-side counts for the source and the winner.
# 3.4.0 -- naming, judging and speed:
#   * the file rename is `paper_pipeline.py` (was paper_round_pipeline.py), with a
#     new `run-decide` command (run, then decide, in series);
#   * `decide` publishes <root>/final_clean_version/: the champion corpus with
#     no scratch/auxiliaries/reports, the generation counter in the filenames
#     incremented by one (int(name.split("-")[1]) + 1, guarded) and the
#     references repointed, ready as the next run's --source;
#   * revision packages carry ONE 7-character content-hash version token
#     (paper-revise/scripts/revision_token.py) instead of letter/digit
#     increments; the orchestrator records it and reports the winner's token;
#   * judge views rewrite their internal file references so an anonymized LaTeX
#     package still compiles, and sanitize OOXML/PDF metadata (core/app/custom
#     properties, tracked-change authors, zip timestamps, PDF /Info //ID /XMP);
#   * `decide`/`status` hash each unchanged byte once (parallel, content-cached,
#     enabled only when no pipeline process holds the lock), keeping the
#     decision certificate byte-identical while cutting the audit's runtime.
# 3.4.1 -- the 2026-09-23 root's three paperwork failures (no behaviour change
# for a run that never failed a stage):
#   * EVERY run kind the plan can produce is now postcheckable AND rebuildable
#     (REBUILD_HANDLERS/POSTCHECK_HANDLERS, checked before a round launches):
#     the audit stage had no rebuilder, so a single failed audit attempt could
#     not be retried at all and took its round's revise and integration runs
#     with it;
#   * the completion signal is looked for in the run's OWN output directory as
#     well as the sandbox root, and an unambiguous one (same stage, same run id)
#     is ADOPTED there instead of failing the attempt -- every prompt now also
#     states the root explicitly, and a stray signal that names another
#     run/stage is reported with its path;
#   * the decision-table detectors measure each row against its own header, so
#     a row re-emitted one cell short (verdict in the neighbouring column) is
#     reported as a SHIFTED row rather than as an undisposed one, and every
#     session can run `paper_pipeline.py selfcheck --sandbox . --stage <kind>`
#     before it writes the marker to get the postcheck's own verdict early.
#   * the same treatment for EVERY stage's own paperwork: a REQUIRED bookkeeping
#     deliverable written one directory up (a reviser's `revision_report.json`
#     in the sandbox root instead of `revised/`) is adopted into place exactly
#     like a misplaced marker; `selfcheck` now also previews the review
#     contract, the revision ledger's finding coverage (against the AUDITED
#     list the sandbox carries), the integration ledger's `artifact` rows, the
#     rewrite arm's declared level, the L1-L11 language pass, the visual record
#     and a judge sheet's ledger arithmetic and check-coverage map; an audit
#     sandbox whose process died after writing its sheet is re-verified instead
#     of re-run, and `audit/audit.json` joins the structured-output parse gate.
# 3.4.2 -- the judge panel's own contract no longer contradicts itself (the
# 2026-09-23 round-1 panel burned 3h20m and still finished incomplete):
#   * `WRITING_RUBRIC` told every judge "a row names its rubric item (Q7)" while
#     the validator REJECTED any ledger row whose `check` was not a frozen id:
#     8 of the 24 sessions failed on nothing but `check 'Q11' is not a frozen
#     check id`, three of them twice and one on all three attempts.
#     `_norm_check_id()` now maps the rubric's Q1-Q12 items onto J3 -- the check
#     that OWNS the rubric, exactly as the sweep's FMT-* ids map onto M20 -- and
#     the prompt says which cell carries the rubric item and which the frozen id;
#   * a ledger row's `check` cell is DESCRIPTIVE (the arithmetic reads
#     tier/severity/evidence only), so an id nobody recognizes is a WARNING that
#     names what to cite, never a failed 20-40 minute session; the coverage map
#     ("one disposition per frozen check id") stays the hard contract;
#   * judges get the same pre-marker pre-flight as every other stage, in wording
#     that leaks no provenance (`judge_selfcheck_block`), so a sheet whose
#     integer contradicts its own ledger is fixed in-session instead of costing
#     a re-judge.
# 3.4.3 -- the registry can no longer refuse the pipeline's own state:
#   * `load()` read state.json through `read_json`, which applies the 64 MiB
#     AGENT-OUTPUT cap: the 2026-09-24 root's VALID 78 MiB registry (both rounds
#     done, the champion pinned and published) was refused as "corrupt or has no
#     run registry" and every command died. The pipeline's own state is read with
#     its OWN cap (`load_state_file`, MAX_STATE_BYTES) and its own message, so
#     "over the limit" is never reported as "corrupt";
#   * `compact_state()` drops the redundant BULK before every save: the full
#     evidence packs stay where they are written (reports/judge_evidence_<id>.json,
#     runs/<id>/CODE_SCANS_after.json, runs/<id>/FORMAT_FIX.json -- 56 MB of the
#     offending registry was copies of those) while the record keeps the counts,
#     the corpus digest and the path; the registry of that root becomes ~6 MB on
#     its next save;
#   * every save keeps the previous registry as `state.json.prev` (a hard link:
#     no copy, no extra I/O), which is the backup the error message has always
#     told operators to restore from, and a registry over the state cap names the
#     way out (`prune --yes` / a fresh root) instead of the wrong diagnosis.
# 3.5.0 -- the rewrite-parity checks (M25-M29 + J5) on the review -> audit ->
# revise path. The 2026-09-27 root's panel credited the from-scratch rewrites
# (w1/w2) with consistency/completeness rows the frozen review never filed
# (US/UK spelling conventions, SI-legend-vs-artwork term parity, claim->evidence
# pointer coverage, sibling definition order, scope-level organization), so the
# revision arm had nothing to fix. The review now enumerates those classes
# (M25 artwork/text parity, M26 house-style conventions via the new
# enumerate_conventions.py, M27 claim->evidence coverage, M28 sibling-definition
# symmetry, M29 caption-promise parity) and the J5 architecture pass writes one
# scope row per document (review/ARCHITECTURE.md; J5 findings carry a `scope`).
# The auditor attacks the dispositions that used to close them; the reviser
# resolves M25-M29 by aligning the editable surface corpus-wide and J5 by E11
# scoped restructuring (content frozen, one RESTRUCTURE_<id>.md per finding).
# The judge panel's frozen coverage map stays M1-M24 + J1-J4 on purpose.
# 3.5.1 -- BOTH DIRECTIONS of every two-sided check. The checks were one-sided:
# J3 filed overclaims (unsupported first/novel claims, causal language, a
# generalization past the design) while an underclaim -- a supported result
# hedged into "may"/"could"/"suggests"/"a trend"/"preliminary" -- was never a
# finding, and the same asymmetry ran through the other paired classes
# (M5 items missing but not unneeded; M21/M22 claims in the letter and the
# availability statement read only in the "too strong" direction; M27 claim
# pointers but not the printed schema M29 never describes; a lost document but
# not an added one; length compression allowed to strip MEANING-BEARING
# hedging, which converts an accurate claim into an overclaim). The fix is
# symmetric, mechanical where it can be:
#   * a new code-side ledger (paper_docx_format.claim_strength_rows) enumerates
#     BOTH directions per claim-bearing paragraph, seeded as
#     work/CLAIM_STRENGTH.md and artifacts/CLAIM_STRENGTH.md with a disposition
#     per row (a decision table under the strict-artifacts policy);
#   * the shared decision rules (D1), the defect-class vocabulary (category 0
#     and category 2), the writing rubric (Q1) and the language pass (L1) name
#     the underclaim as a defect of the same class as the overclaim;
#   * the judge prompt states that a weakened supported claim is `introduced`
#     correctness, never neutral caution;
#   * M5, M21, M22, M27, M29 and the length rule (M18/M19) carry their own
#     reverse direction; `document_set_check` reports added documents as well
#     as lost ones; the revise prompt authorises a calibrated claim edit ONLY
#     where a calibration finding names it (in either direction).
# 3.6.0 -- M30, the SOURCE-HIERARCHY reconciliation. The hierarchy (github
# code > data in raw_data/ > main figures > ... > supplementary text) was only
# a RESOLUTION rule: it decided which side wins once two sources already
# disagreed, and nothing enumerated the DETECTION side. A written number,
# Methods parameter, sample set or label that the shipped code or raw data
# contradicted was found only if a human happened to compare the two. The
# review -> audit -> revise path now carries M30:
#   * the review must enumerate the written-vs-producer pairs (the code-side
#     seed, paper_docx_format.hierarchy_seed_rows + code_literal_rows, pairs
#     every written number the shipped tables do not PROVE with its candidate
#     producer column and the check the code could make -- including a
#     cohort-size sentence against a table's own row count -- and lists the
#     module-level code/config literals), add the producers the seed cannot see
#     (figure <-> generating code, protocol step <-> implementation), file one
#     `M30` finding per incompatible instance with BOTH sides and the
#     authoritative one named, and record `unable -- the producer is not in the
#     corpus` instead of a silent clean;
#   * the auditor attacks the old closures ("the code is out of scope",
#     "raw_data/ is read-only"); the revision prompt resolves an M30 finding by
#     rule E12 (align the written side; rule C owns a code fix; raw_data/ is
#     read-only and stays manual); the rewrite/integrate prompts surface or
#     resolve the conflict under the hierarchy but never edit the code;
#   * the judge's frozen coverage map is unchanged; the comparison prompt states
#     explicitly that a claim the package's own code/data refutes is scoreable
#     correctness/completeness, never cosmetic.
# 3.7.0 -- the PACKAGE-INTEGRITY round: what a certified package still shipped.
# Five classes of defect survived 3.6.0 because nothing enumerated them. Each
# becomes either a code-side row (seeded for the session to dispose) or a
# package gate:
#   * M19 now reports the BAND between the venue's own number and the
#     pipeline's relaxation: a 164-word abstract passed a 150-word venue
#     silently because only the relaxed (165) cap was compared. The band rows
#     name the margin used and every M19 mandate says the venue's base number is
#     the one the submission is measured against;
#   * the reference-entry SHAPE (FMT-R1..R5): a malformed journal/volume field,
#     an entry with no venue at all, a repository/software citation with no
#     version or DOI, a bioRxiv-style identifier carrying a foreign DOI prefix,
#     and (profile-gated by `references.flag_preprints`) a preprint or
#     trial-in-progress reference;
#   * display-item ORDER (FMT-O1, profile-gated by `numbering: "citation"`),
#     front-matter GLUE (FMT-X2: an e-mail or label fused to its neighbour) and
#     another publisher's LEFTOVER boilerplate (FMT-L1, from the profile's
#     `leftover_phrases` list);
#   * AVAILABILITY finality (FMT-AV1: "not yet deposited" / "available from the
#     lead contact" / "on request") and one-revision pinning (FMT-AV2: the same
#     repository committed twice across the statements);
#   * the published PACKAGE: the pipeline's own by-products are stripped by name
#     with the version token included (`is_bookkeeping_name`), everything that
#     remains is scanned for internal working material (PKG-1: internal review
#     session URLs, the re-authoring ledger, stage notes) and every shipped PDF
#     for a form that renders BLANK (FMT-PDF1..3: an XFA/LiveCycle shell, an
#     unfilled form dataset, an export with no text). The readme, the decision
#     report and the decide output list them as author actions.
#   * M30 grew its NON-NUMERIC half: a written "could not be run / produced no
#     output" claim while a shipped table carries that method's rows
#     (`negative_claim_rows`, seed id M30-NC) is now a row.
#   * the review -> audit -> revise path carries the EVIDENCE-INTEGRITY sweeps
#     M31-M36 (artwork-versus-legend consistency, a headline statistic against
#     the correction the paper itself states, availability-locator finality,
#     figure-source-data coverage, disclosure/provenance completeness, and the
#     Zotero live-field refresh parity: a stale citation marker or bibliography
#     order that a Word/Zotero refresh rewrites -- FMT-Z1..Z5 -- with the
#     `zotero-check` CLI and a version-to-version parity gate), each with its own
#     coverage row and artifact; the judge's frozen map is unchanged.
# 3.9.0 -- CHAMPION SELECTION WITHOUT A PANEL (`--champion-select`). `judge`
#   (default) keeps the relative-judgment panel and deterministic ranking;
#   `revise` promotes the round's single review-audit-revised candidate (a2)
#   with no judge panel and no integration arm; `integrate` promotes that
#   candidate's integration arm i<M+2> with no judge panel. The no-judge modes
#   require N=1, are recorded per round, and their decision is PROVISIONAL /
#   NOT JUDGED (the pin/winner/final_clean chain still works). `setup` enables
#   the required integration arm when --integrators was omitted; an explicit
#   mask that omits it is refused. The pipeline and formatter are now thin
#   loaders over ordered `paper_pipeline_parts/` / `paper_docx_format_parts/`
#   (each file under 10,000 lines), and the backward-compatibility aliases
#   (legacy input-area spellings, the ATC shorthand flags, `--non-strict-
#   artifacts`, the boolean artifact-policy keys, the `none` revision-mode
#   alias and unsalted judge tokens) are removed. Facts are not a removal
#   surface: a wrong value is corrected, a misplaced/unused/structural fact is
#   relocated or connected, acronym definitions are kept, PKG-2 holds a
#   numeric fact instead of deleting its sentence, and M4 enumerates descending
#   unit-bearing ranges (not only decimal CIs).
# 3.8.0 -- THE PROBE REVIEW (`setup --probe-review`, default on; `--no-probe-review`
#   or `set-probe-review off` is the off switch). One extra INDEPENDENT session
#   per full-scope round, launched IN PARALLEL with the checklist review and
#   given NOTHING but the corpus (the submission documents AND the evidence
#   areas, raw_data/ and code/ included) -- no review, no finding list, no
#   sweeps. It is GENERIC by design: any defect class may be filed, in the
#   standard six-category/four-rung vocabulary, and wherever a defect can be
#   shown by a computation it declares a small re-runnable verifier:
#     * the orchestrator RE-RUNS every declared verifier at postcheck time and
#       compares its last stdout line with the finding's `computed` value -- a
#       computation that does not reproduce FAILS the attempt (a computation
#       the probe cannot reproduce is a correctness blocker, not a finding);
#       findings without a verifier are evidence rows like any other finding;
#     * its findings become X-9xx rows of the same standing as the discovery
#       round's X-* findings: merged into every downstream copy of
#       `review/round2/findings_extra.json` (the source review sandbox is never
#       mutated), so the reviser must resolve them, the auditor may only drop
#       them with evidence, and the integration ledger must reconcile them
#       (`frozen_discovery/` carries the merged list, probe findings included);
#       the ARCHIVED discovery list is merged too, so a pruned root re-seeds the
#       same ids and the next round's prior_round/ reconciliation covers every
#       probe finding;
#     * the JUDGE panel stays completely blind and is NEVER handed the list: it
#       re-derives its own generic discovery pass, and an X-class difference it
#       proves is filed as a normal resolved/introduced row.
#   The stage exists because one review pass is a sample of the defect space:
#   a superlative claim whose sign the paper's own table contradicted, a stale
#   sidecar string and degenerate intervals in a shipped source table all
#   survived every layer in real runs -- and the discovery round's own probes
#   had read the very table and reported "no anomalies".
VERSION = "3.9.0"
STATE_VERSION = 3
# The driver executes these siblings; a root freezes all of them. Recording only
# the driver let a root run new code with an old formatter (the round-2 case).
# The Qwen adapter is a fourth module because the `qwen` agent preset executes it
# from the same directory; a root without it could not run that preset.
PIPELINE_MODULE_FILES = ("paper_pipeline.py", "paper_docx_format.py",
                         "paper_redlines_adapter.py", "paper_qwen_agent.py",
                         # The render/track shims are read beside the running
                         # driver (`visual_renderer_choices`), so a root that
                         # lacks them silently loses the highest-fidelity
                         # renderer. They are frozen and manifest-recorded like
                         # the modules.
                         "docx2pdf.sh", "docxcompare.sh")
# The two loaders above are thin; their implementation lives in ordered parts
# directories. A root/stage is self-contained only when it carries both, and the
# module manifest records each directory as ONE digest (name + sha256 of every
# file), so a partial or stale bundle is visible to `status`/`sync-code`.
PIPELINE_ASSET_DIRS = ("paper_pipeline_parts", "paper_docx_format_parts")
# Skills are read from beside the running driver too (adopt-sweep's default
# sweeps.md and the review/revise prompt assets), so a root freezes them; a
# trimmed checkout without the skills pack still creates a root (the copy is
# recorded as None rather than aborting setup).
PIPELINE_SKILL_ASSET_DIRS = ("paper-skills",)

# The Zotero tooling policy carried in pipeline_config.json (`setup --zotero`):
#   off   -- never run the `zot` CLI; live fields stay on the skills' manual route
#   read  -- read-only reference resolution/verification, no field edits
#   edit  -- + add/remove/relink citations in the revision/integration copies
#   apply -- + ONE guarded field update of ONE existing library item per change
# DEFAULT_ZOTERO_MODE is deliberately `edit`: the manuscript copies may be
# revised (the point of the pipeline), while the operator's remote library stays
# read-only unless `apply` was chosen explicitly at setup.
ZOTERO_MODES = ("off", "read", "edit", "apply")
DEFAULT_ZOTERO_MODE = "edit"

# `setup --integrators`: a per-round 32-BIT bitmask that selects which agents of
# the round run an INTEGRATION session. Bit (k-1) belongs to the k-th member of
# the round's pool [a1, w1..wM, a2..a{1+N}]: with the bit set, that member's
# integration arm i<k> runs ("this agent integrates what the other members do
# better"); with the bit clear, the arm is not planned at all, so the round pays
# no session for it and, because the arm never exists, it cannot enter the field
# the judges score or the ranking that crowns the round's champion. The default
# 0xFFFFFFFF means "every applicable agent runs its integration" (bits beyond
# the pool size are ignored, so the default keeps selecting the whole pool
# whatever M and N are). Bit 0x0 is legal and means "no integration at all".
INTEGRATOR_ALL = 0xFFFFFFFF
INTEGRATOR_BITS = 32

# The venue/journal default (see the VENUES AND JOURNALS section). `setup`
# records both in pipeline_config.json; a root created before this feature
# carries neither key and keeps behaving exactly as it did, because the default
# venue is the requirement set this pipeline was originally written for.
DEFAULT_VENUE = "nature-biotechnology"
GENERIC_VENUE = "generic"

DEFAULTS = {
    "root": "./paper_rounds",
    "rounds": 3,            # fixed-length pipeline; the round-R champion wins
    "judges": [2],          # independent judge sessions per version, per round list
    "jobs": 255,            # concurrent agent sessions
    "venue": DEFAULT_VENUE, # the submission-requirement set the stages enforce
    "journal": "",          # the target journal (free text; "" = profile default)
    "zotero": DEFAULT_ZOTERO_MODE,   # Zotero tooling policy: off|read|edit|apply
    # The default three-round SCHEDULE (2026-10-06): round 1 stages the two
    # from-scratch rewrites; rounds 2 and 3 have none (M = 0). Rounds 1-2 run the
    # FULL review and every pool member's integration arm; round 3 is the final
    # REVIEW-AUDIT-REVISE round: full review scope, no rewrite and NO integration
    # arm (integrators mask 0), so the panel judges the incumbents plus the
    # revised candidate without a submission-version merge pass.
    "rewrites": [2, 0, 0],  # M per round: rewritten candidates (list or one int)
    "revises": [1, 1, 1],   # N per round: reviewed-and-then-revised candidates
    "review_scope": ["full", "full", "full"],  # per-round review scope
    # Bitmask per round: which pool members integrate. Rounds 1-2 integrate the
    # whole pool; round 3 stages no integration run at all.
    "integrators": [INTEGRATOR_ALL, INTEGRATOR_ALL, 0],
    "timeout": 4 * 3600,    # per-run timeout (manual mode: none)
    "retries": 2,           # automatic retries per failed run (2 = three attempts)
    "retry_backoff": 30,    # base seconds for the exponential retry backoff (0 = no wait)
    "retry_backoff_max": 600,   # cap on a single backoff wait
    "agent": "codex",
    "poll": 10,             # manual-mode completion poll interval
}

# The BUILT-IN round schedule `--round-indices` selects from: one entry per
# round of the default plan, carrying that round's rewrites / revises /
# review scope / integration mask. The pipeline's internal rounds stay 1..K;
# `--round-indices 2 3` makes pipeline round 1 adopt schedule entry 2 and
# pipeline round 2 adopt entry 3 (so a run can start at a later revision round).
ROUND_SCHEDULE_LEN = max(len(DEFAULTS[k]) for k in
                         ("rewrites", "revises", "review_scope", "integrators"))


def _schedule_entry(i: int) -> dict:
    """Schedule entry `i` (1-based); a short default list extends by its last value."""
    def val(key):
        seq = DEFAULTS[key]
        return seq[min(i - 1, len(seq) - 1)]
    return {"rewrites": int(val("rewrites")), "revises": int(val("revises")),
            "review_scope": str(val("review_scope")), "integrators": int(val("integrators"))}


ROUND_SCHEDULE = tuple(_schedule_entry(i) for i in range(1, ROUND_SCHEDULE_LEN + 1))
