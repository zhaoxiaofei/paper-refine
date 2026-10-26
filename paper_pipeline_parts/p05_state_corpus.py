# -*- coding: utf-8 -*-
# Part 05/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# RUN-ID / VERSION-ID HELPERS
# =====================================================================

def rid_a1(r: int) -> str:
    return f"r{r}_a1"


def rid_rewrite(r: int, k: int) -> str:
    return f"r{r}_{rewrite_vid(k)}"


def rid_review(r: int) -> str:
    """The round's SINGLE review run (its findings feed every revise session)."""
    return f"r{r}_review"


def rid_review_b(r: int) -> str:
    """The SECOND review run when `--review-split` is on (part B)."""
    return f"r{r}_review_b"


def rid_feedback(r: int) -> str:
    """The round's JOURNAL-FEEDBACK enumeration run (modes 1-2: transfer/resubmit).

    It turns the editors'/reviewers' decision letter into the concern ledger the
    round's review reconciles and the revise/rewrite sessions answer.
    """
    return f"r{r}_feedback"


def rid_concerns(r: int) -> str:
    """The concern-scoped reconciliation run (modes 3-4: major/minor).

    It REPLACES the round's review: it enumerates the concerns and writes the
    finding list the single revision session consumes, so the general
    review-audit-revise workflow never runs in a major/minor revision.
    """
    return f"r{r}_concerns"


def rid_response(r: int) -> str:
    """The response-to-reviewers run (modes 2-4; option 1 writes no letter)."""
    return f"r{r}_response"


def rid_audit(r: int) -> str:
    """The round's AUDITOR run (review -> audit -> revise), when enabled.

    The auditor is an independent session that never edits the corpus: it
    disposes the frozen review's findings (confirm / drop-with-evidence), turns
    the reviewer's boilerplate "OK" rows into findings when they are real
    defects, and hands the AUDITED list to the revisers. It exists because the
    reviewer's dispositions were the pipeline's largest source of shipped
    leftovers: a row the reviewer closed as "no journal rule" never reached any
    revision arm.
    """
    return f"r{r}_audit"


def rid_probe(r: int) -> str:
    """The round's PROBE REVIEW run (an INDEPENDENT discovery session).

    One extra session per round, launched IN PARALLEL with the review and
    feeding the same frozen finding list (its findings carry the reserved
    `X-9xx` ids). It is GENERIC: it never runs the checklist and is not
    restricted to any defect class -- it hunts whatever it can find in the
    corpus with a cold context, and wherever a defect can be shown by a
    computation it writes a small re-runnable script and declares the value it
    prints. The orchestrator re-runs every declared verifier at postcheck time:
    a computation that does not reproduce is a correctness blocker (the attempt
    fails); findings without a verifier are evidence rows like any other
    finding.
    """
    return f"r{r}_probe"


REVIEW_SPLIT_MODES = ("off", "phases", "aspects")
# The review's per-round SCOPE. "full" runs the whole frozen sweep set; the
# "formatting-writing" scope is the final polish pass: only the surface checks
# (acronyms, display items, hygiene, cross-references, terminology, naming,
# reference/SI/affiliation formatting, anomaly tokens, lengths, OOXML formatting,
# term families, house style) and the prose/architecture passes (J3/J5) run --
# every content/scientific check is recorded as out of scope for the round.
REVIEW_SCOPE_VALUES = ("full", "formatting-writing")
FORMATTING_WRITING_CHECKS = ("M1", "M3", "M6", "M7", "M8", "M9", "M10", "M11", "M12", "M17",
                             "M18", "M19", "M20", "M24", "M26", "J3", "J5")

REVIEW_SPLIT_SCOPES = {
    "phases": ("A: the MECHANICAL sweeps M1-M17 plus the pipeline-mandated M18/M19/M20 and the "
               "adopted M21-M36 (rewrite-parity, the source-hierarchy reconciliation, the "
               "evidence-integrity sweeps and the Zotero live-field parity included; "
               "enumerate, artifact, audit)",
               "B: the JUDGMENT passes J1-J5 and the discovery round D0-D5"),
    "aspects": ("A: the CONTENT/scientific checks -- M1-M8, M13-M16 and J1-J3",
                "B: the PACKAGING/compliance checks -- M9-M12, M17-M20, M21-M36, J4, J5 and the "
                "discovery round D0-D5"),
}


def review_split_of(ctx: Ctx) -> str:
    """The configured review split ('off' | 'phases' | 'aspects')."""
    raw = str((getattr(ctx, "cfg", None) or {}).get("review_split") or "off").strip().lower()
    return raw if raw in REVIEW_SPLIT_MODES else "off"


# --- the PROBE REVIEW stage (`setup --probe-review`, default on) -------------
# A second, INDEPENDENT discovery channel -- generic by design. It is a
# cold-context session that is given the corpus (the submission documents AND
# the evidence areas, `raw_data/` and `code/` included) and NOTHING else: never
# the review, never a finding list, never a sweep artifact. It exists because
# one review pass is a sample of the defect space: a whole class of defects has
# survived every layer in real runs (a comparative claim the paper's own table
# contradicted in sign; a stale sidecar string; degenerate intervals shipped in
# a source table), and the discovery round's own probes had read the very table
# and reported "no anomalies". Its value is a second, unanchored read -- plus
# the pipeline's one hard lever: wherever a defect can be SHOWN BY A
# COMPUTATION, the finding declares a small re-runnable script and the value it
# prints, and the orchestrator re-runs it. A computation that does not
# reproduce is a hard failure; the findings (any class, category 0-5,
# Fatal..Minor) become `X-9xx` rows of the same standing as the discovery
# round's `X-*` findings: the reviser must resolve them, the auditor may only
# drop them with evidence, the integrator must reconcile them, and the JUDGE
# panel stays blind to the list (it re-derives its own generic pass).
#
# The mode is recorded at setup (`probe_review`: "on"/"off"). A root that
# carries no such key -- everything created before this feature -- plans no
# probe run; `set-probe-review on` opts it in. `--only` can, of course, select
# or skip the session for one invocation, but the recorded policy is the off
# switch.
PROBE_REVIEW_MODES = ("on", "off")
PROBE_REVIEW_DEFAULT = "on"
PROBE_DIR = "probe_review"
PROBE_FINDINGS_REL = f"{PROBE_DIR}/findings_probe.json"
PROBE_FINDINGS_MD_REL = f"{PROBE_DIR}/findings_probe.md"
PROBE_COVERAGE_REL = f"{PROBE_DIR}/coverage.md"
PROBE_REPRO_REL = f"{PROBE_DIR}/REPRODUCTION.md"
PROBE_SURFACES_REL = f"{PROBE_DIR}/CLAIM_SURFACES.md"
PROBE_PRODUCERS_REL = f"{PROBE_DIR}/PRODUCERS.md"
# The third seeded CANDIDATE list (2026-10-16): what THIS submission promises,
# and whether each promise resolves. The two audits of the 2026-10-15b packages
# both found "the supplement the documents cite is not in the declared submitted
# set" and "the main text requires sections the manuscript does not carry" --
# structural-completeness defects, which a surface enumeration does not reach
# because nothing on the page is WRONG. The ledger turns that direction into a
# disposal task: every obligation is a row, and a row with no disposition is a
# hole in `coverage.md`.
PROBE_OBLIGATIONS_REL = f"{PROBE_DIR}/OBLIGATIONS.md"
PROBE_SCRIPT_PREFIX = f"{PROBE_DIR}/scripts/"
# The reserved finding-id block: probe findings are X-9xx, so a collision with the
# discovery round's own sequential X-0xx ids is impossible by construction (and
# the merge still remaps defensively if a session ignores the block).
PROBE_ID_RE = re.compile(r"^X-9\d{2}$")
PROBE_FINDING_ID_BASE = 900
# Every DECLARED verifier is re-run at postcheck time. The timeout is per
# script; the scripts are the session's own, offline and deterministic by
# contract.
PROBE_REPRO_TIMEOUT = 120


def probe_review_of(ctx) -> str:
    """Is the round's probe-review stage part of the plan?

    The recorded policy wins; a root without the key (created before the
    feature) plans no probe session. An unknown value falls back to "off"
    rather than to the more expensive mode.
    """
    raw = str((getattr(ctx, "cfg", None) or {}).get("probe_review") or "").strip().lower()
    return raw if raw in PROBE_REVIEW_MODES else "off"


def rid_revise(r: int, vid: str) -> str:
    return f"r{r}_{vid}_revise"


def rid_integrate(r: int, k: int) -> str:
    return f"r{r}_{integrate_vid(k)}"


def rid_judge(r: int, vid: str, j: int) -> str:
    """A judge run id that carries NO round, arm or ordering information.

    The judge sees this id and its sandbox path (its cwd), so both must be
    opaque: `vid` is already the salted per-session token, and the round is
    deliberately absent. The round lives on the run RECORD (rec["round"]), which
    the judge never sees. `r` stays in the signature because callers pass it and
    the token's derivation is round-scoped.
    """
    return f"judge_{vid}_j{j}"


def pin_id_for(r: int, champ_id: str) -> str:
    return f"r{r}_{champ_id}"


def rid_for_fresh(r: int, vid: str) -> str:
    """The run that produces round-local version `vid` ("a1"/"w*"/"a>=2"/"i*")."""
    if vid == A1_ID:
        return rid_a1(r)
    m = FRESH_VID_RE.match(str(vid))
    if not m:
        raise KeyError(f"{vid!r} is not a round-local version id")
    if m.group(1):
        return rid_rewrite(r, m.group(1))
    if m.group(2):
        return rid_revise(r, vid)
    return rid_integrate(r, m.group(3))


class DepsNotMet(RuntimeError):
    """A sandbox cannot be (re)materialized because an upstream run is not done."""


def upstream_deps(rec: dict, ctx=None) -> list:
    """Run ids that must be 'done' before this sandbox can be (re)materialized.

    `ctx` is optional only because the dependency split is also exercised as a
    pure function in the tests; the retry/rebuild path always passes it, and
    the journal-modes branch needs it to see the configured revision mode.
    """
    kind, r = rec.get("kind"), int(rec.get("round") or 0)
    if kind == "rewrite":
        # In a real submission-attempt mode the materializer also copies the
        # concern ledger (`_journal_concern_source` -> `_require_done`), so the
        # feedback run is a dependency even though the base is the only
        # corpus input. Omitting it let `retry` reach that RuntimeError as an
        # unhandled traceback instead of deferring the run as stale.
        deps = [rid_a1(r)]
        if ctx is not None and journal_mode_of(ctx) in (JOURNAL_MODE_TRANSFER,
                                                        JOURNAL_MODE_RESUBMIT):
            deps.append(rid_feedback(r))
        return deps
    if kind == "review":
        deps = [rid_a1(r)]
        if rec.get("id") == rid_review_b(r):
            # A split part B consumes part A's review/ (merge_review_parts
            # freezes A's findings into B's review/findings.json), so an A
            # retry must defer B instead of rebuilding it from stale output.
            deps.append(rid_review(r))
        # `materialize_review` now stages the concern ledger for EVERY feedback
        # mode that is not scoped -- transfer/resubmit AND `llm` -- because the
        # llm review reconciles that ledger too. List it here as well, or a
        # retry with a pending feedback run bypasses the unmet-deps gate and
        # dies inside the materializer instead of deferring cleanly.
        if ctx is not None and journal_has_feedback(ctx) and not journal_is_scoped(ctx):
            deps.append(rid_feedback(r))
        return deps
    if kind == "probe":
        # The probe review is materialized from the round base, like every other
        # base-consuming kind. Without this branch `upstream_deps` returned []
        # for a probe, `unmet_deps` was empty, and a `retry`/`--only` on a probe
        # whose base was still pending bypassed the DepsNotMet defer path and
        # died inside materialize_probe's RuntimeError instead.
        return [rid_a1(r)]
    if kind == "audit":
        return [rec.get("upstream_run_id") or rid_review(r)]
    if kind == "revise":
        # With the auditor enabled the reviser consumes the AUDITED list, so the
        # audit run (not the bare review) is the dependency that must be done.
        # A scoped (major/minor) revision consumes the CONCERNS run instead of a
        # general review; the materializer records which run that is, so the
        # retry/rebuild path never blocks on a run this root does not have.
        deps = [rid_a1(r), rec.get("upstream_run_id") or rid_review(r)]
        # `register()` initializes inputs_manifest to None; `.get(k, {})` does
        # not cover an existing None, and the AttributeError used to break
        # retry/rebuild for a registered-but-unmaterialized revise run.
        if (rec.get("inputs_manifest") or {}).get("audit") is not None:
            deps.append(rid_audit(r))
        return deps
    if kind in ("feedback", "concerns"):
        return [rid_a1(r)]
    if kind == "response":
        # The response letter consumes BOTH the concern ledger and the final
        # package: the ledger run is upstream_run_id, the scoped revision run is
        # package_run_id (a pin needs no dependency).
        deps = []
        if rec.get("upstream_run_id"):
            deps.append(rec["upstream_run_id"])
        if rec.get("package_run_id"):
            deps.append(rec["package_run_id"])
        return deps
    if kind == "integrate":
        # every pool member is a donor, so EVERY pool run must be done first
        pool = list(rec.get("pool_ids") or [])
        if not pool and rec.get("self_id"):
            pool = [rec["self_id"]]
        return [rid_for_fresh(r, v) for v in pool if is_fresh_vid(v)]
    if kind == "judge":
        ids = [rec.get("target_id")] + list(rec.get("field_ids") or [])
        return [rid_for_fresh(r, v) for v in ids if is_fresh_vid(v)]
    return []


def unmet_deps(ctx: Ctx, rec: dict) -> list:
    out = []
    for rid in upstream_deps(rec, ctx):
        r = ctx.run(rid)
        if r is None or r.get("status") != "done":
            out.append(f"{rid} ({(r or {}).get('status', 'missing')})")
    return out


def find_pin(ctx, pid: str):
    for pin in ctx.state.get("pinned") or []:
        if pin.get("id") == pid:
            return pin
    return None


def pinned_docs_dir(ctx, pin: dict) -> Path:
    return ctx.pins_dir / pin["id"] / "documents"


def winner_dir_of(ctx: Ctx, r: int) -> Path:
    """The round's human-facing winner directory, directly under --root."""
    return ctx.root / WINNER_DIR_FMT.format(r=int(r))


def superseded_dir_of(ctx: Ctx) -> Path:
    """Displaced copies are archived here instead of being deleted (nothing the
    pipeline produced is ever destroyed by a retry or an invalidation)."""
    return ctx.root / SUPERSEDED_DIRNAME


# =====================================================================
# CONTEXT / STATE
# =====================================================================

# --- the registry (state.json): read it with its OWN limits ----------------
# `read_json` applies the AGENT-OUTPUT cap (MAX_JSON_BYTES), which exists so a
# runaway session cannot OOM the machine with a 2 GiB scores.json. Applying that
# cap to `state.json` turned a VALID 78 MiB registry into "state file is corrupt
# or has no run registry" and refused EVERY command on the 2026-09-24 root after
# a 2.5-hour run (both rounds had finished, the champion was pinned and
# published, and only the final decision was left). The file was valid JSON and
# 56 MiB of it was redundant copies of evidence packs that already live on disk:
#   * runs.<judge>.judge_evidence  -> reports/judge_evidence_<run>.json
#   * runs.<id>.evidence_after     -> runs/<id>/CODE_SCANS_after.json
#   * runs.<id>.format_fix         -> runs/<id>/FORMAT_FIX.json
# `judge_evidence` alone was 41.6 MiB across 45 judge sessions, 33 MiB of that
# the M4 number ledger of the judge's blinded target, replicated once per
# session. Three layers keep the registry small and its failures diagnosable:
#   1. the pipeline's own state is read with its own cap (MAX_STATE_BYTES) and
#      its own message, so "too big" is never reported as "corrupt";
#   2. `compact_state()` replaces that redundant bulk with the counts, the
#      digest and the path of the full file before every save;
#   3. every save keeps the previous registry as `state.json.prev` (a hard link,
#      so it costs no copy), which is the "backup" the error message has always
#      told operators to restore from.
MAX_STATE_BYTES = 256 * 1024 * 1024
# Above this the registry is reported (console + run log) with its biggest
# run-record fields, so a new bulk field cannot grow unnoticed.
STATE_SOFT_BYTES = 16 * 1024 * 1024
STATE_PREV_SUFFIX = ".prev"


def state_prev_path(path: Path) -> Path:
    """The rolling backup of a state file (same directory, same volume)."""
    return path.with_name(path.name + STATE_PREV_SUFFIX)


def load_state_file(path: Path) -> tuple:
    """(state, problem) for the pipeline's OWN registry (problem == "" when fine).

    Never uses the agent-output cap: `state.json` is written by this program.
    The problem string is what the caller prints, so "over the limit", "not
    valid JSON" and "not the expected shape" stay distinguishable.
    """
    try:
        size = path.stat().st_size
    except OSError as e:                                          # noqa: BLE001
        return None, f"could not be read ({type(e).__name__}: {e})"
    if size > MAX_STATE_BYTES:
        def _mib(n):
            return (f"{n / (1024 * 1024):.1f} MiB" if n >= 1024 * 1024
                    else f"{n / 1024:.1f} KiB")
        return None, (f"is {_mib(size)}, over this pipeline's {_mib(MAX_STATE_BYTES)} registry "
                      f"limit -- prune the rounds (`prune --yes`) or start a fresh root")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:                                          # noqa: BLE001
        return None, f"could not be read ({type(e).__name__}: {e})"
    try:
        return json.loads(text), ""
    except ValueError as e:                                       # noqa: BLE001
        return None, f"is not valid JSON ({e})"


def _evidence_counts(ev: dict) -> dict:
    """The small numeric face of one code-side evidence pack."""
    def n(*path):
        cur = ev
        for key in path:
            if not isinstance(cur, dict):
                return 0
            cur = cur.get(key)
        if isinstance(cur, (list, dict)):
            return len(cur)
        return cur if isinstance(cur, int) else 0
    return {"numbers": n("numbers", "rows"), "format_rows": n("format", "rows"),
            "high_format_rows": n("format", "high"), "captions": n("captions", "captions"),
            "lengths": n("lengths", "rows"), "terms": n("terms", "rows"),
            "outline": n("outline", "rows"), "placeholders": n("placeholders", "count")}


def _evidence_summary(ev: dict, path_rel: str) -> dict:
    return {"compacted": True, "label": ev.get("label"),
            "generated_at": ev.get("generated_at"),
            "corpus_identity": ev.get("corpus_identity"),
            "counts": _evidence_counts(ev), "full": path_rel}


def _format_fix_summary(rep: dict, path_rel: str) -> dict:
    out = {k: v for k, v in rep.items() if k != "documents"}
    out["compacted"] = True
    out["documents"] = len(rep.get("documents") or [])
    out["full"] = path_rel
    return out


def compact_state(st: dict) -> int:
    """Replace the registry's redundant BULK with summaries; return bytes freed.

    Only write-only fields whose full payload is already on disk are touched, and
    each keeps the values the reports read (counts, corpus digest, the normalizer's
    summary numbers) plus the path of the full file. Nothing a postcheck CONSUMES
    is compacted: `inputs_manifest`, `scores`, `evidence_delta`, `residual`,
    `attempts_log` and every verdict stay exactly as they were.
    """
    freed = 0
    for rid, rec in sorted((st.get("runs") or {}).items()):
        if not isinstance(rec, dict):
            continue
        sb = str(rec.get("sandbox") or f"runs/{rid}")
        for field, path_rel, summarize in (
                ("judge_evidence", f"reports/judge_evidence_{rid}.json", _evidence_summary),
                ("evidence_after", f"{sb}/CODE_SCANS_after.json", _evidence_summary),
                ("format_fix", f"{sb}/FORMAT_FIX.json", _format_fix_summary)):
            payload = rec.get(field)
            if not isinstance(payload, dict) or payload.get("compacted"):
                continue
            freed += len(json.dumps(payload, default=str))
            rec[field] = summarize(payload, path_rel)
    return freed


def biggest_run_fields(st: dict, limit: int = 5) -> list:
    """[(bytes, run id, field)] of the biggest run-record fields (for reports)."""
    out = []
    for rid, rec in (st.get("runs") or {}).items():
        if not isinstance(rec, dict):
            continue
        for field, value in rec.items():
            if isinstance(value, (dict, list)) and len(value) > 8:
                out.append((len(json.dumps(value, default=str)), rid, field))
    return sorted(out, reverse=True)[:limit]


