#!/usr/bin/env python3
"""Regression checks for the venue/setup candidates of the 2026-11-22 11:28
fix-bugs wave (batch J).

Run: python3 .paper_test/test_fix_wave1_J_venues_setup.py

  F32  profile listing/loading is bounded and no-follow (FIFO/symlink refused)
  F37  a top-level length_limits.source survives a parallel article_types table
  F126 a non-object state.config is a clean damaged-registry refusal
  F175 a disagreeing mirrored journal/article_type is reported
  F176 the top-level block populates the DEFAULT type only (comment + code)
  F186 `sources` values are carried through unchanged
  F24  a failed/incomplete add-venue sandbox is not published
  F25  a profile staged at the sandbox root is published
  F94  the venue row is matched by its FIRST cell, not any mention
  F103 add-venue --root re-records the frozen venue_profiles digest
  F162 the README check requires the venue's own row
  F187 a symlinked destination README is not read/replaced
  F206 a symlinked --profiles-dir is refused before any write
  F210 the staged profile is read through the bounded reader
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import signal
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("fix_wave1_J_pp", WS / "paper_pipeline.py")
pp = importlib.util.module_from_spec(_spec)
sys.modules["fix_wave1_J_pp"] = pp
_spec.loader.exec_module(pp)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(p):
    return Path(tempfile.mkdtemp(prefix="fw1j_" + p + "_"))


def add_venue_args(**kw):
    base = dict(venue="demo", profiles_dir=None, publish_only=True, from_sandbox=None,
                journal=None, article_type=None, no_download=True, agent="manual",
                agent_cmd=None, timeout=5, root=None)
    base.update(kw)
    return type("A", (), base)()


def run_add_venue(args):
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            pp.cmd_add_venue(args)
        return 0, out.getvalue()
    except SystemExit as e:
        return int(e.code or 0), out.getvalue()


def stage(sb, vid="demo", label="DEMO", status="complete", error=None):
    (sb / "store").mkdir(parents=True, exist_ok=True)
    (sb / "store" / f"{vid}.json").write_text(
        json.dumps({"id": vid, "label": label}), encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(
        json.dumps({"stage": "add-venue", "status": status, "error": error}),
        encoding="utf-8")


class _Ctx:
    cfg_path = "/tmp/pipeline_config.json"

    def __init__(self, cfg, state):
        self.cfg, self.state, self.root = cfg, state, None


def test_f32():
    d = scratch("f32")
    vp = d / "root" / "venue_profiles"
    vp.mkdir(parents=True)
    os.mkfifo(vp / "fifo.json")
    outside = d / "outside.json"
    outside.write_text(json.dumps({"id": "lnk", "label": "EXTERNAL"}), encoding="utf-8")
    (vp / "lnk.json").symlink_to(outside)

    def _alarm(signum, frame):
        raise TimeoutError("profile listing blocked on a FIFO")

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(20)
    try:
        found = pp.available_venue_profiles(d / "root")
    finally:
        signal.alarm(0)
    check("F32 a FIFO profile is listed as INVALID without blocking",
          bool(found.get("fifo", {}).get("error")), found.get("fifo"))
    check("F32 a symlinked profile is not followed", bool(found.get("lnk", {}).get("error")),
          found.get("lnk"))


def test_f37_f176():
    raw = {"id": "t", "label": "T",
           "article_types": [{"id": "default", "label": "Default"},
                             {"id": "letter", "label": "Letter"}],
           "length_limits": {"source": "venue-level source",
                             "abstract": {"base": 150, "relaxation": 1.0},
                             "main_text": {"base": 4000, "relaxation": 1.0}}}
    p = pp.VenueProfile(raw)
    check("F37 the top-level source is carried into the default type",
          p.data["article_types"][0]["length_limits"]["source"] == "venue-level source",
          p.data["article_types"][0]["length_limits"])
    check("F37 the reported source is the top-level citation",
          p.length_limits_source == "venue-level source", p.length_limits_source)
    check("F176 a non-default type still borrows no caps",
          p.with_article_type("letter").length_limits()["abstract"]["base"] is None)
    src = (WS / "paper_pipeline_parts" / "p01_venues.py").read_text(encoding="utf-8")
    check("F176 the comment no longer promises a venue-wide fallback",
          "venue-wide fallback for a type that states NO number" not in src
          and "populates ONLY the default type" in src)


def test_f126_f175():
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            pp.venue_config_findings(_Ctx({"venue": "nature-biotechnology"},
                                          {"config": ["not", "a", "dict"]}))
        raised = None
    except SystemExit as e:
        raised = int(e.code or 0)
    except AttributeError as e:
        raised = f"AttributeError: {e}"
    check("F126 a non-object state.config is a clean refusal (no AttributeError)",
          raised == 1, raised)
    notes, _ = pp.venue_config_findings(_Ctx(
        {"venue": "nature-biotechnology", "journal": "Journal A", "article_type": "article"},
        {"config": {"venue": "nature-biotechnology", "journal": "Journal B",
                    "article_type": "brief-communication"}}))
    check("F175 a disagreeing mirrored journal is reported",
          any("Journal B" in n and "Journal A" in n for n in notes), notes)
    check("F175 a disagreeing mirrored article type is reported",
          any("brief-communication" in n for n in notes), notes)


def test_f186():
    p = pp.VenueProfile({"id": "x", "label": "X",
                         "sources": {"nested": {"url": "https://u"}}})
    check("F186 nested source objects pass through unchanged",
          p.data["sources"]["nested"] == {"url": "https://u"}, p.data["sources"])


def test_f24_f25():
    d = scratch("f24")
    sb = d / "sb"
    stage(sb, status="failed", error="download blocked: paywall")
    (sb / "PUBLISH.md").write_text("blocked: paywall\n", encoding="utf-8")
    store = d / "store"
    store.mkdir()
    code, _ = run_add_venue(add_venue_args(profiles_dir=str(store), from_sandbox=str(sb)))
    check("F24 a failed session is refused with a non-zero exit", code == 1, code)
    check("F24 nothing from the failed session is published", not (store / "demo.json").exists())

    d = scratch("f25")
    sb = d / "sb"
    sb.mkdir()
    (sb / "demo.json").write_text(json.dumps({"id": "demo", "label": "EDITED"}),
                                 encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(
        json.dumps({"stage": "add-venue", "status": "complete", "error": None}),
        encoding="utf-8")
    store = d / "store"
    store.mkdir()
    (store / "demo.json").write_text(json.dumps({"id": "demo", "label": "OLD"}),
                                     encoding="utf-8")
    code, out = run_add_venue(add_venue_args(profiles_dir=str(store), from_sandbox=str(sb)))
    check("F25 a profile staged at the sandbox root is published",
          code == 0 and json.loads((store / "demo.json").read_text())["label"] == "EDITED",
          out[-200:])
    check("F25 the run does not report profile=MISSING", "profile=MISSING" not in out,
          out[-200:])


def test_f94_f162_f187():
    d = scratch("f94")
    body = ("# Venue profiles\n\n## Schema\n\n| field | type |\n|---|---|\n"
            "| `id` | slug for `demo` |\n")
    staged, dest = d / "README.md", d / "store.md"
    staged.write_text(body, encoding="utf-8")
    dest.write_text(body, encoding="utf-8")
    got = pp._merge_readme_row(staged, dest, "demo", {"label": "Demo", "description": "d"})
    rows = [ln for ln in dest.read_text(encoding="utf-8").splitlines()
            if pp._readme_has_venue_row(ln, "demo")]
    check("F94 a schema row mentioning the id is not taken as the venue row",
          got in ("synthesized", "appended") and len(rows) == 1, (got, rows))
    check("F162 a prose mention is not a venue row",
          pp._readme_has_venue_row("`demo` is mentioned in prose", "demo") is False)
    check("F162 the venue's own row is recognised",
          pp._readme_has_venue_row("| `demo` | d |", "demo") is True)

    d = scratch("f187")
    outside = d / "outside.md"
    outside.write_text("| `x` | EXTERNAL SECRET ROW |\n", encoding="utf-8")
    dest = d / "README.md"
    dest.symlink_to(outside)
    got = pp._merge_readme_row(None, dest, "newvenue", {"label": "New", "description": "d"})
    check("F187 a symlinked destination README is refused",
          got.startswith("refused") and dest.is_symlink(), got)
    check("F187 the external file's contents were not copied",
          outside.read_text(encoding="utf-8") == "| `x` | EXTERNAL SECRET ROW |\n")


def test_f103():
    d = scratch("f103")
    root = d / "root"
    vp = root / "venue_profiles"
    vp.mkdir(parents=True)
    (root / "state.json").write_text(json.dumps(
        {"version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": [], "run_logs": [],
         "pipeline": {"modules": {"venue_profiles": "OLD_DIGEST"}}}), encoding="utf-8")
    (root / "pipeline_config.json").write_text(json.dumps({"venue": "demo"}), encoding="utf-8")
    sb = d / "sb"
    stage(sb)
    code, out = run_add_venue(add_venue_args(profiles_dir=str(vp), from_sandbox=str(sb),
                                             root=str(root)))
    digest = json.loads((root / "state.json").read_text())[
        "pipeline"]["modules"]["venue_profiles"]
    check("F103 add-venue --root re-records the frozen venue_profiles digest",
          code == 0 and digest != "OLD_DIGEST", (code, digest, out[-120:]))


def test_f206_f210():
    d = scratch("f206")
    outside = d / "outside"
    outside.mkdir()
    link = d / "link"
    link.symlink_to(outside)
    sb = d / "sb"
    stage(sb)
    code, out = run_add_venue(add_venue_args(profiles_dir=str(link), from_sandbox=str(sb)))
    check("F206 a symlinked --profiles-dir is refused",
          code == 1 and not any(outside.iterdir()), (code, out[-160:]))

    calls = []
    real = pp.read_json
    pp.read_json = lambda p, *a, **k: (calls.append(str(p)), real(p, *a, **k))[1]
    try:
        d = scratch("f210")
        sb = d / "sb"
        stage(sb)
        store = d / "store"
        store.mkdir()
        code, out = run_add_venue(add_venue_args(profiles_dir=str(store),
                                                 from_sandbox=str(sb)))
    finally:
        pp.read_json = real
    hits = sum(1 for c in calls if c.endswith("demo.json"))
    check("F210 the staged profile is validated through the bounded JSON reader",
          code == 0 and hits >= 2, (code, hits))


def main():
    test_f32()
    test_f37_f176()
    test_f126_f175()
    test_f186()
    test_f24_f25()
    test_f94_f162_f187()
    test_f103()
    test_f206_f210()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL J VENUES/SETUP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
