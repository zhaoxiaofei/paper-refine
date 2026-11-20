#!/usr/bin/env python3
"""Regression checks for the fix-bugs wave 1 (run 20261121-025312).

Covers the small confirmed defects whose surfaces are executable here:

  * F03 -- `run_all.tail_failures()` must not read a CHILD process's indented
    `[FAIL]` line as the suite's own failed check;
  * F13 -- a one-sided `cover_letter` block (`max` alone / `min` alone) keeps
    its missing side unbounded instead of inheriting the built-in 300/500;
  * F16 -- the Qwen/Dots adapters refuse an HTTP redirect instead of forwarding
    the Bearer key to the redirect target;
  * F20 -- `prepare_dsh_home()` returns its documented error tuple on a
    read-only profile instead of re-raising;
  * F21 -- the bounded, no-follow package reader enforces the caller's budget;
  * F22 -- a failed M2 reference scan is recorded as an UNKNOWN pin, not
    silently dropped.

Hermetic: local temp dirs and loopback servers only; no agent runs, no network.

Run:  python3 .paper_test/test_fix_bugs_20261121_wave1_fixstage.py
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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TESTDIR = WS / ".paper_test"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(path)
    return path


def load(name: str, path: Path, add_agent_common: bool = False):
    if add_agent_common:
        sys.path.insert(0, str(WS / "agent-common"))
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if add_agent_common:
            sys.path.pop(0)


# =====================================================================
# F03 -- a child process's indented [FAIL] is not the suite's own check
# =====================================================================
def test_run_all_failure_scan():
    print()
    print("== F03: the runner reads the suite's own check lines, not a child's ==")
    run_all = load("fb21_run_all", TESTDIR / "run_all.py")
    rundir = scratch("fb21_runall_")
    (rundir / "passing.log").write_text(
        "  [FAIL] r1_a2_revise: 5 problem(s) -- after the continuation\n"
        "[ok ] the suite's own checks all pass\n"
        "ALL DOCUMENT-RECOVERY CHECKS PASSED\n", encoding="utf-8")
    check("a passing suite that echoes an indented child [FAIL] has no failure line",
          run_all.tail_failures("passing", rundir) == [],
          str(run_all.tail_failures("passing", rundir)))
    (rundir / "failing.log").write_text(
        "  [FAIL] a child process line\n"
        "[FAIL] the suite's own check failed  -- evidence\n", encoding="utf-8")
    check("a real column-0 [FAIL] is still reported",
          run_all.tail_failures("failing", rundir)
          == ["[FAIL] the suite's own check failed  -- evidence"],
          str(run_all.tail_failures("failing", rundir)))
    (rundir / "bare.log").write_text("FAIL the bare form still counts\n", encoding="utf-8")
    check("the bare column-0 FAIL form is still reported",
          run_all.tail_failures("bare", rundir) == ["FAIL the bare form still counts"],
          str(run_all.tail_failures("bare", rundir)))


# =====================================================================
# F13 -- one-sided cover-letter bounds
# =====================================================================
def _write_cover_profile(path: Path, block) -> None:
    profile = {"id": "one-sided", "label": "One Sided", "default_article_type": "research",
               "article_types": [{"id": "research", "label": "Research",
                                  "length_limits": {
                                      "abstract": {"base": None, "relaxation": None},
                                      "main_text": {"base": 10000, "relaxation": 1.0},
                                      **({"cover_letter": block} if block is not None else
                                         {})}}]}
    path.write_text(json.dumps(profile), encoding="utf-8")


def _cover_row(payload):
    return next((r for r in (payload or {}).get("rows") or []
                 if r.get("section") == "cover letter"), None)


def test_one_sided_cover_bound():
    print()
    print("== F13: a one-sided cover-letter block does not invent the other side ==")
    tmp = scratch("fb21_cover_")
    letter = tmp / "cover.md"
    letter.write_text("Dear Editor,\n\n" + " ".join(["word"] * 40) + "\n\nSincerely,\nA. Author\n",
                      encoding="utf-8")
    script = WS / "paper-skills" / "paper-review" / "scripts" / "count_words.py"

    def run(block):
        profile = tmp / "profile.json"
        _write_cover_profile(profile, block)
        proc = subprocess.run([sys.executable, str(script), str(letter), "--venue-profile",
                               str(profile), "--section", "cover-letter", "--json"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return None, proc.stderr
        return json.loads(proc.stdout), ""

    payload, err = run({"max": 200})
    row = _cover_row(payload)
    check("max alone means at most 200 words (no 300 floor)",
          row is not None and row.get("min") is None and row.get("max") == 200
          and row.get("within_preference") is True
          and "at most 200 words" in str(row.get("note")),
          f"{row} {err}")

    payload, err = run({"min": 300})
    row = _cover_row(payload)
    check("min alone means at least 300 words (no 500 ceiling)",
          row is not None and row.get("min") == 300 and row.get("max") is None
          and row.get("within_preference") is False
          and "at least 300 words" in str(row.get("note")),
          f"{row} {err}")

    payload, err = run({"min": None, "max": None})
    row = _cover_row(payload)
    check("an explicit null/null block means no preference",
          row is not None and row.get("min") is None and row.get("max") is None
          and row.get("within_preference") is True,
          f"{row} {err}")

    payload, err = run(None)
    row = _cover_row(payload)
    check("no cover_letter block still falls back to the built-in 300-500 range",
          row is not None and row.get("min") == 300 and row.get("max") == 500
          and row.get("within_preference") is False,
          f"{row} {err}")


# =====================================================================
# F16 -- the adapters refuse a redirect instead of forwarding the key
# =====================================================================
def test_redirect_refusal():
    print()
    print("== F16: a redirect is refused, so the Bearer key never leaves ==")
    seen = []

    class Capture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{capture.server_port}/steal")
            self.end_headers()

    capture = HTTPServer(("127.0.0.1", 0), Capture)
    redirect = HTTPServer(("127.0.0.1", 0), Redirect)
    for server in (capture, redirect):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for filename, modname in (("paper_qwen_agent.py", "fb21_qwen"),
                                  ("paper_dots_agent.py", "fb21_dots")):
            adapter = load(modname, WS / filename, add_agent_common=True)
            status, _body, err = adapter._request(
                "GET", f"http://127.0.0.1:{redirect.server_port}/v1/models",
                api_key="SECRET-KEY")
            check(f"{filename}: the 302 is a transport error, not a followed request",
                  status == 0 and "redirect refused" in str(err), f"{status} {err}")
        check("the redirect target received NO Authorization header",
              seen == [], str(seen))
    finally:
        for server in (capture, redirect):
            server.shutdown()
            server.server_close()


# =====================================================================
# F20 -- prepare_dsh_home returns its error tuple on a copy failure
# =====================================================================
def test_prepare_dsh_home_error_tuple():
    print()
    print("== F20: an unreadable dsh profile returns the documented error ==")
    dsh = load("fb21_dsh", WS / "paper_dsh_runtime.py", add_agent_common=True)
    tmp = scratch("fb21_dsh_home_")
    home = tmp / "home"
    src = home / "profiles" / "headless"
    src.mkdir(parents=True)
    bad = src / "cordis.yml"
    bad.write_text("x", encoding="utf-8")
    os.chmod(bad, 0)
    os.chmod(home, 0o500)
    old = os.environ.get("DSH_HOME")
    os.environ["DSH_HOME"] = str(home)
    try:
        result = dsh.prepare_dsh_home("qwen")
    finally:
        if old is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = old
        os.chmod(home, 0o700)
        os.chmod(bad, 0o600)
    check("a copy failure returns ('', reason, None), never raises",
          isinstance(result, tuple) and result[0] == "" and bool(result[1])
          and result[2] is None, str(result))


# =====================================================================
# F21 -- the bounded, no-follow reader honours a caller's budget
# =====================================================================
def test_bounded_reader_budget():
    print()
    print("== F21: package scans read through the bounded, no-follow reader ==")
    pp = load("fb21_pipeline", WS / "paper_pipeline.py")
    tmp = scratch("fb21_read_")
    small = tmp / "small.txt"
    small.write_text("hello", encoding="utf-8")
    big = tmp / "big.txt"
    big.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    link = tmp / "link.txt"
    os.symlink(small, link)
    check("a file over the caller's limit is refused, not read whole",
          pp.read_text_bounded(big, limit=2_000_000) is None)
    check("a file inside the limit is read",
          pp.read_text_bounded(small, limit=2_000_000) == "hello")
    check("a planted symlink is refused (no O_NOFOLLOW bypass)",
          pp.read_text_bounded(link, limit=2_000_000) is None)


# =====================================================================
# F22 -- a failed M2 pin is recorded, not silently dropped
# =====================================================================
def test_m2_pin_failure_is_unknown():
    print()
    print("== F22: a failed M2 scan leaves an UNKNOWN pin, not a clean table ==")
    pp = load("fb21_pipeline_m2", WS / "paper_pipeline.py")
    tmp = scratch("fb21_m2_")
    review = tmp / "guided_review"
    (review / "artifacts").mkdir(parents=True)
    (review / "artifacts" / "M2_references.md").write_text(
        "| # | document | entry | identifier | disposition |\n"
        "|---|---|---|---|---|\n", encoding="utf-8")
    pins = {"artifacts/M2_references.md": [
        {"columns": ["document", "entry", "identifier"], "count": 0, "label": "M2",
         "error": "the M2 reference seed could not be re-derived from base/ (boom)"}]}
    report = pp.artifact_quality_report(review, require_files=False,
                                        seeded_row_pins=pins)
    problems = report.get("artifacts/M2_references.md") or []
    check("the failure-marked pin is reported as UNKNOWN",
          any("could not be re-derived" in p for p in problems), str(problems)[:300])

    corpus = tmp / "base"
    corpus.mkdir()
    (corpus / "manuscript.md").write_text("Abstract\n\nWe analysed 12 samples.\n",
                                          encoding="utf-8")
    ctx = type("C", (), {"cfg": {}})()
    mod = pp._format_module()
    check("the format module is available to patch reference_integrity_rows",
          mod is not None and hasattr(mod, "reference_integrity_rows"), type(mod).__name__)
    original = getattr(mod, "reference_integrity_rows", None)
    mod.reference_integrity_rows = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("reference scan failed"))
    try:
        derived = pp.review_seeded_row_pins(ctx, corpus)
    finally:
        if original is not None:
            mod.reference_integrity_rows = original
    m2 = derived.get("artifacts/M2_references.md") or []
    check("review_seeded_row_pins records the M2 failure instead of dropping it",
          bool(m2) and any(p.get("error") for p in m2), str(m2)[:300])


def main():
    test_run_all_failure_scan()
    test_one_sided_cover_bound()
    test_redirect_refusal()
    test_prepare_dsh_home_error_tuple()
    test_bounded_reader_budget()
    test_m2_pin_failure_is_unknown()
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL FIX-BUGS WAVE 1 (FIXSTAGE) CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
