#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for the 2026-11-14 fix-bugs wave, group J (state/corpus).

Each check names the verified finding it guards:
  F97   pipeline-written review JSON is read back with revive=True
  F98   a failed sandbox is archived when --root traverses a symlink
  F99   compact_state's `format_fix.full` names the file the writer creates
  F100  prior-audit observations use ONE predicate (materializer + freshness)
  F101  a null `log`/`run_logs` in state.json is reported, not adopted
  F102  upstream_deps("judge") covers every arm materialize_judges requires
  F103  materialize_a1 never trusts a base/ it cannot verify against a source
  F104  an out-of-block probe id is remapped into the reserved X-9xx block
  F105  a judge sandbox created without PROMPT.md prunes stale field/<label>/
  F106  the aggregate verifier budget also bounds the running verifier
  F107  record_attempt stores `last_error`, the key attempt_history_lines reads

F96 the shipped revision_token.py and the pipeline normalize a remote URL
byte-identically (the URL is never read as a version-token reference).

Self-contained and fast: every probe builds a throwaway root under
tempfile.mkdtemp(). Run: python3 .paper_test/test_fix_bugs_20261114_J.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = Path(os.environ.get("PAPER_WS") or HERE.parent)
FAILED = []
TMPDIRS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[ok ] " if ok else "[FAIL] ") + name
          + (f"  -- {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def group(name: str, fn) -> None:
    print()
    print(f"== {name} ==")
    try:
        fn()
    except Exception as exc:                                       # noqa: BLE001
        check(f"{name} (unexpected {type(exc).__name__})", False, str(exc)[:300])


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = load("paper_fixbugs_J", WS / "paper_pipeline.py")

CFG = {"rounds": 2, "judges": 1, "rewrites": [1], "revises": [1], "audit": "on",
       "review_split": "off", "placeholder_lookup": "off", "caption_limit": 0,
       "format_policy": {}, "zotero": "off", "vs_original_rule": "median",
       "cold_start_review": "on", "guided_review": "on"}


def build_root(tmp: Path, rounds: int = 2):
    source = tmp / "source"
    write(source / "manuscript-b.md", "title\n")
    write(source / "refs-b.bib", "refs\n")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(source, root / "non_revised")
    pristine = root / "non_revised"
    ctx = nb.Ctx(root)
    ctx.cfg = dict(CFG, rounds=rounds)
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "jsalt", "config": ctx.cfg, "source": str(source)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    nb.write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.save_state()
    return ctx


# ---------------------------------------------------------------------------
# F97 -- revive=True on pipeline-written frozen review JSON
# ---------------------------------------------------------------------------
def test_f97() -> None:
    tmp = scratch("fixJ-f97-")
    ctx = build_root(tmp, rounds=1)
    row = {"id": "X-901", "severity": "minor", "category": "bug",
           "location": "ms.tex:1", "explanation": "NaN"}
    review_rec = ctx.register(nb.rid_guided_review(1), "guided_review", 1,
                              f"runs/{nb.rid_guided_review(1)}")
    review_rec["status"] = "done"
    rev_sb = ctx.sandbox_of(review_rec)
    nb.write_json_atomic(rev_sb / nb.GUIDED_REVIEW_DIR / "round2" / "findings_extra.json",
                         {"findings": []})
    cold = ctx.register(nb.rid_cold_start_review(1), "cold_start_review", 1,
                        f"runs/{nb.rid_cold_start_review(1)}")
    cold["status"] = "done"
    # The upstream probe file is AGENT-written: the session writes plain JSON, so
    # its exact "NaN" stays the three-character string. Only the pipeline's own
    # write_json_atomic NUL-escapes a sentinel spelling.
    cold_file = ctx.sandbox_of(cold) / nb.COLD_START_FINDINGS_REL
    cold_file.parent.mkdir(parents=True, exist_ok=True)
    cold_file.write_text(json.dumps({"findings": [row]}), encoding="utf-8")
    # The synthesized view (--no-guided-review) is pipeline-written; its row
    # carries the exact string "NaN" that write_json_atomic NUL-escapes.
    target_sb = tmp / "synth_sandbox"
    nb.write_json_atomic(target_sb / nb.GUIDED_REVIEW_DIR / "round2" / "findings_extra.json",
                         {"findings": [row]})
    probs = nb._synthesized_review_problems(ctx, 1, target_sb)
    check("F97 the synthesized frozen view compares equal (no NUL sentinel drift)",
          probs == [], str(probs))

    # The cold-start merge is idempotent: a second call must SKIP. Merge into a
    # DOWNSTREAM sandbox's copy (what production does); the source review
    # sandbox is frozen and is never the merge target.
    merge_sb = tmp / "merge_sandbox"
    nb.write_json_atomic(merge_sb / nb.GUIDED_REVIEW_DIR / "round2" / "findings_extra.json",
                         {"findings": []})
    target_copy = merge_sb / nb.GUIDED_REVIEW_DIR / "round2" / "findings_extra.json"
    before = target_copy.read_bytes()
    merged = nb.merge_cold_start_into_review_copy(ctx, 1, merge_sb)
    check("F97 the merge wrote the row", merged.get("rows") == 1, str(merged))
    after_first = target_copy.read_bytes()
    second = nb.merge_cold_start_into_review_copy(ctx, 1, merge_sb)
    after_second = target_copy.read_bytes()
    check("F97 the second merge is a no-op (skipped)", second.get("skipped") is True,
          str(second))
    check("F97 the frozen file is not rewritten on the idempotent call",
          after_first == after_second)
    check("F97 the first merge did change the file", before != after_first)


# ---------------------------------------------------------------------------
# F98 -- symlinked --root still archives the failed sandbox
# ---------------------------------------------------------------------------
def test_f98() -> None:
    tmp = scratch("fixJ-f98-")
    real = tmp / "realroot"
    (real / "runs" / "r1_a1").mkdir(parents=True)
    write(real / "runs" / "r1_a1" / "x.txt", "x")
    link = tmp / "linkroot"
    link.symlink_to(real, target_is_directory=True)
    ctx = nb.Ctx(link)
    rec = {"id": "r1_a1", "kind": "a1", "round": 1, "sandbox": "runs/r1_a1",
           "attempts": 0, "attempts_log": []}
    try:
        dest = nb.move_failed_sandbox(ctx, rec)
        ok, detail = True, str(dest)
    except Exception as exc:                                       # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    check("F98 move_failed_sandbox survives a symlinked --root", ok, detail)
    check("F98 the attempt archive is on disk",
          (real / "runs" / "r1_a1_try1_failed" / "record.json").is_file())
    record = json.loads((real / "runs" / "r1_a1_try1_failed" / "record.json").read_text())
    check("F98 the archived record carries root-relative paths",
          record.get("sandbox") == "runs/r1_a1"
          and record.get("moved_to") == "runs/r1_a1_try1_failed", str(record))


# ---------------------------------------------------------------------------
# F99 -- compact_state points at the artifact FORMAT_FIX_<label>.json
# ---------------------------------------------------------------------------
def test_f99() -> None:
    tmp = scratch("fixJ-f99-")
    root = tmp / "root"
    sb = root / "runs" / "r1_a1"
    sb.mkdir(parents=True)
    nb.write_json_atomic(sb / "FORMAT_FIX_r1_a1.json",
                         {"documents": [{"file": "ms.docx", "changes": ["x"]}]})
    st = {"runs": {"r1_a1": {"id": "r1_a1", "sandbox": "runs/r1_a1",
                             "format_fix": {"label": "r1_a1",
                                            "documents": [{"file": "ms.docx",
                                                           "changes": ["x"]}]}}}}
    nb.compact_state(st)
    ff = st["runs"]["r1_a1"]["format_fix"]
    check("F99 the compacted summary still carries the document COUNT",
          ff.get("documents") == 1, str(ff))
    check("F99 full names the real FORMAT_FIX_<label>.json artifact",
          ff.get("full") == "runs/r1_a1/FORMAT_FIX_r1_a1.json"
          and (root / ff["full"]).is_file(), str(ff.get("full")))


# ---------------------------------------------------------------------------
# F100 -- a failed prior audit no longer makes the review permanently stale
# ---------------------------------------------------------------------------
def test_f100() -> None:
    tmp = scratch("fixJ-f100-")
    ctx = build_root(tmp, rounds=2)
    shutil.copytree(ctx.pristine, ctx.root / "runs" / nb.rid_a1(2) / "base")
    a1 = ctx.register(nb.rid_a1(2), "a1", 2, f"runs/{nb.rid_a1(2)}",
                      source_id=nb.ORIGINAL_ID)
    a1["status"] = "done"
    audit_sb = ctx.root / "runs" / nb.rid_audit(1)
    write(audit_sb / "audit" / "UNRESOLVED.md", "- observation: something is wrong\n")
    audit_rec = ctx.register(nb.rid_audit(1), "audit", 1, f"runs/{nb.rid_audit(1)}")
    audit_rec["status"] = "failed"
    review = nb.materialize_review(ctx, 2)
    check("F100 the failed audit's observations are NOT copied",
          not (ctx.sandbox_of(review) / "prior_audit").is_dir())
    probs = nb._input_freshness_problems(ctx, review)
    check("F100 the freshness check agrees with the materializer (no prior_audit drift)",
          [p for p in probs if "prior_audit" in p] == [], str(probs))
    # A DONE audit's observations ARE copied and then match the freshness check.
    audit_rec["status"] = "done"
    review = nb.materialize_review(ctx, 2)
    check("F100 a done audit's observations are copied",
          (ctx.sandbox_of(review) / "prior_audit" / "UNRESOLVED.md").is_file())
    probs = nb._input_freshness_problems(ctx, review)
    check("F100 a done audit's copied observations do not drift",
          [p for p in probs if "prior_audit" in p] == [], str(probs))


# ---------------------------------------------------------------------------
# F101 -- null log/run_logs is a clean refusal, not a later AttributeError
# ---------------------------------------------------------------------------
def test_f101() -> None:
    def load_probe(kind: str, state: dict) -> tuple:
        tmp = scratch(f"fixJ-f101-{kind}-")
        root = tmp / "root"
        (root / "runs").mkdir(parents=True)
        (root / "reports").mkdir()
        nb.write_json_atomic(root / "pipeline_config.json", {})
        nb.write_json_atomic(root / "state.json", state)
        ctx = nb.Ctx(root)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                ctx.load(need_cfg=False)
        except SystemExit as exc:
            return int(exc.code or 0), err.getvalue(), ctx
        return 0, err.getvalue(), ctx

    base = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": []}
    rc, err, _ = load_probe("log", dict(base, log=None))
    check("F101 a null `log` is refused at load with a named cause",
          rc != 0 and "'log' must be a list" in err, f"rc={rc} {err[-200:]}")
    rc, err, _ = load_probe("runlogs", dict(base, log=[], run_logs=None))
    check("F101 a null `run_logs` is refused at load with a named cause",
          rc != 0 and "'run_logs' must be a list" in err, f"rc={rc} {err[-200:]}")
    rc, err, ctx = load_probe("ok", dict(base, log=[]))
    ctx.log("probe", "r1_a1", "x")
    check("F101 a valid registry still loads and logs",
          rc == 0 and isinstance(ctx.state.get("log"), list)
          and ctx.state["log"][-1].get("event") == "probe", f"rc={rc} {err[-200:]}")


# ---------------------------------------------------------------------------
# F102 -- judge deps are the same set materialize_judges requires
# ---------------------------------------------------------------------------
def test_f102() -> None:
    ctx = build_root(scratch("fixJ-f102-"), rounds=1)
    rec = {"id": "r1_judge_tok_j1", "kind": "judge", "round": 1,
           "target_id": "a1", "field_ids": ["w1"], "judge_index": 1}
    deps = nb.upstream_deps(rec, ctx)
    need = [nb.rid_for_fresh(1, v) for v in nb.round_produced_ids(ctx, 1)]
    check("F102 upstream_deps('judge') covers every round arm",
          [x for x in need if x not in deps] == [], f"deps={deps} need={need}")
    check("F102 the judge's own target and field members stay listed",
          "r1_w1" in deps, str(deps))
    check("F102 no dependency is listed twice", len(deps) == len(set(deps)), str(deps))


# ---------------------------------------------------------------------------
# F103 -- no recorded source digest => verify the base against the SOURCE
# ---------------------------------------------------------------------------
def test_f103() -> None:
    ctx = build_root(scratch("fixJ-f103-"), rounds=1)
    ctx.state["original_digest"] = None
    base = ctx.root / "runs" / nb.rid_a1(1) / "base"
    shutil.rmtree(base)
    base.mkdir(parents=True)
    write(base / "tampered.md", "not the original\n")
    rec = nb.materialize_a1(ctx, 1)
    want = nb.manifest_digest(nb.manifest_for_sources([(ctx.pristine, "", ())]))
    check("F103 the stale base is rebuilt from the source",
          not (base / "tampered.md").exists()
          and (base / "manuscript-b.md").is_file())
    check("F103 base_source_digest records the source digest, not None",
          rec.get("base_source_digest") == want, str(rec.get("base_source_digest")))


# ---------------------------------------------------------------------------
# F104 -- out-of-block probe ids are remapped into the reserved block
# ---------------------------------------------------------------------------
def test_f104() -> None:
    rows = [{"id": "X-101", "severity": "minor"}, {"id": "X-901", "severity": "minor"}]
    out, remap = nb.cold_start_findings_for_merge([], rows)
    ids = [r["id"] for r in out]
    check("F104 an out-of-block id (X-101) is remapped", "X-101" not in ids, str(ids))
    check("F104 every emitted id is in the reserved X-9xx block",
          all(nb.COLD_START_ID_RE.match(i) for i in ids), str(ids))
    out_ok, _ = nb.cold_start_findings_for_merge([], [{"id": "X-901"}])
    check("F104 a valid X-901 row keeps its id when free",
          [r["id"] for r in out_ok] == ["X-901"], str([r["id"] for r in out_ok]))
    out2, remap2 = nb.cold_start_findings_for_merge(["X-901"],
                                                    [{"id": "X-901"}, {"id": "X-101"}])
    check("F104 used ids and out-of-block ids both move to free slots",
          [r["id"] for r in out2] == ["X-902", "X-903"], str([r["id"] for r in out2]))


# ---------------------------------------------------------------------------
# F105 -- an interrupted judge materialization prunes stale field/<label>/
# ---------------------------------------------------------------------------
def test_f105() -> None:
    tmp = scratch("fixJ-f105-")
    ctx = build_root(tmp, rounds=1)
    rid = nb.rid_judge(1, "tokw1", 1)
    sb = ctx.root / "runs" / rid
    write(sb / "field" / "STALE_LABEL" / "ms.md", "an old opponent\n")
    names = ("round_judges", "judge_enabled", "round_produced_ids", "_require_done",
             "judge_token_for", "sample_labels", "ensure_judge_view",
             "seed_template_visuals", "seed_format_policy_file", "_copy_session_tools",
             "judge_prompt", "judge_view_seed_for", "judge_salt_of", "stamp_tree",
             "leftovers_present")
    orig = {n: getattr(nb, n) for n in names}
    try:
        nb.round_judges = lambda ctx_, r: 1
        nb.judge_enabled = lambda ctx_, r, vid, j: True
        nb.round_produced_ids = lambda ctx_, r: ["w1"]
        nb._require_done = lambda ctx_, rid_, why: {"status": "done"}
        nb.judge_token_for = lambda ctx_, r, vid: "tok" + str(vid)
        nb.sample_labels = lambda r, vid, j, k, salt=None: ["L1"]
        nb.ensure_judge_view = lambda ctx_, r, vid, dst, stamp, seed: (
            dst.mkdir(parents=True, exist_ok=True),
            (dst / "ms.md").write_text(f"{vid}\n", encoding="utf-8"))
        nb.seed_template_visuals = lambda ctx_, sb_: None
        nb.seed_format_policy_file = lambda ctx_, sb_: None
        nb._copy_session_tools = lambda sb_, stamp=None, include_driver=True: None
        nb.judge_prompt = lambda *a, **k: "prompt\n"
        nb.judge_view_seed_for = lambda ctx_, r, vid, j: "seed"
        nb.judge_salt_of = lambda ctx_: "salt"
        nb.stamp_tree = lambda p, stamp=None: None
        nb.leftovers_present = lambda ctx_, rec: False
        field = [{"id": "w1"}, {"id": "a1"}]
        ctx.register(rid, "judge", 1, f"runs/{rid}", target_id="w1", judge_index=1,
                     label_map={}, field_ids=["a1"])
        nb.materialize_judges(ctx, 1, field)
        entries = sorted(p.name for p in (sb / "field").iterdir())
        manifest = ((ctx.run(rid) or {}).get("inputs_manifest") or {}).get("field") or {}
        check("F105 the stale field/<label>/ is pruned", entries == ["L1"], str(entries))
        check("F105 inputs_manifest lists only the current labels",
              sorted((manifest.get("files") or {})) == ["L1/ms.md"],
              str(sorted((manifest.get("files") or {}))))
    finally:
        for n, fn in orig.items():
            setattr(nb, n, fn)


# ---------------------------------------------------------------------------
# F106 -- the aggregate budget bounds the verifier that is already running
# ---------------------------------------------------------------------------
def test_f106() -> None:
    tmp = scratch("fixJ-f106-")
    sb = tmp / "sb"
    (sb / nb.COLD_START_DIR / "scripts").mkdir(parents=True)
    write(sb / nb.COLD_START_DIR / "scripts" / "v.py",
          "import time\nprint('x')\ntime.sleep(0.8)\nprint('deadbeef')\n")
    old = (nb.COLD_START_REPRO_TIMEOUT, nb.COLD_START_REPRO_TOTAL_BUDGET)
    nb.COLD_START_REPRO_TIMEOUT, nb.COLD_START_REPRO_TOTAL_BUDGET = 5.0, 0.3
    try:
        t0 = time.monotonic()
        rep = nb.cold_start_reproduction(
            sb, [{"id": "X-901", "verifier": {
                "script": "cold_start_review/scripts/v.py", "computed": "deadbeef"}}])
        elapsed = time.monotonic() - t0
    finally:
        nb.COLD_START_REPRO_TIMEOUT, nb.COLD_START_REPRO_TOTAL_BUDGET = old
    result = (rep.get("results") or [{}])[0]
    check("F106 a verifier started inside the budget is cut off at the REMAINING budget",
          elapsed < 0.7, f"{elapsed:.2f}s (script sleeps 0.8s)")
    check("F106 the cut-off is a timeout failure, not a reproduced value",
          result.get("status") == "timeout" and "X-901" in (rep.get("broken") or []),
          str(result))


# ---------------------------------------------------------------------------
# F107 -- record_attempt snapshots last_error for the empty-error fallback
# ---------------------------------------------------------------------------
def test_f107() -> None:
    class FakeCtx:
        def __init__(self, rec):
            self._rec = rec

        def runs(self):
            return [self._rec]

    rec = {"id": "r1_a1", "kind": "a1", "round": 1, "attempts": 0,
           "status": "failed", "last_error": "agent killed by signal 9"}
    entry = nb.record_attempt(None, rec, False, [], [])
    check("F107 the attempt entry stores last_error",
          entry.get("last_error") == "agent killed by signal 9", str(entry.get("last_error")))
    lines = nb.attempt_history_lines(FakeCtx(rec))
    text = "\n".join(lines)
    check("F107 the empty-error attempt prints the real reason, not 'no message'",
          "agent killed by signal 9" in text and "no message" not in text, text[:300])
    rec2 = {"id": "r1_w1", "kind": "rewrite", "round": 1, "attempts": 0,
            "status": "failed", "last_error": "stale last_error"}
    nb.record_attempt(None, rec2, False, ["first real problem"], [])
    text2 = "\n".join(nb.attempt_history_lines(FakeCtx(rec2)))
    check("F107 a non-empty error list still wins over last_error",
          "first real problem" in text2, text2[:300])



def test_f96() -> None:
    print()
    print("== F96: the shipped revision_token.py stashes a remote URL like the pipeline ==")
    import importlib.util as _ilu
    skill_path = WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py"
    spec = _ilu.spec_from_file_location("fbJ_revtok", skill_path)
    skill = _ilu.module_from_spec(spec)
    sys.modules["fbJ_revtok"] = skill
    spec.loader.exec_module(skill)
    raw = b"see https://example.org/fig-4f3a9c1.png and refs-4f3a9c1.bib"
    tokens = ["4f3a9c1"]
    want = b"see https://example.org/fig-4f3a9c1.png and refs.bib"
    got_skill = skill.content_token_free(raw, tokens)
    got_pipe = nb._normalize_version_refs(raw, tokens)
    check("F96 the skill keeps the URL and normalizes the local reference",
          got_skill == want, got_skill)
    check("F96 pipeline and skill agree byte-for-byte", got_skill == got_pipe,
          (got_skill, got_pipe))


def main() -> int:
    for name, fn in (
            ("F96 revision-token URL parity", test_f96),
            ("F97 revive=True on pipeline-written review JSON", test_f97),
            ("F98 symlinked --root archives failed sandboxes", test_f98),
            ("F99 compact_state format_fix artifact path", test_f99),
            ("F100 prior-audit materializer/freshness agreement", test_f100),
            ("F101 null state.json log containers", test_f101),
            ("F102 judge dependency set", test_f102),
            ("F103 unverifiable base is rebuilt from its source", test_f103),
            ("F104 reserved probe-id block", test_f104),
            ("F105 stale judge field views", test_f105),
            ("F106 aggregate verifier budget", test_f106),
            ("F107 attempt-history last_error", test_f107)):
        group(name, fn)
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} check(s): " + "; ".join(FAILED))
        return 1
    print("all group J checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