class Ctx:
    """Pipeline root + crash-safe state.

    state.json (version 3: the pool/integration round model) holds:
      source_manifest, source, original_digest, config, runs{id: record},
      rounds{r: record}, pinned[{id, round, source_id, digest, ...}], log[].
    """

    def __init__(self, root: Path, strict_venue: bool = False):
        self.root = root
        # `--strict-venue`: refuse to run on a missing/inconsistent
        # venue-journal configuration instead of only reporting it (see load).
        self.strict_venue = bool(strict_venue)
        self.venue_notes: list = []
        self.venue_problems: list = []
        # The pristine copy of `--source`: always `non_revised/`, the only
        # accepted name. The pipeline never moves or renames the directory.
        self.pristine = root / pristine_dirname(root)
        self.runs_dir = root / "runs"
        self.reports_dir = root / "reports"
        self.pins_dir = root / PIN_DIRNAME
        self.cfg_path = root / "pipeline_config.json"
        self.state_path = root / "state.json"
        self.cfg = {}
        self.state = {"version": STATE_VERSION, "runs": {}, "rounds": {},
                      "pinned": [], "log": []}

    # ---- lifecycle ----
    def load(self, need_cfg: bool = True) -> None:
        if not self.root.is_dir():
            die(f"pipeline root not found: {self.root}  (run `setup` first)")
        _legacy = legacy_input_area_problems(self.root)
        if _legacy:
            die("this root uses a removed input-area spelling:\n  - "
                + "\n  - ".join(_legacy)
                + "\n       Rename the directory once and re-run; the pipeline does not "
                  "resolve legacy aliases.")
        cfg = read_json(self.cfg_path)
        if cfg is None and need_cfg:
            die(f"missing/corrupt {self.cfg_path}  (run `setup` first)")
        self.cfg = cfg or {}
        if cfg is not None:
            # `setup` validates `--judges` (>= 1 per round), but a hand-edited
            # `pipeline_config.json` used to slip past that. With judges=[0]
            # every version's expected directed-score count is 0, so the panel
            # gate called an UNJUDGED round "complete" and `decide` certified
            # it with 0 scores/version and no judge session at all.
            try:
                _rounds = max(1, int(cfg.get("rounds") or 1))
            except (TypeError, ValueError):
                _rounds = 1
            _judges = parse_round_counts(
                cfg.get("judges") if cfg.get("judges") is not None else DEFAULTS["judges"],
                _rounds, "--judges")
            if any(j < 1 for j in _judges):
                die(f"pipeline_config.json: --judges must be >= 1 per round, got {_judges}.\n"
                    f"       {self.cfg_path}\n"
                    f"       A round with no judge can never be certified; edit the config "
                    f"or re-run `setup` with --judges N (N >= 1).")
        if self.state_path.exists():
            st, problem = load_state_file(self.state_path)
            if st is None:
                prev = state_prev_path(self.state_path)
                hint = "\n       No previous registry is on disk yet (state.json.prev is written " \
                       "by every save)."
                if prev.is_file():
                    try:
                        when = time.strftime("%Y-%m-%d %H:%M:%S",
                                             time.localtime(prev.stat().st_mtime))
                    except OSError:
                        when = "an unknown time"
                    hint = (f"\n       The previous registry is on disk as {prev.name} (written "
                            f"{when}): check it, then `mv {prev.name} {self.state_path.name}` "
                            f"restores it.")
                die(f"state file {problem}: {self.state_path}{hint}\n"
                    f"       Deleting it and re-running `setup` requires a fresh --root: existing "
                    f"sandboxes are not auto-adopted.")
            if not isinstance(st, dict) or not isinstance(st.get("runs"), dict):
                die(f"state file carries no run registry: {self.state_path}\n"
                    f"       Restore it from a backup. Deleting it and re-running `setup` "
                    f"requires a fresh --root: existing sandboxes are not auto-adopted.")
            try:
                found = int(st.get("version") or 0)
            except (TypeError, ValueError):
                found = 0
            if found > STATE_VERSION:
                die(f"state.json records version {found}, but this script writes version "
                    f"{STATE_VERSION}: the root was created by a newer pipeline.\n"
                    f"       Refusing to touch {self.state_path}.")
            if found < STATE_VERSION and st.get("runs"):
                die(f"state.json records state version {found} but this script expects "
                    f"{STATE_VERSION} (the pool/integration round model) and the registry is "
                    f"not empty:\n"
                    f"       {self.state_path}\n"
                    f"       This root was created by a different/older pipeline (for example "
                    f"paper_orchestrator.py or a pre-3.0 round model with pairwise cross-pollination "
                    f"arms). Point --root at a root created by this script's `setup`, or start a "
                    f"fresh --root; existing sandboxes are never adopted.")
            for rid, rec in st["runs"].items():
                if not isinstance(rec, dict) or "kind" not in rec or "round" not in rec:
                    die(f"state.json is not a round-pipeline registry: run record {rid!r} "
                        f"carries no 'kind'/'round' field.\n"
                        f"       Point --root at a root created by this script's `setup`.")
                # A record without a sandbox path crashed later with a bare
                # KeyError deep inside a command (e.g. status/retry) instead of
                # naming the damaged record. Validate the fields every command
                # relies on, here, once.
                if not isinstance(rec.get("sandbox"), str) or not rec["sandbox"]:
                    die(f"state.json is damaged: run record {rid!r} carries no 'sandbox' path.\n"
                        f"       {self.state_path}\n"
                        f"       Restore state.json from a backup (the sandboxes themselves are "
                        f"on disk under {self.runs_dir}); the pipeline never adopts a partial "
                        f"registry automatically.")
                try:
                    int(rec["round"])
                except (TypeError, ValueError):
                    die(f"state.json is damaged: run record {rid!r} has a non-numeric 'round' "
                        f"({rec['round']!r}).\n       {self.state_path}")
                if not isinstance(st.get("rounds"), dict) or \
                        not isinstance(st.get("pinned"), list):
                    die(f"state.json is damaged: 'rounds' must be an object and 'pinned' a list.\n"
                        f"       {self.state_path}")
            st.setdefault("rounds", {})
            st.setdefault("pinned", [])
            st.setdefault("log", [])
            st["version"] = STATE_VERSION
            self.state = st
            try:
                size = self.state_path.stat().st_size
            except OSError:
                size = 0
            if size > STATE_SOFT_BYTES:
                heavy = ", ".join(f"{rid}.{field} ({n / 1e6:.1f} MB)"
                                  for n, rid, field in biggest_run_fields(st, 3))
                print(f"[warn] {self.state_path.name} is {size / (1024 * 1024):.1f} MiB"
                      + (f" (largest: {heavy})" if heavy else "")
                      + "; the deprecated evidence copies inside it are compacted to their "
                        "counts/paths on the next save, and the previous registry is kept as "
                        f"{state_prev_path(self.state_path).name}")
            note = pipeline_identity_note(self)
            if note:
                print(note)
        # The venue and the journal are configuration, not content: a root whose
        # venue id resolves to nothing, whose recorded profile snapshot
        # disagrees with the config, or whose journal does not belong to the
        # selected venue is reported HERE, once, for every command that loads
        # the root. `status` and `agents` still work (they need no prompt);
        # every command that renders a prompt resolves the profile strictly and
        # refuses to run (see venue_profile_of).
        self.venue_notes, self.venue_problems = venue_config_findings(self)
        for note in self.venue_notes:
            print(f"[venue] {note}")
        for problem in self.venue_problems:
            print(f"[{'ERROR' if self.strict_venue else 'warn'}] venue: {problem}")
        if self.strict_venue and self.venue_problems:
            die("--strict-venue: fix the venue/journal configuration above (set-venue / "
                "set-journal) or drop the flag to run with warnings only.")
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if not self.state["runs"] and self.runs_dir.is_dir():
            orphans = sorted(p.name for p in self.runs_dir.iterdir()
                             if p.is_dir() and not p.name.startswith("_"))
            if orphans:
                shown = ", ".join(orphans[:6]) + ("..." if len(orphans) > 6 else "")
                print(f"[warn] {self.state_path.name} has no run registry but "
                      f"{len(orphans)} sandbox(es) exist under runs/ ({shown}). "
                      f"They will NOT be adopted automatically; restore state.json to resume.")

    def save_state(self) -> None:
        self.state["updated"] = utcnow()
        if CURRENT_RUN_LOG:
            try:
                rel = str(Path(CURRENT_RUN_LOG).resolve().relative_to(self.root.resolve()))
            except (ValueError, OSError):
                rel = str(CURRENT_RUN_LOG)
            logs = self.state.setdefault("run_logs", [])
            if rel not in logs:
                logs.append(rel)
                del logs[:-20]
        # COMPACT before writing: the fields `compact_state` drops are copies of
        # files that live on disk anyway, and keeping them here is what turned
        # the 2026-09-24 registry into 78 MiB (and then into a refused root).
        freed = compact_state(self.state)
        if freed:
            self.state.setdefault("log", []).append(
                {"ts": utcnow(), "event": "state-compacted", "run_id": None,
                 "detail": f"replaced {freed / 1e6:.1f} MB of redundant evidence copies "
                           f"(judge_evidence/evidence_after/format_fix) with their counts and "
                           f"the path of the full file"})
        # Keep the PREVIOUS registry as a hard link before the atomic replace: a
        # pointer, not a copy, so an 80 MB state costs no extra bytes and no I/O.
        prev = state_prev_path(self.state_path)
        try:
            if self.state_path.is_file():
                if prev.exists():
                    prev.unlink()
                os.link(self.state_path, prev)
        except OSError:
            pass                        # no hardlinks (drvfs) or a concurrent save: best effort
        write_json_atomic(self.state_path, self.state)
        try:
            size = self.state_path.stat().st_size
        except OSError:
            size = 0
        if size > STATE_SOFT_BYTES and not self.state.get("state_size_warned"):
            self.state["state_size_warned"] = utcnow()
            heavy = ", ".join(f"{rid}.{field} ({n / 1e6:.1f} MB)"
                              for n, rid, field in biggest_run_fields(self.state, 3))
            print(f"[warn] {self.state_path.name} is {size / (1024 * 1024):.1f} MiB"
                  + (f" (largest: {heavy})" if heavy else "")
                  + "; a growing registry slows every command -- report it, and `prune --yes` "
                    "reclaims the records' sandboxes when the run is decided")

    # ---- cross-process exclusion ----
    @contextlib.contextmanager
    def lock(self, what: str):
        """Hold the root's advisory lock while a MUTATING command runs.

        Nothing else guards the root: two `run` processes (a double start, a
        forgotten second terminal, a cron job) both see the same pending runs,
        both launch agents into the SAME sandbox -- two sessions writing one
        deliverable -- and both save their own state.json copy, so the second
        save silently drops the first one's run records. `run`, `decide`, `retry`,
        `prune` and `redline` therefore take this lock for the whole command
        (`decide` writes decision.json, the round reports and final_clean_version/).

        The lock is a plain file holding the owner's pid. A lock whose pid is
        gone (crashed/killed pipeline) is reclaimed with a warning instead of
        blocking the operator forever.
        """
        lock_path = self.root / LOCK_FILE
        info = {"pid": os.getpid(), "what": what, "since": utcnow(),
                "root": str(self.root)}
        acquired = False
        # Publish the owner JSON ATOMICALLY with the lock: creating an empty
        # lock and then writing its JSON leaves a window where a second process
        # reads "no pid" and declares the LIVE lock stale. A staged file linked
        # into place appears complete or not at all.
        staged = self.root / f"{LOCK_FILE}.{os.getpid()}.tmp"
        staged.write_text(json.dumps(info, indent=2), encoding="utf-8")
        try:
            acquired = self._claim_lock(lock_path, staged, info, what)
        finally:
            try:
                staged.unlink()
            except OSError:
                pass
        if not acquired:
            die(f"could not acquire the pipeline lock {lock_path}; remove it by hand if no other "
                f"pipeline process is running")
        try:
            yield
        finally:
            try:
                holder = read_json(lock_path, revive=False) or {}
                if holder.get("pid") == os.getpid():
                    lock_path.unlink()
            except OSError:
                pass

    def _reclaim_stale_lock(self, lock_path: Path, holder: dict, what: str) -> bool:
        """Reclaim ONE stale lock; True means retry the create.

        A LIVE owner dies with the actionable message. The reclaim moves the
        stale file aside with an atomic rename: of two processes reclaiming the
        same lock exactly one rename succeeds, so the loser can never unlink a
        lock the winner has just created. This is deliberately shared by the
        hardlink path and the O_EXCL fallback: on a no-hardlink filesystem
        (drvfs) `os.link` raises plain OSError, and the old placement inside
        the `FileExistsError` branch made every later command die "remove the
        lock by hand" after a crash.
        """
        pid = holder.get("pid")
        if pid is None:
            # A lock written by a creator that is not (yet) atomic: give it a
            # moment to finish writing before calling it stale.
            for _ in range(20):
                time.sleep(0.05)
                holder = read_json(lock_path, revive=False) or {}
                if holder.get("pid") is not None:
                    break
            pid = holder.get("pid")
        try:
            _pid_n = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            _pid_n = None
        if _pid_n is not None and pid_alive(_pid_n):
            die(f"another pipeline process is already working on this root "
                f"(pid {pid}, {holder.get('what')!r} since {holder.get('since')}).\n"
                f"       Refusing to run {what!r} concurrently: two writers would "
                f"double-execute agent sessions and overwrite each other's state.json.\n"
                f"       Wait for it to finish, or -- if you are sure it is gone -- delete "
                f"{lock_path} and re-run.")
        print(f"[warn] reclaiming a STALE pipeline lock {lock_path} "
              f"(owner pid {pid!r} is not running)")
        stale = lock_path.with_name(f"{LOCK_FILE}.stale.{os.getpid()}")
        try:
            os.rename(lock_path, stale)
        except FileNotFoundError:
            return True               # another process reclaimed it first
        except OSError:
            return True
        captured = read_json(stale, revive=False) or {}
        if captured != holder:
            # The file changed between our read and the rename: another process
            # had already reclaimed the stale lock and created its own. Put the
            # live lock back (link never clobbers a newer one) and refuse
            # instead of running beside it.
            restored = False
            try:
                os.link(stale, lock_path)
                restored = True
            except OSError:
                # No hardlink support (drvfs): restore with an exclusive
                # create and a byte copy, never `os.replace` (which would
                # clobber a newer live lock).
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                except OSError:
                    pass
                else:
                    with os.fdopen(fd, "wb") as f:
                        f.write(stale.read_bytes())
                    restored = True
            if restored:
                try:
                    stale.unlink()
                except OSError:
                    pass
            die(f"the pipeline lock {lock_path} was reclaimed by another process while "
                f"this command was starting; re-run it (moved copy: {stale})")
        try:
            stale.unlink()
        except OSError:
            pass
        return True

    def _claim_lock(self, lock_path: Path, staged: Path, info: dict, what: str) -> bool:
        """Create the lock from `staged`, reclaiming a stale one at most once.

        Returns True when this process owns the lock. Reclaim moves the stale
        lock aside with an atomic rename: of two processes reclaiming the same
        stale lock exactly one rename succeeds, so the loser can never unlink a
        lock the winner has just created (the old unlink-then-create sequence
        let both processes believe they held it).
        """
        acquired = False
        for attempt in (1, 2):
            try:
                os.link(staged, lock_path)
            except FileExistsError:
                self._reclaim_stale_lock(lock_path,
                                         read_json(lock_path, revive=False) or {}, what)
                continue
            except OSError:
                # No hardlink support on this filesystem: fall back to the
                # exclusive create (the content window returns, but the lock
                # still excludes). The fallback reclaims a stale lock too --
                # otherwise crash recovery is dead code on exactly the
                # filesystems that need it.
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                except FileExistsError:
                    self._reclaim_stale_lock(lock_path,
                                             read_json(lock_path, revive=False) or {}, what)
                    continue
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(info, f, indent=2)
            else:
                pass
            acquired = True
            break
        return acquired

    def rounds_count(self) -> int:
        # The SAME clamp `config_rounds` applies, and for the same reason: a
        # hand-edited `"rounds": 0` made this accessor return 0 (every other
        # caller clamps, but `pinned_integrity`'s range(1, 1), the r0_a2
        # final-version id and prune's keep_from do not), silently disabling
        # winner verification instead of failing.
        return config_rounds(self)

    def judges_count(self, r: int = None) -> int:
        """Judge sessions per version.

        With `r`, the round's own count (`--judges` is a per-round list; a
        decided round's recorded plan wins -- see round_judges()). Without it,
        the count of the first configured round, which is what a caller that has
        no round at hand (a config summary) should print.
        """
        if r is None:
            return int(counts_of(self.cfg, "judges", self.rounds_count())[0])
        return int(round_judges(self, r))

    # ---- run records ----
    def run(self, rid: str):
        return self.state["runs"].get(rid)

    def runs(self, kind: str = None, round_no: int = None) -> list:
        recs = list(self.state["runs"].values())
        if kind:
            recs = [r for r in recs if r.get("kind") == kind]
        if round_no is not None:
            recs = [r for r in recs if r.get("round") == int(round_no)]
        recs.sort(key=lambda r: nat_key(r.get("id", "")))
        return recs

    def sandbox_of(self, rec: dict) -> Path:
        raw = Path(rec["sandbox"])
        root = self.root.resolve()
        # An absolute spelling is tolerated only when it points INSIDE this root
        # (a legacy/hand-edited record); `Path.__truediv__` would otherwise
        # silently discard the root and let `prune` delete an outside tree.
        full = (raw if raw.is_absolute() else self.root / raw).resolve()
        try:
            full.relative_to(root)
        except ValueError:
            die(f"state.json is damaged: run record {rec.get('id')!r} points OUTSIDE the root "
                f"({raw} -> {full}).\n       {self.state_path}\n"
                f"       A sandbox must stay below {root}; refusing to use it.")
        return full

    def round_rec(self, r: int) -> dict:
        key = str(int(r))
        rounds = self.state.get("rounds")
        if not isinstance(rounds, dict):
            rounds = self.state["rounds"] = {}
        rec = rounds.get(key)
        if rec is None:
            rec = {"round": int(r), "status": "pending", "created": utcnow()}
            rounds[key] = rec
        return rec

    def round_get(self, r: int) -> dict:
        """Read-only view of a round record (never creates one).

        Reporting commands (`status`, decision reports) use this so that
        inspecting a pipeline cannot mutate its state.
        """
        return (self.state.get("rounds") or {}).get(str(int(r))) or {}

    def register(self, rid: str, kind: str, round_no: int, sandbox_rel: str, **extra) -> dict:
        rec = self.state["runs"].get(rid)
        if rec is None:
            rec = {"id": rid, "kind": kind, "round": int(round_no), "sandbox": sandbox_rel,
                   "status": "pending", "attempts": 0, "created": utcnow(), "started": None,
                   "finished": None, "last_error": None, "last_duration": None,
                   "postcheck": None, "inputs_manifest": None, "upstream_run_id": None,
                   "source_id": None, "self_id": None, "other_id": None, "target_id": None,
                   "judge_index": None, "label_map": None, "field_ids": None,
                   "corpus_digest": None, "summary": None, "scores": None}
            self.state["runs"][rid] = rec
            self.log("registered", rid, kind)
        for k, v in extra.items():
            if v is not None and rec.get(k) != v:
                rec[k] = v
        return rec

    def log(self, event: str, run_id: str = None, detail: str = None) -> None:
        self.state["log"].append({"ts": utcnow(), "event": event,
                                  "run_id": run_id, "detail": detail})
        if len(self.state["log"]) > 800:
            self.state["log"] = self.state["log"][-500:]

    @property
    def source_manifest(self):
        return self.state.get("source_manifest")


# =====================================================================
# INTEGRITY
# =====================================================================

def pristine_integrity(ctx: Ctx) -> tuple:
    """(ok, detail) for the master copy of the original corpus."""
    if hash_checks_skipped():
        # `--skip-hash`: the copy is NOT verified. Report that as such -- never
        # as "ok" (see the block comment on SKIP_HASH_CHECKS).
        return True, "not verified (--skip-hash)"
    stored = ctx.source_manifest
    if not isinstance(stored, dict):
        return False, "no setup-time manifest recorded in state.json"
    if not ctx.pristine.is_dir():
        return False, f"pristine copy missing: {ctx.pristine}"
    cur = hash_manifest(ctx.pristine)
    if manifests_equal(cur, stored):
        return True, f"{cur['count']} file(s) match the setup-time manifest"
    a, b = cur.get("files", {}), stored.get("files", {})
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return False, ("pristine original changed: "
                   f"{len(changed)} modified, {len(set(a) - set(b))} added, "
                   f"{len(set(b) - set(a))} removed")


def pinned_integrity(ctx: Ctx) -> list:
    """Content-addressed chain check.

    Verifies every pinned champion AND every published winner directory
    (<root>/round<R>_winner/): both must still hash to the digest the round
    recorded, otherwise the chain the decision rests on is broken.
    """
    if hash_checks_skipped():
        return []               # not verified; the reports say so (hash_skip_note)
    errs = []
    for pin in ctx.state.get("pinned") or []:
        docs = pinned_docs_dir(ctx, pin)
        if not docs.is_dir():
            errs.append(f"pinned/{pin['id']}/documents is missing")
            continue
        cur = corpus_tree_digest(docs)
        if cur != pin.get("digest"):
            errs.append(f"pinned/{pin['id']} content changed (digest {cur[:12]} != recorded "
                        f"{str(pin.get('digest'))[:12]})")
    for r in range(1, ctx.rounds_count() + 1):
        rrec = ctx.state.get("rounds", {}).get(str(int(r))) or {}
        if rrec.get("status") != "done":
            continue
        name = rrec.get("winner_dir")
        if not name:
            errs.append(f"round {r} is complete but records no published winner directory")
            continue
        d = ctx.root / name
        if not d.is_dir():
            errs.append(f"{name}/ is missing (every completed round publishes its winner under "
                        f"--root)")
            continue
        pin_id = rrec.get("pin_id")
        pin = find_pin(ctx, pin_id) if pin_id else None
        pin_docs = pinned_docs_dir(ctx, pin) if pin else None
        if pin is None:
            # A round record without a pin (a minimal/legacy root) has nothing to
            # compare against; a RECORDED pin that is gone is a real error.
            if pin_id:
                errs.append(f"{name}/ cannot be verified: its pin {pin_id!r} is missing")
            continue
        if pin_docs is None or not pin_docs.is_dir():
            errs.append(f"{name}/ cannot be verified: pinned/{pin_id}/documents is missing")
            continue
        # Compared against the PIN rather than against a stored digest, so the
        # READ-ONLY raw-data area can be left out of both sides: that directory
        # is an INPUT whose content is verified against the pristine original
        # (see enforce_readonly_raw_data), not something the round produced, and
        # a normalised copy of it must not read as "the champion changed".
        want = manifest_digest(without_raw_data(corpus_tree_manifest(pin_docs)))
        cur = manifest_digest(without_raw_data(corpus_tree_manifest(d)))
        if cur != want:
            errs.append(f"{name}/ no longer matches its pinned champion "
                        f"(digest {cur[:12]} != {want[:12]})")
    return errs


def input_mismatches(ctx: Ctx, rec: dict) -> list:
    """Byte-identity check of every read-only input recorded for a run sandbox."""
    if hash_checks_skipped():
        return []               # not verified (--skip-hash)
    sb = ctx.sandbox_of(rec)
    im = rec.get("inputs_manifest") or {}
    errs = []
    for area in sorted(im):
        p = area_dir(sb, area)
        if not p.is_dir():
            errs.append(f"{area}/ is missing from the sandbox")
            continue
        if not manifests_equal(hash_manifest(p, follow_dir_links=True), im[area]):
            errs.append(f"{area}/ was modified after the sandbox was built")
    return errs


# =====================================================================
# VERSION CORPUS (one shape for digesting, judging and pinning)
#
# A "version" (field member) is represented everywhere by its CORPUS: the
# documents at the top level of the directory handed to a judge as target/.
#   original          -> the pristine tree itself
#   a1 (round base)   -> runs/r<R>_a1/base/
#   w1..wM            -> the rewrite run's rewritten/ contents, code/ folded in
#   a2..a{1+N}        -> the revise run's revised/ contents, code/ folded in
#   i1..iK            -> the integration run's integrated/ contents, code/ in
#   pinned champion   -> pinned/<r>_<id>/documents/
# Deduplication, pinning and judging all use this one shape, so a copy of a
# pinned champion (the next round's base) hashes identically to its pin and is
# deduplicated -- that is how "pinned content equal to the original appears
# once" falls out of content hashing instead of label bookkeeping.
# =====================================================================

def corpus_sources(ctx: Ctx, r: int, vid: str) -> list:
    """Ordered [(source_dir, prefix_in_corpus, excluded_top_level_names)].

    Later sources override earlier ones with the same relative path. The
    exclusion set is what keeps the stage's own process scratch
    (revised/work/, rewritten/work/, integrated/work/) out of the submission
    corpus; see CORPUS_EXCLUDE_TOP.
    """
    if vid == ORIGINAL_ID:
        return [(working_original_dir(ctx), "", ())]
    if is_fresh_vid(vid):
        rec = ctx.run(rid_for_fresh(r, vid))
        if rec is None:
            return []
        sb = ctx.sandbox_of(rec)
        if vid == A1_ID:
            return [(sb / "base", "", ())]
        srcs = []
        if (sb / CODE_DIR).is_dir():
            srcs.append((sb / CODE_DIR, "code/", ()))
        srcs.append((sb / output_dir_for_vid(vid), "", CORPUS_EXCLUDE_TOP))
        return srcs
    pin = find_pin(ctx, vid)
    if pin is None:
        return []
    return [(pinned_docs_dir(ctx, pin), "", ())]


def output_dir_for_vid(vid: str) -> str:
    """The sandbox directory a fresh arm writes its candidate package into."""
    arm = arm_of_vid(vid)
    return {"rewrite": REWRITTEN_DIR, "integrate": INTEGRATED_DIR}.get(arm, REVISED_DIR)


def output_dir_for_kind(kind: str) -> str:
    """The sandbox directory a run KIND writes its candidate package into."""
    return {"rewrite": REWRITTEN_DIR, "integrate": INTEGRATED_DIR}.get(kind, REVISED_DIR)


def output_dir_of(rec: dict) -> str:
    """The sandbox directory a run writes its candidate package into."""
    return output_dir_for_kind(rec.get("kind"))


def manifest_for_sources(sources: list) -> dict:
    """{rel path: sha256} for ordered [(dir, prefix, excluded)] corpus sources.

    ONE definition of a version corpus, shared by the digest the pipeline
    records (`corpus_manifest`) and by every code-side scan that claims to
    describe the same corpus (`code_side_evidence`): the revision auxiliaries
    and the pipeline's own mandated bookkeeping (which build_corpus_dir() strips
    from every materialized copy) are dropped, the sources' own top-level
    exclusions (`work/` scratch) apply, and later sources override earlier ones
    with the same relative path.
    """
    entries = []
    for src, prefix, excluded in sources:
        if not src.is_dir():
            continue
        # follow_dir_links: a sandbox package may carry an evidence area
        # (raw_data/, human_review_feedback/) as a symlink to the
        # root's canonical copy (see ensure_pristine_input). The digest a run
        # records must see the SAME files the pin materializes, or pin_champion
        # dies on its own "internal inconsistency" check.
        for p in _iter_tree_files(src, follow_dir_links=True):
            if not p.is_file() or _is_aux_doc(p.name):
                continue
            if is_bookkeeping_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_disabled_evidence_rel(rel):
                continue
            entries.append((prefix + rel, p))
    digs = sha256_files([p for _k, p in entries])
    files = {k: d for (k, _p), d in zip(entries, digs)}
    return {"files": files, "count": len(files)}


def corpus_manifest(ctx: Ctx, r: int, vid: str) -> dict:
    """{rel path: sha256} for a version corpus -- the corpus IDENTITY."""
    return manifest_for_sources(corpus_sources(ctx, r, vid))


def recompute_corpus_digest(ctx: Ctx, r: int, vid: str) -> str:
    return manifest_digest(corpus_manifest(ctx, r, vid))


# ---------------------------------------------------------------------
# Content fingerprint: the identity of a version's DOCUMENTS, independent of
# their names and of the pipeline's own bookkeeping files.
#
# The field is documented as "content is the only identity", but the integrity
# digest hashes RELATIVE PATHS as well. Two consequences were measured on a real
# run: a package that renames files without changing them, or a package whose
# only difference is a regenerated CHANGELOG/MANUAL_STEPS/REVISION_REPORT, is a
# distinct field member and gets its own judge panel. The fingerprint closes
# that gap while the integrity digest keeps doing its own job (pin/winner
# verification, tamper detection). It is a MULTISET of file content digests, so
# duplicated documents still count twice and a lost file is still visible.
# ---------------------------------------------------------------------

def corpus_content_set_fingerprint(sources: list) -> str:
    """Name- and bookkeeping-insensitive fingerprint of a version corpus."""
    overrides = corpus_source_overrides(sources)
    paths = []
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src, follow_dir_links=True):
            if not p.is_file() or _is_aux_doc(p.name) or is_bookkeeping_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            paths.append(p)
    if not paths:
        # No files at all: the corpus is MISSING (a pruned or unmaterialized
        # sandbox), not empty. Returning "" lets the callers fall back to the
        # recorded integrity digest instead of treating every missing corpus as
        # the same empty-content member.
        return ""
    digs = sha256_files(paths)
    return hashlib.sha256("\n".join(sorted(digs)).encode("utf-8")).hexdigest()


def corpus_content_fingerprint(ctx: Ctx, r: int, vid: str) -> str:
    return corpus_content_set_fingerprint(corpus_sources(ctx, r, vid))


# ---------------------------------------------------------------------
# Revision token: the 7-character content-hash version ID of a package.
#
# The revision stages name every editable document with ONE token derived from
# the package's content (replacing the legacy letter/digit increments): the
# first 7 hex characters of SHA-256 over the sorted content digests of the
# payload files, with the payload defined exactly like a version corpus (no
# work/ scratch, no difference-tracking auxiliaries -- see TRACKING_AUX_NAME_RE
# -- and no self-written reports) and with NAMES ignored. A version marker
# inside file CONTENTS (a repointed LaTeX \bibliography{refs-4f3a9c1.bib} or
# \addbibresource{refs-4f3a9c1.bib}, say) is REMOVED before hashing, so
# applying the token does not change it -- in BOTH apply paths: the replaced
# trailing token ("ms-a.tex" -> "ms-<T>.tex") and the token-less APPEND
# ("refs.bib" -> "refs-<T>.bib"), whose old "<VERSION>" substitution left
# "refs" and "refs-<T>" with DIFFERENT normalized bytes. The same algorithm is
# shipped to the agents as paper-revise/scripts/revision_token.py, and the test
# suite asserts the two implementations agree.
# ---------------------------------------------------------------------
DOCHASH_HEX7_RE = re.compile(r"^[0-9a-f]{7}$")


def _payload_files_of_dir(dirp: Path) -> list:
    out = []
    if not dirp.is_dir():
        return out
    for p in _iter_tree_files(dirp, follow_dir_links=True):
        if not p.is_file():
            continue
        rel = p.relative_to(dirp)
        if any(part == "work" for part in rel.parts[:-1]):
            # `work/` at ANY depth is stage scratch; only the top-level check
            # let `supp/work/render.png` change the content-hash token while
            # being invisible to the scans.
            continue
        if is_author_to_complete_readme_name(p.name):
            # The hand-off checklist is not a manuscript payload document: it
            # appears, changes and disappears as the author disposes items, and
            # must not invalidate the package's content-hash version token (the
            # postcheck may generate it AFTER the stage applied the token).
            continue
        if is_bookkeeping_name(p.name) or _is_aux_doc(p.name):
            continue
        out.append(p)
    return out


