#!/usr/bin/env python3
"""`--skip-hash`: skip the integrity VERIFICATION passes, never the recording.

On a big root the verification passes -- the pristine copy, the pinned
champions, the published winners, every completed run's frozen inputs, the
judge-view digests and the a1 base digest -- are most of the wall time of
`status`, `run` and `decide`. `--skip-hash` turns those comparisons off for ONE
invocation, and this suite pins both halves of that contract:

  * WITH the flag a tampered root is accepted, and every report says the checks
    were SKIPPED (status, decision.json's `integrity` and `certification`,
    final_clean_version.readme.md) -- never that they were verified;
  * WITH the flag digests are still RECORDED (state.json, the pins and every
    run's own corpus_digest), so the very next invocation WITHOUT the flag
    still detects the same tamper;
  * WITHOUT the flag nothing changes: the tamper blocks `run` (exit != 0) and
    un-certifies `decide` (exit 5), which is the pre-existing behaviour.

Run:  python3 .paper_test/test_skip_hash.py
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
spec = importlib.util.spec_from_file_location("paper_skip_hash", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_skip_hash"] = nb
spec.loader.exec_module(nb)

STUB = WS / ".paper_test" / "stub_agent.py"
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
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


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_root(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    root = tmp / "root"
    proc = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
               "--rewrites", "1", "--revises", "1", "--judges", "1")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run_root(root: Path, *extra):
    return cli("run", "--root", str(root),
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "0", *extra)


def state_of(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def decision_of(root: Path) -> dict:
    return json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))


def test_switch_and_wiring():
    print("== the switch: per invocation, off by default, visible in every CLI ==")
    check("the switch is OFF until an invocation turns it on (the default)",
          nb.configure_hash_checks(False) == "" and nb.hash_checks_skipped() is False)
    note = nb.configure_hash_checks(True)
    check("the switch turns the verification passes off and returns the report note",
          nb.hash_checks_skipped() is True and "SKIPPED" in note and "RECORDED" in note,
          note[:120])
    check("turning it back off clears the note and the flag",
          nb.configure_hash_checks(False) == "" and nb.hash_checks_skipped() is False)
    for cmd in ("run", "decide", "status", "retry", "run-decide"):
        help_out = cli(cmd, "--help")
        check(f"`{cmd} --help` documents --skip-hash (it is a common flag)",
              "--skip-hash" in help_out.stdout and "VERIFICATION passes" in help_out.stdout,
              help_out.stdout[-160:])


def test_tampered_chain_and_the_flag():
    """A tampered pin: refused without the flag, accepted with it, reported as skipped."""
    print()
    print("== a tampered pinned champion: blocked by default, skipped on request ==")
    tmp = scratch("paper_skip_hash_")
    root = make_root(tmp)
    p = run_root(root)
    state = state_of(root)
    check("the fixture round completes and pins a champion",
          p.returncode == 0 and state.get("pinned"),
          (p.stdout + p.stderr)[-200:])
    pin = (state.get("pinned") or [])[0]
    docs = root / "pinned" / pin["id"] / "documents"
    target = next((q for q in sorted(docs.rglob("*")) if q.is_file()), None)
    assert target is not None, docs
    with open(target, "a", encoding="utf-8") as f:
        f.write("\ntampered\n")
    # status: the default reports the change; the flag reports the skip.
    st = cli("status", "--root", str(root))
    check("status (no flag) reports the pinned champion as CHANGED",
          "pinned:        CHANGED" in (st.stdout + st.stderr),
          (st.stdout + st.stderr)[-200:])
    st_skip = cli("status", "--root", str(root), "--skip-hash")
    out = st_skip.stdout + st_skip.stderr
    check("status --skip-hash says the checks were SKIPPED (never 'verified')",
          "not verified (--skip-hash)" in out and "hash checks:   SKIPPED" in out
          and "hash checks:   verified" not in out,
          out[-260:])
    # run: refused by default, accepted with the flag.
    blocked = run_root(root)
    check("run (no flag) refuses a broken pinned chain",
          blocked.returncode != 0
          and "pinned champion content changed after it was registered" in
          (blocked.stdout + blocked.stderr),
          (blocked.stdout + blocked.stderr)[-260:])
    allowed = run_root(root, "--skip-hash")
    check("run --skip-hash proceeds and says the checks were skipped",
          allowed.returncode == 0 and "SKIPPED" in (allowed.stdout + allowed.stderr),
          (allowed.stdout + allowed.stderr)[-260:])
    # decide: exit 5 without the flag; certified-with-a-note with it.
    refused = cli("decide", "--root", str(root))
    check("decide (no flag) refuses to certify the tampered chain (exit 5)",
          refused.returncode == 5
          and decision_of(root)["certification"]["certified"] is False,
          (refused.stdout + refused.stderr)[-200:])
    signed = cli("decide", "--root", str(root), "--skip-hash")
    dec = decision_of(root)
    cert = dec["certification"]
    check("decide --skip-hash certifies, and the verdict records hash_checks=skipped",
          signed.returncode == 0 and cert["certified"] is True
          and cert.get("hash_checks") == "skipped"
          and any("--skip-hash" in str(n) for n in cert.get("notes") or []),
          json.dumps({k: cert.get(k) for k in ("certified", "hash_checks")}))
    check("decision.json's integrity block records the skip too",
          dec["integrity"].get("hash_checks") == "skipped"
          and "--skip-hash" in str(dec["integrity"].get("hash_checks_note")),
          json.dumps({k: dec["integrity"].get(k) for k in ("hash_checks",)})[:120])
    check("the published status document carries the skipped note",
          "--skip-hash" in (root / nb.FINAL_CLEAN_README_NAME).read_text(encoding="utf-8"))
    # The skip is per INVOCATION: the recorded digests are still there, so the
    # very next plain invocation detects the same tamper again.
    again = cli("decide", "--root", str(root))
    check("a later invocation WITHOUT the flag detects the tamper again (digests were kept)",
          again.returncode == 5
          and decision_of(root)["certification"].get("hash_checks") == "verified"
          and decision_of(root)["certification"]["certified"] is False,
          (again.stdout + again.stderr)[-160:])
    return root


def test_tampered_sandbox_input_and_fresh_recording():
    print()
    print("== a tampered run input, and recording still happens under the flag ==")
    tmp = scratch("paper_skip_hash2_")
    root = make_root(tmp)
    p = run_root(root, "--skip-hash")
    state = state_of(root)
    check("a round driven from the start WITH --skip-hash completes and pins",
          p.returncode == 0 and state.get("pinned") and state.get("original_digest"),
          (p.stdout + p.stderr)[-200:])
    produced = [r for r in state["runs"].values()
                if r.get("kind") in ("rewrite", "revise", "integrate")]
    check("the producing runs still RECORD their content digests under the flag",
          produced and all(r.get("corpus_digest") for r in produced),
          str([(r["id"], bool(r.get("corpus_digest"))) for r in produced[:3]]))
    check("the pins carry their digests under the flag",
          all(pin.get("digest") for pin in state.get("pinned") or []))
    # The chain the flag recorded is verifiable by a later invocation that does
    # NOT skip: this decide must certify (nothing was tampered).
    clean = cli("decide", "--root", str(root))
    check("a later plain decide verifies the same chain and certifies",
          clean.returncode == 0
          and decision_of(root)["certification"].get("hash_checks") == "verified",
          (clean.stdout + clean.stderr)[-160:])
    # Now tamper one run's frozen input: the default path blocks, the flag skips.
    victim = root / "runs" / "r1_review" / "base" / "manuscript.md"
    assert victim.is_file(), victim
    with open(victim, "a", encoding="utf-8") as f:
        f.write("\ntampered input\n")
    blocked = run_root(root)
    check("run (no flag) refuses a modified frozen run input",
          blocked.returncode != 0 and "was modified after the sandbox was built" in
          (blocked.stdout + blocked.stderr),
          (blocked.stdout + blocked.stderr)[-220:])
    allowed = run_root(root, "--skip-hash")
    check("run --skip-hash proceeds past the same modified input",
          allowed.returncode == 0, (allowed.stdout + allowed.stderr)[-160:])


def main() -> int:
    try:
        test_switch_and_wiring()
        test_tampered_chain_and_the_flag()
        test_tampered_sandbox_input_and_fresh_recording()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} SKIP-HASH CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL SKIP-HASH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
