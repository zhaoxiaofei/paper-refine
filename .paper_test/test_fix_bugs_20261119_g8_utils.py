#!/usr/bin/env python3
"""Regression checks for 2026-11-19 fix-bugs wave 1, group `g8_utils`.

Candidates: F038, F128, F130, F136, F137, F138, F142, F144, F145, F171, F172,
F175. Each check pins one behaviour this wave re-verified on the tree and
repaired; every fixture is hermetic (tempfile.mkdtemp()) and a chmod-000 fixture
is restored before cleanup so a non-root runner can remove it.

Run:  python3 .paper_test/test_fix_bugs_20261119_g8_utils.py
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
from unittest import mock

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1119g8_pp", "paper_pipeline.py")
ec = load("fb1119g8_ec", "scripts/env_test_closure.py")
rt = load("fb1119g8_rt", "paper-skills/paper-revise/scripts/revision_token.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def restore_modes(root: Path) -> None:
    for p in sorted(root.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        try:
            os.chmod(p, 0o755 if p.is_dir() else 0o644)
        except OSError:
            pass
    try:
        os.chmod(root, 0o755)
    except OSError:
        pass


def cleanup() -> None:
    for tmp in TMPDIRS:
        restore_modes(tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def run_node(source: str):
    node = shutil.which("node")
    if not node:
        return None
    proc = subprocess.run([node, "--input-type=module", "-e", source],
                          cwd=str(WS), text=True, capture_output=True, timeout=120)
    return proc


# ---------------------------------------------------------------- F038
def test_f038_windows_component_walk():
    print("\n== F038: the dangling-symlink walk starts at the path ROOT ==")
    twins = [WS / "mcp-docx-compare" / "containment.mjs",
             WS / "mcp-docx-converter" / "containment.mjs"]
    for mjs in twins:
        text = mjs.read_text(encoding="utf-8")
        check(f"F038 {mjs.parent.name} seeds the walk from path.parse(abs).root",
              "const root = path.parse(abs).root;" in text
              and "abs.slice(root.length)" in text
              and "let cur = path.sep;" not in text)
    proc = run_node(
        "import * as path from 'node:path';\n"
        "const abs = 'C:\\\\Users\\\\x\\\\out.docx';\n"
        "const oldCur = path.win32.join(path.win32.sep, 'C:');\n"
        "const root = path.win32.parse(abs).root;\n"
        "const parts = abs.slice(root.length).split(path.win32.sep).filter(Boolean);\n"
        "let cur = root; const built = [];\n"
        "for (const part of parts) { cur = path.win32.join(cur, part); built.push(cur); }\n"
        "console.log(JSON.stringify({oldCur, root, built}));\n")
    if proc is None:
        check("F038 node unavailable: win32 component proof skipped statically", True)
    else:
        try:
            got = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            got = {}
        check("F038 the old seed built an invalid '\\\\C:' component",
              got.get("oldCur") == "\\C:", str(got))
        check("F038 the fixed walk builds drive-rooted, lstat-able components",
              got.get("root") == "C:\\"
              and got.get("built") == ["C:\\Users", "C:\\Users\\x",
                                       "C:\\Users\\x\\out.docx"], str(got))
    # POSIX behaviour must be unchanged: a dangling link inside a root is refused.
    tmp = scratch("f038_")
    allowed = tmp / "allowed"
    allowed.mkdir()
    (allowed / "ok.docx").write_bytes(b"x")
    os.symlink(tmp / "missing.docx", allowed / "dangling.docx")
    mod = json.dumps(str(WS / "mcp-docx-compare" / "containment.mjs"))
    proc = run_node(
        f"import {{ containsPath }} from {mod};\n"
        f"console.log(JSON.stringify({{dangling: containsPath({json.dumps(str(allowed / 'dangling.docx'))},"
        f" [{json.dumps(str(allowed))}]), ok: containsPath({json.dumps(str(allowed / 'ok.docx'))},"
        f" [{json.dumps(str(allowed))}])}}));\n")
    if proc is not None:
        try:
            got = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            got = {}
        check("F038 a dangling link is still refused, a real target still allowed",
              got.get("dangling") is False and got.get("ok") is True, str(got))


# ---------------------------------------------------------------- F128
def test_f128_symlink_parent_guard_after_dotdot():
    print("\n== F128: '..' after a symlinked component is refused, not collapsed ==")
    tmp = scratch("f128_")
    root = tmp / "root"
    (root / "sb").mkdir(parents=True)
    outside = tmp / "outside"
    outside.mkdir()
    (root / "sb" / "link").symlink_to(outside, target_is_directory=True)
    pp.register_write_anchor(root)
    dst = root / "sb" / "link" / ".." / "escaped.txt"
    try:
        pp.write_text_atomic(dst, "pwned")
        raised = None
    except OSError as e:
        raised = e
    check("F128 the atomic writer refuses link/../escaped.txt", raised is not None, str(raised))
    check("F128 no byte landed outside the tree",
          not (tmp / "escaped.txt").exists() and not (root / "sb" / "escaped.txt").exists())
    try:
        pp._refuse_symlinked_read_parent(root / "sb" / "link" / ".." / "x.txt")
        read_raised = None
    except OSError as e:
        read_raised = e
    check("F128 the bounded READER refuses the same shape", read_raised is not None,
          str(read_raised))
    pp.write_text_atomic(root / "sb" / "ok.txt", "ok")
    check("F128 a legitimate write inside the root still works",
          (root / "sb" / "ok.txt").read_text(encoding="utf-8") == "ok")
    # The one legal directory link (a canonical evidence area) is still readable.
    store = root / "non_revised" / "raw_data"
    store.mkdir(parents=True)
    (store / "table.csv").write_text("a,b\n", encoding="utf-8")
    pkg = root / "runs" / "r1" / "revised"
    pkg.mkdir(parents=True)
    os.symlink(os.path.relpath(store, pkg), pkg / "raw_data")
    try:
        pp._refuse_symlinked_read_parent(pkg / "raw_data" / "table.csv")
        evidence_ok = True
    except OSError:
        evidence_ok = False
    check("F128 the canonical evidence link is still readable", evidence_ok)


# ---------------------------------------------------------------- F130
def test_f130_surrogate_filename_json():
    print("\n== F130: a surrogate-escaped file name no longer aborts the writer ==")
    tmp = scratch("f130_")
    name = "bad\udcffname.txt"
    dest = tmp / "out.json"
    try:
        pp.write_json_atomic(dest, {"files": {name: "abc"}})
        raised = None
    except Exception as e:                                          # noqa: BLE001
        raised = e
    check("F130 the manifest/state writer does not raise", raised is None, repr(raised))
    check("F130 the destination was written", dest.is_file())
    raw = dest.read_text(encoding="utf-8")
    check("F130 the file is strict JSON with the same name",
          json.loads(raw)["files"] == {name: "abc"})
    check("F130 read_json revives the same surrogate string",
          pp.read_json(dest)["files"] == {name: "abc"})
    pp.write_json_atomic(dest, {"files": {"plain.txt": "abc"}})
    check("F130 plain ASCII output is unchanged",
          dest.read_text(encoding="utf-8") ==
          '{\n  "files": {\n    "plain.txt": "abc"\n  }\n}')


# ---------------------------------------------------------------- F136
def test_f136_unreadable_asset_is_not_absent():
    print("\n== F136: an unreadable frozen asset is not recorded as absent ==")
    tmp = scratch("f136_")
    base = tmp / "base"
    (base / "paper_pipeline_parts").mkdir(parents=True)
    (base / "paper_pipeline_parts" / "p01.py").write_text("x", encoding="utf-8")
    good = pp.asset_dir_digest(base, "paper_pipeline_parts")
    os.chmod(base / "paper_pipeline_parts" / "p01.py", 0o000)
    try:
        unreadable = pp.asset_dir_digest(base, "paper_pipeline_parts")
    finally:
        os.chmod(base / "paper_pipeline_parts" / "p01.py", 0o644)
    check("F136 a readable bundle still hashes", isinstance(good, str) and len(good) == 64,
          str(good))
    check("F136 an unreadable bundle returns the distinct sentinel",
          unreadable == "<unreadable>", repr(unreadable))
    check("F136 an absent directory still returns None",
          pp.asset_dir_digest(base, "not-there") is None)
    os.chmod(base / "paper_pipeline_parts" / "p01.py", 0o000)
    try:
        frozen = pp.module_manifest(base)
    finally:
        os.chmod(base / "paper_pipeline_parts" / "p01.py", 0o644)
    check("F136 module_manifest records the sentinel, not None",
          frozen.get("paper_pipeline_parts") == "<unreadable>", str(frozen))
    # The drift readers compare only TRUTHY hashes (`if a and b and a != b`):
    # the sentinel must therefore be truthy and different from a real digest.
    check("F136 the sentinel survives the truthy drift comparison",
          bool("<unreadable>") and "<unreadable>" != good)


def test_f136b_unreadable_subdirectory_is_unreadable():
    print("\n== F136/N-g8-2: an unreadable SUBDIRECTORY is not hashed as a complete tree ==")
    tmp = scratch("f136b_")
    asset = tmp / "asset"
    (asset / "sub").mkdir(parents=True)
    (asset / "a.txt").write_text("a", encoding="utf-8")
    (asset / "sub" / "b.txt").write_text("b", encoding="utf-8")
    good = pp.asset_dir_digest(tmp, "asset")
    os.chmod(asset / "sub", 0o000)
    try:
        unreadable = pp.asset_dir_digest(tmp, "asset")
    finally:
        os.chmod(asset / "sub", 0o755)
    check("F136/N-g8-2 a readable tree still hashes", isinstance(good, str) and len(good) == 64)
    check("F136/N-g8-2 an unreadable subtree returns the sentinel",
          unreadable == "<unreadable>", repr(unreadable))


# ---------------------------------------------------------------- F137
def test_f137_iqr_malformed_is_worst():
    print("\n== F137: an uncomputable IQR is the WORST value, never 0.0 ==")
    inf = float("inf")
    check("F137 a NaN score does not yield the best IQR",
          pp.iqr_of([float("nan"), 1.0]) == inf)
    check("F137 an Infinity score does not yield the best IQR",
          pp.iqr_of([float("inf"), 2.0]) == inf)
    check("F137 a non-numeric score does not yield the best IQR",
          pp.iqr_of(["x", 1.0]) == inf)
    check("F137 a valid panel still yields its real IQR", pp.iqr_of([1.0, 2.0, 3.0]) == 1.0)
    check("F137 a single score keeps the defined 0.0", pp.iqr_of([3.0]) == 0.0)
    check("F137 a larger IQR ranks worse than a smaller one",
          pp.iqr_of([1.0, 2.0, 3.0]) == 1.0 and inf > 1.0)


# ---------------------------------------------------------------- F138
def test_f138_lookup_cache_never_fatal():
    print("\n== F138: the lookup cache write is never fatal ==")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.root = scratch("f138_")
    ok = True
    for bad in ({"k": {"hits": {1, 2}}}, {"k": {"hits": b"x"}},
                {"k": {"hits": "ok\udcff"}}):
        try:
            pp._lookup_cache_store(ctx, bad)
        except Exception as e:                                      # noqa: BLE001
            ok = False
            print(f"  raised {type(e).__name__}: {e}")
    check("F138 a set/bytes/non-UTF-8 cache value does not escape the store", ok)
    pp._lookup_cache_store(ctx, {"k": {"verdict": "found", "hits": ["ok"]}})
    check("F138 a well-formed cache value is still stored",
          pp._lookup_cache(ctx).get("k", {}).get("hits") == ["ok"])


# ---------------------------------------------------------------- F142
def test_f142_symlinked_corpus_root():
    print("\n== F142: a corpus directory that is itself a link is refused ==")
    tmp = scratch("f142_")
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "ms.docx").write_bytes(b"outside bytes")
    linked = tmp / "corpus_link"
    linked.symlink_to(outside, target_is_directory=True)
    real = tmp / "real"
    real.mkdir()
    (real / "ms.docx").write_bytes(b"outside bytes")
    check("F142 corpus_tree_manifest refuses the link like hash_manifest",
          pp.corpus_tree_manifest(linked) == {"files": {}, "count": 0}
          and pp.hash_manifest(linked) == {"files": {}, "count": 0})
    check("F142 corpus_dir_manifest refuses the link too",
          pp.corpus_dir_manifest(linked) == {"files": {}, "count": 0})
    check("F142 a real directory still hashes its files",
          "ms.docx" in (pp.corpus_dir_manifest(real).get("files") or {})
          and "ms.docx" in (pp.corpus_tree_manifest(real).get("files") or {}))


# ---------------------------------------------------------------- F144
def test_f144_requirements_write_is_atomic():
    print("\n== F144: requirements.test.txt is written atomically ==")
    tmp = scratch("f144_")
    out = tmp / "requirements.test.txt"
    rc = ec.main([str(out), "python-docx"])
    check("F144 a normal export still succeeds", rc == 0 and out.is_file(), str(rc))
    check("F144 no temporary sibling is left behind",
          [p.name for p in tmp.iterdir()] == [out.name],
          str([p.name for p in tmp.iterdir()]))
    # A failed replace must leave the PREVIOUS record in place, not a short file.
    before = out.read_text(encoding="utf-8")
    with mock.patch.object(ec.os, "replace", side_effect=OSError("boom")):
        rc = ec.main([str(out), "python-docx"])
    check("F144 a failed replace exits nonzero", rc == 1, str(rc))
    check("F144 a failed replace leaves the old record byte-identical",
          out.read_text(encoding="utf-8") == before)
    check("F144 a failed replace cleans its temporary",
          not [p for p in tmp.iterdir() if p.name.endswith(".tmp")],
          str([p.name for p in tmp.iterdir()]))
    # A symlinked destination is refused instead of written through.
    target = tmp / "target.txt"
    target.write_text("keep me\n", encoding="utf-8")
    link = tmp / "linked.requirements.test.txt"
    os.symlink(target, link)
    rc = ec.main([str(link), "python-docx"])
    check("F144 a symlinked destination is refused, never followed",
          rc == 1 and target.read_text(encoding="utf-8") == "keep me\n", str(rc))


# ---------------------------------------------------------------- F145
def test_f145_unlink_failure_is_not_reported_gone():
    print("\n== F145: a junk file that could not be removed fails the sweep ==")
    tmp = scratch("f145_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "keep.txt").write_text("k", encoding="utf-8")
    (pkg / "junk.pyc").write_text("junk", encoding="utf-8")
    os.chmod(pkg, 0o500)
    try:
        try:
            pp.strip_non_shippable_files_in_dir(pkg)
            raised = None
        except OSError as e:
            raised = e
        check("F145 an unremovable junk file raises instead of being reported gone",
              raised is not None and "junk.pyc" in str(raised), str(raised))
        check("F145 the junk file is still there (nothing was silently certified)",
              (pkg / "junk.pyc").is_file())
    finally:
        os.chmod(pkg, 0o755)
    (pkg / "junk.pyc").unlink()
    res = pp.strip_non_shippable_files_in_dir(pkg)
    check("F145 a clean sweep still returns its record", res.get("failed") == [], str(res))


# ---------------------------------------------------------------- F171
def test_f171_uppercase_identity_label_is_not_a_token():
    print("\n== F171: an uppercase identity letter is not a version token ==")
    for name in ("Appendix_A.docx", "Figure_B.pdf", "sample-A.txt", "Fig_A.png"):
        check(f"F171 {name} carries no version token",
              rt.filename_token(name) is None, repr(rt.filename_token(name)))
    for name, tok in (("manuscript-a.docx", "a"), ("ms-a.md", "a"),
                      ("supp-v2.tex", "v2"), ("paper-4f3a9c1.docx", "4f3a9c1")):
        check(f"F171 {name} still carries {tok!r}",
              rt.filename_token(name) == tok, repr(rt.filename_token(name)))
    check("F171 an identity label reference is not normalized away",
          rt.content_token_free(b"See Appendix_A.docx and Fig_A.png", []) ==
          b"See Appendix_A.docx and Fig_A.png")
    check("F171 a real 7-hex reference is still normalized",
          rt.content_token_free(b"See refs-4f3a9c1.bib", []) == b"See refs.bib")


# ---------------------------------------------------------------- F172
def test_f172_missing_transitive_dependency_fails_the_export():
    print("\n== F172: a missing transitive dependency fails the export ==")
    tmp = scratch("f172_")

    class FakeDist:
        def __init__(self, name, version, requires):
            self.metadata = {"Name": name}
            self.version = version
            self.requires = requires

    root = FakeDist("fake-root", "1.0", ["lxml >= 3.1.0", "typing-extensions"])
    deps = {"fake-root": root}
    # `lxml` is missing; `typing-extensions` is installed.
    deps["typing-extensions"] = FakeDist("typing-extensions", "4.9", [])

    def fake_distribution(name):
        try:
            return deps[ec._norm_dist(name)]
        except KeyError:
            raise ec.md.PackageNotFoundError(name) from None

    with mock.patch.object(ec.md, "distribution", side_effect=fake_distribution):
        unresolved = []
        seen = ec.closure(("fake-root",), unresolved=unresolved)
        check("F172 the closure records the missing dependency",
              unresolved == ["lxml"], str(unresolved))
        check("F172 the installed root/dependency are still resolved",
              set(seen) == {"fake-root", "typing-extensions"}, str(sorted(seen)))
        out = tmp / "requirements.test.txt"
        rc = ec.main([str(out), "fake-root"])
    check("F172 the export exits nonzero instead of reporting a full closure",
          rc == 1, str(rc))
    check("F172 no partial requirements file is written", not out.exists())


# ---------------------------------------------------------------- F175
def test_f175_skill_marker_sentence_is_qualified():
    print("\n== F175: the final-outputs marker sentence is mode-qualified ==")
    text = (WS / "paper-skills" / "paper-revise" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    check("F175 the unqualified claim is gone",
          "High priority is a `[AUTHOR TO COMPLETE: ...]` placeholder." not in flat)
    check("F175 the qualified sentence names the document policy and readme/off",
          "Under the `document` hand-off policy a high-priority item is a "
          "`[AUTHOR TO COMPLETE: ...]` placeholder" in flat
          and "under `readme`/`off` it is a high-importance TODO row" in flat)
    check("F175 hard rule 2 still forbids the marker under readme",
          "under `readme` the marker must NOT appear in a document" in flat)


def main() -> int:
    print(f"workspace: {WS}")
    try:
        test_f038_windows_component_walk()
        test_f128_symlink_parent_guard_after_dotdot()
        test_f130_surrogate_filename_json()
        test_f136_unreadable_asset_is_not_absent()
        test_f136b_unreadable_subdirectory_is_unreadable()
        test_f137_iqr_malformed_is_worst()
        test_f138_lookup_cache_never_fatal()
        test_f142_symlinked_corpus_root()
        test_f144_requirements_write_is_atomic()
        test_f145_unlink_failure_is_not_reported_gone()
        test_f171_uppercase_identity_label_is_not_a_token()
        test_f172_missing_transitive_dependency_fails_the_export()
        test_f175_skill_marker_sentence_is_qualified()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