def _normalize_version_refs(data: bytes, tokens) -> bytes:
    """Version-token REFERENCES in file bytes, with the marker REMOVED.

    Only reference-like occurrences are touched -- never a bare "-x" in prose:
      1. any token (or 7-hex token) immediately followed by a file extension;
      2. any token inside a LaTeX reference command's argument.
    Removing the marker (with its separator) keeps the hash stable when the
    token is applied: "fig1.png" and "fig1-4f3a9c1.png" both normalize to
    "fig1.png", and "refs.bib" and "refs-4f3a9c1.bib" alike -- the sibling
    `<VERSION>` substitution could not make the token-less append path stable.
    A prose "-a" ("panel-a") is still untouched.
    """
    alts = [re.escape(str(t).encode()) for t in sorted(set(tokens), key=len, reverse=True) if t]
    alts.append(rb"[0-9a-f]{7}")
    tok = rb"(?:" + b"|".join(alts) + rb")"
    data = re.sub(rb"([-_])" + tok + rb"(?=\.[A-Za-z][A-Za-z0-9]{0,9}\b)",
                  rb"", data)
    cmd = re.compile(
        rb"(\\(?:input|include|subfile|bibliography|bibliographystyle|addbibresource|"
        rb"includegraphics|lstinputlisting|inputminted|externaldocument|subimport|import)\b"
        rb"[^{}]*?\{)([^{}]*)(\})")

    def _arg(m):
        inner = re.sub(rb"([-_])" + tok + rb"(?![0-9A-Za-z_])", rb"", m.group(2))
        return m.group(1) + inner + m.group(3)

    return cmd.sub(_arg, data)


def revision_token_for_dir(dirp: Path) -> dict:
    """{'token','files','tokens_seen','consistent','notes'} for one package dir."""
    files = _payload_files_of_dir(dirp)
    tokens = []
    named = []                                  # (rel path, filename token or None)
    for p in files:
        rel = p.relative_to(dirp).as_posix()
        m = DOC_TOKEN_RE.search(p.stem)
        token = m.group(0)[1:] if m else None
        if token:
            tokens.append(token)
        named.append((rel, token))
    digs = []
    unreadable = []
    for p in files:
        try:
            digs.append(hashlib.sha256(_normalize_version_refs(p.read_bytes(), tokens)).hexdigest())
        except OSError as e:
            unreadable.append(f"{p.relative_to(dirp).as_posix()}: {e.strerror or e}")
            continue
    if not digs:
        return {"token": "", "files": 0, "tokens_seen": [], "consistent": False,
                "notes": ["no payload file could be read"]}
    token = hashlib.sha256("\n".join(sorted(digs)).encode("utf-8")).hexdigest()[:7]
    # The READ-ONLY raw-data directory keeps the ORIGINAL file names: any version
    # token a name inside it carries belongs to the run that produced the source
    # corpus, never to this package, so it is not this package's naming evidence.
    # The token VALUE above is deliberately still computed over every payload
    # file (the raw data included), so it stays equal to what the agents compute
    # with paper-revise/scripts/revision_token.py.
    hex_tokens = sorted({t for rel, t in named
                         if t and DOCHASH_HEX7_RE.match(t) and not is_evidence_rel(rel)})
    doc_hex_tokens = sorted({t for rel, t in named
                             if t and DOCHASH_HEX7_RE.match(t)
                             and not is_evidence_rel(rel)
                             and Path(rel).suffix.lower() in EDITABLE_DOC_EXTS})
    consistent = bool(hex_tokens) and all(t == token for t in hex_tokens)
    notes = []
    if unreadable:
        notes.append(f"{len(unreadable)} payload file(s) could not be read and are EXCLUDED "
                     f"from the content hash: {'; '.join(unreadable[:3])}"
                     + (f" (+{len(unreadable) - 3} more)" if len(unreadable) > 3 else ""))
    if not hex_tokens:
        notes.append("no 7-hex filename token yet (legacy letter/digit tokens or none applied)")
    elif not consistent:
        notes.append(f"filename token(s) {hex_tokens} do not match the content-derived token "
                     f"{token}")
    return {"token": token, "files": len(files),
            "tokens_seen": sorted({t for rel, t in named if t and not is_evidence_rel(rel)}),
            "hex_tokens": hex_tokens, "doc_hex_tokens": doc_hex_tokens,
            "consistent": consistent, "notes": notes}


def _record_revision_token(rec: dict, dirp: Path, warns: list,
                           errs: list = None, pipeline_changed: bool = False) -> None:
    """Record a package's content-hash version token.

    A package that carries no 7-hex token (a legacy letter/digit name, or an
    agent that has not applied the naming rule) is recorded as-is WITHOUT a
    warning: older conventions stay readable. A filename token that CONTRADICTS
    the content-derived token is a real inconsistency; it is a stage ERROR when
    the caller can fail and more than one editable-document token survived (a
    stale pre-revision copy), otherwise a warning.
    """
    try:
        info = revision_token_for_dir(dirp)
    except OSError as e:                                          # noqa: BLE001
        warns.append(f"revision token could not be computed: {e}")
        return
    rec["revision_token"] = info
    if info.get("token") and info.get("hex_tokens") and not info.get("consistent"):
        if pipeline_changed:
            msg = (f"revision token: filename token(s) {info['tokens_seen']} vs the "
                   f"content-derived token {info['token']} -- the orchestrator's OWN format "
                   f"normalization rewrote a document after the token was applied (see the "
                   f"run's FORMAT_FIX artifact); the delivered bytes are the ones with token "
                   f"{info['token']}. Re-apply the token after normalization, or treat this "
                   f"as a pipeline-side naming note")
        else:
            msg = (f"revision token mismatch: filename token(s) {info['tokens_seen']} vs the "
                   f"content-derived token {info['token']} -- the package was edited after its "
                   f"token was applied, or a token was copied from another package")
        # More than one 7-hex token on EDITABLE DOCUMENTS is never a naming
        # nuisance: it means the same document family travelled twice (a stale
        # pre-revision copy plus the renamed copy). That is exactly the
        # NeoHeteroclitic 2026-10-17 package: both `...mainText-9915d6e.docx`
        # and the old `...mainText-FrontiersTemplate-zotero-bbb4e84.docx`
        # matched the submitted set and would both reach the journal. A warning
        # let the stage pass; the naming contract says ONE copy of each
        # document, so this is a stage error whenever the caller can fail.
        if errs is not None and len(info.get("doc_hex_tokens") or []) > 1:
            errs.append(msg + "; the package carries more than one 7-hex token on editable "
                        "documents, so at least one stale copy survived -- keep the current "
                        "copy and remove the old one")
        else:
            warns.append(msg)


def recorded_content_fingerprint(ctx: Ctx, r: int, vid: str):
    """The fingerprint recorded when the version was produced (no I/O)."""
    if vid == ORIGINAL_ID:
        return working_original_fingerprint(ctx)
    if is_fresh_vid(vid):
        return (ctx.run(rid_for_fresh(r, vid)) or {}).get("content_fingerprint")
    return (find_pin(ctx, vid) or {}).get("content_fingerprint")


def effective_content_fingerprint(ctx: Ctx, r: int, vid: str) -> str:
    """Recorded fingerprint, or a live one for roots created before this field."""
    fp = recorded_content_fingerprint(ctx, r, vid)
    if fp:
        return fp
    try:
        return corpus_content_fingerprint(ctx, r, vid)
    except OSError:
        return ""


def recorded_version_digest(ctx: Ctx, r: int, vid: str):
    """The digest recorded when the version's run/pin completed.

    `original` is the one exception: `working_original_digest` resolves it under
    the corpus rule (live when the working original is on disk, recorded
    otherwise). Every other version answers from its run or pin record.
    """
    if vid == ORIGINAL_ID:
        return working_original_digest(ctx)
    if is_fresh_vid(vid):
        rec = ctx.run(rid_for_fresh(r, vid))
        return (rec or {}).get("corpus_digest")
    pin = find_pin(ctx, vid)
    return (pin or {}).get("digest")


def build_corpus_dir(ctx: Ctx, r: int, vid: str, dst: Path) -> None:
    """Materialize a version's corpus into dst (same order as corpus_manifest).

    Pinned/published copies are stripped of the pipeline's own bookkeeping: the
    agent that wrote the version also wrote those reports, so they are not
    evidence a judge may weigh and their presence differs between labels (see
    CORPORA_STRIP_BOOKKEEPING). The run's own sandbox keeps them.

    Metadata (mtimes, modes, attributes) is PRESERVED: these copies are not
    handed to a judge -- the judge gets an anonymized view instead
    (build_judge_view) -- so nothing here needs equalizing, and the author's/
    agent's own file metadata survives into the pin, the published winner and
    the next round's base.
    """
    for src, prefix, excluded in corpus_sources(ctx, r, vid):
        if not src.is_dir():
            continue
        target = dst / prefix.rstrip("/") if prefix else dst
        copy_into(src, target, exclude_top=excluded, skip_aux=True,
                  strip_bookkeeping=True, root=ctx.root)


def corpus_files_for_view(ctx: Ctx, r: int, vid: str) -> list:
    """[(corpus-relative path, source path)] of a version, judge-view rules.

    Applies the filters build_corpus_dir() applies (auxiliaries and the pipeline's
    bookkeeping are dropped, the process scratch is excluded, and a later source
    overrides an earlier one for the same relative path) PLUS the judge-only rule
    of corpus_dir_view_files(): every derived output whose editable source is in
    the package goes as well -- the build by-products (a view is the one place
    where even READING a build log, with its absolute paths, build date, tool and
    machine names, would be a provenance leak) and the renderings the judge can
    compile itself (a .bbl of a shipped .bib, a PDF of a shipped .docx/.tex), so
    the judge compares sources. Every DOCUMENT of the pin is still in the view.
    """
    sources = corpus_sources(ctx, r, vid)
    overrides = corpus_source_overrides(sources)
    out, seen = [], set()
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for rel, p in corpus_dir_view_files(src):
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            key = prefix + rel
            if key in overrides[i] or key in seen:
                continue
            seen.add(key)
            out.append((key, p))
    return out


def corpus_dir_view_files(dirp: Path) -> list:
    """[(relative path, path)] for one directory under the judge-view rules.

    Slightly narrower than the corpus `build_corpus_dir()` materializes, because
    the judge is the one party that may not even READ what the corpus carries:
    difference-tracking auxiliaries (see TRACKING_AUX_NAME_RE), the pipeline's
    own bookkeeping/report files (`CORPORA_STRIP_BOOKKEEPING`), the process
    scratch (`CORPUS_EXCLUDE_TOP`, i.e. `work/`) and every derived output whose
    editable source is in the package (see `_is_view_excluded_file()`: a
    `.log`/`.fls` records the build machine's paths and dates in its CONTENT, a
    version an agent went over loses the whole by-product set so its PRESENCE
    would say which package was worked on, and a `.bbl`/`.pdf` that can be
    compiled from a shipped `.bib`/`.docx`/`.tex` is redundant next to its
    source) never reach a judge view -- so a judge cannot score or infer anything
    from an auxiliary file, a changelog, a ledger, a build log or a rendering.
    """
    out = []
    entries = _iter_tree_files(dirp, follow_dir_links=True)
    siblings = {}
    for p in entries:
        siblings.setdefault(p.parent, []).append(p.name)
    for p in entries:
        if _is_view_excluded_file(p.name, siblings.get(p.parent, ())):
            continue
        if is_bookkeeping_name(p.name):
            continue
        rel = p.relative_to(dirp).as_posix()
        if rel.split("/", 1)[0] in CORPUS_EXCLUDE_TOP:
            continue
        if is_disabled_evidence_rel(rel):
            # An inert `<evidence>.disabled/` area is neither submission content
            # nor readable evidence: it must never reach a judge view.
            continue
        out.append((rel, p))
    return out


def content_multiset(paths) -> list:
    """Sorted multiset of file-content digests under the given directories."""
    files = []
    for root in paths:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file():
                files.append(p)
    return sorted(sha256_files(files, on_error="<unreadable>"))


def judge_view_digest(judge_view: Path) -> list:
    """The content multiset of a materialized judge view."""
    return content_multiset([judge_view])


def _view_digest(ctx: Ctx, r: int, vid: str) -> list:
    """The RAW source-content multiset of `vid` (no anonymization applied).

    Kept for diagnostics/tests; the identity of a materialized VIEW is
    expected_view_digest(), because a view rewrites references and sanitizes
    metadata and therefore is not byte-identical to its source corpus.
    """
    if vid == ORIGINAL_ID:
        return content_multiset([working_original_dir(ctx)])
    return sorted(sha256_files([p for _rel, p in corpus_files_for_view(ctx, r, vid)]))


# ---- judge views: anonymous names, REWRITTEN references, SANITIZED metadata --
#
# Two things the raw rename pass got wrong, both fixed here:
#
#  1. A LaTeX package must stay COMPILABLE in the judge's sandbox. The view
#     renames every file and directory, so the text files that reference them
#     (\input/\include/\includegraphics/\addbibresource/\bibliography, build
#     scripts and \graphicspath entries) are rewritten to the anonymous names,
#     preserving the tree shape and therefore the relative paths.
#  2. Metadata is a bias channel: OOXML core/app/custom properties carry
#     author, company, application and creation/modification dates, tracked
#     changes and comments carry author/date attributes, zip entries carry
#     timestamps, and a PDF carries /Info (Producer, Creator, dates) and XMP.
#     The view strips/neutralizes all of those (PDF values are blanked in place,
#     keeping every byte offset valid; if a PDF's metadata is compressed or
#     unparsable the notes say so and the judge prompt still forbids using it).
VIEW_TEXT_EXTS = (".tex", ".ltx", ".bib", ".md", ".txt", ".rst", ".sh", ".py",
                  ".r", ".mk", ".cmake", ".toml", ".yml", ".yaml", ".json",
                  ".csv", ".cfg", ".ini",
                  # derived build text: they reference the same filenames, and a
                  # stale .bcf/.aux would break the next LaTeX build
                  ".aux", ".bcf", ".blg", ".out", ".log", ".bbl", ".toc",
                  ".lof", ".lot", ".nav", ".snm", ".vrb", ".xml")
VIEW_TEXT_NAMES = ("makefile", "gnumakefile", "cmakelists.txt", "latexmkrc")
VIEW_OOXML_EXTS = (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm")
VIEW_PDF_EXTS = (".pdf",)
VIEW_LATEX_TARGET_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".svg")
# LaTeX source files are addressed WITHOUT their extension by \input,
# \include, \bibliography, \addbibresource and \subfile. Their stems must be
# rewritten too, or the renamed view cannot compile.
VIEW_LATEX_SOURCE_EXTS = (".tex", ".ltx", ".bib", ".sty", ".cls")
VIEW_FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)
VIEW_FIXED_DATE = "2020-01-01T00:00:00Z"
_VIEW_EXPECT_CACHE = {}
_VIEW_EXPECT_LOCK = threading.Lock()
_VIEW_SANITIZE_CACHE = {}
_VIEW_SANITIZE_TOTAL = {"bytes": 0}
_VIEW_SANITIZE_MAX_ENTRIES = 256
_VIEW_SANITIZE_MAX_TOTAL = 256 * 1024 * 1024
_VIEW_SANITIZE_MAX_FILE = 16 * 1024 * 1024


def _view_is_text(rel: str) -> bool:
    name = Path(rel).name
    return (Path(rel).suffix.lower() in VIEW_TEXT_EXTS
            or name.lower() in VIEW_TEXT_NAMES)


def _view_layout(files: list, r: int, vid: str, view_seed: str) -> tuple:
    """(dir_names, file_map) with the ORIGINAL random draws (same seed logic).

    The EVIDENCE areas are the one exception to the anonymous layout: their
    files keep an anonymized NAME but live under a stable, labeled directory
    (`evidence/raw_data/…`, `evidence/human_review_feedback/…`,
    `evidence/llm_review_feedback/…`) so a judge can tell producer evidence and
    review feedback from submission documents. The
    `human_review_feedback/original_submission/` child keeps its name too (it is
    the reviewer-visible manuscript, an input where present), while every
    other/deeper directory and every file name stays salted per view. The
    labels are identical in every view -- the areas are byte-identical inputs,
    so they carry no signal about which version is which.
    """
    rng = random.Random(f"judge-view|{view_seed}|{int(r)}|{vid}".encode("utf-8"))
    dirs = sorted({str(Path(rel).parent.as_posix()) for rel, _p in files
                   if str(Path(rel).parent.as_posix()) not in (".", "")})
    evidence_dirs = [d for d in dirs if evidence_area_of(d)]
    normal_dirs = [d for d in dirs if not evidence_area_of(d)]
    shuffled = normal_dirs[:]
    rng.shuffle(shuffled)
    dir_names = {d: f"d{i:02d}" for i, d in enumerate(shuffled)}
    # A same-depth sibling must not get the same anonymous name: two evidence
    # subdirectories otherwise collapse to one view directory, and their files
    # (numbered per parent) overwrite each other. Index each anonymous segment
    # among the siblings under its real parent; ancestors are included even
    # when they hold no file directly, so an intermediate segment has an index
    # too. The labels stay identical in every view (evidence areas are
    # byte-identical inputs), so this leaks no cross-view correlation.
    evidence_tree = set(evidence_dirs)
    for d in evidence_dirs:
        segs = d.split("/")
        for i in range(2, len(segs)):
            evidence_tree.add("/".join(segs[:i]))
    siblings = {}
    for d in sorted(evidence_tree):
        siblings.setdefault(str(Path(d).parent.as_posix()), []).append(d)
    sibling_index = {d: i for kids in siblings.values()
                     for i, d in enumerate(kids, 1)}
    for d in evidence_dirs:
        top = evidence_area_of(d)
        area = RAW_DATA_DIR if top in RAW_DATA_DIRNAMES else top
        rest = d.split("/")[1:]
        parts = []
        cur = top
        for i, seg in enumerate(rest, 1):
            cur = f"{cur}/{seg}" if cur else seg
            if (i == 1 and top == HUMAN_FEEDBACK_DIR
                    and seg == ORIGINAL_SUBMISSION_DIRNAME):
                # Fixed, identical in every view: the judge must be able to tell
                # the reviewer-visible manuscript from a submission document.
                parts.append(ORIGINAL_SUBMISSION_DIRNAME)
            else:
                parts.append(f"s{sibling_index.get(cur, 1):02d}")
        dir_names[d] = "/".join([EVIDENCE_VIEW_ROOT, area] + parts)
    by_dir = {}
    for rel, src in files:
        parent = str(Path(rel).parent.as_posix())
        by_dir.setdefault(parent if parent != "." else "", []).append((rel, src))
    file_map = {}
    for parent, entries in sorted(by_dir.items()):
        order = entries[:]
        rng.shuffle(order)
        for i, (rel, _src) in enumerate(order, 1):
            new_dir = dir_names[parent] if parent else ""
            name = f"f{i:04d}{Path(rel).suffix}"
            file_map[rel] = f"{new_dir}/{name}" if new_dir else name
    return dir_names, file_map


def _latex_stem(rel: str) -> str:
    suffix = Path(rel).suffix
    return rel[:-len(suffix)] if suffix else rel


LATEX_REF_CMDS = ("input", "include", "subfile", "bibliography", "bibliographystyle",
                  "addbibresource", "includegraphics", "lstinputlisting", "inputminted",
                  "externaldocument", "subimport", "import")


def _rewrite_view_references(text: str, old_rel: str, new_rel: str, file_map: dict) -> str:
    """Rewrite path-like references so the renamed tree stays buildable.

    Three passes: exact file paths/basenames anywhere; extension-less arguments
    of the LaTeX reference commands (never bare words in prose); and
    \\graphicspath entries (directory renames).
    """
    old_dir = posixpath.dirname(old_rel) or "."
    new_dir = posixpath.dirname(new_rel) or "."
    subs = {}
    stems = {}
    stems_source = {}
    stems_target = {}
    dir_map = {}

    def add(mapping, old, new):
        if old and old != new and old not in mapping:
            mapping[old] = new

    for o, n in file_map.items():
        o_base, n_base = posixpath.basename(o), posixpath.basename(n)
        o_rel, n_rel = posixpath.relpath(o, old_dir), posixpath.relpath(n, new_dir)
        add(subs, o_rel, n_rel)
        add(subs, o_base, n_base)
        suffix = Path(o).suffix.lower()
        if suffix in VIEW_LATEX_TARGET_EXTS:
            # A target (`plot.pdf`) is what \includegraphics{plot} means.
            add(stems_target, _latex_stem(o_rel), _latex_stem(n_rel))
            add(stems_target, _latex_stem(o_base), _latex_stem(n_base))
        if suffix in (VIEW_LATEX_TARGET_EXTS + VIEW_LATEX_SOURCE_EXTS):
            add(stems, _latex_stem(o_rel), _latex_stem(n_rel))
            add(stems, _latex_stem(o_base), _latex_stem(n_base))
        if suffix in VIEW_LATEX_SOURCE_EXTS:
            # `\input{fig1}` means the SOURCE `fig1.tex`, never the image
            # `fig1.png` that shares the stem; mixing both in one table let a
            # shuffled directory order rewrite the input to an image.
            add(stems_source, _latex_stem(o_rel), _latex_stem(n_rel))
            add(stems_source, _latex_stem(o_base), _latex_stem(n_base))
        o_dir, n_dir = posixpath.dirname(o), posixpath.dirname(n)
        if o_dir:
            add(dir_map, posixpath.relpath(o_dir, old_dir), posixpath.relpath(n_dir, new_dir))
    if subs:
        keys = sorted(subs, key=len, reverse=True)
        pat = re.compile(r"(?<![A-Za-z0-9_\\])(" + "|".join(re.escape(k) for k in keys)
                         + r")(?![A-Za-z0-9_])")
        text = pat.sub(lambda m: subs[m.group(1)], text)
    if stems:
        cmd_pat = re.compile(r"\\(?P<cmd>" + "|".join(LATEX_REF_CMDS)
                             + r")\b(\s*\[[^\]]*\])?\s*\{([^{}]*)\}")

        def cmd_repl(m):
            arg = m.group(3)
            # \bibliography{refs,intro} and \addbibresource{refs,intro} carry
            # a comma-separated list; looking the whole string up left both
            # keys pointing at names the renamed tree no longer has.
            pieces = arg.split(",")
            # \includegraphics{plot} means the PLOTTED file (`plot.pdf`), never
            # the standalone source (`plot.tex`) that happens to share its stem:
            # a source and a target of one stem must not compete for one key.
            table = (stems_target if m.group("cmd") == "includegraphics"
                     else (stems_source or stems))
            mapped = [table.get(piece.strip(), piece) for piece in pieces]
            if mapped == pieces:
                return m.group(0)
            return m.group(0).replace("{" + arg + "}", "{" + ",".join(mapped) + "}")

        text = cmd_pat.sub(cmd_repl, text)
    if dir_map:
        def one(mm):
            d = mm.group(1).rstrip("/")
            d = re.sub(r"^\./", "", d)       # `./figures` and `figures` are one key
            return "{" + (dir_map.get(d, d) or ".") + "/}"

        # `\graphicspath{{figures/}}` has TWO brace levels. The old non-greedy
        # regex stopped at the first `}`, so group(1) was "{figures/" and the
        # inner `{dir}` substitution never matched: the directory rename was
        # dead code and a judge view kept pointing at the old figure directory.
        # Scan the argument's balanced braces instead.
        out, pos = [], 0
        for m in re.finditer(r"\\graphicspath\s*\{", text):
            if m.start() < pos:
                continue
            depth, j = 1, m.end()
            while j < len(text) and depth:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            if depth:                  # unclosed argument: leave it untouched
                break
            out.append(text[pos:m.start()])
            out.append("\\graphicspath{")
            out.append(re.sub(r"\{([^{}]*)\}", one, text[m.end():j - 1]))
            out.append("}")
            pos = j
        out.append(text[pos:])
        text = "".join(out)
    return text


def _blank_xml_elements(data: bytes, tags, value: bytes = b"") -> bytes:
    for tag in tags:
        pat = re.compile(rb"(<" + tag + rb"\b[^>]*>)(.*?)(</" + tag + rb">)", re.S | re.I)
        data = pat.sub(lambda m: m.group(1) + value + m.group(3), data)
    return data


_RELS_ENTRY_RE = re.compile(rb"<Relationship\b[^>]*/>")
_CONTENT_TYPE_OVERRIDE_RE = re.compile(rb"<Override\b[^>]*/>")


def _rels_part_base_dir(name: str) -> str:
    """The directory a `.rels` part's relative targets resolve against.

    `_rels/.rels` targets are package-absolute; `word/_rels/document.xml.rels`
    targets resolve inside `word/` (the part's own `_rels` directory's parent).
    """
    head, _sep, _tail = name.rpartition("_rels/")
    return head


def _prune_dropped_part_references(payload: bytes, name: str, dropped: set,
                                   notes: list) -> bytes:
    """Drop the relationships and content-type Overrides that name a removed part.

    A sanitizer that deletes a part but leaves the package's pointers at it
    hands the judge a package Word answers with "unreadable content"/repair: an
    internal relationship whose Target is not in the archive (and an Override
    for a part that does not exist) is an OPC integrity violation. The
    pointer-free `[Content_Types].xml` Default entries stay: a Default for an
    extension with no part is legal.
    """
    low = name.lower()
    if not dropped:
        return payload
    if low == "[content_types].xml":
        def _override(m):
            pm = re.search(rb'PartName="([^"]*)"', m.group(0))
            part = pm.group(1).decode("utf-8", "replace").lstrip("/") if pm else ""
            if part and part.lower() in dropped:
                notes.append(f"dropped the [Content_Types].xml Override for {part}")
                return b""
            return m.group(0)
        return _CONTENT_TYPE_OVERRIDE_RE.sub(_override, payload)
    if not low.endswith(".rels"):
        return payload
    base_dir = _rels_part_base_dir(low)

    def _rel(m):
        el = m.group(0)
        tm = re.search(rb'TargetMode="([^"]*)"', el)
        if tm and tm.group(1).lower() == b"external":
            return el
        t = re.search(rb'Target="([^"]*)"', el)
        if not t:
            return el
        target = t.group(1).decode("utf-8", "replace")
        resolved = posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")
        if resolved.lower() in dropped:
            notes.append(f"dropped the {name} relationship to the removed part {resolved}")
            return b""
        return el
    return _RELS_ENTRY_RE.sub(_rel, payload)


