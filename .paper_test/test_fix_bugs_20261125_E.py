#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 fix-bugs wave, group E.

One check per confirmed candidate (F007, F009, F011, F018, F019, F020, F021,
F023, F107, F108, F109). Every check fails on the pre-fix tree and pins the
invariant the fix restores.

Hermetic: temp dirs only, no network, no Word/Office. The two `setup` invocations
drive the maintained `paper_pipeline.py` as an operator would.

Run:  python3 .paper_test/test_fix_bugs_20261125_E.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1125e_pp", "paper_pipeline.py")

FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


class FakeCtx:
    """Just the attributes corpus/redline/tracking helpers read."""

    def __init__(self, root: Path, state: dict = None):
        self.root = Path(root)
        self.pristine = self.root / "non_revised"
        self.state = {} if state is None else state
        self.source_manifest = {}


def cli(*argv, timeout=300):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + "word " * 40 + "\n\nIntroduction\n\n" + "text " * 80 + "\n",
        encoding="utf-8")
    return src


def make_root(tmp: Path) -> Path:
    src = make_source(tmp)
    root = tmp / "root"
    proc = cli("setup", "--source", str(src), "--root", str(root),
               "--rounds", "1", "--rewrites", "1", "--revises", "1", "--judges", "1")
    assert proc.returncode == 0, (proc.stdout[-2000:], proc.stderr[-2000:])
    return root


# ---------------------------------------------------------------- F007
def test_f007_symlinked_staged_store():
    print("\n== F007: add-venue must not publish through a symlinked staged store/ ==")
    tmp = scratch("e_f007_")
    sb = tmp / "sb"
    sb.mkdir()
    outside = tmp / "outside"
    (outside / "demo.official").mkdir(parents=True)
    (outside / "demo.json").write_text(json.dumps({"id": "demo", "label": "Demo"}),
                                       encoding="utf-8")
    (outside / "README.md").write_text(
        "| Venue | Description |\n|---|---|\n| `demo` | x |\n", encoding="utf-8")
    (outside / "demo.official" / "secret.txt").write_text("SECRET-HOST-FILE", encoding="utf-8")
    os.symlink(outside, sb / "store")
    dest = tmp / "dest"
    dest.mkdir()
    published = False
    try:
        pub = pp.publish_add_venue_staging(sb, dest, "demo")
        published = ((dest / "demo.official" / "secret.txt").exists()
                     or (dest / "demo.json").exists())
        detail = json.dumps(pub)
    except OSError as e:
        detail = f"refused: {e}"
    check("F007 a symlinked store/ is refused, not read through", not published, detail)


# ---------------------------------------------------------------- F009
def test_f009_missing_census():
    print("\n== F009: a missing defect census is MISSING EVIDENCE, not zero ==")
    missing = pp.no_progress_measure(
        {"defect_prefix_census": None, "defect_prefix_total": 0,
         "median": 1, "mean": 1, "iqr": 0})
    clean = pp.no_progress_measure(
        {"defect_prefix_census": [0], "defect_prefix_total": 0,
         "median": 1, "mean": 1, "iqr": 0})
    sentinel = pp.champion_sort_key(
        {"defect_prefix_census": None, "median": 1, "mean": 1, "iqr": 0})
    check("F009 no census sorts as the worst key, like champion_sort_key",
          missing is not None and missing[0] == (10 ** 9,)
          and sentinel[0] == 10 ** 9 and missing > clean,
          f"{missing} vs clean {clean}, champion census {sentinel[0]}")


# ---------------------------------------------------------------- F011
def test_f011_policy_bool_validation():
    print("\n== F011: --format-policy type-checks unlink_zotero_fields_at_publish ==")
    tmp = scratch("e_f011_")
    src = make_source(tmp)
    policy = tmp / "policy.json"
    policy.write_text(json.dumps({"unlink_zotero_fields_at_publish": ["no"]}),
                      encoding="utf-8")
    proc = cli("setup", "--source", str(src), "--root", str(tmp / "root"),
               "--format-policy", str(policy))
    check("F011 a wrong-typed unlink_zotero_fields_at_publish is refused at setup",
          proc.returncode == 2 and "unlink_zotero_fields_at_publish" in proc.stderr,
          f"exit={proc.returncode} stderr={proc.stderr[-400:]!r}")


