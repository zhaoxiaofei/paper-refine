#!/usr/bin/env python3
"""`run --only` inside the journal revision modes.

The journal chain's stages (feedback, concerns, review, audit, revise,
integrate, response) are selectable exactly like the round model's stages; a
partial invocation drives only what it selected and leaves the round
incomplete. The response letter and `journal_submission/` stay a plain-`run`
sink: they are assembled only when every stage of the chain is done.

Run:  python3 .paper_test/test_journal_only.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
STUB = WS / ".paper_test" / "stub_agent.py"
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
spec = importlib.util.spec_from_file_location("paper_jo", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_jo"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def run_cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *map(str, argv)],
                          capture_output=True, text=True, timeout=timeout)


def build_source(root: Path) -> Path:
    src = root / "src"
    (src / "raw_data").mkdir(parents=True)
    (src / "human_review_feedback").mkdir(parents=True)
    (src / "manuscript.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the cells.\n\n"
        "Introduction\nscRNA-seq was performed once and the claims follow.\n", encoding="utf-8")
    (src / "human_review_feedback" / "reviewer_comments.txt").write_text(
        "Reviewer 1:\n\n"
        "1. The sample size is too small and the claims are too strong for the evidence.\n\n"
        "2. The methods do not describe the sequencing depth or the number of cells profiled.\n",
        encoding="utf-8")
    return src


def setup_root(tmp: Path, mode: str) -> Path:
    src = build_source(tmp)
    root = tmp / "root"
    r = run_cli("setup", "--source", str(src), "--root", str(root),
                "--rounds", "1", "--rewrites", "0", "--revises", "1",
                "--integrators", "0x0", "--judges", "1", "--audit", "off",
                "--revision-mode", mode,
                "--journal-feedback-from", "iScience", "--journal", "Frontiers in Immunology")
    if r.returncode != 0:
        raise RuntimeError(f"setup failed: {r.stdout[-400:]}{r.stderr[-400:]}")
    return root


def run_root(root: Path, *extra) -> subprocess.CompletedProcess:
    return run_cli("run", "--root", str(root),
                   "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                   "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
                   "--timeout", "300", "--retries", "0", *extra)


def status_of(root: Path, rid: str) -> str:
    st = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return str((st.get("runs") or {}).get(rid, {}).get("status") or "")


def test_only_vocabulary():
    spec1 = nb.parse_only_spec("feedback")
    check("--only feedback parses as the feedback stage",
          spec1 is not None and spec1.stages == {"feedback"}, str(spec1.stages if spec1 else None))
    spec2 = nb.parse_only_spec("r1_feedback")
    check("--only r1_feedback parses as round 1's feedback session",
          spec2 is not None and spec2.sessions.get(1) == ["feedback"], str(spec2.sessions))
    spec3 = nb.parse_only_spec("2:concerns")
    check("--only 2:concerns parses as round 2's concerns stage",
          spec3 is not None and spec3.pairs.get(2) == {"concerns"}, str(spec3.pairs))
    spec4 = nb.parse_only_spec("resp")
    check("the response alias parses", spec4 is not None and spec4.stages == {"response"})
    check("the audit session token maps to audit, not revise",
          nb.OnlySpec._token_stage("audit") == "audit" and
          nb.OnlySpec._token_stage("r1_audit") == "review")  # only bare tokens are stages
    spec5 = nb.parse_only_spec("w,feedback")
    check("round-model and journal stages combine in one item",
          spec5 is not None and spec5.stages == {"rewrite", "feedback"}, str(spec5.stages))
    check("a scoped-mode stage list is accepted",
          nb.parse_only_spec("concerns,revise").stages == {"concerns", "revise"})
    tmpl = nb.parse_only_spec("1:conform")
    check("--only accepts the conform stage (bare and round-qualified; old names alias it)",
          tmpl is not None and tmpl.pairs.get(1) == {"conform"}
          and nb.parse_only_spec("conform").stages == {"conform"}
          and nb.parse_only_spec("template").stages == {"conform"}
          and nb.parse_only_spec("author-submission").stages == {"conform"}
          and nb.parse_only_spec("1:apply-template").pairs.get(1) == {"conform"}
          and nb.only_is_template_stage_only(tmpl)
          and nb.only_is_template_stage_only(nb.parse_only_spec("apply-template"))
          and not nb.only_is_template_stage_only(nb.parse_only_spec("conform,review")))


def test_only_in_transfer_mode():
    tmp = scratch("paper_jo_transfer_")
    root = setup_root(tmp, "transfer")

    r = run_root(root, "--only", "feedback")
    out = r.stdout + r.stderr
    check("run --only feedback is accepted in transfer mode",
          r.returncode == 3 and "does not apply to revision mode" not in out,
          f"rc={r.returncode} {out[-220:]!r}")
    check("the selected feedback stage ran", status_of(root, "r1_feedback") == "done",
          status_of(root, "r1_feedback"))
    check("nothing else ran and no package was assembled",
          status_of(root, "r1_review") != "done"
          and not (root / "journal_submission").exists())

    r = run_root(root, "--only", "review")
    check("run --only review resumes from the finished feedback",
          r.returncode == 3 and status_of(root, "r1_review") == "done",
          f"rc={r.returncode} review={status_of(root, 'r1_review')}")
    check("the revise arm is still pending and the package is not assembled",
          status_of(root, "r1_a2_revise") != "done"
          and not (root / "journal_submission").exists())

    r = run_root(root, "--only", "revise")
    check("run --only revise drives only the revision arm",
          r.returncode == 3 and status_of(root, "r1_a2_revise") == "done",
          f"rc={r.returncode} revise={status_of(root, 'r1_a2_revise')}")
    check("a partial chain never assembles journal_submission/",
          not (root / "journal_submission").exists())

    r = run_root(root)
    check("a plain run finishes the chain and assembles the package",
          r.returncode == 0 and (root / "journal_submission").is_dir()
          and (root / "journal_submission" / "manuscript.txt").is_file(),
          f"rc={r.returncode} {(r.stdout + r.stderr)[-220:]!r}")


def test_only_in_scoped_mode():
    tmp = scratch("paper_jo_scoped_")
    root = setup_root(tmp, "major")

    r = run_root(root, "--only", "concerns")
    check("run --only concerns is accepted in the scoped mode",
          r.returncode == 3 and status_of(root, "r1_concerns") == "done",
          f"rc={r.returncode} concerns={status_of(root, 'r1_concerns')}")
    check("the scoped partial run assembles no package",
          not (root / "journal_submission").exists())

    r = run_root(root)
    check("a plain run completes the scoped chain and publishes the package",
          r.returncode == 0 and (root / "journal_submission").is_dir()
          and any((root / "journal_submission").glob("RESPONSE*")),
          f"rc={r.returncode} {(r.stdout + r.stderr)[-220:]!r}")


def main() -> int:
    try:
        test_only_vocabulary()
        test_only_in_transfer_mode()
        test_only_in_scoped_mode()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} JOURNAL-ONLY CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL JOURNAL-ONLY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