def _sanitize_ooxml_bytes(data: bytes) -> tuple:
    """(bytes, notes): strip provenance metadata and CANONICALIZE the archive.

    A judge must see submission CONTENT only. This removes, in order:

      * the archive fingerprint -- every entry is re-written in sorted order with
        one compression method, one timestamp, no extra field/comment and a fixed
        external attribute, so "produced by Word" vs "re-written by a script"
        (or by the pipeline's own formatter) is not observable;
      * Word's per-save edit metadata -- `w:rsid*` attributes and the
        `<w:rsids>` block, `w14:paraId`/`w14:textId` and the durable comment ids
        (`w16cid:durableId`), `w:proofErr` spell/grammar markers and
        `w:lastRenderedPageBreak` caches: these persist across saves and would
        let a judge correlate or date versions;
      * tracked changes -- `w:ins` is unwrapped and `w:del`/`w:delText`,
        `w:*PrChange`, `w:cellIns`/`w:cellDel`/`w:cellMerge` and move markers are
        dropped, so the view is the ACCEPTED document (whether a package carries
        revision marks is not a scoring input);
      * document properties -- author/lastModifiedBy/title/subject/description,
        revision number, application/company/manager/template, the Word
        statistics block (stale word/page counts reveal an edit after the last
        Word save) and the thumbnail part (together with the package
        relationship and any content-type Override that named it: a dangling
        internal relationship is a package Word answers with "unreadable
        content"/repair);
      * settings.xml edit state -- `w:proofState`, `w:attachedTemplate`,
        `w:docVars` and `w:trackChanges`;
      * `customXml/**` payloads (a generic metadata carrier) are blanked while
        the parts stay present so the package keeps opening;
      * the pipeline's own hand-off marker prefix is neutralised in text (the
        payload the author must fill in is untouched): a judge cannot tell that
        a package passed through the revision pipeline from the marker syntax.
    """
    notes = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zin:
            items = [(i.filename, zin.read(i.filename)) for i in zin.infolist()]
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError,
            NotImplementedError) as e:                            # noqa: BLE001
        return data, [f"not a readable OOXML zip ({e}); metadata left as is"]
    stripped = 0
    accepted = 0
    fixed_date = VIEW_FIXED_DATE.encode()

    def _accept_changes(payload: bytes) -> bytes:
        """Drop revision marks / edit ids; return the accepted document XML."""
        nonlocal accepted
        new = re.sub(rb"<w:rsids\b[^>]*>.*?</w:rsids>", b"", payload, flags=re.S)
        new = re.sub(rb"<w:rsids\b[^>]*/>", b"", new)
        new = re.sub(rb"\s(?:[\w]+:)?(?:rsid\w*|paraId|textId|durableId)=\"[^\"]*\"", b"", new)
        new = re.sub(rb"<w:proofErr\b[^>]*/>", b"", new)
        new = re.sub(rb"<w:lastRenderedPageBreak\b[^>]*/>", b"", new)
        new = re.sub(rb"<w:proofState\b[^>]*/>", b"", new)
        new = re.sub(rb"<w:attachedTemplate\b[^>]*/>", b"", new)
        new = re.sub(rb"<w:docVars\b[^>]*>.*?</w:docVars>", b"", new, flags=re.S)
        new = re.sub(rb"<w:trackChanges\b[^>]*/>", b"", new)
        def _drop_nested(tag: bytes) -> None:
            """Remove a nested revision wrapper innermost-first.

            A single non-greedy pass pairs the OUTER open with the INNER close
            and leaves the rest of the outer element (including its close tag)
            behind: text that should have been deleted is resurrected and the
            XML can stop being well-formed. Repeat on the innermost match
            until the tag is gone. A SELF-CLOSING mark (`<w:del .../>`) is
            removed on its own and never consumes the enclosing element's close
            tag, which would leave the outer mark open.
            """
            nonlocal new
            pat = re.compile(
                rb"<w:" + tag + rb"\b[^>]*/>"
                rb"|<w:" + tag + rb"\b[^>]*>(?:(?!<w:" + tag
                + rb"\b(?![^>]*/>)).)*?</w:" + tag + rb">", re.S)
            for _ in range(64):
                stripped = pat.sub(b"", new)
                if stripped == new:
                    return
                new = stripped

        _drop_nested(b"del")
        _drop_nested(b"cellDel")
        _drop_nested(b"moveFrom")
        new = re.sub(rb"<w:del\b[^>]*/>", b"", new)
        new = re.sub(rb"<w:delText\b[^>]*>.*?</w:delText>", b"", new, flags=re.S)
        new = re.sub(rb"<w:(rPrChange|pPrChange|tblPrChange|trPrChange|tcPrChange|"
                     rb"sectPrChange|numberingChange)\b[^>]*>.*?</w:\1>", b"", new, flags=re.S)
        new = re.sub(rb"<w:(cellIns|cellDel|cellMerge|moveFrom)\b[^>]*>.*?</w:\1>", b"",
                     new, flags=re.S)
        new = re.sub(rb"<w:(?:cellIns|cellDel|cellMerge|moveFrom)\b[^>]*/>", b"", new)
        new = re.sub(rb"<w:moveTo\b[^>]*>(.*?)</w:moveTo>", rb"\1", new, flags=re.S)
        # Word nests `w:ins` inside `w:ins` (a later insertion inside an
        # earlier one). One non-greedy pass pairs the OUTER open tag with the
        # INNER close tag, so it unwraps the outer mark and leaves the inner
        # one live -- the view is then not the accepted document the docstring
        # (and the judge's read) promises. Re-apply until no `w:ins` survives;
        # each pass removes at least one mark, so this terminates.
        for _ in range(64):
            unwrapped = re.sub(rb"<w:ins\b[^>]*>(.*?)</w:ins>", rb"\1", new, flags=re.S)
            if unwrapped == new:
                break
            new = unwrapped
        if new != payload:
            accepted += 1
        return new

    # Parts this sanitizer REMOVES are known before the archive is rewritten, so
    # every pointer at them can be pruned in the same pass: a `.rels` Target or
    # a `[Content_Types].xml` Override that names a part no longer present makes
    # the view a corrupt OPC package (Word: "unreadable content"/repair).
    dropped = {name.lower() for name, _payload in items
               if name.lower().startswith("docprops/thumbnail.")}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, payload in sorted(items, key=lambda kv: kv[0]):
            low = name.lower()
            if low in dropped:
                stripped += 1
                continue                              # a stale rendered page + Word setting
            payload = _prune_dropped_part_references(payload, name, dropped, notes)
            if low == "docprops/core.xml":
                payload = _blank_xml_elements(payload, (b"dc:creator", b"cp:lastModifiedBy"),
                                              b"author")
                payload = _blank_xml_elements(payload, (b"dc:title", b"dc:subject",
                                                        b"dc:description", b"cp:keywords",
                                                        b"cp:category", b"cp:contentStatus"))
                payload = _blank_xml_elements(payload, (b"dcterms:created", b"dcterms:modified"),
                                              fixed_date)
                payload = _blank_xml_elements(payload, (b"cp:revision",), b"1")
                stripped += 1
            elif low == "docprops/app.xml":
                payload = _blank_xml_elements(payload, (b"Company", b"Manager", b"Application",
                                                        b"AppVersion", b"Template"))
                payload = _blank_xml_elements(payload, (b"TotalTime", b"LastPrinted"), b"0")
                # Word's cached statistics go stale the moment a script rewrites
                # the document -- a judge could read "this was edited after the
                # last Word save" straight out of them.
                payload = _blank_xml_elements(
                    payload, (b"Pages", b"Words", b"Characters", b"CharactersWithSpaces",
                              b"Lines", b"Paragraphs", b"Slides", b"Notes",
                              b"HiddenSlides", b"MMClips", b"HyperlinksChanged",
                              b"LinksUpToDate", b"SharedDoc", b"ScaleCrop", b"DocSecurity"),
                    b"0")
                stripped += 1
            elif low == "docprops/custom.xml":
                payload = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           b'<Properties xmlns="http://schemas.openxmlformats.org/'
                           b'officeDocument/2006/custom-properties"/>')
                stripped += 1
            elif low.startswith("customxml/") and low.endswith(".xml"):
                payload = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           b"<root/>")
                stripped += 1
            elif low.startswith(("word/", "xl/", "ppt/")) and low.endswith(".xml"):
                payload = _accept_changes(payload)
                new = re.sub(rb'((?:w|w15|w16):(?:author|initials))="[^"]*"', rb'\1="author"',
                             payload)
                new = re.sub(rb"((?:w|w15|w16):date)=\"[^\"]*\"",
                             rb"\1=" + b'"' + fixed_date + b'"', new)
                if new != payload:
                    stripped += 1
                payload = new
                # the pipeline's own hand-off marker prefix must not identify a
                # package as "revised by the pipeline"; the payload stays.
                payload = payload.replace(PLACEHOLDER_TOKEN.encode(), b"[TO BE COMPLETED")
            elif low.endswith((".xml", ".rels")):
                payload = _accept_changes(payload)
                if low.endswith(".rels"):
                    # A relationship TARGET that names an absolute local path
                    # (the venue's Word template attaches
                    # `file:///C:\Users\<someone>\...\*.dotx`, and a package may
                    # link a local file in any other way): the blind view must
                    # not carry a machine/user name, and no judge can open the
                    # path anyway. The relationship itself stays -- an element
                    # may reference it, and a dropped relationship is a
                    # dangling `r:id` -- so only the target is neutralized, and
                    # only inside a `.rels` part (a document's own text may
                    # legitimately quote such an attribute).
                    new = re.sub(
                        rb'(Target=")(?:file:|[A-Za-z]:[\\/]|\\\\[^"/]*[\\/])[^"]*"',
                        rb'\1about:blank"', payload)
                    if new != payload:
                        stripped += 1
                    payload = new
            info = zipfile.ZipInfo(name, date_time=VIEW_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            info.internal_attr = 0
            zout.writestr(info, payload)
    if not stripped:
        notes.append("no OOXML property part was found to sanitize")
    if accepted:
        notes.append(f"revision marks accepted in {accepted} part(s) "
                     f"(the view is the accepted document)")
    return out.getvalue(), notes


def _blank_pdf_value(value: bytes) -> bytes:
    """A same-length neutral PDF value (offsets must not move)."""
    if value.startswith(b"(") and value.endswith(b")"):
        return b"(" + b" " * max(0, len(value) - 2) + b")"
    if value.startswith(b"<") and value.endswith(b">"):
        return b"<" + b"0" * max(0, len(value) - 2) + b">"
    return value


def _blank_xmp_fields(stream: bytes) -> bytes:
    for tag in (b"rdf:li", b"xmp:CreateDate", b"xmp:ModifyDate", b"xmp:MetadataDate",
                b"xmp:CreatorTool", b"pdf:Producer", b"dc:title", b"dc:description"):
        pat = re.compile(rb"(<" + tag + rb"\b[^>]*>)(.*?)(</" + tag + rb">)", re.S)
        stream = pat.sub(lambda m: m.group(1) + b" " * len(m.group(2)) + m.group(3), stream)
    return stream


def _sanitize_pdf_bytes(data: bytes) -> tuple:
    """(bytes, notes): blank PDF Info/XMP/ID values in place (equal length)."""
    notes = []
    changed = 0
    # A linearized PDF carries a trailer at the HEAD and the real /Info in the
    # FINAL trailer: `re.search` blanked only the first, leaving the author and
    # title visible in the judge view.
    _info_ids = []
    for m in re.finditer(rb"trailer\b.*?/Info\s+(\d+)\s+0\s+R", data, re.S):
        if m.group(1) not in _info_ids:
            _info_ids.append(m.group(1))
    if _info_ids:
        for _iid in _info_ids:
            om = re.search(rb"(?m)^\s*" + _iid + rb"\s+0\s+obj.*?endobj", data, re.S)
            if not om:
                notes.append("PDF /Info object is compressed/unparsable; its metadata was "
                             "left as is")
                continue
            obj = om.group(0)
            new_obj = obj
            for key in (b"Author", b"Creator", b"Producer", b"Title", b"Subject", b"Keywords",
                        b"CreationDate", b"ModDate", b"Trapped", b"GTS_PDFXVersion"):
                pat = re.compile(rb"(/" + key + rb"\s*)(\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>)")
                new_obj = pat.sub(lambda mm: mm.group(1) + _blank_pdf_value(mm.group(2)), new_obj)
            if new_obj != obj:
                data = data[:om.start()] + new_obj + data[om.end():]
                changed += 1
    else:
        notes.append("no uncompressed PDF /Info dictionary found; metadata was left as is")
    # /ID is in the trailer/xref at the END of the file, but a LINEARIZED PDF
    # also carries its ID in the first-page hint at the head. Blank every /ID
    # array outside a stream body (a literal in a content stream is text, not
    # the document ID), so the blind view cannot be correlated by file ID.
    # Both the hex `<...>` and the string `(...)` spellings are accepted.
    stream_spans = [(m.start(), m.end())
                    for m in re.finditer(rb"stream\r?\n.*?endstream", data, re.S)]

    def _not_in_stream(pos: int) -> bool:
        return not any(a <= pos < b for a, b in stream_spans)

    def _blank_id(mm):
        if not _not_in_stream(mm.start()):
            return mm.group(0)
        return (mm.group(1) + _blank_pdf_value(mm.group(2)) + mm.group(3)
                + _blank_pdf_value(mm.group(4)))

    new_data = re.sub(
        rb"(/ID\s*\[\s*)(<[0-9A-Fa-f\s]*>|\((?:\\.|[^()\\])*\))"
        rb"(\s*)(<[0-9A-Fa-f\s]*>|\((?:\\.|[^()\\])*\))",
        _blank_id, data)
    if new_data != data:
        data = new_data
        changed += 1
    xm = re.search(rb"/Metadata\s+(\d+)\s+0\s+R", data)
    if xm:
        om = re.search(rb"(?m)^\s*" + xm.group(1) + rb"\s+0\s+obj.*?endobj", data, re.S)
        if om and b"/Filter" not in om.group(0):
            block = om.group(0)
            sm = re.search(rb"(stream\r?\n)(.*?)(endstream)", block, re.S)
            if sm and _blank_xmp_fields(sm.group(2)) != sm.group(2):
                new_block = (block[:sm.start(2)] + _blank_xmp_fields(sm.group(2))
                             + block[sm.end(2):])
                data = data[:om.start()] + new_block + data[om.end():]
                changed += 1
    if not changed:
        notes.append("no PDF metadata value could be blanked")
    return data, notes


def _transform_view_file(old_rel: str, src: Path, file_map: dict):
    """(transformed bytes | None, notes) for one view file (None = copy as is)."""
    ext = src.suffix.lower()
    if _view_is_text(old_rel):
        raw = src.read_bytes()
        text = raw.decode("utf-8", "surrogateescape")
        text = _rewrite_view_references(text, old_rel, file_map[old_rel], file_map)
        # The pipeline's hand-off marker prefix must not identify a package as
        # "revised by the pipeline"; the payload the author fills in stays.
        text = text.replace(PLACEHOLDER_TOKEN, "[TO BE COMPLETED")
        return text.encode("utf-8", "surrogateescape"), []
    if ext in VIEW_OOXML_EXTS or ext in VIEW_PDF_EXTS:
        raw = src.read_bytes()
        # The sanitized bytes do not depend on the view seed: the same figure or
        # document appears in many views, so cache by content (bounded).
        kind = "ooxml" if ext in VIEW_OOXML_EXTS else "pdf"
        key = (kind, hashlib.sha256(raw).hexdigest())
        with _VIEW_EXPECT_LOCK:
            hit = _VIEW_SANITIZE_CACHE.get(key)
        if hit is not None:
            return hit[0], hit[1]
        data, notes = (_sanitize_ooxml_bytes(raw) if kind == "ooxml"
                       else _sanitize_pdf_bytes(raw))
        if (len(raw) <= _VIEW_SANITIZE_MAX_FILE
                and len(_VIEW_SANITIZE_CACHE) < _VIEW_SANITIZE_MAX_ENTRIES
                and _VIEW_SANITIZE_TOTAL["bytes"] + len(data) <= _VIEW_SANITIZE_MAX_TOTAL):
            with _VIEW_EXPECT_LOCK:
                _VIEW_SANITIZE_CACHE[key] = (data, notes)
                _VIEW_SANITIZE_TOTAL["bytes"] += len(data)
        return data, notes
    return None, []


def expected_view_digest(ctx: Ctx, r: int, vid: str, view_seed: str) -> list:
    """The content multiset a judge view of `vid` with `view_seed` must have.

    The view is NOT byte-identical to its source corpus: references are rewritten
    to the anonymous names and document metadata is sanitized. This computes the
    expected digests with exactly the same transform, and caches the result keyed
    by the SOURCE content (so a corpus change is still detected).
    """
    files = corpus_files_for_view(ctx, r, vid)
    src_key = tuple(sorted(sha256_files([p for _rel, p in files])))
    key = (int(r), str(vid), str(view_seed), src_key)
    with _VIEW_EXPECT_LOCK:
        hit = _VIEW_EXPECT_CACHE.get(key)
    if hit is not None:
        return hit
    _dir_names, file_map = _view_layout(files, r, vid, view_seed)
    digs = []
    for old_rel, src in files:
        data, _notes = _transform_view_file(old_rel, src, file_map)
        digs.append(hashlib.sha256(data).hexdigest() if data is not None else sha256_file(src))
    digs = sorted(digs)
    with _VIEW_EXPECT_LOCK:
        if len(_VIEW_EXPECT_CACHE) > 5000:
            _VIEW_EXPECT_CACHE.clear()
        _VIEW_EXPECT_CACHE[key] = digs
    return digs


def build_judge_view(ctx: Ctx, r: int, vid: str, dst: Path, stamp: float,
                     view_seed: str) -> None:
    r"""Materialize a version as an ANONYMOUS judge view.

    What a judge can see must not carry information that could bias a
    comparison, so this is deliberately NOT a copy of the package's own names:

      * ONLY SUBMISSION CONTENT IS IN THE VIEW: the version's corpus minus its
        revision auxiliaries, its bookkeeping/report files, its process scratch
        and every derived output whose editable source is in the package
        (corpus_dir_view_files() / _is_view_excluded_file()), so neither the
        file SET (a package an agent went over loses the by-products the
        untouched original keeps) nor a file's CONTENT (a build log names
        absolute paths and the build date) can say whether -- or by what -- a
        package was worked on. The judge gets the SOURCES (a .bib rather than
        its .bbl, a .docx/.tex rather than its PDF) and can compile or render
        them itself;
      * every directory becomes "d01", "d02", ... and every file becomes
        "f0001<ext>", "f0002<ext>", ... -- the assignment is a salted random
        permutation PER VIEW, so the same document gets a DIFFERENT anonymous
        name in the target and in every opponent (no cross-view correlation),
        while the file extension (the file type the judge needs to read it) and
        the tree SHAPE (which files sit together) are preserved;
      * REFERENCES ARE REWRITTEN: text files that point at other files
        (\input/\include/\includegraphics/\addbibresource/\bibliography, build
        scripts, \graphicspath entries) are rewritten to the anonymous names, so
        a LaTeX/Word package stays COMPILABLE inside the sandbox (the relative
        tree shape is preserved);
      * METADATA IS SANITIZED: OOXML (docx/xlsx/pptx) core/app/custom
        properties and tracked-change/comment author+date attributes are
        neutralized and every zip entry gets one fixed timestamp; a PDF's
        /Info, /ID and uncompressed XMP values are blanked IN PLACE (equal
        length, so the xref stays valid). Where a PDF stores its metadata in a
        compressed/unparsable object, the sanitizer says so and leaves it; the
        judge prompt still forbids using any metadata as evidence;
      * no source mtimes, modes, ownership, ACLs, xattrs or other attributes
        survive (files are written by content only);
      * the whole view is then stamped with one mtime and one mode (0o644 for
        files, 0o755 for directories), so no timestamp or permission bit can
        order the packages or reveal provenance.

    Files that NO judge sees (sandboxes, pins, published winners, integration
    views) keep their names, timestamps, modes and attributes -- see
    build_corpus_dir.
    """
    files = corpus_files_for_view(ctx, r, vid)
    _dir_names, file_map = _view_layout(files, r, vid, view_seed)
    dst.mkdir(parents=True, exist_ok=True)
    for rel, src in files:
        out = dst / file_map[rel]
        out.parent.mkdir(parents=True, exist_ok=True)
        data, _notes = _transform_view_file(rel, src, file_map)
        if data is None:
            shutil.copyfile(src, out)                 # content only: no metadata
        else:
            out.write_bytes(data)
        try:
            os.chmod(out, 0o644)
        except OSError:
            pass
    for sub in [dst, *sorted(dst.rglob("*"))]:
        if sub.is_dir():
            try:
                os.chmod(sub, 0o755)
            except OSError:
                pass
    stamp_tree(dst, stamp)


def ensure_judge_view(ctx: Ctx, r: int, vid: str, dst: Path, stamp: float,
                      view_seed: str) -> bool:
    """build_judge_view() with the partial-copy repair of ensure_copy().

    A judge view is compared by the CONTENT MULTISET of its TRANSFORMED files
    (anonymous names, rewritten references, sanitized metadata) and rebuilt when
    it does not match the current corpus.
    """
    want = expected_view_digest(ctx, r, vid, view_seed)
    if dst.is_dir() and judge_view_digest(dst) == want:
        return False
    if dst.exists():
        rmtree_force(dst, ignore_errors=True)
    build_judge_view(ctx, r, vid, dst, stamp, view_seed)
    return True


def judge_view_seed_for(ctx: Ctx, r: int, target_vid, judge_index) -> str:
    """The per-session view seed, reconstructible from a judge run record.

    `materialize_judges` derives it as salt|opaque-token|judge-index; storing
    nothing extra is enough for the postcheck and the freshness revalidation to
    recompute the expected (transformed) digests of every view.
    """
    return (f"{judge_salt_of(ctx)}|{judge_token_for(ctx, r, target_vid)}|"
            f"{int(judge_index)}")


def sample_labels(r: int, vid: str, j: int, k: int, salt: str = "") -> list:
    """Randomized opponent labels for one judge session.

    Seeded from (round, target version, judge index) AND the per-root secret, so
    a re-run of the same root is reproducible while the label -> version map
    cannot be recomputed inside the sandbox. Round, version id and judge index
    are all small, enumerable values that the judge is partly TOLD (the prompt
    states the round and the judge index), so without the salt a judge that
    knows this pipeline could brute-force which label is the previous champion
    or the later arm. The salt is the same per-root secret that keeps the
    session token opaque (see judge_token_for); the map itself still lives only
    in the run record.
    """
    seed = int(hashlib.sha256(f"paper-round-field|{r}|{vid}|{j}|{salt}".encode("utf-8"))
               .hexdigest()[:16], 16)
    labels = [f"v{i}" for i in range(1, k + 1)]
    random.Random(seed).shuffle(labels)
    return labels


def freshness_vid(rec: dict):
    """The round-local version id a run produces (None for review/judge runs).

    The run record carries `produces` for every content-producing arm, which is
    what keeps the mapping correct for any M/N plan instead of re-deriving it
    from the run id.
    """
    if rec.get("kind") == "a1":
        return A1_ID
    vid = rec.get("produces")
    if vid and is_fresh_vid(vid):
        return str(vid)
    legacy = _vid_from_run_id(rec.get("id"))
    if legacy:
        return legacy
    return None


def _vid_from_run_id(run_id) -> str:
    """The round-local version a run id names ("r2_a3_revise" -> "a3"), or None."""
    m = re.match(r"^r\d+_([a-z]+\d+?)(?:_revise)?$", str(run_id or ""))
    if m and is_fresh_vid(m.group(1)) and m.group(1) != A1_ID:
        return m.group(1)
    return None


# =====================================================================
# SANDBOX MATERIALIZATION (staged + idempotent)
# =====================================================================

def stash_logs(sb: Path, logs_dir: Path, rid: str, attempt: int = None) -> list:
    """Preserve agent logs before a sandbox is removed (rebuild/retry).

    Returns the archived paths, so the attempt record can POINT at the
    transcript of the attempt it belongs to: a bare `<run>._agent.log` is unique
    but does not say which attempt wrote it (the 2026-09-22 root kept attempt 1's
    15 MB transcript as `r1_review._agent.log` with nothing referring to it).
    """
    moved = []
    if sb.is_dir():
        logs_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(sb.glob("_agent.log*")):
            try:
                # A run can be retried several times per second-resolution stamp;
                # a fixed name would overwrite the earlier attempt's log, which is
                # the only evidence of what that attempt actually did.
                name = (f"{rid}.attempt-{int(attempt)}.{f.name}" if attempt
                        else f"{rid}.{f.name}")
                dest = unique_path(logs_dir / name)
                shutil.move(str(f), str(dest))
                moved.append(dest)
            except OSError:
                pass
    return moved


def bump_attempt(rec: dict) -> int:
    """Count one attempt: the per-invocation counter AND the monotone total.

    `attempts` is what the retry policy and the status table's ATT column use,
    and `retry` resets it to 0; `attempts_done` never goes back, so the attempt
    that wrote a sandbox keeps its number (and therefore its archive directory
    and its log name) across a reset.
    """
    rec["attempts"] = int(rec.get("attempts") or 0) + 1
    rec["attempts_done"] = int(rec.get("attempts_done") or 0) + 1
    return rec["attempts_done"]


def attempt_number(rec: dict) -> int:
    """The 1-based number of the attempt the record's live sandbox belongs to."""
    try:
        return max(1, int(rec.get("attempts_done") or 0))
    except (TypeError, ValueError):
        return 1


def next_attempt_number(rec: dict) -> int:
    """The number the NEXT attempt of this run will carry (see `attempt_number`)."""
    try:
        return max(1, int(rec.get("attempts_done") or 0) + 1)
    except (TypeError, ValueError):
        return 1


def sandbox_attempts(rec: dict) -> list:
    """The attempt numbers whose work lives in the CURRENT sandbox of `rec`.

    Every entry whose sandbox was already kept starts a new group, so with the
    scoped repair in play a kept sandbox may hold a stage attempt AND the repair
    session that followed it in the same directory (both are attempts of the run).
    """
    out = []
    for e in rec.get("attempts_log") or []:
        if e.get("sandbox_moved_to") or (e.get("archive") and e.get("archived")):
            out = []
            continue
        if e.get("attempt"):
            out.append(int(e["attempt"]))
    return out


def failed_sandbox_dir(ctx: Ctx, rec: dict, attempt: int = None) -> Path:
    """`runs/<run>_try<N>_failed/` -- `N` counts the run's FAILED TRIES (1-based).

    The number is the failure ordinal, not the attempt ordinal: the operator's
    handle on the evidence is "the sandbox of try 1 / try 2", and the attempts
    inside a kept sandbox (a stage attempt plus the repair session that ran in it)
    are recorded in its `record.json` and in `attempts_log`.
    """
    rid = str(rec.get("id"))
    n = int(attempt or 0) or (len(list(ctx.runs_dir.glob(f"{rid}_try*_failed"))) + 1)
    return ctx.runs_dir / (rid + FAILED_SUFFIX_FMT.format(n=n))


def _attempt_messages(msgs) -> list:
    """The COMPLETE message list of one attempt, for the run record.

    No message-count cap: every error and every warning of every attempt (the
    first one, the first retry, the second retry, ...) is recorded, because a
    truncated list is how two of attempt 1's three problems disappeared on the
    2026-09-22 root. Only a pathological total size is cut (512 KB per list), and
    then the note says exactly how many messages were left out -- they are still
    in the attempt's archive and in the run log.
    """
    msgs = [str(m) for m in list(msgs or [])]
    out, used = [], 0
    for i, m in enumerate(msgs):
        text = m[:ATTEMPT_MESSAGE_LIMIT]
        if used + len(text) > ATTEMPT_LIST_BYTES_LIMIT:
            out.append(f"... {len(msgs) - i} further message(s) were NOT copied into "
                       f"state.json (this attempt's list exceeds "
                       f"{ATTEMPT_LIST_BYTES_LIMIT // 1024} KiB); the complete list is in the "
                       f"attempt's archived record.json and in the run log under reports/")
            break
        out.append(text)
        used += len(text)
    return out


def record_attempt(ctx: Ctx, rec: dict, ok: bool, errors=None, warnings=None,
                   source: str = "postcheck") -> dict:
    """Append ONE attempt's diagnostics to the run record (never overwritten).

    `postcheck`/`last_error` describe the LAST attempt only, so a run that failed
    twice reported one failure and lost the other. This is the history: which
    gates fired in which attempt, in order, with the timing, the decision-artifact
    quality report, the marker's own summary, and where that attempt's artifacts
    and transcript were kept.
    """
    entry = {
        "attempt": attempt_number(rec),
        "source": source,
        # The ATTEMPT's own start, not the run's first one: `rec["started"]` is
        # set once and kept, so a run retried an hour later used to report the
        # original start for every attempt.
        "started": rec.get("last_attempt_started") or rec.get("started"),
        "finished": utcnow(),
        "duration": rec.get("last_duration"),
        "status": rec.get("status"),
        "ok": bool(ok),
        # The TRUE totals, next to the (complete, but size-capped) lists: an
        # operator can see at a glance how many problems an attempt carried even
        # if a pathological list was cut.
        "n_errors": len(list(errors or [])),
        "n_warnings": len(list(warnings or [])),
        "errors": _attempt_messages(errors),
        "warnings": _attempt_messages(warnings),
        "artifact_quality": rec.get("artifact_quality") or None,
        "summary": rec.get("summary") or None,
        "sandbox": rec.get("sandbox"),
        "prompt": PROMPT_FILE,
        # Which CLI session produced this attempt (used by the CONTINUATION).
        "agent_session_id": rec.get("agent_session_id"),
        "checked_at": (rec.get("postcheck") or {}).get("checked_at"),
        # Filled in when the failed sandbox is actually kept (moved): the attempt
        # record must not claim a path that does not exist yet (`sandbox_attempts`
        # reads this field to tell which attempts share the live sandbox).
        "archive": None,
        "sandbox_moved_to": None,
        "agent_log": None,
    }
    history = rec.setdefault("attempts_log", [])
    if history and history[-1].get("attempt") == entry["attempt"]:
        history[-1] = entry                  # the same attempt, re-postchecked
    else:
        history.append(entry)
    if len(history) > ATTEMPTS_LOG_LIMIT:
        del history[:-ATTEMPTS_LOG_LIMIT]
    return entry


def move_failed_sandbox(ctx: Ctx, rec: dict) -> Path:
    """Rename a failed attempt's WHOLE sandbox to `runs/<run>_try<N>_failed/`.

    Called before a retry (and when a run fails for good): the retry then builds a
    fresh `runs/<run>/`, and the failed attempt keeps everything it produced --
    the deliverables exactly as the postcheck judged them, the seeded tables, the
    corpus copies, the transcript and a self-describing `record.json`. A rename is
    O(1) on one filesystem and costs no second copy; a cross-device or busy target
    falls back to a copy, and any failure is reported as a warning (never fatal --
    the attempt's diagnostics live in state.json -> attempts_log regardless).
    """
    n = attempt_number(rec)
    sb = ctx.sandbox_of(rec)
    inside = sandbox_attempts(rec) or [n]
    dest = failed_sandbox_dir(ctx, rec)
    history = rec.get("attempts_log") or []
    entry = next((e for e in reversed(history) if e.get("attempt") == n), None)
    record = dict(entry or {"attempt": n, "ok": False, "errors": [], "warnings": []})
    record.update({"run_id": rec.get("id"), "kind": rec.get("kind"), "round": rec.get("round"),
                   "sandbox": str(sb.relative_to(ctx.root)) if sb.is_dir() else None,
                   "attempts_in_sandbox": inside,
                   "moved_at": utcnow(), "moved_to": str(dest.relative_to(ctx.root))})
    if not sb.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        write_json_atomic(dest / "record.json", record)
    else:
        if dest.exists():
            dest = unique_path(dest)
        # Record the path the rename will ACTUALLY use before writing
        # record.json: unique_path() may have renamed it, and the post-write
        # update below used to reach only the in-memory dict, leaving the
        # archived record pointing at the pre-collision name.
        record["moved_to"] = str(dest.relative_to(ctx.root))
        try:
            sb.rename(dest)
        except OSError:
            shutil.copytree(sb, dest)
            rmtree_force(sb, ignore_errors=True)
        write_json_atomic(dest / "record.json", record)
    if entry is not None:
        entry["archived"] = True
        entry["archive"] = str(dest.relative_to(ctx.root))
        entry["sandbox_moved_to"] = str(dest.relative_to(ctx.root))
        log = dest / "_agent.log"
        if log.is_file():
            entry["agent_log"] = str(log.relative_to(ctx.root))
    else:
        rec.setdefault("attempts_log", []).append(record)
    ctx.log("failed-sandbox-moved", rec.get("id"),
            f"attempt {n}: {dest.relative_to(ctx.root)}")
    print(f"  [keep] {rec['id']}: failed try {dest.name.rsplit('_try', 1)[-1].split('_')[0]}'s "
          f"sandbox (attempt(s) {', '.join(str(a) for a in inside)}) is kept at "
          f"{dest.relative_to(ctx.root)}/ -- deliverables, transcript and record.json")
    return dest


def keep_failed_sandboxes(ctx: Ctx, manual: bool = False) -> list:
    """Rename every still-failed run's sandbox to `runs/<run>_try<N>_failed/`.

    Called when an invocation ends with failures: the retry path already keeps the
    sandbox it is about to rebuild (`move_failed_sandbox`), and this covers the
    run that failed for good -- so `runs/<run>/` never lingers as an
    indistinguishable mix of attempts, and `runs/<run>_try<N>_failed/` always
    carries the deliverables exactly as the postcheck judged them.

    Manual mode is exempt: the operator owns that sandbox, the flow re-issues its
    prompt, and `move_failed_sandbox` would take the prompt away.
    """
    if manual:
        return []
    kept = []
    for rec in ctx.runs():
        if rec.get("status") != "failed":
            continue
        sb = ctx.sandbox_of(rec)
        if not sb.is_dir():
            continue
        try:
            kept.append(move_failed_sandbox(ctx, rec))
        except OSError as e:                                        # noqa: BLE001
            print(f"  [warn] {rec['id']}: could not keep the failed sandbox ({e}); its "
                  f"diagnostics stay in state.json's attempts_log")
    if kept:
        ctx.save_state()
    return kept


def attempt_history_lines(ctx: Ctx, indent: str = "  ", limit: int = 40) -> list:
    """One line per retained FAILED attempt, for `status` and DECISION_REPORT.md.

    The run table can only show the last attempt (that is what the run record's
    `postcheck`/`last_error` describe); this is the part that says what the other
    attempts died of and where their evidence is.
    """
    out = []
    for rec in ctx.runs():
        history = rec.get("attempts_log") or []
        failed = [h for h in history if not h.get("ok")]
        repairs = rec.get("repairs") or []
        if not failed and not repairs:
            continue
        out.append(f"{indent}{rec['id']} ({rec.get('kind')}, round {rec.get('round')}): "
                   f"{len(history)} attempt(s), {len(failed)} failed"
                   + (f", {len(repairs)} artifact repair(s)" if repairs else ""))
        for h in failed[:limit]:
            first = ((h.get("errors") or [None])[0]
                     or f"agent process failed: {h.get('last_error') or 'no message'}")
            # `source` already names a reconstruction when there is one; the flag is
            # only for records written by hand (see backfill_attempts-style repairs).
            origin = (" (reconstructed)" if h.get("reconstructed")
                      and "reconstruct" not in str(h.get("source") or "").lower() else "")
            out.append(f"{indent}  attempt {h.get('attempt')} "
                       f"({fmt_dur(h.get('duration'))}, "
                       f"{len(h.get('errors') or [])} problem(s), "
                       f"{h.get('source', 'postcheck')}{origin}): {first[:240]}")
            kept = h.get("sandbox_moved_to") or h.get("archive") or ""
            if h.get("archive_pruned"):
                out.append(f"{indent}    kept: {kept} (archive pruned; the attempt's record "
                           f"stays in state.json)")
            elif h.get("artifacts_lost"):
                # `agent_log` has been stored as a STRING since the record was
                # introduced (`entry["agent_log"] = str(log.relative_to(...))`);
                # `[0]` on it printed the first CHARACTER ("| transcript: r").
                # The sibling branch below already normalizes the older list
                # shape, so this one does the same.
                log = h.get("agent_log")
                if isinstance(log, list):        # older records stored a list
                    log = log[0] if log else None
                out.append(f"{indent}    artifacts: NOT preserved (the attempt's sandbox was "
                           f"rebuilt before the pipeline archived attempts)"
                           + (f" | transcript: {log}" if log else ""))
            elif kept and (ctx.root / kept).is_dir():
                log = h.get("agent_log")
                if isinstance(log, list):        # older records stored a list
                    log = log[0] if log else None
                out.append(f"{indent}    kept: {kept}/" + (f" | transcript: {log}" if log else ""))
            elif h.get("ok") is False:
                out.append(f"{indent}    the failed sandbox is renamed to "
                           f"runs/{rec.get('id')}_try<N>_failed/ when the retry rebuilds it")
        for rep in repairs[:limit]:
            out.append(f"{indent}  artifact repair (attempt {rep.get('attempt')}, "
                       f"{fmt_dur(rep.get('duration'))}): {len(rep.get('problems') or [])} "
                       f"decision-artifact problem(s) -> "
                       f"{'cleared' if rep.get('ok') else 'NOT cleared'}; changed: "
                       f"{', '.join(rep.get('changed') or []) or 'nothing'}")
            if rep.get("error"):
                out.append(f"{indent}    {str(rep['error'])[:240]}")
            if rep.get("transcript"):
                out.append(f"{indent}    transcript: {rep['transcript']}")
    return out


def archive_stale_marker(sb: Path, rid: str) -> None:
    """Move any pre-existing completion signal aside before a fresh attempt, so
    a crashed retry can never be scored on the previous attempt's marker.

    Both the agent marker and (for judge runs) scores.json are archived: a
    half-written sheet from an earlier attempt must not be able to masquerade
    as the new attempt's result.
    """
    logs = sb.parent / LOGS_DIRNAME
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for rel, tag in ((MARKER_FILE, "prev_marker"), (SCORES_FILE, "prev_scores")):
        p = sb / rel
        if not p.exists():
            continue
        logs.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(p), str(unique_path(logs / f"{rid}.{tag}.{stamp}.json")))
        except OSError:
            try:
                p.unlink()
            except OSError:
                pass


