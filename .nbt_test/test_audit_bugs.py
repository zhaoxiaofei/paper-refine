#!/usr/bin/env python3
"""Regression suite for the bug audit (judge bias, data corruption, races).

Run:  python3 .nbt_test/test_audit_bugs.py

Every check FAILS on the pre-fix tree and PASSES on the fixed one, so this file
is both the reproduction and the guard for each finding:

  A. judge bias      every view a judge can see (target/, field/*, original/) must
                     carry ONE timestamp -- the original copy used to keep the
                     author's real mtimes while the candidate views were stamped.
  B. data corruption materialization must be self-healing: a sandbox killed in
                     the middle of a copy used to freeze the PARTIAL input in
                     place (and record the truncation as the run's frozen
                     manifest), so the agent worked from a corpus that had
                     silently lost documents.
  C. races           atomic writers shared one "<name>.tmp" (a concurrent writer
                     could publish half-written bytes or crash with
                     FileNotFoundError), and nothing stopped two `run` processes
                     from double-executing the same agent sessions and
                     overwriting each other's state.json.
  D. reproducibility a decided round's candidate set came from the MUTABLE
                     config, so editing --rewrites/--revises made `decide`
                     recompute a different champion and report a bogus integrity
                     problem. The round's recorded plan now wins.
  E. ranking input   a marker reporting a NEGATIVE critical_remaining won the
                     statistical tie-break. Nonsensical counts are now ignored.
  F. hard limits     judge-token collisions (two versions sharing one sandbox),
                     same-second archive names (silently nested archives) and
                     unbounded agent-written JSON (OOM) are all refused/repaired
                     explicitly instead of failing silently.
  G. damaged state   a run record without a sandbox path crashed with a bare
                     KeyError deep inside a command; `load()` now names it.

`NBT_WS` retargets the suite at a baseline copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_bugs", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_bugs"] = nb
spec.loader.exec_module(nb)

STUB = Path(__file__).resolve().parent / "stub_agent.py"
STUB_JUDGE = Path(__file__).resolve().parent / "stub_judge.py"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def build_root(tmp: Path, judges=1, rewrites=1, revises=1):
    """A synthetic round-1 root whose base is a copy of its pristine original."""
    source = tmp / "source"
    write(source / "manuscript-b.md", "title\n")
    write(source / "refs-b.bib", "refs\n")
    write(source / "raw_figs" / "data.tsv", "a\tb\n")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(source, root / "non-revised")
    pristine = root / "non-revised"
    ctx = nb.Ctx(root)
    # `audit: "off"` keeps this suite about MATERIALIZATION repair: the default
    # (auditor on) would make every revise materialization wait for r1_audit.
    ctx.cfg = {"rounds": 1, "judges": judges, "rewrites": [rewrites], "revises": [revises],
               "audit": "off"}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "auditsalt", "config": ctx.cfg, "source": str(source)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a1")
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, "a1")
    return ctx


def register_fresh(ctx, vid, text):
    rid = nb.rid_for_fresh(1, vid)
    kind = nb.arm_of_vid(vid)
    out = ctx.root / "runs" / rid / nb.output_dir_for_vid(vid)
    write(out / "manuscript-p.md", text)
    rec = ctx.register(rid, kind, 1, f"runs/{rid}", source_id="a1", produces=vid)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
    return rec


# =====================================================================
# A. judge bias: one timestamp across every view a judge can see
# =====================================================================

def test_judge_views_share_one_timestamp():
    print("== A. judge views carry ONE timestamp (target/field/original) ==")
    tmp = scratch("nbt_bug_a_")
    ctx = build_root(tmp)
    # the pristine copy keeps the author's real (old) mtimes
    old = time.time() - 400 * 86400
    for p in [ctx.pristine, *sorted(ctx.pristine.rglob("*"))]:
        try:
            os.utime(p, (old, old))
        except OSError:
            pass
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx, vid, f"{vid}\n")
    field, _dropped = nb.build_field(ctx, 1)
    judge_ids = nb.materialize_judges(ctx, 1, field)
    sb = ctx.sandbox_of(ctx.run(judge_ids[0]))
    stamps = {}
    for area, root in (("target", sb / "target"), ("original", sb / "original"),
                       ("field", sb / "field")):
        for p in sorted(root.rglob("*")):
            if p.is_file():
                stamps[p.relative_to(sb).as_posix()] = round(p.stat().st_mtime)
    distinct = sorted(set(stamps.values()))
    check("A every judged view file shares one mtime", len(distinct) == 1,
          f"{len(distinct)} distinct mtime(s): "
          + ", ".join(f"{k}={v}" for k, v in sorted(stamps.items())[:6]))
    check("A the original view is NOT the author's real timestamp",
          all(abs(v - old) > 3600 for v in stamps.values()) if stamps else False,
          f"author mtime={round(old)} view={distinct}")
    # a second judge session (same target) is stamped the same way
    sb2 = ctx.sandbox_of(ctx.run(judge_ids[1])) if len(judge_ids) > 1 else None
    if sb2 is not None:
        m2 = {(p.relative_to(sb2).as_posix()): round(p.stat().st_mtime)
              for p in sorted(sb2.rglob("*")) if p.is_file()}
        check("A the whole judge wave is equalized too", len(set(m2.values())) == 1)


# =====================================================================
# B. data corruption: partial input copies are repaired, not trusted
# =====================================================================

def test_partial_copies_are_repaired():
    print()
    print("== B. materialization repairs a partial (crash-truncated) copy ==")

    # --- materialize_revise: base/, non-revised/ and review/ -----------------
    tmp = scratch("nbt_bug_b1_")
    ctx = build_root(tmp)
    rev = nb.materialize_review(ctx, 1)
    write(ctx.sandbox_of(rev) / "review" / "findings.json", "{}")
    rev["status"] = "done"
    rid = nb.rid_for_fresh(1, "a2")
    sb = ctx.runs_dir / rid
    # simulate "killed in the middle of the copy": only ONE file made it
    write(sb / "base" / "manuscript-b.md", "title\n")
    write(sb / "non-revised" / "manuscript-b.md", "title\n")
    write(sb / "review" / "findings.json", "{}")
    rec = nb.materialize_revise(ctx, 1, "a2")
    base_ok = nb.dir_matches(sb / "base",
                             nb.hash_manifest(ctx.sandbox_of(ctx.run("r1_a1")) / "base")["files"])
    nr_ok = nb.dir_matches(sb / "non-revised", ctx.source_manifest["files"])
    review_ok = nb.dir_matches(sb / "review",
                               nb.hash_manifest(ctx.sandbox_of(rev) / "review")["files"])
    check("B a truncated revise base/ is rebuilt from the round's base", base_ok,
          str(sorted((rec["inputs_manifest"]["base"]["files"]))))
    check("B a truncated revise non-revised/ is rebuilt from the pristine original", nr_ok)
    check("B a truncated frozen review/ is rebuilt from the review run", review_ok)
    check("B the recorded inputs_manifest is the FULL upstream corpus",
          set(rec["inputs_manifest"]["base"]["files"]) ==
          set(nb.hash_manifest(ctx.sandbox_of(ctx.run("r1_a1")) / "base")["files"]))

    # --- materialize_integrate: self/, others/<id>/ --------------------------
    tmp2 = scratch("nbt_bug_b2_")
    ctx2 = build_root(tmp2, rewrites=1, revises=1)
    for vid in ("w1", "a2"):
        register_fresh(ctx2, vid, f"{vid}\n")
    rid2 = nb.rid_for_fresh(1, "i2")           # i2 = w1 <- (a1, a2)
    sb2 = ctx2.runs_dir / rid2
    write(sb2 / "self" / "manuscript-p.md", "w1\n")          # donor a2 missing
    write(sb2 / "others" / "a2" / "manuscript-p.md", "a2\n")  # truncated a1 donor
    write(sb2 / "others" / "stale_arm" / "x.md", "leftover\n")
    rec2 = nb.materialize_integrate(ctx2, 1, 2)
    self_ok = nb.dir_matches(sb2 / "self", nb.corpus_manifest(ctx2, 1, "w1")["files"])
    a1_ok = nb.dir_matches(sb2 / "others" / "a1", nb.corpus_manifest(ctx2, 1, "a1")["files"])
    a2_ok = nb.dir_matches(sb2 / "others" / "a2", nb.corpus_manifest(ctx2, 1, "a2")["files"])
    stale_gone = not (sb2 / "others" / "stale_arm").exists()
    check("B a truncated integration self/ is rebuilt", self_ok)
    check("B a truncated donor is rebuilt from its corpus", a1_ok and a2_ok,
          f"a1={a1_ok} a2={a2_ok}")
    check("B a donor that is not in the pool is dropped", stale_gone)
    check("B the integration manifest matches the repaired sandbox",
          rec2["inputs_manifest"]["others"]["files"] ==
          nb.hash_manifest(sb2 / "others")["files"])

    # --- materialize_judges: a view truncated BEFORE the record existed ------
    tmp3 = scratch("nbt_bug_b3_")
    ctx3 = build_root(tmp3)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx3, vid, f"{vid}\n")
    field, _ = nb.build_field(ctx3, 1)
    judge_ids = nb.materialize_judges(ctx3, 1, field)
    sb3 = ctx3.sandbox_of(ctx3.run(judge_ids[0]))
    full = nb.hash_manifest(sb3 / "target")["files"]
    # simulate a crash before the run record was written: partial views, no record
    ctx3.state["runs"].pop(judge_ids[0])
    (sb3 / "PROMPT.md").unlink()
    for p in sorted((sb3 / "target").rglob("*")):
        if p.is_file():
            p.unlink()
    nb.materialize_judges(ctx3, 1, field)
    check("B a judge view truncated before the record existed is rebuilt",
          nb.hash_manifest(sb3 / "target")["files"] == full)

    # --- materialize_judges: a DAMAGED view of an already-built sandbox ------
    tmp4 = scratch("nbt_bug_b4_")
    ctx4 = build_root(tmp4)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx4, vid, f"{vid}\n")
    field4, _ = nb.build_field(ctx4, 1)
    judge_ids4 = nb.materialize_judges(ctx4, 1, field4)
    sb4 = ctx4.sandbox_of(ctx4.run(judge_ids4[0]))
    for p in sorted((sb4 / "target").rglob("*")):
        if p.is_file():
            p.unlink()
    nb.materialize_judges(ctx4, 1, field4)
    damaged = ctx4.run(judge_ids4[0])
    check("B a damaged judge sandbox is marked stale for the staging loop "
          "(never executed with a truncated corpus)",
          damaged.get("status") == "stale" and "target/" in (damaged.get("stale_reason") or ""),
          f"status={damaged.get('status')} reason={damaged.get('stale_reason')}")


# =====================================================================
# C. races
# =====================================================================

def test_atomic_writers_do_not_share_tmp():
    print()
    print("== C. concurrent atomic writers never publish a half-written file ==")
    tmp = scratch("nbt_bug_c1_")
    dst = tmp / "state.json"
    real_dump = nb.json.dump
    errors = []

    def slow_dump(obj, f, **kw):
        text = json.dumps(obj, **kw)
        f.write(text[:len(text) // 2])
        f.flush()
        time.sleep(0.4)                    # the other writer finishes meanwhile
        f.write(text[len(text) // 2:])

    def writer_a():
        nb.json.dump = slow_dump
        try:
            nb.write_json_atomic(dst, {"writer": "A", "payload": "a" * 400})
        except Exception as e:                                      # noqa: BLE001
            errors.append(f"A:{type(e).__name__}:{e}")
        finally:
            nb.json.dump = real_dump

    def writer_b():
        time.sleep(0.15)
        try:
            nb.write_json_atomic(dst, {"writer": "B", "payload": "b" * 400})
        except Exception as e:                                      # noqa: BLE001
            errors.append(f"B:{type(e).__name__}:{e}")

    ta, tb = threading.Thread(target=writer_a), threading.Thread(target=writer_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    check("C neither concurrent writer crashes", not errors, "; ".join(errors))
    try:
        obj = json.loads(dst.read_text(encoding="utf-8"))
        valid = obj.get("payload") in ("a" * 400, "b" * 400) and obj.get("writer") in ("A", "B")
    except ValueError as e:
        valid, obj = False, f"{type(e).__name__}: {e}"
    check("C the published file is exactly one writer's complete document (never a mix)",
          valid, str(obj)[:120])
    check("C no temporary file is left behind",
          not [p for p in tmp.iterdir() if p.name.endswith(".tmp")],
          str([p.name for p in tmp.iterdir()]))


def test_pipeline_lock_excludes_concurrent_writers():
    print()
    print("== C. the pipeline lock serialises mutating commands ==")
    tmp = scratch("nbt_bug_c2_")
    ctx = build_root(tmp)
    # 1. a live holder blocks a second writer
    lock_path = ctx.root / nb.LOCK_FILE
    nb.write_json_atomic(lock_path, {"pid": os.getpid(), "what": "run", "since": nb.utcnow()})
    blocked = None
    try:
        with ctx.lock("retry"):
            blocked = False
    except SystemExit as e:
        blocked = e.code
    check("C a live lock makes the second command refuse (non-zero exit)",
          blocked not in (None, False, 0), str(blocked))
    check("C the refused command did NOT delete the holder's lock", lock_path.is_file())

    # 2. a stale lock (dead pid) is reclaimed
    nb.write_json_atomic(lock_path, {"pid": 999999999, "what": "run", "since": nb.utcnow()})
    acquired = False
    try:
        with ctx.lock("retry"):
            acquired = True
    except SystemExit as e:
        acquired = f"exit {e.code}"
    check("C a stale lock (dead owner) is reclaimed instead of blocking forever",
          acquired is True, str(acquired))
    check("C the lock is released when the command finishes", not lock_path.exists())

    # 3. the real CLI refuses while another process holds the lock
    holder_src = (
        "import json,os,sys,time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(WS)!r})\n"
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('np', {str(WS / 'nbt_pipeline.py')!r})\n"
        "np = importlib.util.module_from_spec(spec); spec.loader.exec_module(np)\n"
        "root = Path(sys.argv[1])\n"
        "ctx = np.Ctx(root); ctx.load()\n"
        "p = root / np.LOCK_FILE\n"
        "p.write_text(json.dumps({'pid': os.getpid(), 'what': 'run', 'since': 'now'}))\n"
        "print('locked', flush=True)\n"
        "time.sleep(20)\n")
    nb.write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.save_state()
    holder = subprocess.Popen([sys.executable, "-c", holder_src, str(ctx.root)],
                              stdout=subprocess.PIPE, text=True)
    try:
        line = holder.stdout.readline().strip()
        check("C the helper process holds the lock", line == "locked", line)
        proc = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "retry",
                               "--root", str(ctx.root), "--run", "r1_a1"],
                              capture_output=True, text=True, timeout=60)
        out = proc.stdout + proc.stderr
        check("C `retry` refuses to run while a `run` holds the lock",
              proc.returncode != 0 and "already working on this root" in out, out[-160:])
    finally:
        holder.terminate()
        holder.wait(timeout=20)
    try:
        (ctx.root / nb.LOCK_FILE).unlink()
    except OSError:
        pass


# =====================================================================
# D. reproducibility: the recorded plan wins over the mutable config
# =====================================================================

def test_decide_uses_the_recorded_plan():
    print()
    print("== D. a decided round's plan survives a config edit ==")
    tmp = scratch("nbt_bug_d_")
    ctx = build_root(tmp)
    ctx.round_rec(1).update({"status": "done", "plan": {"rewrites": 2, "revises": 1,
                                                        "pool": ["a1", "w1", "w2", "a2"],
                                                        "integrated": ["i1", "i2", "i3", "i4"]}})
    ctx.cfg["rewrites"], ctx.cfg["revises"] = [0], [3]      # operator edits the config
    m, n = nb.round_counts(ctx, 1)
    check("D round_counts uses the recorded plan, not the edited config",
          (m, n) == (2, 1), f"M={m} N={n}")
    check("D the candidate set is the recorded one",
          nb.round_candidate_ids(m, n) == ["w1", "w2", "a2", "i1", "i2", "i3", "i4"],
          str(nb.round_candidate_ids(m, n)))

    # end-to-end: a real round, then an edited config, then `decide` must still
    # certify the stored champion instead of inventing an integrity problem.
    tmp2 = scratch("nbt_bug_d2_")
    source = tmp2 / "source"
    write(source / "manuscript-b.md", "title\n")
    write(source / "refs-b.bib", "x\n")
    root = tmp2 / "root"
    setup = [sys.executable, str(WS / "nbt_pipeline.py"), "setup", "--source", str(source),
             "--root", str(root), "--rounds", "1", "--judges", "1", "--rewrites", "1",
             "--revises", "1"]
    subprocess.run(setup, capture_output=True, text=True, check=True)
    run = [sys.executable, str(WS / "nbt_pipeline.py"), "run", "--root", str(root),
           "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
           "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
           "--retries", "0", "--jobs", "6"]
    proc = subprocess.run(run, capture_output=True, text=True, timeout=900)
    check("D e2e the round completes", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-200:])
    cfg_path = root / "pipeline_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["rewrites"], cfg["revises"] = [0, 0], [5, 5]
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    st = json.loads((root / "state.json").read_text(encoding="utf-8"))
    st["config"].update({"rewrites": [0, 0], "revises": [5, 5]})
    (root / "state.json").write_text(json.dumps(st), encoding="utf-8")
    stored_champion = st["rounds"]["1"]["champion"]
    dec = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "decide",
                          "--root", str(root)], capture_output=True, text=True, timeout=600)
    out = dec.stdout + dec.stderr
    check("D e2e decide still certifies after the config was edited", dec.returncode == 0,
          out[-200:])
    check("D e2e decide reports the STORED champion", f"champion={stored_champion}" in out,
          out[-200:])
    check("D e2e no bogus 'recomputed champion' problem is reported",
          "recomputed champion" not in out, out[-300:])


# =====================================================================
# E. ranking input: negative counts never win the tie-break
# =====================================================================

def test_negative_counts_are_ignored():
    print()
    print("== E. a negative critical_remaining cannot win the tie-break ==")
    tmp = scratch("nbt_bug_e_")
    ctx = build_root(tmp)
    for vid, crit in (("w1", -99), ("a2", 0)):
        rid = nb.rid_for_fresh(1, vid)
        rec = ctx.register(rid, nb.arm_of_vid(vid), 1, f"runs/{rid}", produces=vid)
        rec.update({"status": "done", "summary": {"critical_remaining": crit,
                                                  "manual_items": -3}})
    w1_crit, w1_writing, w1_manual = nb.candidate_tiebreak_inputs(ctx, 1, "w1")
    a2_crit, a2_writing, a2_manual = nb.candidate_tiebreak_inputs(ctx, 1, "a2")
    check("E the -99 marker is treated like a MISSING number (never better than 0)",
          w1_crit == nb.MISSING_TIEBREAK and a2_crit == 0, f"w1={w1_crit} a2={a2_crit}")
    check("E a writing count nobody reported is MISSING too (never better than 0)",
          w1_writing == nb.MISSING_TIEBREAK and a2_writing == nb.MISSING_TIEBREAK,
          f"w1={w1_writing} a2={a2_writing}")
    check("E a negative manual_items is ignored too",
          w1_manual == nb.MISSING_TIEBREAK and a2_manual == nb.MISSING_TIEBREAK,
          f"w1={w1_manual} a2={a2_manual}")
    # the postcheck reports it as a warning on the producing run
    sb = ctx.sandbox_of(ctx.run(nb.rid_for_fresh(1, "a2")))
    write(sb / "revised" / "manuscript-p.md", "x\n")
    write(sb / "revised" / "revision_report.json", json.dumps([{"id": "F-001"}]))
    write(sb / "revised" / "CHANGELOG.md", "# c\n")
    write(sb / "revised" / "MANUAL_STEPS.md", "- none\n")
    nb.write_json_atomic(sb / nb.MARKER_FILE,
                         {"stage": "revise", "run_id": "r1_a2_revise", "round": 1,
                          "status": "complete",
                          "summary": {"findings_total": 1, "fixed": 1,
                                      "critical_remaining": -2, "manual_items": -1}})
    a2rec = ctx.run(nb.rid_for_fresh(1, "a2"))
    a2rec["inputs_manifest"] = {}
    ok, errs, warns, _ = nb.postcheck_revise(ctx, a2rec)
    check("E the postcheck WARNS about the negative numbers",
          any("NEGATIVE" in w for w in warns), str(warns)[:200])


# =====================================================================
# F. hard limits: token collisions, archive names, oversized agent JSON
# =====================================================================

def test_judge_token_collision_is_refused():
    print()
    print("== F. judge-token collisions must not merge two sandboxes ==")
    tmp = scratch("nbt_bug_f1_")
    ctx = build_root(tmp)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx, vid, f"{vid}\n")
    field, _ = nb.build_field(ctx, 1)
    real = nb.judge_token_for
    nb.judge_token_for = lambda ctx_, r, vid: "tcollide1"     # force a collision
    try:
        msg = ""
        try:
            nb.materialize_judges(ctx, 1, field)
        except RuntimeError as e:
            msg = str(e)
        check("F a token collision is refused with an explanatory error",
              "collision" in msg.lower(), msg[:160])
        judge_dirs = [p for p in (ctx.root / "runs").iterdir()
                      if p.name.startswith("r1_judge_")]
        check("F no judge sandbox was created under a colliding token",
              not judge_dirs, str([p.name for p in judge_dirs]))
    finally:
        nb.judge_token_for = real


def test_same_second_archives_do_not_overwrite():
    print()
    print("== F. same-second archives are not nested/overwritten ==")
    tmp = scratch("nbt_bug_f2_")
    base = tmp / "archive.20260917T000000Z"
    check("F unique_path returns the base when it is free", nb.unique_path(base) == base)
    base.mkdir()
    check("F unique_path avoids an existing name",
          nb.unique_path(base) != base and nb.unique_path(base).name.startswith(base.name))
    # stashed agent logs: two stashes of the same run must both survive
    ctx = build_root(tmp)
    rid = nb.rid_a1(1)
    sb = ctx.sandbox_of(ctx.run(rid))
    write(sb / "_agent.log", "first attempt\n")
    nb.stash_logs(sb, ctx.runs_dir / nb.LOGS_DIRNAME, rid)
    write(sb / "_agent.log", "second attempt\n")
    nb.stash_logs(sb, ctx.runs_dir / nb.LOGS_DIRNAME, rid)
    logs = sorted((ctx.runs_dir / nb.LOGS_DIRNAME).iterdir())
    texts = sorted(p.read_text(encoding="utf-8").strip() for p in logs)
    check("F both attempts' logs survive the stash", texts == ["first attempt", "second attempt"],
          str([p.name for p in logs]))
    # archive_stale_marker twice in the same second
    nb.write_json_atomic(sb / nb.MARKER_FILE, {"stage": "review", "round": 1})
    nb.archive_stale_marker(sb, rid)
    nb.write_json_atomic(sb / nb.MARKER_FILE, {"stage": "review", "round": 1, "second": True})
    nb.archive_stale_marker(sb, rid)
    archived = [p for p in (ctx.runs_dir / nb.LOGS_DIRNAME).iterdir()
                if "prev_marker" in p.name]
    check("F both archived markers survive their same-second stamp",
          len(archived) == 2, str([p.name for p in archived]))


def test_oversized_agent_json_is_refused():
    print()
    print("== F. an oversized agent-written JSON is refused, not parsed ==")
    tmp = scratch("nbt_bug_f3_")
    p = tmp / "findings.json"
    write(p, json.dumps({"findings": [{"id": "F-001"}]}))
    real_cap = nb.MAX_JSON_BYTES
    nb.MAX_JSON_BYTES = 10                       # pretend the cap is 10 bytes
    try:
        check("F read_json refuses the oversized file",
              nb.read_json(p, revive=False, lenient=True) is None)
        ctx = build_root(tmp)
        rid = nb.rid_for_fresh(1, "a2")
        rec = ctx.register(rid, "revise", 1, f"runs/{rid}", produces="a2")
        write(ctx.sandbox_of(rec) / "revised" / "findings.json",
              json.dumps({"findings": [{"id": "F-001", "note": "x" * 200}]}))
        probs = nb.structured_output_problems(ctx, rec)
        check("F the structured-output check names the size limit",
              any("MiB agent-output limit" in x for x in probs), str(probs)[:160])
    finally:
        nb.MAX_JSON_BYTES = real_cap
    check("F the real cap is generous enough for real deliverables",
          nb.MAX_JSON_BYTES >= 16 * 1024 * 1024, str(nb.MAX_JSON_BYTES))


# =====================================================================
# G. damaged state.json is named, not crashed into
# =====================================================================

def test_damaged_state_is_reported():
    print()
    print("== G. a damaged run record is reported instead of raising KeyError ==")
    tmp = scratch("nbt_bug_g_")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "pipeline_config.json").write_text(json.dumps({"rounds": 1, "judges": 1}))
    (root / "state.json").write_text(json.dumps(
        {"version": nb.STATE_VERSION, "runs": {"r1_x": {"kind": "judge", "round": 1}},
         "rounds": {}, "pinned": [], "log": []}))
    ctx = nb.Ctx(root)
    out, err = "", ""
    code = None
    import io
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        ctx.load()
    except SystemExit as e:
        code = e.code
    finally:
        out, err = sys.stdout.getvalue(), sys.stderr.getvalue()
        sys.stdout, sys.stderr = old_out, old_err
    check("G load() refuses the damaged registry cleanly", code == 1, str(code))
    check("G the message names the damaged record",
          "r1_x" in (out + err) and "sandbox" in (out + err), (out + err)[-160:])


def main() -> int:
    sections = (("A", test_judge_views_share_one_timestamp),
                ("B", test_partial_copies_are_repaired),
                ("C", test_atomic_writers_do_not_share_tmp),
                ("C", test_pipeline_lock_excludes_concurrent_writers),
                ("D", test_decide_uses_the_recorded_plan),
                ("E", test_negative_counts_are_ignored),
                ("F", test_judge_token_collision_is_refused),
                ("F", test_same_second_archives_do_not_overwrite),
                ("F", test_oversized_agent_json_is_refused),
                ("G", test_damaged_state_is_reported))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL AUDIT-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