# ---------------------------------------------------------------- F018
def test_f018_redline_non_dict_version():
    print("\n== F018: a non-dict redlines/manifest.json version entry is stale ==")
    tmp = scratch("e_f018_")
    root = tmp / "root"
    root.mkdir()
    ctx = FakeCtx(root)
    rd = root / "redlines"
    rd.mkdir()
    (rd / "manifest.json").write_text(json.dumps({"versions": ["bogus"]}),
                                      encoding="utf-8")
    ok, detail = False, ""
    try:
        manifest = pp.run_redlines(ctx, rounds=[], versions=None, tool="auto")
        ok = isinstance(manifest, dict) and manifest.get("versions") == []
        detail = json.dumps(manifest.get("versions"))
    except AttributeError as e:
        detail = f"AttributeError: {e}"
    check("F018 a non-dict stored version row is dropped, not .get()'d", ok, detail)


# ---------------------------------------------------------------- F019
def test_f019_tracking_non_object_manifest():
    print("\n== F019: a non-object tracking/manifest.json is rebuilt, not a crash ==")
    tmp = scratch("e_f019_")
    root = tmp / "root"
    root.mkdir()
    ctx = FakeCtx(root)
    td = root / "tracking"
    td.mkdir()
    (td / "manifest.json").write_text(json.dumps([{"label": "x"}]), encoding="utf-8")
    ok, detail = False, ""
    try:
        m1 = pp.merge_tracking_entries(ctx, [])
        m2 = pp.run_difference_tracking(ctx, rounds=[], versions=None,
                                        tool="auto", quiet=True)
        ok = (isinstance(m1, dict) and m1.get("versions") == []
              and isinstance(m2, dict) and m2.get("versions") == [])
        detail = f"{m1.get('versions')} / {m2.get('versions')}"
    except AttributeError as e:
        detail = f"AttributeError: {e}"
    check("F019 a JSON list manifest is coerced to the empty registry", ok, detail)


# ---------------------------------------------------------------- F020
def test_f020_skip_hash_json_stdout():
    print("\n== F020: --skip-hash does not corrupt a --json command's stdout ==")
    tmp = scratch("e_f020_")
    root = make_root(tmp)
    proc = cli("agents", "--root", str(root), "--json", "--skip-hash")
    parsed = None
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError) as e:
        parsed = e
    check("F020 `agents --json --skip-hash` stdout parses as JSON",
          proc.returncode == 0 and isinstance(parsed, dict) and "rounds" in parsed,
          f"exit={proc.returncode} first={proc.stdout[:120]!r} err={parsed!r}")


# ---------------------------------------------------------------- F021
def test_f021_bare_no_findings():
    print("\n== F021: the documented bare `no findings` disposition is accepted ==")
    ok = (pp._audit_disposition_ok("no findings")
          and pp._audit_disposition_ok("no finding")
          and pp._audit_disposition_ok("0 findings")
          # the filler guard still refuses a filler tail
          and not pp._audit_disposition_ok("no findings -- lorem ipsum"))
    check("F021 `no findings` passes while a filler tail still fails", ok,
          f"no findings={pp._audit_disposition_ok('no findings')}")


# ---------------------------------------------------------------- F023
def test_f023_profile_rules_is_directory():
    print("\n== F023: a directory at INSTRUCTIONS/PROFILE_RULES.md is refused ==")
    tmp = scratch("e_f023_")
    sb = tmp / "sb"
    (sb / "INSTRUCTIONS" / "PROFILE_RULES.md").mkdir(parents=True)
    raised = None
    with contextlib.redirect_stderr(open(os.devnull, "w")):
        try:
            pp.page_stage_prompt(sb, "BODY\n\nRULE BLOCK\n",
                                 [("TEST RULE", "RULE BLOCK\n")],
                                 "guided_review", profile="medium")
        except SystemExit as e:
            raised = e.code
        except IsADirectoryError as e:
            raised = f"IsADirectoryError: {e}"
    check("F023 the paging pass fails closed with the documented refusal", raised == 1,
          f"raised={raised!r}")