def materialize_a1(ctx: Ctx, r: int) -> dict:
    """(i) A1_r: a byte-identical copy of the pristine original (r=1) or of the
    previous round's pinned champion (r>1). No agent run."""
    rid = rid_a1(r)
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    base, nr = sb / "base", sb / PRISTINE_DIR
    src_id, src_dir = ORIGINAL_ID, working_original_dir(ctx)
    if r > 1:
        prev = ctx.round_rec(r - 1)
        pin = find_pin(ctx, prev.get("pin_id"))
        if pin is None:
            if prev.get("status") != "done":
                # `run --only R` can ask for a later round while an EARLIER round
                # is still pending. That is an unsatisfied dependency, not a
                # corrupt root: report it as such so the operator is told to run
                # the earlier round instead of "repair the upstream output".
                raise DepsNotMet(
                    f"round {r} needs round {r - 1}'s pinned champion, but round {r - 1} is "
                    f"{prev.get('status', 'pending')}; finish it first "
                    f"(e.g. `run --only {r - 1}`, or a plain `run`)")
            raise RuntimeError(f"cannot materialize round {r} base: round {r - 1} has no pinned "
                               f"champion though it is marked done (the pin record is missing; "
                               f"restore it from a state.json backup)")
        src_id, src_dir = pin["id"], pinned_docs_dir(ctx, pin)
    want = (working_original_digest(ctx) if src_id == ORIGINAL_ID
            else (find_pin(ctx, src_id) or {}).get("digest"))
    if (base.exists() and want
            and manifest_digest(manifest_for_sources([(base, "", ())])) != want):
        # An earlier round was re-run and its champion changed: a stale base copy
        # must never silently become this round's base (the digest would say one
        # thing and the documents another). The comparison uses the SAME corpus
        # rule as `want` and as the re-computation below -- comparing the
        # whole-tree digest here rebuilt an intact base on EVERY invocation as
        # soon as the package carried a bookkeeping-named file (the ledger or
        # CHANGELOG the corpus rule strips).
        rmtree_force(base)
    if not base.exists():
        copy_into(src_dir, base, root=ctx.root)
    # The pristine input is materialized with the read-only evidence areas
    # SYMLINKED to the root's canonical copy (see ensure_pristine_input); the
    # helper is idempotent and repairs a partial or tampered copy itself.
    ensure_pristine_input(ctx, nr)
    rec = ctx.register(rid, "a1", r, f"runs/{rid}", source_id=src_id)
    rec["inputs_manifest"] = {
        "base": hash_manifest(base, follow_dir_links=True),
        PRISTINE_DIR: hash_manifest(nr, follow_dir_links=True)}
    rec["corpus_digest"] = recompute_corpus_digest(ctx, r, A1_ID)
    rec["content_fingerprint"] = corpus_content_fingerprint(ctx, r, A1_ID)
    rec["base_source_digest"] = want
    if want and rec["corpus_digest"] != want:
        raise RuntimeError(f"A1_{r} base/ does not match its source {src_id!r} "
                           f"({rec['corpus_digest'][:12]} != {str(want)[:12]})")
    rec["status"] = "done"
    rec["started"] = rec.get("started") or utcnow()
    rec["finished"] = rec.get("finished") or utcnow()
    rec["last_error"] = None
    # No warning for "this base has no agent session": the round base IS a
    # byte-for-byte copy of its source by construction (kind "a1"), and saying so
    # in every root's state.json buries the warnings that do point at something.
    rec["postcheck"] = {"ok": True, "errors": [], "warnings": [], "checked_at": utcnow()}
    return rec


def _require_done(ctx: Ctx, rid: str, why: str) -> dict:
    rec = ctx.run(rid)
    if rec is None or rec.get("status") != "done":
        raise RuntimeError(f"refusing to materialize downstream sandbox: {why} "
                           f"({rid} is {(rec or {}).get('status', 'missing')})")
    return rec


def materialize_rewrite(ctx: Ctx, r: int, k: int) -> dict:
    """The k-th REWRITTEN candidate W<k>_r: base + non_revised/ + rewritten/.

    All M rewrites are staged FIRST in the round -- before the review -- because
    the order the round asks for is "create the rewritten candidates, add them
    to the pool, then review/revise and integrate". A rewrite sandbox consumes
    nothing but the round's own base, so retrying one never invalidates the
    review/revise arm, and retrying the review never invalidates a rewrite (see
    revalidate_round_inputs).
    """
    vid = rewrite_vid(k)
    rid = rid_for_fresh(r, vid)
    m, _n = round_counts(ctx, r)
    sb = ctx.runs_dir / rid
    a1 = ctx.run(rid_a1(r))
    if a1 is None or a1.get("status") != "done":
        raise RuntimeError(f"cannot materialize {rid}: the round's base {rid_a1(r)} is "
                           f"{(a1 or {}).get('status', 'missing')}")
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    extra_inputs = {}
    if journal_mode_of(ctx) in (JOURNAL_MODE_TRANSFER, JOURNAL_MODE_RESUBMIT):
        # A rewrite for a real submission attempt must answer the decision
        # letter: the concern ledger travels beside the corpus.
        fb = _journal_concern_source(ctx, r)
        ensure_copy(fb / "concerns", sb / "concerns")
        extra_inputs["concerns"] = hash_manifest(sb / "concerns")
        if (fb / "feedback").is_dir():
            ensure_copy(fb / "feedback", sb / "feedback")
            extra_inputs["feedback"] = hash_manifest(sb / "feedback", follow_dir_links=True)
    (sb / REWRITTEN_DIR).mkdir(exist_ok=True)
    stage_venue_template(ctx, sb)
    seed_template_visuals(ctx, sb)
    seed_evidence_pack(ctx, sb, sb / "base", "stage")
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        # write_text_atomic: the existence check above is the "already
        # materialized" marker, so a crash mid-write must never leave a
        # truncated PROMPT.md behind for a later invocation to trust.
        write_text_atomic(prompt, rewrite_prompt(sb, rid, r, index=int(k), total=m,
                                                caption_limit=caption_limit_of(ctx),
                                                zotero=zotero_mode_of(ctx),
                                                prior_failure=note,
                                                level=rewrite_level_of(k, m),
                                                venue=venue_profile_of(ctx),
                                                author_to_complete=author_to_complete_mode_of(ctx),
                                                journal_block=(journal_rewrite_block(ctx)
                                                               if journal_has_feedback(ctx)
                                                               and not journal_is_scoped(ctx)
                                                               else ""),
                                                venue_norm=venue_norm_for(ctx)))
    rec = ctx.register(rid, "rewrite", r, f"runs/{rid}", upstream_run_id=rid_a1(r),
                       source_id=A1_ID, produces=vid)
    rec["rewrite_level"] = rewrite_level_of(k, m)
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True)}
    rec["inputs_manifest"].update(extra_inputs)
    return rec


def materialize_review(ctx: Ctx, r: int, part: str = "a") -> dict:
    """(ii) Phase-1 sandbox: base/ + non_revised/ + prior_round/ (r>1) + review/ (OUT)."""
    rid = rid_review(r) if part == "a" else rid_review_b(r)
    sb = ctx.runs_dir / rid
    a1 = ctx.run(rid_a1(r))
    if a1 is None:
        raise RuntimeError(f"cannot materialize {rid}: {rid_a1(r)} does not exist")
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    if journal_has_feedback(ctx) and not journal_is_scoped(ctx):
        # The review reconciles the feedback ledger (a decision letter, or the
        # false-positive-filtered LLM review in `llm` mode): it travels beside
        # the corpus (never inside it). Staging only transfer/resubmit told an
        # llm-mode reviewer to read `concerns/` files that did not exist.
        fb = _journal_concern_source(ctx, r)
        ensure_copy(fb / "concerns", sb / "concerns")
        if (fb / "feedback").is_dir():
            ensure_copy(fb / "feedback", sb / "feedback")
    prior = prior_review_dir(ctx, r)
    inputs = {"base": hash_manifest(sb / "base"),
              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True)}
    if (sb / "feedback").is_dir():
        inputs["feedback"] = hash_manifest(sb / "feedback", follow_dir_links=True)
    if (sb / "concerns").is_dir():
        inputs["concerns"] = hash_manifest(sb / "concerns")
    if prior is not None:
        want_prior = {name: sha256_file(prior / name) for name in PRIOR_ROUND_FILES
                      if (prior / name).is_file()}
        if want_prior and not dir_matches(sb / "prior_round", want_prior):
            # A partial carry-over copy is rebuilt, not trusted: the review must
            # reconcile EVERY prior finding, and a silently truncated
            # prior_round/ would make that reconciliation vacuous.
            if (sb / "prior_round").exists():
                rmtree_force(sb / "prior_round", ignore_errors=True)
            (sb / "prior_round").mkdir(parents=True, exist_ok=True)
            for name in want_prior:
                shutil.copy2(prior / name, sb / "prior_round" / name)
    if (sb / "prior_round").is_dir():
        inputs["prior_round"] = hash_manifest(sb / "prior_round")
    # The previous round's auditor leaves unresolved observations for the next
    # review (AGENTS.md rule 1/8). Carry them as a separate, read-only input so
    # the review can file the real ones without touching the prior-round
    # finding list.
    prior_audit_dir = sb / "prior_audit"
    if prior_audit_dir.exists():
        rmtree_force(prior_audit_dir, ignore_errors=True)
    if r > 1:
        audit_rec = ctx.run(rid_audit(r - 1))
        if audit_rec is not None:
            audit_obs = ctx.sandbox_of(audit_rec) / "audit" / "UNRESOLVED.md"
            if audit_obs.is_file():
                prior_audit_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(audit_obs, prior_audit_dir / "UNRESOLVED.md")
                inputs["prior_audit"] = hash_manifest(prior_audit_dir)
    split_mode = review_split_of(ctx)
    if part == "b" and split_mode != "off":
        # The second session's scope is complementary; it does NOT merge (the
        # orchestrator concatenates the two findings files after both finish),
        # but it can read the other session's OUTPUT once it is complete.
        a_sb = ctx.sandbox_of(ctx.run(rid_review(r)) or {"sandbox": f"runs/{rid_review(r)}"})
        if (a_sb / REVIEW_DIR).is_dir():
            ensure_copy(a_sb / REVIEW_DIR, sb / "review_a")
            inputs["review_a"] = hash_manifest(sb / "review_a")
    (sb / REVIEW_DIR).mkdir(exist_ok=True)
    stage_venue_template(ctx, sb)
    seed_template_visuals(ctx, sb)
    # Seed the M20 formatting sweep: the code-side OOXML scan IS the enumeration
    # (text-only converters cannot see layout/character formatting), so the
    # orchestrator writes the rows before the agent starts and the prompt asks
    # the agent to dispose every row and add the classes the scan cannot see.
    seed_evidence_pack(ctx, sb, sb / "base", "review")
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        scope = round_review_scope(ctx, r)
        write_text_atomic(prompt, review_prompt(sb, rid, r,
                                               caption_limit=caption_limit_of(ctx),
                                               zotero=zotero_mode_of(ctx),
                                               prior_round=(sb / "prior_round").is_dir(),
                                               prior_audit=(sb / "prior_audit").is_dir(),
                                               prior_failure=note,
                                               author_to_complete=author_to_complete_mode_of(ctx),
                                               journal_block=(journal_review_block(ctx, sb)
                                                              if journal_has_feedback(ctx)
                                                              and not journal_is_scoped(ctx)
                                                              else ""),
                                               # A scoped round is ONE review pass by
                                               # definition; the complementary-split
                                               # machinery would contradict its scope.
                                               split=(part if split_mode != "off"
                                                      and scope == "full" else None),
                                               split_mode=split_mode,
                                               scope=scope,
                                               venue=venue_profile_of(ctx),
                                               venue_norm=venue_norm_for(ctx)))
    rec = ctx.register(rid, "review", r, f"runs/{rid}",
                       upstream_run_id=rid_a1(r), source_id=a1.get("source_id"))
    rec["inputs_manifest"] = inputs
    return rec


def materialize_audit(ctx: Ctx, r: int) -> dict:
    """The AUDITOR sandbox: base/ + non_revised/ + the FROZEN review/, read-only.

    The audit stage only exists when `setup --audit on` was given. It is a
    decision session, not an editing session: it writes `audit/` and nothing
    else, and every frozen finding it drops has to carry evidence the revisers
    and the human can re-check.
    """
    rid = rid_audit(r)
    sb = ctx.runs_dir / rid
    a1 = ctx.run(rid_a1(r))
    if a1 is None:
        raise RuntimeError(f"cannot materialize {rid}: {rid_a1(r)} does not exist")
    merge_rid = rid_review_b(r) if review_split_of(ctx) != "off" else rid_review(r)
    rev_rec = _require_done(ctx, merge_rid,
                            "the auditor consumes the round's frozen review/ output")
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    ensure_copy(ctx.sandbox_of(rev_rec) / REVIEW_DIR, sb / REVIEW_DIR)
    # The PROBE session is an independent producer of X-9xx rows: merge them
    # into THIS sandbox's frozen review copy (never into the source review), so
    # the auditor disposes them beside every other frozen id.
    probe_merge = merge_probe_into_review_copy(ctx, r, sb)
    if journal_has_feedback(ctx):
        # The auditor disposes JF findings against the real letter, and a
        # concern the reviewers raised against the earlier version can only be
        # classified with that version in view: carry the ledger and the
        # labeled feedback/ area (original_submission included) beside the
        # frozen review, exactly like the revise sandbox does.
        if (ctx.sandbox_of(rev_rec) / "concerns").is_dir():
            ensure_copy(ctx.sandbox_of(rev_rec) / "concerns", sb / "concerns")
        if (ctx.sandbox_of(rev_rec) / "feedback").is_dir():
            ensure_copy(ctx.sandbox_of(rev_rec) / "feedback", sb / "feedback")
    (sb / "audit").mkdir(exist_ok=True)
    stage_venue_template(ctx, sb)
    seed_template_visuals(ctx, sb)
    seed_evidence_pack(ctx, sb, sb / "base", "audit")
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt, audit_prompt(sb, rid, r, prior_failure=note,
                                              zotero=zotero_mode_of(ctx),
                                              venue=venue_profile_of(ctx),
                                              author_to_complete=author_to_complete_mode_of(ctx),
                                              venue_norm=venue_norm_for(ctx)))
    rec = ctx.register(rid, "audit", r, f"runs/{rid}",
                       upstream_run_id=merge_rid, source_id=a1.get("source_id"))
    rec["probe_merge"] = probe_merge
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True),
                              "review": hash_manifest(sb / REVIEW_DIR)}
    if (sb / "feedback").is_dir():
        rec["inputs_manifest"]["feedback"] = hash_manifest(sb / "feedback",
                                                          follow_dir_links=True)
    if (sb / "concerns").is_dir():
        rec["inputs_manifest"]["concerns"] = hash_manifest(sb / "concerns")
    return rec


