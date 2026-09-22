#!/usr/bin/env python3
"""Attempt history + evidence retention — red on the pre-fix tree.

The reported gap: the 2026-09-22 root's `r1_review` failed TWICE, for different
reasons, and the run record (and therefore `status`, the run table in
DECISION_REPORT.md and the console) described only the second failure. Attempt
1's three problems existed only because they had been copied into attempt 2's
PROMPT.md, and attempt 1's artifacts were destroyed by the retry that followed
them. The rule this suite guards: EVERY attempt keeps its diagnostics, its
artifacts and its transcript, and the pipeline says where they are.

  A. numbering   attempts are numbered monotonically across `retry`
                 (`attempts_done`), so an archive/log name never collides with a
                 different attempt's.
  B. records     every postcheck AND every process-level failure appends an entry
                 (errors, warnings, artifact quality, marker summary, timing,
                 source) to the run record; the same attempt re-postchecked
                 replaces its entry instead of duplicating it; the log is capped.
  C. archive     a failed attempt's sandbox is preserved before the rebuild
                 (deliverables linked, input corpora and `work/corpus` skipped,
                 transcript moved to runs/_logs/ and referenced), and the copies
                 survive the sandbox's removal.
  D. surfacing   `attempt_history_lines` (used by `status` and the decision
                 report) names every failed attempt with its first problem and
                 where its evidence is; the console prints all of an attempt's
                 problems, one per line, instead of one truncated line.
  E. messages    a repeated boilerplate disposition is quoted in full and names
                 the rows it is about (the operator's only handle on the defect).
  F. prune       a pruned round's attempt archives go with its sandboxes, and the
                 attempt records stay readable in state.json.

Run:  python3 .nbt_test/test_attempt_history.py
`NBT_WS` retargets the suite at a baseline (pre-fix -> red) tree.
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
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_hist", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_hist"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(p)
    return p


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_root(tmp: Path) -> nb.Ctx:
    """A round-1 root whose base is a copy of its pristine original (a1 done)."""
    source = tmp / "source"
    write(source / "manuscript-b.md", "title\n")
    write(source / "refs-b.bib", "refs\n")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(source, root / "non-revised")
    pristine = root / "non-revised"
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [1], "revises": [1], "audit": "off",
               "review_split": "off", "placeholder_lookup": "off", "caption_limit": 0,
               "format_policy": {}, "zotero": "off", "vs_original_rule": "median"}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "attemptsalt", "config": ctx.cfg, "source": str(source)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    # `status`/`retry` load the root through Ctx.load(), which needs the config.
    nb.write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.save_state()
    return ctx


BOILERPLATE = "OK — summary written from the paragraph's own claim"


def write_failed_review(sb: Path, rec: dict, *, rows: int = 30, with_coverage: bool = False):
    """A review deliverable that cannot pass: no coverage table, boilerplate rows."""
    art = sb / nb.REVIEW_DIR / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"| {i} | cnb-12-2-mainText.docx | Methods | {i} | 5 | summary {i} | "
                     f"{BOILERPLATE} |" for i in range(rows))
    write(art / "OUTLINE.md",
          "# OUTLINE\n\n| # | document | heading | paragraph | words | summary | disposition |\n"
          "|---|---|---|---|---|---|---|\n" + body + "\n")
    write(sb / nb.MARKER_FILE, json.dumps({"stage": "review", "run_id": rec["id"], "round": 1,
                                           "status": "complete",
                                           "summary": {"findings_total": 0}}))
    fj = {"submission_dir": "./base", "findings": []}
    if with_coverage:
        fj["coverage"] = []
    write(sb / nb.REVIEW_DIR / "findings.json", json.dumps(fj))


print("== A. attempt numbering is monotone across retry ==")
rec_a = {"attempts": 0, "attempts_done": 0}
check("A1 the first attempt is number 1", nb.bump_attempt(rec_a) == 1 and
      nb.attempt_number(rec_a) == 1, f"{rec_a}")
nb.bump_attempt(rec_a)
check("A2 the second attempt is number 2", nb.attempt_number(rec_a) == 2)
nb.reset_run_record(rec_a)
check("A3 retry clears `attempts` but not the monotone total",
      rec_a["attempts"] == 0 and nb.attempt_number(rec_a) == 2)
check("A4 the next attempt continues the series",
      nb.bump_attempt(rec_a) == 3 and nb.attempt_number(rec_a) == 3)

print()
print("== B. every attempt is recorded (postcheck, process, caps) ==")
ctx = build_root(scratch("nbt_hist_b_"))
rec = nb.materialize_review(ctx, 1)
sb = ctx.sandbox_of(rec)
write_failed_review(sb, rec)
nb.bump_attempt(rec)
ok1 = nb.postcheck(ctx, rec)
check("B1 the failed attempt is appended with its errors and artifact quality",
      not ok1 and len(rec["attempts_log"]) == 1
      and rec["attempts_log"][0]["ok"] is False
      and len(rec["attempts_log"][0]["errors"]) >= 3
      and rec["attempts_log"][0]["status"] == "failed",
      str(rec["attempts_log"][0]["errors"])[:120])
check("B2 the record points at the attempt's own archive path",
      rec["attempts_log"][0]["archive"] ==
      str(Path("runs") / nb.ATTEMPTS_DIRNAME / rec["id"] / "attempt-1"),
      rec["attempts_log"][0]["archive"])
before = len(rec["attempts_log"])
nb.postcheck(ctx, rec)                       # same attempt, re-postchecked
check("B3 a re-postcheck of the SAME attempt replaces its entry",
      len(rec["attempts_log"]) == before, f"{len(rec['attempts_log'])} entries")
proc = {"id": "r1_w1", "kind": "rewrite", "round": 1, "status": "pending", "attempts": 0,
        "sandbox": "runs/r1_w1", "last_duration": None, "postcheck": None}
ctx.state["runs"]["r1_w1"] = proc
nb.bump_attempt(proc)
nb.record_attempt(ctx, proc, False, ["agent exited rc=1"], [], source="process")
check("B4 a process-level failure is recorded like a postcheck failure",
      proc["attempts_log"][0]["source"] == "process"
      and proc["attempts_log"][0]["errors"] == ["agent exited rc=1"])
for _ in range(nb.ATTEMPTS_LOG_LIMIT + 5):
    nb.bump_attempt(proc)
    nb.record_attempt(ctx, proc, False, ["boom"], [])
check("B5 the history is capped so a retry loop cannot grow state.json without bound",
      len(proc["attempts_log"]) == nb.ATTEMPTS_LOG_LIMIT
      and proc["attempts_log"][-1]["attempt"] > nb.ATTEMPTS_LOG_LIMIT,
      f"{len(proc['attempts_log'])} entries, last attempt "
      f"{proc['attempts_log'][-1]['attempt']}")
# EVERY message of an attempt is kept (no count cap -- that is how attempt 1's two
# other problems disappeared on the 2026-09-22 root); the only guard left is a
# total-size cap, and it says exactly how many messages it left out.
many = [f"m{i}" for i in range(2000)]
kept = nb._attempt_messages(many)
check("B6 every message is kept, however many an attempt produced",
      len(kept) == len(many) and kept[0] == "m0" and kept[-1] == "m1999",
      f"{len(kept)} of {len(many)}")
huge = ["x" * nb.ATTEMPT_MESSAGE_LIMIT for _ in range(
    nb.ATTEMPT_LIST_BYTES_LIMIT // nb.ATTEMPT_MESSAGE_LIMIT + 5)]
capped = nb._attempt_messages(huge)
check("B7 a pathological total size is cut, and the note says how much was left out",
      len(capped) < len(huge) and "NOT copied into" in capped[-1],
      f"{len(capped)} of {len(huge)}")

print()
print("== C. a failed attempt's artifacts survive the rebuild ==")
write(sb / "_agent.log", "attempt 1 transcript\n")
failed_attempt = nb.attempt_number(rec)
nb.rebuild_sandbox(ctx, rec)
arch = nb.attempt_archive_dir(ctx, rec, failed_attempt)
kept_outline = arch / "sandbox" / nb.REVIEW_DIR / "artifacts" / "OUTLINE.md"
check("C1 the artifacts that failed the postcheck are preserved",
      kept_outline.is_file() and BOILERPLATE in kept_outline.read_text(encoding="utf-8"))
check("C2 the re-derivable input corpora are NOT archived",
      not (arch / "sandbox" / "base").exists()
      and not (arch / "sandbox" / "non-revised").exists())
check("C3 the transcript is stashed with the attempt number and referenced",
      (ctx.runs_dir / nb.LOGS_DIRNAME / f"{rec['id']}.attempt-1._agent.log").is_file()
      and rec["attempts_log"][0]["agent_log"] ==
      [str(Path("runs") / nb.LOGS_DIRNAME / f"{rec['id']}.attempt-1._agent.log")],
      str(rec["attempts_log"][0].get("agent_log")))
record = json.loads((arch / "record.json").read_text(encoding="utf-8"))
check("C4 the archive is self-describing (record.json carries the attempt's record)",
      record["attempt"] == 1 and record["ok"] is False and record["run_id"] == rec["id"]
      and record["errors"], str(sorted(record))[:120])
linked = record.get("linked_files", 0)
check("C5 the archive hardlinks where it can (copies as the fallback)",
      linked + record.get("copied_files", 0) > 0, f"linked={linked} copied={record['copied_files']}")
rebuilt = ctx.sandbox_of(rec) / nb.REVIEW_DIR / "artifacts" / "OUTLINE.md"
check("C6 the sandbox itself was rebuilt fresh (no marker, no stale deliverable)",
      not (ctx.sandbox_of(rec) / nb.MARKER_FILE).exists()
      and (not rebuilt.is_file() or BOILERPLATE not in rebuilt.read_text(encoding="utf-8")))
check("C7 the preserved copy is independent of the sandbox it came from",
      kept_outline.read_text(encoding="utf-8").count(BOILERPLATE) == 30)

print()
print("== D. the history is surfaced (status, report, console) ==")
lines = "\n".join(nb.attempt_history_lines(ctx))
check("D1 the history names the run, the attempt and its first problem",
      f"{rec['id']} (review, round 1): 1 attempt(s), 1 failed" in lines
      and "attempt 1" in lines and "problem(s)" in lines, lines[:160])
check("D2 the history points at the kept artifacts and transcript",
      f"kept: runs/{nb.ATTEMPTS_DIRNAME}/{rec['id']}/attempt-1" in lines
      and f"transcript: runs/{nb.LOGS_DIRNAME}/{rec['id']}.attempt-1._agent.log" in lines)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    nb.print_failure(rec["id"], rec["attempts_log"][0]["errors"])
out = buf.getvalue()
check("D3 the console prints every problem, one per line (no 140-character cut)",
      all(e in out for e in rec["attempts_log"][0]["errors"])
      and out.count("\n        - ") == len(rec["attempts_log"][0]["errors"]),
      out[:160])
status_buf = io.StringIO()
ctx.save_state()          # `status` re-loads the root from disk
with contextlib.redirect_stdout(status_buf), contextlib.redirect_stderr(status_buf):
    try:
        nb.cmd_status(type("A", (), {"root": str(ctx.root)})())
    except SystemExit as e:
        print(f"[debug] cmd_status exited {e}")
check("D4 `status` shows the attempt history",
      "ATTEMPT HISTORY" in status_buf.getvalue()
      and f"{rec['id']} (review, round 1)" in status_buf.getvalue(),
      status_buf.getvalue()[-500:])

print()
print("== E. the failure message names the rows it is about ==")
rows = [{"document": "cnb-12-2-mainText.docx", "heading": "Methods", "paragraph": str(i),
         "summary": f"s{i}", "disposition": BOILERPLATE} for i in range(30)]
probs = nb.disposition_artifact_problems(rows)
msg = next((p for p in probs if "repeat the SAME sentence" in p), "")
check("E1 the repeated sentence is quoted in full, not cut at 70 characters",
      BOILERPLATE.lower() in msg and "(truncated)" not in msg, msg[:200])
check("E2 the message names the rows",
      "rows: cnb-12-2-mainText.docx / Methods / para 0" in msg and "and 26 more" in msg,
      msg[-160:])
outline_rows = [{"document": "d.docx", "heading": "h", "paragraph": str(i), "summary": "",
                 "disposition": f"v{i}"} for i in range(30)]
omsg = " ".join(nb.outline_artifact_problems(outline_rows))
check("E3 the empty-summary message names rows too",
      "OUTLINE rows carry no summary" in omsg and "d.docx / h / para 0" in omsg, omsg[:200])

print()
print("== F. prune reclaims the archives, the records stay ==")
ctx2 = build_root(scratch("nbt_hist_f_"))
ctx2.cfg["rounds"] = 1
rec2 = nb.materialize_review(ctx2, 1)
nb.bump_attempt(rec2)
write_failed_review(ctx2.sandbox_of(rec2), rec2)
nb.postcheck(ctx2, rec2)
nb.rebuild_sandbox(ctx2, rec2)
ctx2.round_rec(1).update({"status": "done"})
ctx2.save_state()
arch2 = nb.attempt_archive_dir(ctx2, rec2, 1)
check("F1 the archive exists before prune", arch2.is_dir())
args = type("A", (), {"keep_latest": 0, "yes": True})()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    nb._cmd_prune_locked(ctx2, args)
check("F2 prune removes the attempt archive of the pruned round", not arch2.is_dir(),
      buf.getvalue()[:160])
check("F3 the attempt record survives in state.json and says the archive is gone",
      rec2["attempts_log"][0].get("archive_pruned") is True
      and "archive pruned" in "\n".join(nb.attempt_history_lines(ctx2)))

print()
print("== G. the transcript's header names the attempt and its true start time ==")
ctx3 = build_root(scratch("nbt_hist_g_"))
rec3 = nb.materialize_review(ctx3, 1)
nb.bump_attempt(rec3)
nb.record_attempt(ctx3, rec3, False, ["boom"], [])       # attempt 1 is on the books
before = nb.utcnow()
res = nb._execute_attempt_in(ctx3.sandbox_of(rec3), rec3, ["true"], 60)
log = (ctx3.sandbox_of(rec3) / "_agent.log").read_text(encoding="utf-8")
after = nb.utcnow()
header = next((ln for ln in log.splitlines() if ln.startswith("===== attempt")), "")
check("G1 the header numbers the attempt the way the history does",
      header.startswith("===== attempt 2 start "), header)
check("G2 the header carries the START time, not the time the agent returned",
      before <= header.split("start ")[1].rstrip(" =") <= after
      and f"dur={res['dur']:.1f}s" in log, f"{header} | before={before} after={after}")
rec3["last_duration"] = round(res["dur"], 1)
nb.bump_attempt(rec3)
nb.record_attempt(ctx3, rec3, True, [], [])
check("G3 the history's attempt carries that same start time and duration",
      rec3["attempts_log"][1]["started"] == header.split("start ")[1].rstrip(" =")
      and rec3["attempts_log"][1]["duration"] == round(res["dur"], 1),
      f"{rec3['attempts_log'][1]['started']} vs {header}")

print()
print("== H. the invocation log (reports/<cmd>-<stamp>.log) ==")
root_h = scratch("nbt_hist_h_")
log_path = nb.start_run_log("run", root_h, ["nbt_pipeline.py", "run", "--root", str(root_h)])
check("H1 start_run_log opens reports/<cmd>-<stamp>.log with a header",
      log_path.is_file() and log_path.parent.name == "reports"
      and "nbt_pipeline run" in log_path.read_text(encoding="utf-8")
      and "--root" in log_path.read_text(encoding="utf-8"), str(log_path))
_stdout, _stderr = sys.stdout, sys.stderr
nb.install_run_log(log_path)
print("hello from the run log")
sys.stdout, sys.stderr = _stdout, _stderr
check("H2 the installed tee mirrors both console streams into the file",
      "hello from the run log" in log_path.read_text(encoding="utf-8"))
ctx_h = build_root(scratch("nbt_hist_h2_"))
nb.CURRENT_RUN_LOG = log_path
ctx_h.save_state()
saved = json.loads(ctx_h.state_path.read_text(encoding="utf-8"))
nb.CURRENT_RUN_LOG = None
check("H3 a saved root records the invocation's log under `run_logs`",
      (saved.get("run_logs") or []) and str(saved["run_logs"][-1]).endswith(log_path.name),
      str(saved.get("run_logs")))
inner = nb.start_run_log("retry", ctx_h.root, ["nbt_pipeline.py", "retry"])
nb.CURRENT_RUN_LOG = inner
ctx_h.save_state()
saved = json.loads(ctx_h.state_path.read_text(encoding="utf-8"))
nb.CURRENT_RUN_LOG = None
check("H4 a log inside the root is recorded as a root-relative path",
      saved["run_logs"][-1] == f"reports/{inner.name}",
      f"{saved['run_logs'][-1]!r} vs {f'reports/{inner.name}'!r}")

for d in TMPDIRS:
    shutil.rmtree(d, ignore_errors=True)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL ATTEMPT-HISTORY CHECKS PASSED")