# ---------------------------------------------------------------- F107
def test_f107_unsanitized_container_gap():
    print("\n== F107: a copy-as-is metadata container is a NAMED anonymity gap ==")
    tmp = scratch("e_f107_")
    root = tmp / "root"
    (root / "non_revised").mkdir(parents=True)
    odt = root / "non_revised" / "ms.odt"
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("meta.xml",
                   "<office:document-meta><meta>"
                   "<dc:creator>Alice Author</dc:creator>"
                   "</meta></office:document-meta>")
        z.writestr("content.xml", "<office:document-content/>")
    ctx = FakeCtx(root)
    out = tmp / "view"
    pp.build_judge_view(ctx, 1, pp.ORIGINAL_ID, out, time.time(), "seed")
    warnings = (ctx.state.get("view_transform_warnings") or {})
    flat = [w for rows in warnings.values() for w in rows]
    cert = {}
    pp.record_anonymity_gaps(ctx, cert)
    check("F107 the .odt copy records an anonymity gap in state and the decision",
          any(".odt" in w and "byte-for-byte" in w for w in flat)
          and bool(cert.get("anonymity_gaps")),
          f"warnings={flat} cert={bool(cert.get('anonymity_gaps'))}")


# ---------------------------------------------------------------- F108
def test_f108_work_dir_judged():
    print("\n== F108: a top-level work/ is either scratch everywhere or judged ==")
    tmp = scratch("e_f108_")
    root = tmp / "root"
    (root / "non_revised" / "work").mkdir(parents=True)
    (root / "non_revised" / "ms.tex").write_text("hi", encoding="utf-8")
    (root / "non_revised" / "work" / "notes.txt").write_text("scratch", encoding="utf-8")
    ctx = FakeCtx(root)
    manifest = set((pp.corpus_manifest(ctx, 1, pp.ORIGINAL_ID).get("files") or {}))
    view = {rel for rel, _p in pp.corpus_files_for_view(ctx, 1, pp.ORIGINAL_ID)}
    check("F108 the digest/pin corpus and the judge view carry the same files",
          manifest == view, f"manifest={sorted(manifest)} view={sorted(view)}")


# ---------------------------------------------------------------- F109
def test_f109_string_round_normalized():
    print("\n== F109: a state.json round recorded as \"1\" is normalized on load ==")
    tmp = scratch("e_f109_")
    root = tmp / "root"
    root.mkdir()
    (root / "pipeline_config.json").write_text(
        json.dumps({"rounds": 1, "judges": [1], "venue": "generic"}), encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "version": pp.STATE_VERSION,
        "runs": {"r1_judge_a1_j1": {
            "id": "r1_judge_a1_j1", "kind": "judge", "round": "1",
            "sandbox": "runs/r1_judge_a1_j1", "status": "done"}},
        "rounds": {}, "pinned": [], "log": []}), encoding="utf-8")
    ok, detail = False, ""
    try:
        ctx = pp.Ctx(root)
        ctx.load(need_cfg=False)
        rec = ctx.run("r1_judge_a1_j1")
        found = ctx.runs(kind="judge", round_no=1)
        ok = rec.get("round") == 1 and [r.get("id") for r in found] == ["r1_judge_a1_j1"]
        detail = f"round={rec.get('round')!r} found={[r.get('id') for r in found]}"
    except SystemExit as e:
        detail = f"SystemExit {e}"
    check("F109 round-scoped queries see the legacy string round", ok, detail)


def main() -> int:
    try:
        test_f007_symlinked_staged_store()
        test_f009_missing_census()
        test_f011_policy_bool_validation()
        test_f018_redline_non_dict_version()
        test_f019_tracking_non_object_manifest()
        test_f020_skip_hash_json_stdout()
        test_f021_bare_no_findings()
        test_f023_profile_rules_is_directory()
        test_f107_unsanitized_container_gap()
        test_f108_work_dir_judged()
        test_f109_string_round_normalized()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