# =====================================================================
# THE PROBE REVIEW (see `rid_probe` / `PROBE_REVIEW_MODES`)
#
#   probe_review/          — the ONLY output directory (see PROBE_DIR)
#     CLAIM_SURFACES.md    — seeded: claim-bearing sentences (a CANDIDATE list)
#     PRODUCERS.md         — seeded: the corpus's own table/code inventory
#     findings_probe.json/md — the findings (any class; X-9xx ids) + `checked`
#     coverage.md          — the areas examined, counts and honest limits
#     scripts/*.py         — every declared verifier, re-runnable
#     REPRODUCTION.md      — code-written by the postcheck (NOT the session)
#
# The orchestrator RE-RUNS every DECLARED verifier at postcheck time and
# compares the last stdout line with its `computed` value: equal -> the
# computation is trustworthy; different -> the attempt FAILS (a computation the
# probe cannot reproduce is a correctness blocker, not a finding). The findings
# (X-9xx) ride in the round's discovery list
# (`review/round2/findings_extra.json` in every downstream copy), so the
# reviser must resolve them, the auditor may only drop them with evidence, and
# the integrator must reconcile them.
# =====================================================================

# The probe is GENERIC on purpose: any defect class may be reported, in the
# same six-category / four-rung vocabulary every session uses. A computation (a
# script whose last stdout line is compared by the orchestrator) is a TOOL for
# the rows that can be verified that way, not a restriction on what the session
# may look at or report: a stale sidecar string, a missing deliverable, an
# inconsistent number, an unreadable figure or a broken pointer is just as
# reportable as a claim its own producer contradicts.


def seeded_probe_paths(sb: Path) -> set:
    """Every file the probe materializer writes before the agent starts.

    `leftovers_present` treats them as INPUTS: a freshly materialized probe
    sandbox must not read as "already worked in".
    """
    return {sb / PROBE_SURFACES_REL, sb / PROBE_PRODUCERS_REL,
            sb / PROBE_OBLIGATIONS_REL}


def probe_obligation_rows(root: Path, limit: int = 200) -> list:
    """Rows for `PROBE_OBLIGATIONS.md`: what the submission promises, resolved.

    Three families, each derived from the corpus's own declarations -- nothing
    here reads a checklist or a rule the venue did not state:
      * `submitted set` -- the package's own README declares a glob (when it
        does); every other carried file is named as NOT submitted, so a
        document that cites one is a completeness defect rather than a nuance;
      * `cited display item` -- a figure/table label a submitted document cites,
        with whether the declared set (or the corpus) carries a matching file;
      * `written pointer` -- a file name a submitted document names, with where
        (if anywhere) the package carries it.

    This is a CANDIDATE list like the other two: the session still decides what
    each row means, and an obligation it cannot resolve is a finding or a
    recorded limitation, never a silent skip.
    """
    rows = []
    root = Path(root)
    if not root.is_dir():
        return rows
    try:
        decl = declared_submission_set(root)
    except Exception:                                             # noqa: BLE001
        decl = {}
    submitted = list(decl.get("files") or [])
    carried = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    if decl.get("declared"):
        for rel in submitted[:60]:
            rows.append({"family": "submitted set", "obligation": rel,
                         "resolves": "yes (declared as submitted)", "where": rel})
        for rel in (decl.get("carried_not_submitted") or [])[:40]:
            rows.append({"family": "submitted set", "obligation": rel,
                         "resolves": "no (carried, NOT submitted)",
                         "where": f"corpus only: {rel}"})
    else:
        rows.append({"family": "submitted set",
                     "obligation": "the package declares no submitted set",
                     "resolves": "unknown",
                     "where": decl.get("ignored_reason") or "no README declares a glob"})
    # Written pointers and cited display items: the two shapes the submission
    # itself creates, resolved against what the package actually carries.
    try:
        for r in non_submitted_reference_rows(root, submission_not_carried_areas_plain()):
            rows.append({"family": "written pointer",
                         "obligation": f"{r.get('reference')} (in {r.get('file')}:{r.get('line')})",
                         "resolves": "no (the submission does not carry it)",
                         "where": str(r.get("detail") or "")[:120]})
    except Exception:                                             # noqa: BLE001
        pass
    try:
        for r in package_display_item_rows(root):
            rows.append({"family": "cited display item",
                         "obligation": f"{r.get('reference')} (cited in {r.get('file')})",
                         "resolves": "no (no matching file)",
                         "where": str(r.get("detail") or "")[:120]})
    except Exception:                                             # noqa: BLE001
        pass
    rows.append({"family": "coverage",
                 "obligation": f"the corpus carries {len(carried)} file(s); "
                               f"{len(submitted)} declared as submitted",
                 "resolves": "context", "where": ""})
    return rows[:limit]


def probe_table_inventory(corpus: Path, limit: int = 400) -> list:
    """Rows for `PROBE_PRODUCERS.md`: the corpus's own data tables + code files.

    Deterministic and cheap: tabular files get their header columns and data-row
    count, everything else is listed by path. This is the producer CANDIDATE
    list the prompt requires the session to go beyond, never the enumeration.
    """
    rows = []
    for area in RAW_DATA_DIRNAMES:
        root = corpus / area
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if len(rows) >= limit or not p.is_file():
                continue
            suffix = p.suffix.lower()
            if suffix not in (".tsv", ".csv", ".json", ".md", ".txt"):
                continue
            rel = p.relative_to(corpus).as_posix()
            columns, count = "(non-tabular)", ""
            if suffix in (".tsv", ".csv"):
                try:
                    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
                        header = f.readline().rstrip("\n")
                        count = sum(1 for _ in f)
                    cells = header.split("\t" if suffix == ".tsv" else ",")
                    columns = " | ".join(str(c).strip()[:40] for c in cells[:14]) or "(empty)"
                except OSError:
                    columns = "(unreadable)"
            rows.append({"file": rel, "data rows": count, "columns (first 14)": columns})
    code = corpus / CODE_DIR
    if code.is_dir():
        for p in sorted(code.rglob("*")):
            if len(rows) >= limit or not p.is_file():
                continue
            if p.suffix.lower() in (".py", ".r", ".sh", ".ipynb", ".json", ".yaml", ".yml",
                                    ".toml", ".cfg", ".ini"):
                rows.append({"file": p.relative_to(corpus).as_posix(), "data rows": "",
                             "columns (first 14)": "(producer code/config)"})
    return rows


def seed_probe_surfaces(ctx: Ctx, sb: Path, r: int) -> dict:
    """Write the probe sandbox's two candidate inventories (inputs, not answers).

    CLAIM_SURFACES.md is the same paragraph model the review's claim-strength
    ledger uses, so the probe cannot silently miss a claim surface the pipeline
    knows exists; PRODUCERS.md is the data/code inventory. Both are marked as
    CANDIDATE lists: the prompt requires the session to read the surfaces and
    the producers itself and to account for every surface in coverage.md.
    """
    corpus = sb / "base"
    try:
        ev = code_side_evidence(ctx, corpus, f"{rid_probe(r)}:probe")
    except Exception as e:                                        # noqa: BLE001
        ev = {"error": f"{type(e).__name__}: {e}"}
    claim_rows = []
    for c in ((ev.get("claims") or {}).get("rows") or []):
        markers = c.get("markers")
        claim_rows.append({
            "document": c.get("document"), "paragraph": c.get("paragraph"),
            "kind": c.get("kind"), "direction": c.get("direction"),
            "marker(s)": ", ".join(markers) if isinstance(markers, (list, tuple))
            else str(markers or ""),
            "sentence": (c.get("sentence") or "")[:160]})
    write_text_atomic(sb / PROBE_SURFACES_REL, (
        "# CLAIM SURFACES — seeded CANDIDATE list (the enumeration is YOURS)\n\n"
        "Every claim-bearing sentence the orchestrator's paragraph model found (the same model the "
        "review's J3 claim-strength ledger uses). `direction` = the polarity the model saw: `over` "
        "= a maximal claim, `under` = a hedge. This list is NOT the enumeration: read the surfaces "
        "themselves — the abstract, every figure legend, the cover letter, the Results and "
        "statistics paragraphs — and account for each surface in `coverage.md`.\n\n"
        + _evidence_artifact_table(
            claim_rows, ["document", "paragraph", "kind", "direction", "marker(s)", "sentence"],
            "no claim-bearing sentence was found by the code-side model")
        + "\n"))
    write_text_atomic(sb / PROBE_PRODUCERS_REL, (
        "# PRODUCERS — seeded CANDIDATE list (data tables and code in the corpus)\n\n"
        "The corpus's own `" + "/`, `".join(RAW_DATA_DIRNAMES) + "/` files and its `code/` "
        "directory. Tabular files show their header columns and data-row count so a claim can be "
        "paired with the column that must support it. This list is NOT the enumeration: read the "
        "files you need, and use a producer the corpus carries even when it is not listed here.\n\n"
        + _evidence_artifact_table(
            probe_table_inventory(corpus),
            ["file", "data rows", "columns (first 14)"],
            "no producer file (data table or code) was found in the corpus")
        + "\n"))
    write_text_atomic(sb / PROBE_OBLIGATIONS_REL, (
        "# OBLIGATIONS — seeded CANDIDATE list (what THIS submission promises)\n\n"
        "Completeness runs in TWO directions. The other two lists point at what the corpus SAYS "
        "(claims, producers); this one points at what the corpus OWES its own reader — the "
        "submitted set its README declares, the display items the documents cite, and the file "
        "names they write. A row whose `resolves` column is 'no' is not automatically a finding "
        "(the author may have decided deliberately), but it MUST be disposed in `coverage.md`: "
        "either a finding, or a one-line statement of why the omission is intended. A submission "
        "that ships less than it says it ships is a defect a reviewer sees on first read.\n\n"
        "ALSO CHECK, and account for each in coverage.md: does the manuscript carry the structure "
        "its OWN venue requires (every section the venue's recorded rule set names, every "
        "deliverable the submission's own cross-references assume, every display item whose label "
        "appears in the text)? A missing section or a cited-but-absent item belongs to this "
        "family even though nothing on the page is wrong.\n\n"
        + _evidence_artifact_table(
            probe_obligation_rows(corpus),
            ["family", "obligation", "resolves", "where"],
            "no obligation could be derived (no README declaration, no pointer, no display item)")
        + "\n"))
    return {"claims": len(claim_rows)}


def materialize_probe(ctx: Ctx, r: int) -> dict:
    """The PROBE REVIEW sandbox (see `rid_probe`): a cold-context discovery pass.

    Materialized from the round base ONLY. Deliberately absent: `review/`,
    `prior_round/`, any finding list, any sweep artifact. The session's value
    is that it re-derives its own read of the corpus -- and its own
    computations -- in a context that has not just disposed the checklist's
    rows. The seeds are CANDIDATE lists, not a scope: any defect class may be
    reported.
    """
    rid = rid_probe(r)
    a1 = ctx.run(rid_a1(r))
    if a1 is None:
        raise RuntimeError(f"cannot materialize {rid}: {rid_a1(r)} does not exist")
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    (sb / PROBE_DIR).mkdir(exist_ok=True)
    seed_probe_surfaces(ctx, sb, r)
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / PROMPT_FILE
    if not prompt.is_file():
        write_text_atomic(prompt, probe_prompt(sb, rid, r, prior_failure=note,
                                               venue=venue_profile_of(ctx),
                                               author_to_complete=author_to_complete_mode_of(ctx)))
    rec = ctx.register(rid, "probe", r, f"runs/{rid}",
                       upstream_run_id=rid_a1(r), source_id=a1.get("source_id"))
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR,
                                                          follow_dir_links=True)}
    return rec


def _probe_value_equal(declared, produced) -> bool:
    """Is the declared `computed` value equal to what the script re-printed?

    Whitespace-insensitive; two numbers compare NUMERICALLY (0.912 == 0.9120,
    3.1e-2 == 0.031); any other value compares as a canonical string. "Close"
    is not enough: the row's claim is that the script prints THIS value.
    """
    a = " ".join(str(declared or "").split())
    b = " ".join(str(produced or "").split())
    if a == b:
        return True
    if not a or not b:
        return False
    try:
        # float() collapses 9007199254740993 to 9007199254740992 and turns
        # 1e999 into inf: a one-ulp error would be "reproduced". Decimal keeps
        # the written value exact.
        from decimal import Decimal, InvalidOperation
        return Decimal(a) == Decimal(b)
    except (TypeError, ValueError, InvalidOperation):
        return False


def _probe_contract_problems(sb: Path) -> tuple:
    """(errors, warnings, findings) for `probe_review/findings_probe.json`.

    Sandbox-local and pure, exactly like the review's contract helpers, so the
    session's pre-flight (`sandbox_selfcheck`) applies the detectors the
    postcheck will apply -- never a different verdict.

    The probe is GENERIC: a finding may be any defect class anywhere in the
    corpus (documents, raw_data/, code/, figures, references), in the same
    six-category / four-rung vocabulary every session uses, and a finding MAY
    carry a `verifier` -- a re-runnable script plus the exact value it prints --
    when the defect can be shown by computation. What is checked here:

      * `checked`: every AREA the probe examined, with its candidate and finding
        counts, so a zero-finding outcome is an examined corpus and not an
        unrun pass;
      * every finding's standard shape, unique id in the reserved X-9xx block;
      * every declared verifier: a relative script under `probe_review/scripts/`
        that exists, plus the non-empty `computed` value it must print (the
        orchestrator re-runs it -- see `probe_reproduction`).
    """
    errs, warns = [], []
    p = sb / PROBE_FINDINGS_REL
    if not p.is_file():
        return ([f"{PROBE_FINDINGS_REL} is missing: the probe's findings (an EMPTY list is "
                 f"legal) and its `checked` inventory are the deliverable, and that artifact is "
                 f"what distinguishes an examined corpus from an unrun pass"], [], [])
    doc = read_json(p, revive=False, lenient=True)               # agent-written
    if not isinstance(doc, dict):
        return ([f"{PROBE_FINDINGS_REL} does not parse as a JSON object"], [], [])
    checked = doc.get("checked")
    if not isinstance(checked, list) or not checked:
        errs.append(f"{PROBE_FINDINGS_REL} carries no 'checked' list: every area the probe "
                    f"examined (documents and sections, raw_data/, code/, figures, references, "
                    f"cross-document consistency, ...) is listed with the number of candidates "
                    f"examined and the findings filed, so a zero-finding outcome is an examined "
                    f"corpus and not an unrun pass")
        checked = []
    for c in checked:
        if not isinstance(c, dict) or not str(c.get("area") or "").strip():
            errs.append(f"{PROBE_FINDINGS_REL}: a `checked` row has no 'area' name")
            continue
        area = str(c["area"]).strip()
        for key in ("examined", "findings"):
            try:
                value = int(c.get(key))
            except (TypeError, ValueError):
                value = -1
            if value < 0:
                errs.append(f"{PROBE_FINDINGS_REL}: checked area {area!r} carries no usable "
                            f"{key!r} count")
    raw = doc.get("findings")
    if not isinstance(raw, list):
        errs.append(f"{PROBE_FINDINGS_REL} carries no 'findings' list (an empty list is legal "
                    f"when `checked` documents the examination)")
        raw = []
    findings, seen = [], set()
    for i, f in enumerate(raw):
        if not isinstance(f, dict):
            errs.append(f"{PROBE_FINDINGS_REL}: finding {i} is not an object")
            continue
        fid = str(f.get("id") or "").strip()
        if not PROBE_ID_RE.match(fid):
            errs.append(f"{PROBE_FINDINGS_REL}: id {fid or '(none)'!r} is outside the reserved "
                        f"probe block X-901...X-999")
            continue
        if fid in seen:
            errs.append(f"{PROBE_FINDINGS_REL}: duplicate id {fid}")
        seen.add(fid)
        for key in ("location", "evidence", "explanation"):
            if not str(f.get(key) or "").strip():
                errs.append(f"{PROBE_FINDINGS_REL} {fid}: no {key}")
        if str(f.get("severity") or "").strip().lower() not in DISCOVERY_SEVERITIES:
            errs.append(f"{PROBE_FINDINGS_REL} {fid}: severity {f.get('severity')!r} is not one "
                        f"of {'/'.join(s.capitalize() for s in DISCOVERY_SEVERITIES)}")
        try:
            ok_cat = 0 <= int(f.get("category")) <= 5
        except (TypeError, ValueError):
            ok_cat = False
        if not ok_cat:
            errs.append(f"{PROBE_FINDINGS_REL} {fid}: category {f.get('category')!r} is not an "
                        f"integer 0-5")
        verifier = f.get("verifier")
        if verifier is not None:
            if not isinstance(verifier, dict):
                errs.append(f"{PROBE_FINDINGS_REL} {fid}: `verifier` is not an object "
                            f"({{script, computed, shows}}) -- omit it when no computation can "
                            f"show the defect")
            else:
                script = str(verifier.get("script") or "").strip()
                if not script:
                    errs.append(f"{PROBE_FINDINGS_REL} {fid}: the verifier carries no `script`")
                else:
                    sp = Path(script)
                    if sp.is_absolute() or ".." in sp.parts \
                            or not script.startswith(PROBE_SCRIPT_PREFIX):
                        errs.append(f"{PROBE_FINDINGS_REL} {fid}: verifier script {script!r} "
                                    f"must be a relative path under {PROBE_SCRIPT_PREFIX}")
                    elif not (sb / sp).is_file():
                        errs.append(f"{PROBE_FINDINGS_REL} {fid}: verifier script {script!r} "
                                    f"does not exist")
                if not str(verifier.get("computed") or "").strip():
                    errs.append(f"{PROBE_FINDINGS_REL} {fid}: the verifier carries no `computed` "
                                f"value (EXACTLY the last non-empty stdout line the script "
                                f"prints)")
        findings.append(f)
    return errs, warns, findings


def probe_reproduction(sb: Path, findings: list) -> dict:
    """Re-run every DECLARED verifier and record what it printed.

    A finding's `verifier` is {script, computed, shows}: the script's last
    non-empty stdout line must equal `computed`. The orchestrator runs it itself
    (offline, bounded, cwd = the sandbox root); a mismatch, a missing script, a
    non-zero exit, an empty output or a timeout is an error the caller turns into
    a failed attempt -- a computation the probe cannot reproduce is a
    correctness blocker, not a finding. Findings WITHOUT a verifier are
    evidence/quotation rows: they are not re-run (their evidence is the quoted
    text or file:line reference), and they carry status `no-verifier` in the
    record.
    """
    results = []
    for f in findings or ():
        fid = str(f.get("id") or "")
        verifier = f.get("verifier")
        if not isinstance(verifier, dict):
            results.append({"row": fid, "script": "", "declared": "", "produced": "",
                            "status": "no-verifier", "detail": ""})
            continue
        script = str(verifier.get("script") or "").strip()
        entry = {"row": fid, "script": script,
                 "declared": " ".join(str(verifier.get("computed") or "").split()),
                 "produced": "", "status": "", "detail": ""}
        target = sb / script if script else None
        # The verifier must live under `probe_review/scripts/`, by REAL path:
        # `is_within(target, sb / PROBE_DIR)` resolved both sides, so replacing
        # `probe_review` with a symlink to /tmp/outside made the outside script
        # and the anchor agree and the orchestrator executed it.
        try:
            root = sb.resolve() / PROBE_SCRIPT_PREFIX
            scripts_dir = sb / PROBE_DIR / "scripts"
            safe = (target is not None and not (sb / PROBE_DIR).is_symlink()
                    and not scripts_dir.is_symlink()
                    and target.is_file()
                    and target.resolve().is_relative_to(root))
        except OSError:
            safe = False
        if not safe:
            entry.update(status="missing")
            results.append(entry)
            continue
        try:
            # The WHOLE stdout, not its final 8192 bytes: a correct last line
            # longer than that failed, and a long line whose suffix happened to
            # float-equal the claim passed.
            proc = subprocess.run(
                [sys.executable, str(target)], cwd=str(sb), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=PROBE_REPRO_TIMEOUT)
            text = (proc.stdout or b"").decode("utf-8", "replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            produced = lines[-1] if lines else ""
            entry["produced"] = " ".join(produced.split())[:200]
            if proc.returncode != 0:
                entry.update(status="failed", detail=f"exit {proc.returncode}")
            elif not produced:
                entry.update(status="empty")
            elif _probe_value_equal(entry["declared"], produced):
                entry.update(status="reproduced")
            else:
                entry.update(status="mismatch")
        except subprocess.TimeoutExpired:
            entry.update(status="timeout", detail=f"over {PROBE_REPRO_TIMEOUT}s")
        except OSError as e:                                     # noqa: BLE001
            entry.update(status="failed", detail=f"{type(e).__name__}: {e}"[:120])
        results.append(entry)
    verified = [r for r in results if r["status"] != "no-verifier"]
    mismatches = [r["row"] for r in verified if r["status"] == "mismatch"]
    broken = [r["row"] for r in verified
              if r["status"] in ("missing", "timeout", "failed", "empty")]
    return {"rows": len(results), "verified": len(verified),
            "reproduced": sum(1 for r in verified if r["status"] == "reproduced"),
            "mismatches": mismatches, "broken": broken, "results": results}


def _write_probe_reproduction(sb: Path, repro: dict) -> None:
    """The code-written reproduction record (`probe_review/REPRODUCTION.md`)."""
    lines = ["# PROBE REPRODUCTION — the orchestrator re-ran every declared verifier", "",
             "| finding | script | declared | re-run printed | status |",
             "|---|---|---|---|---|"]
    for r in repro.get("results") or ():
        lines.append("| {row} | `{script}` | {declared} | {produced} | {status}{detail} |".format(
            row=r.get("row"), script=r.get("script"), declared=r.get("declared") or "(none)",
            produced=r.get("produced") or "(none)", status=r.get("status"),
            detail=(f" ({r['detail']})" if r.get("detail") else "")))
    lines += ["", f"{repro.get('reproduced', 0)} of {repro.get('verified', 0)} declared "
                  f"verifier(s) reproduced exactly; {len(repro.get('mismatches') or [])} "
                  f"mismatch(es), {len(repro.get('broken') or [])} broken script(s). A mismatch "
                  "or a broken script fails the attempt: a computation the probe cannot "
                  "reproduce is a correctness blocker, not a finding.", ""]
    write_text_atomic(sb / PROBE_REPRO_REL, "\n".join(lines))


def postcheck_probe(ctx: Ctx, rec: dict):
    """The probe session's contract: the checked inventory, the findings, and
    every DECLARED verifier RE-RUN.

    Structural plus computational. The findings are generic (any category, any
    severity, any location in the corpus); the `checked` inventory is what makes
    a zero-finding outcome distinguishable from an unrun pass; and for every
    finding that carries a verifier, the orchestrator re-runs the script and
    compares its last stdout line with the declared `computed` value. A mismatch
    is a hard error (the attempt fails and is retried), never a warning --
    a computation the probe cannot reproduce is a correctness blocker.
    """
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "probe", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    perrs, pwarns, findings = _probe_contract_problems(sb)
    errs.extend(perrs)
    warns.extend(pwarns)
    coverage = sb / PROBE_COVERAGE_REL
    if not coverage.is_file():
        errs.append(f"{PROBE_COVERAGE_REL} is missing: the areas examined, the counts and the "
                    f"round's honest limits are part of the deliverable")
    else:
        try:
            if not coverage.read_text(encoding="utf-8", errors="replace").strip():
                errs.append(f"{PROBE_COVERAGE_REL} is EMPTY: account for the areas examined, the "
                            f"findings they produced and what could not be checked")
        except OSError as e:                                     # noqa: BLE001
            errs.append(f"{PROBE_COVERAGE_REL} could not be read ({e})")
    repro = probe_reproduction(sb, findings)
    if findings:
        _write_probe_reproduction(sb, repro)
    findings_ids = sorted(str(f.get("id") or "").strip() for f in findings)
    repro["findings"] = findings_ids
    rec["probe_review"] = repro
    for r in repro["results"]:
        if r["status"] == "mismatch":
            errs.append(f"{PROBE_FINDINGS_REL} {r['row']}: the re-run of `{r['script']}` printed "
                        f"{r['produced']!r} where the finding declares {r['declared']!r} -- the "
                        f"declared computation does not reproduce (a correctness blocker: fix "
                        f"the script or the declared value)")
        elif r["status"] in ("missing", "timeout", "failed", "empty"):
            errs.append(f"{PROBE_FINDINGS_REL} {r['row']}: the verifier `{r['script']}` "
                        f"{'is missing' if r['status'] == 'missing' else r['status']}"
                        + (f" ({r['detail']})" if r["detail"] else "")
                        + " -- a declared verifier must be a re-runnable script that prints its "
                          "`computed` value as the last stdout line (omit the verifier when no "
                          "computation can show the defect)")
    _check_pristine_copy(ctx, rec, pristine_dirname(ctx.sandbox_of(rec)), errs)
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def probe_findings_rows(ctx: Ctx, r: int) -> list:
    """The probe session's X-9xx findings ([] when the round ran no probe).

    A FINISHED probe run wins, even when its list is empty -- falling back to
    the archive could resurrect a superseded list. A root whose probe sandbox is
    gone (pruned, or a decision re-derived later) reads the archived copy under
    `reports/round<r>_review/`, so the frozen list stays reproducible.
    """
    try:
        r = int(r)
    except (TypeError, ValueError):
        return []
    rec = ctx.run(rid_probe(r))
    if rec is not None and str(rec.get("status") or "") == "done":
        live = ctx.sandbox_of(rec) / PROBE_FINDINGS_REL
        if live.is_file():
            doc = read_json(live, revive=False, lenient=True)
            found = doc.get("findings") if isinstance(doc, dict) else []
            return [f for f in (found or ()) if isinstance(f, dict)
                    and str(f.get("id") or "").strip()]
        # The sandbox was pruned: a DONE record must read the archive, not
        # silently return an empty discovery list.
    # The ARCHIVED round keeps the probe findings MERGED into its
    # findings_extra.json (see archive_review_outputs): they are already part of
    # the archived discovery list, so re-adding them here would double-seed the
    # same defects under remapped ids.
    archived = read_json(ctx.reports_dir / f"round{r}_review" / "findings_extra.json",
                         revive=False, lenient=True)
    if isinstance(archived, dict) and isinstance(archived.get("probe_merge"), dict):
        return []
    doc = read_json(ctx.reports_dir / f"round{r}_review" / "findings_probe.json",
                    revive=False, lenient=True)
    found = doc.get("findings") if isinstance(doc, dict) else []
    return [f for f in (found or ()) if isinstance(f, dict)
            and str(f.get("id") or "").strip()]


def probe_review_upstream_doc(ctx: Ctx, r: int) -> dict:
    """The UNMERGED review `round2/findings_extra.json` doc ({} when none).

    Resolved like every other downstream consumer: the concerns run in a scoped
    (major/minor) revision, session B under a split review, the single review
    run otherwise, then the archived copy -- so a pruned root still yields the
    base the merge is computed from.
    """
    if journal_is_scoped(ctx):
        rid, archive = rid_concerns(r), f"round{int(r)}_concerns"
    elif review_split_of(ctx) != "off":
        rid, archive = rid_review_b(r), f"round{int(r)}_review"
    else:
        rid, archive = rid_review(r), f"round{int(r)}_review"
    rec = ctx.run(rid)
    if rec is not None and str(rec.get("status") or "") == "done":
        doc = read_json(ctx.sandbox_of(rec) / REVIEW_DIR / "round2" / "findings_extra.json",
                        revive=False, lenient=True)
        if isinstance(doc, dict):
            return doc
    doc = read_json(ctx.reports_dir / archive / "findings_extra.json",
                    revive=False, lenient=True)
    return doc if isinstance(doc, dict) else {}


def probe_findings_for_merge(existing_ids, rows) -> tuple:
    """(findings with collision-free ids, remap) against the ids already in a list.

    Deterministic, in row order: a probe row whose id is already used (or that
    is outside the reserved X-9xx block) moves to the first free X-9xx slot.
    Every consumer that applies this rule to the same inputs (the merged review
    copies, the integration seed) reaches the same ids.
    """
    used = {str(i) for i in (existing_ids or ()) if str(i).strip()}
    out, remap = [], {}
    for row in rows or ():
        row = dict(row)
        fid = str(row.get("id") or "").strip()
        new = fid
        if not DISCOVERY_X_ID_RE.match(new) or new in used:
            k = PROBE_FINDING_ID_BASE + 1
            while f"X-{k:03d}" in used:
                k += 1
            new = f"X-{k:03d}"
            remap[fid] = new
        used.add(new)
        row["id"] = new
        out.append(row)
    return out, remap


def probe_merged_review_doc(ctx: Ctx, r: int, base_doc) -> tuple:
    """(merged doc or None, rows added, remap) for one review-copy merge.

    The ONE place that computes what `merge_probe_into_review_copy` writes, so
    the materializer and the input-freshness check (`_review_copy_mismatch`)
    cannot disagree about the expected content. `None` means the probe carried
    no findings and the copy is the upstream bytes, unchanged.
    """
    rows = probe_findings_rows(ctx, r)
    if not rows:
        return None, [], {}
    doc = base_doc if isinstance(base_doc, dict) else {}
    block = doc.get("probe_merge")
    if isinstance(block, dict) and str(block.get("source") or "") == rid_probe(r):
        # The base is ALREADY the merged doc (only reachable through the archive
        # fallback of probe_review_upstream_doc): merging again would duplicate
        # every row under remapped ids.
        return doc, [], block.get("id_remap") or {}
    existing = [f for f in (doc.get("findings") or []) if isinstance(f, dict)]
    merged_rows, remap = probe_findings_for_merge([f.get("id") for f in existing], rows)
    merged = dict(doc)
    merged["findings"] = existing + merged_rows
    merged["probe_merge"] = {"source": rid_probe(r), "rows": len(merged_rows),
                             "id_remap": remap}
    return merged, merged_rows, remap


def merge_probe_into_review_copy(ctx: Ctx, r: int, sb: Path) -> dict:
    """Merge the probe session's X-9xx findings into THIS sandbox's review copy.

    The probe findings have the same standing as the discovery round's X-* rows,
    so they travel in the ONE file every downstream contract reads
    (`review/round2/findings_extra.json`). The SOURCE review sandbox is never
    mutated -- it is frozen and byte-verified -- and every consumer (auditor,
    each reviser) gets the same merged copy. Colliding ids are remapped
    deterministically (see `probe_findings_for_merge`) and the merge block records
    the remap.
    """
    rows = probe_findings_rows(ctx, r)
    if not rows:
        return {"rows": 0, "remap": {}}
    target = sb / REVIEW_DIR / "round2" / "findings_extra.json"
    # Compute the expected merge from the UNMERGED upstream review (never from
    # the copy, which may already carry a merge block): writing the expected doc
    # is idempotent, replaces a stale merge after a probe retry, and cannot
    # duplicate rows under remapped ids.
    merged, merged_rows, remap = probe_merged_review_doc(
        ctx, r, probe_review_upstream_doc(ctx, r))
    if merged is None:
        return {"rows": 0, "remap": {}}
    current = read_json(target, revive=False, lenient=True)
    if isinstance(current, dict) and current == merged:
        return {"rows": len(merged_rows), "remap": remap, "skipped": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target, merged)
    lines = ["# Probe findings (X-9xx) — merged into this sandbox's frozen review", "",
             "| id | location | severity | category | explanation |", "|---|---|---|---|---|"]
    for f in merged_rows:
        lines.append("| {i} | {loc} | {sev} | {cat} | {expl} |".format(
            i=f.get("id"), loc=str(f.get("location") or "").replace("|", "/"),
            sev=f.get("severity"), cat=f.get("category"),
            expl=str(f.get("explanation") or "").replace("|", "/")[:160]))
    if remap:
        lines += ["", "id remap (collision with an existing finding): "
                      + ", ".join(f"{k} -> {v}" for k, v in sorted(remap.items())), ""]
    write_text_atomic(sb / PROBE_FINDINGS_MD_REL, "\n".join(lines) + "\n")
    return {"rows": len(merged_rows), "remap": remap}


def materialize_revise(ctx: Ctx, r: int, vid: str) -> dict:
    """Phase-2 sandbox for ONE reviewed-and-then-revised candidate.

    Created ONLY once the round's review marker exists. Each of the round's N
    revise sessions receives its OWN read-only copy of the SAME frozen review/,
    so the N candidates are independent revisions of one finding list.

    A4 rationale for the split: Phase 1's context (sweep artifacts, coverage
    table, discovery output) is the largest in the pipeline, while Phase 2 needs
    bounded context for targeted edits; a failure in either phase is retryable
    without re-paying the other; and the two skills already communicate through
    findings.json, so the split exposes an interface that already exists. The
    handoff is between SESSIONS, not within one prompt -- a single prompt that
    asks the agent to "review, then revise" defeats the purpose.

    The review/ directory is handed over as a READ-ONLY copy. Read-only-ness is
    enforced by the prompt plus the byte-identity postcheck, which is a HARD
    failure. The alternative we did not pick is chmod 0444/0555 hardening: this
    pipeline may run on Windows/drvfs roots where read-only files break
    sandbox rebuilds (`retry`) and shutil.rmtree, and a permission bit is not
    what makes the freeze meaningful -- the hash comparison is.
    """
    _m, n = round_counts(ctx, r)
    rid = rid_for_fresh(r, vid)
    sb = ctx.runs_dir / rid
    if journal_is_scoped(ctx):
        # A major/minor revision consumes the concerns run's finding list, not a
        # general review: that is what keeps the edits concern-scoped.
        merge_rid = rid_concerns(r)
    else:
        merge_rid = rid_review_b(r) if review_split_of(ctx) != "off" else rid_review(r)
    rev_rec = _require_done(ctx, merge_rid,
                            "every revise session consumes the round's frozen review/ output")
    _require_done(ctx, rid_a1(r), "every revise session edits a copy of the round's base")
    src_sb = ctx.sandbox_of(rev_rec)
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(ctx.run(rid_a1(r))) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    # The frozen review/ is the authoritative finding list: a partial copy must
    # never be trusted (the revision ledger keys on every finding id).
    ensure_copy(src_sb / REVIEW_DIR, sb / REVIEW_DIR)
    # The PROBE session's X-9xx findings are part of the frozen list this
    # reviser must resolve: merge them into THIS sandbox's review copy (the
    # source review sandbox is never touched; every consumer gets the same
    # merged list -- see merge_probe_into_review_copy).
    probe_merge = merge_probe_into_review_copy(ctx, r, sb)
    if journal_has_feedback(ctx):
        if (src_sb / "concerns").is_dir():
            ensure_copy(src_sb / "concerns", sb / "concerns")
        if (src_sb / "feedback").is_dir():
            ensure_copy(src_sb / "feedback", sb / "feedback")
    aud_manifest = None
    if audit_enabled(ctx) and not journal_is_scoped(ctx):
        # The reviser acts on the AUDITED list: the auditor's drops (with their
        # evidence) and its `AU-` additions travel beside the frozen review/.
        aud_rec = _require_done(ctx, rid_audit(r),
                                "the reviser consumes the AUDITED finding list (--audit on)")
        ensure_copy(ctx.sandbox_of(aud_rec) / "audit", sb / "audit")
        aud_manifest = hash_manifest(sb / "audit")
    (sb / REVISED_DIR).mkdir(exist_ok=True)
    # A retry used to start from base/ with only the failure TEXT, while the
    # prompt told the agent to read a sibling sandbox it was forbidden to open.
    # Copy the rejected package INTO this sandbox so the retry can inspect (and
    # repair) exactly what the postcheck judged.
    try:
        prev_dirs = sorted(
            (p for p in ctx.runs_dir.glob(f"{rid}_try*_failed") if p.is_dir()),
            key=lambda p: p.stat().st_mtime, reverse=True)
        if prev_dirs and (prev_dirs[0] / REVISED_DIR).is_dir():
            ensure_copy(prev_dirs[0] / REVISED_DIR,
                        sb / "previous_attempt" / REVISED_DIR)
            # A retry of a retry would otherwise nest one previous_attempt/
            # inside the next, growing without bound.
            nested = sb / "previous_attempt" / REVISED_DIR / "previous_attempt"
            if nested.exists():
                shutil.rmtree(nested, ignore_errors=True)
    except OSError:
        pass
    stage_venue_template(ctx, sb)
    seed_template_visuals(ctx, sb)
    seed_evidence_pack(ctx, sb, sb / "base", "stage")
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt, revise_prompt(sb, rid, r, index=int(str(vid)[1:]) - 1,
                                               total=n,
                                               caption_limit=caption_limit_of(ctx),
                                               zotero=zotero_mode_of(ctx),
                                               prior_failure=note,
                                               audit=audit_enabled(ctx),
                                               venue=venue_profile_of(ctx),
                                               author_to_complete=author_to_complete_mode_of(ctx),
                                               journal_block=(journal_revise_block(ctx)
                                                              if journal_has_feedback(ctx)
                                                              else ""),
                                               venue_norm=venue_norm_for(ctx)))
    rec = ctx.register(rid, "revise", r, f"runs/{rid}",
                       upstream_run_id=merge_rid, source_id=A1_ID, produces=vid)
    rec["probe_merge"] = probe_merge
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True),
                              "review": hash_manifest(sb / REVIEW_DIR)}
    if (sb / "feedback").is_dir():
        rec["inputs_manifest"]["feedback"] = hash_manifest(sb / "feedback",
                                                          follow_dir_links=True)
    if (sb / "concerns").is_dir():
        rec["inputs_manifest"]["concerns"] = hash_manifest(sb / "concerns")
    if aud_manifest is not None:
        rec["inputs_manifest"]["audit"] = aud_manifest
    return rec


def materialize_integrate(ctx: Ctx, r: int, k: int) -> dict:
    """The k-th INTEGRATION sandbox: self/ = one pool member, others/<id>/ = ALL
    the other members of the round's pool.

    This replaces the old pairwise "cross-pollination" arms. There is exactly
    ONE integration run per pool member (K = 1 + M + N per round), and each of
    them sees the whole pool at once: with M=2, N=1 the four runs are
    a1 <- (w1, w2, a2), w1 <- (a1, w2, a2), w2 <- (a1, w1, a2) and
    a2 <- (a1, w1, w2). Every donor is a read-only package of its own; the
    result keeps its own member as the base and incorporates what the others
    demonstrably do better.
    """
    m, n = round_counts(ctx, r)
    pool = round_pool_ids(m, n)
    vid = integrate_vid(k)
    if not (1 <= int(k) <= len(pool)):
        raise RuntimeError(f"round {r} has {len(pool)} pool member(s); integration "
                           f"invocation {k} is out of range")
    self_id = pool[int(k) - 1]
    other_ids = [v for v in pool if v != self_id]
    rid = rid_for_fresh(r, vid)
    sb = ctx.runs_dir / rid
    for v in pool:
        _require_done(ctx, rid_for_fresh(r, v),
                      f"an integration run consumes the WHOLE pool (member {v!r} is not done)")
    sb.mkdir(parents=True, exist_ok=True)
    # Every view is verified against the CURRENT pool member and rebuilt when it
    # does not match, so a sandbox killed mid-copy can never hand the agent a
    # truncated base or a truncated donor set.
    ensure_corpus_dir(ctx, r, self_id, sb / "self")
    for other in other_ids:
        ensure_corpus_dir(ctx, r, other, sb / "others" / other)
    # Drop donor directories that do not belong to this run's pool (a leftover
    # from an interrupted materialization of a different plan would otherwise be
    # read as if it were a member of this round).
    others_dir = sb / "others"
    if others_dir.is_dir():
        for stale in [p for p in others_dir.iterdir()
                      if p.is_dir() and p.name not in other_ids]:
            rmtree_force(stale, ignore_errors=True)
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    (sb / INTEGRATED_DIR).mkdir(exist_ok=True)
    stage_venue_template(ctx, sb)
    seed_template_visuals(ctx, sb)
    seed_evidence_pack(ctx, sb, sb / "self", "stage")
    # The round's frozen discovery list (X-*, see DISCOVERY_SEED_DIR): the ONE
    # review artifact this stage consumes. The revision arms resolved it, so a
    # donor may carry its fix; the ledger must reconcile every id (ported /
    # kept-base / no-donor-fix) or the round's revision work can be lost here.
    disc = seed_discovery_findings(ctx, r, sb)
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt, integrate_prompt(sb, rid, r, self_id, other_ids,
                                                  caption_limit=caption_limit_of(ctx),
                                                  zotero=zotero_mode_of(ctx),
                                                  prior_failure=note,
                                                  venue=venue_profile_of(ctx),
                                                  author_to_complete=author_to_complete_mode_of(ctx),
                                                  venue_norm=venue_norm_for(ctx),
                                                  discovery_ids=disc["ids"],
                                                  discovery_dropped=disc["dropped"]))
    rec = ctx.register(rid, "integrate", r, f"runs/{rid}", self_id=self_id,
                       other_ids=other_ids, pool_ids=pool, produces=vid,
                       field_ids=other_ids, discovery_ids=list(disc["ids"]))
    rec["inputs_manifest"] = {"self": hash_manifest(sb / "self"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True),
                              "others": hash_manifest(sb / "others")}
    if disc["dir"] is not None:
        rec["inputs_manifest"][DISCOVERY_SEED_DIR] = hash_manifest(sb / DISCOVERY_SEED_DIR)
    return rec


def producing_run_id(r: int, vid: str):
    if vid == ORIGINAL_ID:
        return None
    if is_fresh_vid(vid):
        return rid_for_fresh(r, vid)
    return None   # a pinned champion's provenance lives in its pin record


def drop_legacy_judge_original(sandbox: Path, rec: dict = None) -> bool:
    """Remove an old openly named ``original/`` view from a judge sandbox.

    Roots materialized before the 2026-10-17 blinding fix still carry it.
    Reusing such a sandbox would hand the judge the pristine original again
    even though the prompt no longer names it. The directory is a derived,
    anonymized view, not agent work, so removing it preserves the session's
    own output while restoring the blind layout.
    """
    legacy = Path(sandbox) / "original"
    if not legacy.exists() and not legacy.is_symlink():
        return False
    if legacy.is_symlink():
        legacy.unlink()
    else:
        rmtree_force(legacy)
    if isinstance(rec, dict):
        manifest = rec.get("inputs_manifest")
        if isinstance(manifest, dict):
            manifest.pop("original", None)
    return True


def materialize_judges(ctx: Ctx, r: int, field: list) -> list:
    """Judge sandboxes: target/ and field/<random labels>.

    The label -> version map is written to the run record only; the sandbox
    gets the labels and nothing else about them.
    """
    judges = round_judges(ctx, r)
    k_opp = len(field) - 1
    if k_opp < 1:
        raise RuntimeError(f"round {r}: field has {len(field)} member(s); no opponents to judge")
    for vid in round_produced_ids(ctx, r):
        _require_done(ctx, rid_for_fresh(r, vid),
                      "a judge field needs every arm of the round (the base, every rewrite, every "
                      "reviewed-and-revised candidate and every integration run the round's "
                      "integrator mask selected)")
    # The token names the run AND its sandbox directory, so two versions that
    # hashed to the same token would silently share one sandbox (the second
    # materialization would reuse the first's target/ and prompt): the panel
    # would be scoring the wrong corpus. Detect it and refuse instead of
    # merging two sessions.
    seen_tokens = {}
    for v in field:
        tok = judge_token_for(ctx, r, v["id"])
        if tok in seen_tokens and seen_tokens[tok] != v["id"]:
            raise RuntimeError(
                f"judge session token collision: versions {seen_tokens[tok]!r} and {v['id']!r} "
                f"both map to {tok!r}; the panel would score one corpus under two labels. "
                f"Re-run `setup` for a fresh per-root salt (the salt is what makes the tokens "
                f"unpredictable), then re-run the judge wave.")
        seen_tokens[tok] = v["id"]
    out = []
    for v in field:
        vid = v["id"]
        others = sorted([w for w in field if w["id"] != vid], key=lambda w: w["id"])
        # The judge's own bookkeeping (run id + sheet target_id) must not reveal
        # the version's provenance, so both use an opaque token mixed with the
        # root's random salt (a bare hash of (round, version id) is brute-forceable
        # over the handful of candidate ids); the run record keeps the token ->
        # version-id mapping.
        token = judge_token_for(ctx, r, vid)
        # One timestamp for this target's views (target/ + every field label), so
        # a judge cannot order the packages by "when the file was written".
        view_stamp = time.time()
        for j in range(1, judges + 1):
            if not judge_enabled(ctx, r, vid, j):
                # `run --only r1_judge_w2_j1` selected other sessions: this one is not
                # planned at all (no sandbox, no session, no sheet), and the
                # aggregation's per-version expectation is adjusted to match.
                continue
            rid = rid_judge(r, token, j)
            sb = ctx.runs_dir / rid
            existing = ctx.run(rid)
            if existing is not None and sb.is_dir() and (sb / "PROMPT.md").is_file():
                drop_legacy_judge_original(sb, existing)
                # The sandbox was fully materialized once. Never rebuild it
                # blindly (it may hold an agent's partial work), but do not hand
                # a DAMAGED read-only view to an agent either: a truncated
                # target/field would be judged as if it were the whole corpus.
                # An untouched damaged sandbox is marked stale, so the staging
                # loop rebuilds it from the current corpora before any session
                # starts; a damaged sandbox that already holds agent output is
                # left alone for the postcheck/operator to dispose of.
                view_seed = judge_view_seed_for(ctx, r, vid, j)
                problems = []
                if not hash_checks_skipped():
                    if judge_view_digest(sb / "target") != expected_view_digest(
                            ctx, r, vid, f"{view_seed}|target"):
                        problems.append("target/")
                    for label, w in (existing.get("label_map") or {}).items():
                        if judge_view_digest(sb / "field" / label) != expected_view_digest(
                                ctx, r, w, f"{view_seed}|{label}"):
                            problems.append(f"field/{label}/")
                            break
                if problems and not leftovers_present(ctx, existing):
                    print(f"[warn] {rid}: read-only view(s) {', '.join(problems)} do not match "
                          f"their corpora (interrupted copy?); rebuilding the sandbox instead of "
                          f"judging a truncated corpus")
                    ctx.log("judge-view-damaged", rid, ", ".join(problems))
                    existing["status"] = "stale"
                    existing["stale_reason"] = ("read-only judge view damaged: "
                                                + ", ".join(problems))
                    existing["last_error"] = f"stale: {existing['stale_reason']}"
                out.append(rid)
                continue
            sb.mkdir(parents=True, exist_ok=True)
            drop_legacy_judge_original(sb)
            # The seed mixes the per-root salt, THIS session's opaque token and
            # the judge index, so every view in every session is permuted
            # independently (and a rebuild of the same session reproduces it).
            view_seed = judge_view_seed_for(ctx, r, vid, j)
            ensure_judge_view(ctx, r, vid, sb / "target", view_stamp, f"{view_seed}|target")
            labels = sample_labels(r, vid, j, k_opp, salt=judge_salt_of(ctx))
            label_map = {}
            for label, w in zip(labels, others):
                ensure_judge_view(ctx, r, w["id"], sb / "field" / label, view_stamp,
                                  f"{view_seed}|{label}")
                label_map[label] = w["id"]
            # ONE timestamp and one mode for every view this session can see.
            for rel in ("target", "field"):
                stamp_tree(sb / rel, view_stamp)
            # BLINDING: the judge gets NO orchestrator artifact. Even a scan
            # computed from its own target/ would hand it a pre-digested view of
            # the content (and a digest/token/path it could correlate across
            # sessions). The judge derives its own M18/M19/M20 rows from the
            # blinded packages with the same public tool; the orchestrator only
            # verifies those rows afterwards (postcheck_judge), never seeds them.
            # The judge gets the venue's template RULES as prompt text and the
            # venue's own template RENDER (both identical for every session and
            # every target/opponent). That is the one venue-level exception to
            # "no orchestrator artifact": nothing derived from target/field is
            # seeded, so provenance stays blinded.
            seed_template_visuals(ctx, sb)
            # The venue's TABLE rule (venue-level, identical for every session,
            # nothing derived from target/field) so the judge can derive its own
            # M20 table rows with the public scanner: `scan <dir> --policy
            # format_policy.json`.
            seed_format_policy_file(ctx, sb)
            # NO discovery list is seeded into a judge sandbox: the judge must
            # be COMPLETELY blind to where any package came from (no other
            # session's findings, no round, no producing agent), so the
            # discovery classes are RE-DERIVED by the judge itself -- one
            # bounded pass per side, identical for the target and every
            # opponent (see `judge_discovery_block` and `judge_discovery_-
            # problems`). The integration stage still receives the review's
            # frozen list, because it is not a blind stage (see
            # DISCOVERY_SEED_DIR).
            prompt = sb / "PROMPT.md"
            if not prompt.is_file():
                _copy_session_tools(sb, stamp=view_stamp)
                write_text_atomic(prompt, judge_prompt(
                    sb, rid, r, token, j, judges, labels,
                    # C26: the panel balances the reading order
                    # (half of it reads the field before the
                    # target) so no first-read anchor can
                    # decide a pair on its own; a single
                    # judge keeps the target-first order.
                    field_first=(judges > 1 and j % 2 == 0),
                    caption_limit=caption_limit_of(ctx),
                    zotero=zotero_mode_of(ctx),
                    venue=venue_profile_of(ctx),
                    dedup_mode=dedup_mode_of(ctx),
                    author_to_complete=author_to_complete_mode_of(ctx),
                    venue_norm=venue_norm_for(ctx)))
            # One timestamp for the WHOLE judge sandbox (views, prompt and the
            # public tool alike): a listing must not be able to order the
            # session's own files, and the "whole wave is equalized" guarantee
            # has to hold at the sandbox level, not only inside the views.
            stamp_tree(sb, view_stamp)
            rec = ctx.register(rid, "judge", r, f"runs/{rid}", target_id=vid, judge_index=j,
                               judge_order=("field-first" if (judges > 1 and j % 2 == 0)
                                            else "target-first"),
                               label_map=label_map, field_ids=[w["id"] for w in others],
                               upstream_run_id=producing_run_id(r, vid),
                               judge_target_token=token,
                               # The contract the PROMPT asks for: a sheet from this sandbox
                               # must carry the graded basis (tier + ledger), and
                               # validate_judge_sheet enforces it. Legacy records without this
                               # key are tolerated with a warning and counted as uncalibrated
                               # in the decision record.
                               contract=JUDGE_CONTRACT_VERSION)
            rec["target_digest"] = recorded_version_digest(ctx, r, vid)
            rec["field_digests"] = [{"id": w["id"], "digest": recorded_version_digest(ctx, r, w["id"])}
                                    for w in others]
            rec["inputs_manifest"] = {"target": hash_manifest(sb / "target"),
                                      "field": hash_manifest(sb / "field")}
            out.append(rid)
    return out


def build_field(ctx: Ctx, r: int) -> tuple:
    """field_r = {original} U {pins from rounds < r} U the round's fresh arms
    (base, M rewrites, N revisions, and the integrated candidates the round's
    integrator mask selected -- every pool member when the mask is the default
    0xFFFFFFFF),
    deduplicated by the DOCUMENT content fingerprint (first occurrence wins; see
    corpus_content_set_fingerprint for why the name/bookkeeping-sensitive
    integrity digest is not used here). Returns (entries, dropped) where each
    entry is {"id", "digest", "fingerprint", "kind", ...}."""
    entries = [{"id": ORIGINAL_ID, "digest": working_original_digest(ctx),
                "kind": "original"}]
    for pin in sorted(ctx.state.get("pinned") or [], key=lambda p: int(p.get("round") or 0)):
        if int(pin.get("round") or 0) < int(r):
            entries.append({"id": pin["id"], "digest": pin.get("digest"), "kind": "pinned",
                            "from_round": pin.get("round"), "source_id": pin.get("source_id")})
    for vid in round_produced_ids(ctx, r):
        rec = ctx.run(rid_for_fresh(r, vid)) or {}
        entries.append({"id": vid, "digest": rec.get("corpus_digest"), "kind": "fresh",
                        "run": rid_for_fresh(r, vid), "arm": arm_of_vid(vid)})
    seen, out, dropped = {}, [], []
    for e in entries:
        d = e.get("digest")
        if not d:
            dropped.append({"id": e["id"], "reason": "no content digest recorded yet"})
            continue
        fp = effective_content_fingerprint(ctx, r, e["id"]) or d
        e["fingerprint"] = fp
        if fp in seen:
            dropped.append({"id": e["id"],
                            "reason": f"content-identical (same documents, ignoring file names "
                                      f"and bookkeeping text) to '{seen[fp]}' -- deduplicated"})
            continue
        seen[fp] = e["id"]
        out.append(e)
    return out, dropped


# --- the rebuild dispatch ---------------------------------------------------
# `postcheck()` has one handler per run kind (POSTCHECK_HANDLERS) and this table
# carries the materializer that re-creates that kind's sandbox. The two tables
# are the pipeline's contract with itself, and they had drifted: the AUDIT stage
# was added to the plan and to the postchecks but NOT to `rebuild_sandbox`'s
# if/elif chain, so the FIRST retry of an audit attempt died with "cannot
# rebuild unknown run kind 'audit'" and the run was abandoned after 1 of its 3
# attempts -- which also took that round's `a2` revision and all four
# integration runs down with it (root cnb-13to14-0923-1040-2482bdf, 2026-09-23).
# A dict keyed by kind removes the silent-drift failure mode: a kind that is in
# the plan but in neither table is refused BEFORE any agent is launched
# (see `run_kind_support_problems`).
def _rebuild_review(ctx: Ctx, rec: dict) -> None:
    """Rebuild session A or B of a split review (the run id names the part)."""
    r = int(rec["round"])
    part = "b" if str(rec.get("id")) == rid_review_b(r) else "a"
    materialize_review(ctx, r, part)


def _rebuild_judge(ctx: Ctx, rec: dict) -> None:
    r = int(rec["round"])
    field, _dropped = build_field(ctx, r)
    materialize_judges(ctx, r, field)


REBUILD_HANDLERS = {
    "a1": lambda ctx, rec: materialize_a1(ctx, int(rec["round"])),
    "rewrite": lambda ctx, rec: materialize_rewrite(ctx, int(rec["round"]), _vid_index(rec)),
    "review": _rebuild_review,
    "probe": lambda ctx, rec: materialize_probe(ctx, int(rec["round"])),
    "audit": lambda ctx, rec: materialize_audit(ctx, int(rec["round"])),
    "revise": lambda ctx, rec: materialize_revise(ctx, int(rec["round"]), _rec_vid(rec)),
    "integrate": lambda ctx, rec: materialize_integrate(ctx, int(rec["round"]), _vid_index(rec)),
    "judge": _rebuild_judge,
}


def rebuild_sandbox(ctx: Ctx, rec: dict) -> None:
    """Remove and re-materialize one sandbox (logs are stashed first).

    Refuses cleanly while an upstream run is not done: a Phase-2/3/4 sandbox is
    built FROM its upstream output, so materializing it early would either crash
    mid-way or (worse) rebuild it from content that is about to be replaced.
    `run` rebuilds each stage in dependency order; `retry` only rebuilds when the
    dependencies are already satisfied.
    """
    blocked = unmet_deps(ctx, rec)
    if blocked:
        raise DepsNotMet(f"cannot rebuild {rec['id']} yet: upstream run(s) not done: "
                         f"{', '.join(blocked)}")
    sb = ctx.sandbox_of(rec)
    if sb.exists():
        # The failed attempt's WHOLE sandbox is renamed to
        # `runs/<run>_try<N>_failed/` (it keeps the deliverables the postcheck
        # judged, its transcript and a record.json); the materializer below then
        # builds a fresh sandbox at the original path.
        try:
            move_failed_sandbox(ctx, rec)
        except OSError as e:                                    # noqa: BLE001
            print(f"  [warn] {rec['id']}: could not keep attempt {attempt_number(rec)}'s sandbox "
                  f"({e}); its diagnostics stay in state.json's attempts_log")
            rmtree_force(sb, ignore_errors=True)
    kind = rec["kind"]
    handler = REBUILD_HANDLERS.get(kind)
    if handler is None:
        # A PIPELINE BUG, not a property of this run: the operator's only way
        # out is a fixed pipeline, so the message says exactly that (and names
        # the archive that holds the attempt, which is already safely renamed).
        raise RuntimeError(
            f"cannot rebuild unknown run kind {kind!r} (this build knows "
            f"{', '.join(sorted(REBUILD_HANDLERS))}) -- PIPELINE BUG: no materializer is "
            f"registered for that kind, so `retry --run {rec.get('id')}` cannot work either "
            f"until it is fixed; the attempt's sandbox is preserved under "
            f"runs/{rec.get('id')}_try<N>_failed/")
    handler(ctx, rec)
    # The sandbox this record's post-revise chain described is GONE (it was
    # renamed to the attempt archive and a fresh tree materialized). Keeping
    # the audit/repair records would make the next accepted revision look
    # audited and suppress the chain on bytes that were never audited.
    rec.pop("revision_audit", None)
    rec.pop("revision_repair", None)
    rec.pop("revision_chain", None)
    rec["postcheck"] = None
    rec["last_error"] = None


def _rec_vid(rec: dict) -> str:
    """The round-local version a content-producing run creates.

    `produces` is written by the materializer; the run-id parse is the fallback
    for records written by hand (the test harnesses) or by an older tree.
    """
    vid = rec.get("produces")
    if vid:
        return str(vid)
    legacy = _vid_from_run_id(rec.get("id"))
    if legacy:
        return legacy
    raise RuntimeError(f"run {rec.get('id')!r} records no 'produces' version id and its id does "
                       f"not name one; it cannot be rebuilt (was the root created by an older "
                       f"pipeline?)")


def _vid_index(rec: dict) -> int:
    """The 1-based arm index encoded in a run's produced version id (w<k>/i<k>)."""
    vid = _rec_vid(rec)
    m = FRESH_VID_RE.match(vid)
    if not m or not (m.group(1) or m.group(3)):
        raise RuntimeError(f"run {rec.get('id')!r} produces {vid!r}, which carries no arm index")
    return int(m.group(1) or m.group(3))


def reset_run_record(rec: dict) -> None:
    """Clear a run's bookkeeping so the next attempt cannot inherit an old result."""
    rec.update({"status": "pending", "attempts": 0, "last_error": None, "postcheck": None,
                "scores": None, "summary": None})
    for k in ("stale_reason", "corpus_digest", "content_fingerprint", "captions",
              "document_set", "placeholders", "critical_findings_input",
              "target_digest", "field_digests",
              # The post-revise chain's records describe the package the
              # previous attempt produced. Every caller of this reset replaces
              # that package (a rebuilt sandbox, a revalidation reset), so the
              # chain must run again on the new one -- inheriting these keys
              # made a retried revise run look audited when it was not.
              "revision_audit", "revision_repair", "revision_chain",
              # The CLI session id names the attempt whose transcript is in THIS
              # sandbox (see capture_agent_session_id) -- and every caller of this
              # reset replaces that sandbox: `rebuild_sandbox` moves the old one
              # to `runs/<id>_try<N>_failed/` and materializes a fresh tree, and
              # the revalidation reset deletes it outright. A continuation that
              # adopted the id would resume a superseded round's conversation
              # inside the NEW sandbox, which is exactly the "the agent runs on
              # content the round no longer contains" failure the reset exists to
              # stop. `resume_attempts` stays: its keys are session ids, so an
              # entry can never be charged to a session that is not running.
              "agent_session_id"):
        rec.pop(k, None)


# ---------------------------------------------------------------------
# Input-freshness revalidation (in-round retries).
#
# materialize_a1() digest-checks the round base before reusing it, but the
# rewrite/review/revise/integrate/judge materializers only ever CREATE an input
# when it is missing. `retry` invalidates COMPLETED rounds only, so after an
# upstream run of the current round is retried, a downstream sandbox keeps the
# superseded input bytes -- and the next materialization re-hashes those bytes
# into a fresh, self-consistent inputs_manifest, so no postcheck sees it either.
# An agent would then run on content the round no longer contains. These
# helpers re-derive each input area from the CURRENT upstream and reset the runs
# that drifted (together with their dependents).
# ---------------------------------------------------------------------

PRIOR_ROUND_FILES = ("findings.json", "findings.md", "findings_extra.json",
                     "findings_extra.md", "new_sweeps.md", "round2_summary.md")


def _review_copy_mismatch(ctx: Ctx, r: int, sb: Path, upstream_dir: Path):
    """None when the sandbox's frozen review copy is what this round must hold.

    The audit and revision sandboxes receive the review WITH the probe findings
    merged into `round2/findings_extra.json` (`merge_probe_into_review_copy`),
    so comparing the whole area against the raw upstream review marked every
    such sandbox stale as soon as the probe filed anything -- each new
    invocation reset the audit and blocked the revisers. Compare the area
    file-by-file and allow EXACTLY that one file to differ, provided it equals
    the merge this build computes from the CURRENT probe run: a probe retry that
    changes the list still drifts (and resets the downstream sandboxes, which is
    the point), and a probe run that is not done means the copy is out of date.
    """
    prec = ctx.run(rid_probe(r))
    if probe_review_of(ctx) != "off" and prec is not None \
            and str(prec.get("status") or "") != "done":
        return (f"the probe run {rid_probe(r)} is not done: the findings this round's auditor "
                f"and revisers consume will change")
    cur = hash_manifest(sb / REVIEW_DIR).get("files") or {}
    want = hash_manifest(upstream_dir).get("files") or {}
    rel = "round2/findings_extra.json"
    differing = sorted({k for k in set(cur) | set(want) if cur.get(k) != want.get(k)})
    if not differing:
        # Byte-identical to the upstream review: nothing to explain.
        return None
    others = [k for k in differing if k != rel]
    if others:
        return (f"{REVIEW_DIR}/ no longer matches its current upstream source "
                f"({', '.join(others[:3])})")
    expected, _rows, _remap = probe_merged_review_doc(ctx, r, probe_review_upstream_doc(ctx, r))
    actual = read_json(sb / REVIEW_DIR / rel, revive=False, lenient=True)
    if expected is None or actual != expected:
        return (f"{REVIEW_DIR}/{rel} no longer matches the frozen list this round's auditor "
                f"and revisers must consume (the probe findings changed)")
    return None


def _journal_staged_freshness_problems(ctx: Ctx, r: int, sb: Path) -> list:
    """Drift of a sandbox's `feedback/` and `concerns/` copies.

    Those areas are read-only evidence copied from the feedback/concerns run.
    A feedback retry re-stages them from the canonical source, but a downstream
    sandbox keeps the copy it was born with and its own recorded manifest still
    matches that stale copy -- so nothing marked it stale. Compare the areas
    against the CURRENT ledger run, exactly like the review/base checks above.
    """
    try:
        src_sb = _journal_concern_source(ctx, r)
    except RuntimeError:
        return ["the journal feedback/concerns run is not done"]
    probs = []
    for area in ("feedback", "concerns"):
        src = src_sb / area
        if not src.is_dir():
            continue
        dst = sb / area
        if not dst.is_dir():
            probs.append(f"{area}/ is missing (the feedback/concerns run carries it)")
        elif not manifests_equal(hash_manifest(dst, follow_dir_links=True),
                                  hash_manifest(src, follow_dir_links=True)):
            probs.append(f"{area}/ no longer matches the current feedback/concerns ledger")
    return probs


def _input_freshness_problems(ctx: Ctx, rec: dict) -> list:
    """Input-area drift for ONE run, measured against its CURRENT upstream."""
    kind, r = rec["kind"], int(rec["round"])
    sb = ctx.sandbox_of(rec)
    src_ok = bool(ctx.source_manifest)

    def mismatch(area: str, expected: dict):
        p = area_dir(sb, area)
        if not p.is_dir():
            return f"{area}/ is missing (upstream content changed)"
        # follow_dir_links: a sandbox's evidence areas are symlinks to the
        # root's canonical copy (see ensure_pristine_input).
        if not manifests_equal(hash_manifest(p, follow_dir_links=True), expected):
            return f"{area}/ no longer matches its current upstream source"
        return None

    a1 = ctx.run(rid_a1(r))
    probs = []
    # A session that carries the staged feedback/ledger must see the CURRENT
    # letter, not the copy frozen before a feedback retry.
    if (journal_has_feedback(ctx) and kind not in ("feedback", "concerns")
            and ((sb / "feedback").is_dir() or (sb / "concerns").is_dir())):
        probs.extend(_journal_staged_freshness_problems(ctx, r, sb))
    if kind == "rewrite":
        if a1 is not None and a1.get("status") == "done":
            probs.append(mismatch("base", hash_manifest(ctx.sandbox_of(a1) / "base")))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
    elif kind == "review":
        if a1 is not None and a1.get("status") == "done":
            probs.append(mismatch("base", hash_manifest(ctx.sandbox_of(a1) / "base")))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
        prior = prior_review_dir(ctx, r)
        if prior is not None and (sb / "prior_round").is_dir():
            expected = {name: sha256_file(prior / name) for name in PRIOR_ROUND_FILES
                        if (prior / name).is_file()}
            if expected and hash_manifest(sb / "prior_round").get("files") != expected:
                probs.append("prior_round/ no longer matches the archived prior review")
        prior_audit_obs = None
        if r > 1:
            audit_rec = ctx.run(rid_audit(r - 1))
            if audit_rec is not None:
                cand = ctx.sandbox_of(audit_rec) / "audit" / "UNRESOLVED.md"
                if cand.is_file():
                    prior_audit_obs = cand
        prior_audit_copy = sb / "prior_audit" / "UNRESOLVED.md"
        if prior_audit_obs is not None:
            if (not prior_audit_copy.is_file()
                    or sha256_file(prior_audit_copy) != sha256_file(prior_audit_obs)):
                probs.append("prior_audit/UNRESOLVED.md no longer matches the prior audit")
        elif (sb / "prior_audit").is_dir():
            probs.append("prior_audit/ is present but the prior audit no longer has observations")
        # Session B's frozen input is session A's review/ OUTPUT. Retrying A
        # changes it, but B's own review_a/ still matches the manifest B recorded
        # when it was built, so the old checks above never saw the drift. Compare
        # the copy against A's CURRENT review/ (the audit and every reviser
        # consume B's merged list, so a stale copy would silently freeze an old
        # finding set).
        if review_split_of(ctx) != "off" and rec.get("id") == rid_review_b(r):
            a_rec = ctx.run(rid_review(r))
            if a_rec is None or a_rec.get("status") != "done":
                probs.append("upstream review session A is not done")
            elif not manifests_equal(hash_manifest(sb / "review_a"),
                                     hash_manifest(ctx.sandbox_of(a_rec) / REVIEW_DIR)):
                probs.append("review_a/ no longer matches session A's current review")
    elif kind == "revise":
        if a1 is not None and a1.get("status") == "done":
            probs.append(mismatch("base", hash_manifest(ctx.sandbox_of(a1) / "base")))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
        # A scoped (major/minor) revision consumes the CONCERNS run's finding
        # list, not a general review: pointing this check at the review run
        # would mark every scoped revision stale on every re-run.
        # With --review-split the revise sandbox holds SESSION B's frozen review
        # (materialize_revise copies rid_review_b), so hashing session A's dir
        # made every revise arm look stale on every re-entry.
        rev_rid = (rid_concerns(r) if journal_is_scoped(ctx)
                   else rid_review_b(r) if review_split_of(ctx) != "off" else rid_review(r))
        rev_rec = ctx.run(rev_rid)
        if rev_rec is None or rev_rec.get("status") != "done":
            probs.append("upstream review/concerns run is not done")
        else:
            # BOTH revise paths receive the probe merge (materialize_revise
            # calls merge_probe_into_review_copy): a scoped revise on the
            # concerns review, a general revise on the review. Compare against
            # the merged copy in either case -- the old scoped-only branch left
            # the general path with no review check at all after F004.
            probs.append(_review_copy_mismatch(ctx, r, sb,
                                               ctx.sandbox_of(rev_rec) / REVIEW_DIR))
    elif kind == "probe":
        # The probe reads the round base and the pristine original, like every
        # other round-family session; its own provenance record is written by
        # the postcheck, so only the INPUT areas are drift-checked here.
        if a1 is not None and a1.get("status") == "done":
            probs.append(mismatch("base", hash_manifest(ctx.sandbox_of(a1) / "base")))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
    elif kind in ("feedback", "concerns"):
        if a1 is not None and a1.get("status") == "done":
            probs.append(mismatch("base", hash_manifest(ctx.sandbox_of(a1) / "base")))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
    elif kind == "response":
        tgt_rel = str(rec.get("target_dir") or "").strip()
        if tgt_rel:
            tgt = ctx.root / tgt_rel
            if tgt.is_dir() and (sb / "target").is_dir():
                # The sandbox target/ is copied with exclude_top=("work",) and
                # skip_aux=True; comparing it with the FULL source manifest made
                # the mismatch permanent, so every re-entry reset a completed
                # response run.
                want = hash_manifest(tgt, exclude_top=("work",))
                files = {rel: dig for rel, dig in (want.get("files") or {}).items()
                         if not _is_aux_doc(Path(rel).name)}
                probs.append(mismatch("target", {"files": files, "count": len(files)}))
        src_rec = ctx.run(rid_concerns(r) if journal_is_scoped(ctx) else rid_feedback(r))
        if src_rec is not None and src_rec.get("status") == "done" \
                and (sb / "concerns").is_dir():
            probs.append(mismatch("concerns",
                                  hash_manifest(ctx.sandbox_of(src_rec) / "concerns")))
    elif kind == "audit":
        # The auditor consumes the round's base AND the frozen review, and its
        # whole product is a disposition OF that review. If the review (or the
        # base) is retried while an audit sandbox already exists, the sandbox
        # would be judged against -- and re-hash -- a review the revisers will
        # never see; both areas are re-derived here like the revise arm's.
        if a1 is not None and a1.get("status") == "done":
            probs.append(mismatch("base", hash_manifest(ctx.sandbox_of(a1) / "base")))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
        merge_rid = rid_review_b(r) if review_split_of(ctx) != "off" else rid_review(r)
        rv = ctx.run(merge_rid)
        if rv is None or rv.get("status") != "done":
            probs.append("upstream review run is not done")
        else:
            probs.append(_review_copy_mismatch(ctx, r, sb,
                                               ctx.sandbox_of(rv) / REVIEW_DIR))
    elif kind == "integrate":
        self_id = rec.get("self_id")
        others = list(rec.get("other_ids") or [])
        if not self_id or not others:
            probs.append(f"{rec['id']} does not record the pool it integrates "
                         f"(self_id/other_ids); it cannot be revalidated")
            return [p for p in probs if p]
        probs.append(mismatch("self", corpus_manifest(ctx, r, self_id)))
        if src_ok:
            probs.append(mismatch(pristine_dirname(sb), ctx.source_manifest))
        others_dir = sb / "others"
        if not others_dir.is_dir():
            probs.append("others/ is missing (upstream content changed)")
        else:
            expected = {}
            for vid in others:
                for rel, dig in (corpus_manifest(ctx, r, vid).get("files") or {}).items():
                    expected[f"{vid}/{rel}"] = dig
            if hash_manifest(others_dir).get("files") != expected:
                probs.append("others/ no longer matches the current pool corpora")
    elif kind == "judge":
        # A judge view is ANONYMIZED (build_judge_view), so it cannot be
        # compared by path: the invariant is the CONTENT multiset of each view
        # AFTER the view transform (rewritten references, sanitized metadata).
        # A tampered view still differs here (and the path-keyed
        # inputs_manifest snapshot catches any later edit as well).
        _seed = judge_view_seed_for(ctx, r, rec.get("target_id"), rec.get("judge_index"))

        def view_mismatch(area: str, vid: str):
            p = sb / area
            if not p.is_dir():
                return f"{area}/ is missing (upstream content changed)"
            suffix = area.split("/", 1)[1] if area.startswith("field/") else area
            if judge_view_digest(p) != expected_view_digest(ctx, r, vid, f"{_seed}|{suffix}"):
                return f"{area}/ no longer carries the current corpus of '{vid}'"
            return None

        tid = rec.get("target_id")
        if tid:
            probs.append(view_mismatch("target", tid))
        labels = rec.get("label_map") or {}
        for label, vid in sorted(labels.items()):
            probs.append(view_mismatch(f"field/{label}", vid))
    return [p for p in probs if p]


def revalidate_round_inputs(ctx: Ctx, r: int) -> list:
    """Reset this round's runs whose frozen inputs drifted from their upstream.

    Called by `run` before a round is staged. A reset run is marked stale so the
    staging loop rebuilds it in dependency order; the reset also invalidates its
    DEPENDENTS structurally, because their inputs are derived from it. Failed
    runs are left to the retry policy.
    """
    m, n = round_counts(ctx, r)
    pool = round_pool_ids(m, n)
    rewrite_ids = [rid_for_fresh(r, v) for v in pool if arm_of_vid(v) == "rewrite"]
    revise_ids = [rid_for_fresh(r, v) for v in pool if arm_of_vid(v) == "revise"]
    integrate_ids = [rid_for_fresh(r, v) for v in round_integrated_run_ids(ctx, r, m, n)]
    jmode = journal_mode_of(ctx)
    j_feedback = rid_feedback(r) if journal_has_feedback(ctx) and not journal_is_scoped(ctx) \
        else None
    j_concerns = rid_concerns(r) if journal_is_scoped(ctx) else None
    j_response = rid_response(r) if ctx.run(rid_response(r)) is not None else None
    # review -> AUDIT -> revise: the auditor freezes a COPY of the review and
    # every reviser consumes the auditor's disposition, so a reset upstream must
    # reach the audit sandbox too (it is not an arm of the pool, so nothing else
    # in this function would ever look at it).
    audit_ids = [rid_audit(r)] if ctx.run(rid_audit(r)) is not None else []
    probe_ids = [rid_probe(r)] if ctx.run(rid_probe(r)) is not None else []
    order = ((rewrite_ids + ([rid_review(r)] if n else []) + probe_ids + audit_ids
              + revise_ids + integrate_ids)
             + ([j_feedback] if j_feedback else []) + ([j_concerns] if j_concerns else [])
             + ([j_response] if j_response else []))
    if n and review_split_of(ctx) != "off":
        # INSERT session B; keep the journal stages in the order. The previous
        # assignment REPLACED the whole list, so a `--review-split` run in a
        # journal mode never revalidated a stale feedback/concerns/response
        # sandbox: the drift survived and the response letter stayed "done".
        order = (rewrite_ids + [rid_review(r), rid_review_b(r)] + probe_ids + audit_ids
                 + revise_ids + integrate_ids
                 + ([j_feedback] if j_feedback else [])
                 + ([j_concerns] if j_concerns else [])
                 + ([j_response] if j_response else []))
    judge_ids = [rec["id"] for rec in ctx.runs(kind="judge", round_no=r)]
    # Any arm's content change invalidates every judge session of the round (the
    # panel scores the whole field), and every pool member feeds every
    # integration run that takes it as a donor.
    dependents = {rid_a1(r): rewrite_ids + ([rid_review(r)] if n else []) + probe_ids,
                  rid_review(r): list(audit_ids) + list(revise_ids)}
    for _pid in probe_ids:
        # The auditor and every reviser consume the merged review copy, so a
        # reset probe must reach them (their frozen list is derived from it).
        dependents[_pid] = list(audit_ids) + list(revise_ids)
    for _aid in audit_ids:
        # The revisers' sandboxes carry the auditor's `audit/` copy.
        dependents[_aid] = list(revise_ids)
    if j_feedback:
        dependents.setdefault(rid_a1(r), []).append(j_feedback)
        dependents[j_feedback] = (list(rewrite_ids) + ([rid_review(r)] if n else []))
    if j_concerns:
        dependents.setdefault(rid_a1(r), []).append(j_concerns)
        dependents[j_concerns] = list(revise_ids)
        for rid in revise_ids:
            dependents.setdefault(rid, [])
            if j_response:
                dependents[rid].append(j_response)
    if j_response and jmode in (JOURNAL_MODE_TRANSFER, JOURNAL_MODE_RESUBMIT):
        # The post-round response describes the final package: any pool member
        # changing invalidates it.
        for vid in pool:
            if vid != A1_ID:
                dependents.setdefault(rid_for_fresh(r, vid), []).append(j_response)
        for iid in integrate_ids:
            dependents.setdefault(iid, []).append(j_response)
        if j_feedback:
            dependents.setdefault(j_feedback, []).append(j_response)
    if n and review_split_of(ctx) != "off":
        # B's frozen input is A's review/ output, so resetting A resets B too.
        dependents[rid_review(r)] = [rid_review_b(r)] + dependents[rid_review(r)]
        dependents[rid_review_b(r)] = list(audit_ids) + list(revise_ids)
    for k_idx, vid in enumerate(pool):
        if vid == A1_ID:
            continue
        rid = rid_for_fresh(r, vid)
        consumers = [rid_for_fresh(r, integrate_vid(j + 1))
                     for j, src in enumerate(pool) if src != vid]
        # APPEND, never overwrite: the resubmit-mode branch above already
        # declared the response letter a dependent of every pool member (it
        # describes the final package), and a plain assignment would discard it
        # so a retried arm left a stale letter behind.
        dependents[rid] = dependents.get(rid, []) + consumers + judge_ids
    for iid in integrate_ids:
        # APPEND, never overwrite: the resubmit/transfer branch above already
        # declared the response letter a dependent of every integration run
        # (the letter describes the package the integrators produced), and a
        # plain assignment discarded that edge, so a retried integration run
        # left a stale response letter behind. Same bug the pool-member loop
        # below documents.
        dependents[iid] = dependents.get(iid, []) + list(judge_ids)
    reset_ids = []

    def reset(rid: str, why: str) -> None:
        if rid in reset_ids:
            return
        rec = ctx.run(rid)
        if rec is None or rec.get("kind") == "a1":
            return
        reset_ids.append(rid)
        sb = ctx.sandbox_of(rec)
        if sb.is_dir():
            stash_logs(sb, ctx.runs_dir / LOGS_DIRNAME, rid, attempt=attempt_number(rec))
            rmtree_force(sb, ignore_errors=True)
        reset_run_record(rec)
        rec["status"] = "stale"
        rec["stale_reason"] = why
        rec["last_error"] = f"stale: {why}"
        ctx.log("revalidate-reset", rid, why[:200])
        print(f"[run] r{r} revalidate: {rid} reset ({why})")
        for dep in dependents.get(rid, []):
            reset(dep, f"upstream {rid} was reset")

    for rid in order + judge_ids:
        rec = ctx.run(rid)
        if rec is None or rid in reset_ids:
            continue
        if rec.get("status") not in ("done", "pending"):
            continue                    # failed/stale runs are rebuilt by the staging loop
        if not ctx.sandbox_of(rec).is_dir():
            continue                    # nothing on disk to go stale
        probs = _input_freshness_problems(ctx, rec)
        if probs:
            reset(rid, "; ".join(probs)[:300])
    if reset_ids:
        ctx.save_state()
    return reset_ids
