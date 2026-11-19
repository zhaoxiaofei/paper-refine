#!/usr/bin/env python3
"""Regression checks for the 2026-11-19 fix-bugs wave 1, group g2_helpers.

One check per candidate this wave re-validated on the tree and repaired:

  F007  a plain/HTML/DOCX heading ends the reference list (no phantom entries)
  F129  run_bounded kills the child's process group on Ctrl-C, not only on timeout
  F131  an --only made only of separators is a usage error, not "everything"
  F132  the DOCX paragraph reader enforces the package budget and skips notes
  F133  pid_alive never uses os.kill(pid, 0) on Windows (it would TERMINATE it)
  F135  a FIFO nested inside a copied package is skipped, not a raw shutil.Error
  F146  a materializer refuses to rebuild into a tree rmtree_force failed to wipe
  F150  a reference correction needs identity evidence, not just similarity
  F173  convert_corpus follows the canonical symlinked evidence area only

Hermetic: every fixture lives under tempfile.mkdtemp(); the CLI/harness checks
drive their own root under that directory.

Run:  python3 .paper_test/test_fix_bugs_20261119_g2_helpers.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONVERTER = WS / "paper-skills" / "paper-review" / "scripts" / "convert_corpus.py"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fbfix1119_g2_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def make_docx(path: Path, paras) -> None:
    """A minimal DOCX whose paragraphs carry explicit w:pStyle ids."""
    body = "".join(
        '<w:p><w:pPr><w:pStyle w:val="%s"/></w:pPr><w:r>'
        '<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
        % (escape(style), escape(text)) for text, style in paras)
    xml = '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, body)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


# ---------------------------------------------------------------- F007
def test_f007_reference_section_ends_on_heading():
    lines = ["References", "[1] Smith J. A study. 2020.",
             "Methods", "1. We collected samples in 2019, at three sites."]
    entries = pp._reference_entries_in_lines(lines, set())
    check("F007 plain-text Methods heading ends the reference list",
          entries == {"[1] smith j. a study. 2020."}, repr(entries))

    html = pp._html_text_lines(
        "<h1>References</h1><p>[1] Smith J. A study. 2020.</p>"
        "<h2>Methods</h2><p>1. We collected samples in 2019, at three sites.</p>")
    entries = pp._reference_entries_in_lines(html, set())
    check("F007 rendered-HTML Methods heading ends the reference list",
          entries == {"[1] smith j. a study. 2020."}, repr(entries))

    # A real second entry is still collected (the heading test must not stop
    # the scan on an ordinary reference line).
    entries = pp._reference_entries_in_lines(
        ["References", "[1] Smith J. A study. 2020.",
         "[2] Doe A. Another study. 2021."], set())
    check("F007 ordinary entries still collected", len(entries) == 2, repr(entries))

    # A heading-SHAPED entry carrying a year is an entry, not a section break.
    entries = pp._reference_entries_in_lines(
        ["References", "WHO 2020", "[2] Doe A. Another study. 2021."], set())
    check("F007 a heading-shaped entry with a year does not end the list",
          "[2] doe a. another study. 2021." in entries, repr(entries))

    # A DOCX style heading whose TEXT is not heading-shaped (numbered) must
    # still end the list: the style, not the wording, says it is a heading.
    tmp = scratch("f007_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    make_docx(pkg / "manuscript.docx", [
        ("References", ""),
        ("[1] Smith J. A study. 2020.", ""),
        ("2.2 Methods", "Heading2"),
        ("1. We collected samples in 2019, at three sites.", ""),
    ])
    keys = pp._reference_entry_keys(pkg)
    check("F007 DOCX style heading ends the reference list",
          keys == {"[1] smith j. a study. 2020."}, repr(keys))


# ---------------------------------------------------------------- F129
def test_f129_run_bounded_kills_group_on_exception():
    """A non-timeout exception out of wait() must kill the child's group."""
    class FakeProc:
        pid = 999999

        def __init__(self, exc):
            self.exc = exc
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.killed = False

        def wait(self, timeout=None):
            raise self.exc

        def kill(self):
            self.killed = True

    real_popen = pp.subprocess.Popen
    for exc in (KeyboardInterrupt(), RuntimeError("boom")):
        proc = FakeProc(exc)
        pp.subprocess.Popen = lambda *a, **k: proc
        try:
            raised = None
            try:
                pp.run_bounded(["x"], 60)
            except BaseException as e:                     # noqa: BLE001
                raised = e
        finally:
            pp.subprocess.Popen = real_popen
        check(f"F129 {type(exc).__name__} propagates and kills the child",
              isinstance(raised, type(exc)) and proc.killed,
              f"raised={type(raised).__name__} killed={proc.killed}")

    if os.name != "posix" or not shutil.which("sh"):
        print("[skip] F129 subprocess e2e needs POSIX sh")
        return
    tmp = scratch("f129_")
    pidfile = tmp / "pid"
    child = tmp / "child.py"
    child.write_text(
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('paperp', sys.argv[1])\n"
        "np = importlib.util.module_from_spec(spec)\n"
        "sys.modules['paperp'] = np\n"
        "spec.loader.exec_module(np)\n"
        "np.run_bounded(['sh', '-c', 'echo $$ > \"$1\"; sleep 300', 'sh', sys.argv[2]], 60)\n",
        encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(child), str(WS / "paper_pipeline.py"), str(pidfile)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    gpid = None
    try:
        for _ in range(200):
            if pidfile.exists() and pidfile.read_text().strip():
                gpid = int(pidfile.read_text().strip())
                break
            time.sleep(0.05)
        check("F129 child tool started in its own group", gpid is not None)
        if gpid is None:
            return
        time.sleep(0.2)                    # let the child reach proc.wait()
        proc.send_signal(signal.SIGINT)
        proc.communicate(timeout=30)
        deadline = time.time() + 10
        alive = True
        while time.time() < deadline:
            try:
                os.kill(gpid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.05)
        check("F129 Ctrl-C does not leave the tool's group running", not alive,
              f"group pid {gpid} alive={alive}")
    finally:
        if gpid is not None:
            try:
                os.killpg(gpid, signal.SIGKILL)
            except OSError:
                pass
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


# ---------------------------------------------------------------- F131
def test_f131_separator_only_only_is_an_error():
    for bad in (",", " ", ",,", "   ", [" "]):
        try:
            got = pp.parse_only_spec(bad)
        except SystemExit as e:
            check(f"F131 {bad!r} is a usage error", e.code == 2, f"exit={e.code}")
            continue
        check(f"F131 {bad!r} is a usage error", False, f"returned {got!r}")
    check("F131 an absent/empty flag still means everything",
          pp.parse_only_spec(None) is None and pp.parse_only_spec("") is None)
    spec = pp.parse_only_spec("1,,2")
    check("F131 a real selection still parses", spec is not None and spec.rounds == {1, 2},
          repr(spec and spec.rounds))


# ---------------------------------------------------------------- F132
def test_f132_docx_package_budget_and_notes():
    tmp = scratch("f132_")
    body = ('<w:document xmlns:w="%s"><w:body><w:p><w:r><w:t>Body</w:t>'
            '</w:r></w:p></w:body></w:document>' % W)
    header = ('<w:hdr xmlns:w="%s"><w:p><w:r><w:t>Header</w:t></w:r></w:p>'
              '</w:hdr>' % W)
    # 1) entry-count budget: a package with more members than the cap is
    #    refused (returns None: an unscannable submitted file), where the old
    #    reader parsed it.
    many = tmp / "many.docx"
    with zipfile.ZipFile(many, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", body)
        for i in range(pp.MAX_DOCX_ENTRIES):
            z.writestr("word/header%d.xml" % i, header)
    check("F132 entry-count budget refuses an over-count package",
          pp._docx_paragraphs_with_styles(many, include_notes=True) is None)
    # 2) total-size budget: charge the declared decompressed total before any
    #    read.
    big = tmp / "big.docx"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml",
                   body.replace("Body", "B" * 4000))
        z.writestr("word/footnotes.xml",
                   '<w:footnotes xmlns:w="%s"><w:footnote><w:p><w:r><w:t>%s'
                   '</w:t></w:r></w:p></w:footnote></w:footnotes>'
                   % (W, "N" * 4000))
    real_total = pp.MAX_DOCX_TOTAL_BYTES
    pp.MAX_DOCX_TOTAL_BYTES = 500
    try:
        over = pp._docx_paragraphs_with_styles(big, include_notes=True)
    finally:
        pp.MAX_DOCX_TOTAL_BYTES = real_total
    check("F132 total-size budget refuses an over-total package", over is None,
          repr(over))
    check("F132 the same package is readable under the real budget",
          pp._docx_paragraphs_with_styles(big, include_notes=True) is not None)
    # 3) include_notes=False must not read/parse the note/header parts.
    small = tmp / "small.docx"
    with zipfile.ZipFile(small, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", body)
        z.writestr("word/header1.xml", header)
    check("F132 header prose still read when asked",
          any("Header" in text for text, _s in
              (pp._docx_paragraphs_with_styles(small, include_notes=True) or [])))
    bad_note = tmp / "badnote.docx"
    with zipfile.ZipFile(bad_note, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", body)
        z.writestr("word/footnotes.xml", "<not-xml")
    check("F132 a malformed note part is not read for a body-only scan",
          pp._docx_paragraphs_with_styles(bad_note, include_notes=False) is not None)
    check("F132 a malformed note part still fails the note-reading scan closed",
          pp._docx_paragraphs_with_styles(bad_note, include_notes=True) is None)


# ---------------------------------------------------------------- F133
def test_f133_pid_alive_never_kills_on_windows():
    real_os = pp.os
    real_windows_probe = pp._pid_alive_windows

    class FakeWindowsOS:
        name = "nt"

        def kill(self, *a):
            raise AssertionError("os.kill(pid, 0) must not run on Windows")

    seen = []
    pp.os = FakeWindowsOS()
    pp._pid_alive_windows = lambda pid: seen.append(pid) or False
    try:
        got = pp.pid_alive(4242)
        check("F133 Windows probe uses the handle helper and never os.kill",
              got is False and seen == [4242], f"got={got} seen={seen}")
        pp._pid_alive_windows = lambda pid: True
        check("F133 Windows probe reports a live process alive",
              pp.pid_alive(4242) is True)
    finally:
        pp.os = real_os
        pp._pid_alive_windows = real_windows_probe

    class FakePosixOS:
        name = "posix"

        def __init__(self):
            self.calls = []

        def kill(self, pid, sig):
            self.calls.append((pid, sig))
            raise ProcessLookupError

    fake = FakePosixOS()
    pp.os = fake
    try:
        check("F133 POSIX probe still uses signal 0",
              pp.pid_alive(4242) is False and fake.calls == [(4242, 0)],
              repr(fake.calls))
    finally:
        pp.os = real_os


# ---------------------------------------------------------------- F135
def test_f135_nested_fifo_is_skipped():
    if not hasattr(os, "mkfifo"):
        print("[skip] F135 needs os.mkfifo")
        return
    tmp = scratch("f135_")
    src = tmp / "src"
    (src / "figures").mkdir(parents=True)
    (src / "manuscript.md").write_text("x", encoding="utf-8")
    os.mkfifo(src / "figures" / "pipe.dat")
    dst = tmp / "dst"
    err = None
    try:
        pp.copy_into(src, dst)
    except Exception as e:                                 # noqa: BLE001
        err = e
    check("F135 a nested FIFO no longer raises shutil.Error", err is None, repr(err))
    check("F135 the package is still copied around the FIFO",
          (dst / "manuscript.md").is_file()
          and not (dst / "figures" / "pipe.dat").exists()
          and not (dst / "figures" / "pipe.dat").is_symlink())
    src2 = tmp / "src2"
    src2.mkdir()
    (src2 / "a.md").write_text("x", encoding="utf-8")
    os.mkfifo(src2 / "pipe.dat")
    try:
        pp.copy_into(src2, tmp / "dst2")
        top_ok = True
    except Exception:                                      # noqa: BLE001
        top_ok = False
    check("F135 a top-level FIFO is skipped, not fatal", top_ok)


# ---------------------------------------------------------------- F146
def test_f146_failed_wipe_is_not_merged():
    tmp = scratch("f146_")
    src = tmp / "src"
    src.mkdir()
    (src / "a.md").write_text("new", encoding="utf-8")
    dst = tmp / "dst"
    dst.mkdir()
    (dst / "stale.md").write_text("STALE", encoding="utf-8")
    real = pp.rmtree_force
    pp.rmtree_force = lambda p, ignore_errors=False: False
    try:
        try:
            pp.ensure_copy(src, dst)
            raised = None
        except RuntimeError as e:
            raised = e
        check("F146 ensure_copy refuses to rebuild into a surviving tree",
              raised is not None, repr(raised))
        ctx = types.SimpleNamespace(root=tmp, pristine=src)
        dst2 = tmp / "dst2"
        dst2.mkdir()
        (dst2 / "stale.md").write_text("STALE", encoding="utf-8")
        try:
            pp.ensure_pristine_input(ctx, dst2)
            raised2 = None
        except RuntimeError as e:
            raised2 = e
        check("F146 ensure_pristine_input refuses to rebuild into a surviving tree",
              raised2 is not None, repr(raised2))
    finally:
        pp.rmtree_force = real
    # The ordinary path is unchanged: a wipeable tree is rebuilt and the stale
    # file is really gone.
    check("F146 a successful wipe still rebuilds",
          pp.ensure_copy(src, dst) is True and not (dst / "stale.md").exists())


# ---------------------------------------------------------------- F150
def _ref_pair(tmp: Path, tag: str, old: str, new: str):
    base = tmp / (tag + "_base")
    cand = tmp / (tag + "_cand")
    base.mkdir()
    cand.mkdir()
    (base / "m.md").write_text(
        "Body sentence.\n\n## References\n\n" + old + "\n", encoding="utf-8")
    (cand / "m.md").write_text(
        "Body sentence.\n\n## References\n\n" + new + "\n", encoding="utf-8")
    return base, cand


def test_f150_reference_correction_needs_identity():
    tmp = scratch("f150_")
    old = "[1] Smith J. A study of widget growth. Journal of Widgets. 2020;1:1-10."
    swapped = "[1] Brown K. A study of widget growth. Journal of Widgets. 2020;1:1-10."
    base, cand = _ref_pair(tmp, "swap", old, swapped)
    pairs, added, removed = pp._reference_entry_corrections(base, cand)
    check("F150 an author-swapped entry is NOT paired as a correction",
          pairs == [] and len(added) == 1 and len(removed) == 1,
          f"pairs={pairs} added={added} removed={removed}")
    got = pp.content_edit_problems(None, base, cand, "x",
                                   insertions_allowed=False, deletions_allowed=False)
    check("F150 the fabricated replacement reaches the reference gate",
          any("reference entr" in p for p in got), str(got)[:260])

    # A title typo under the same first author and year IS an in-place fix.
    base, cand = _ref_pair(
        tmp, "typo",
        "[1] Smith J. A study of widgt growth. Journal of Widgets. 2020;1:1-10.",
        "[1] Smith J. A study of widget growth. Journal of Widgets. 2020;1:1-10.")
    pairs, added, removed = pp._reference_entry_corrections(base, cand)
    check("F150 a title typo is still paired (same author + year)",
          bool(pairs) and not added and not removed, f"pairs={pairs}")
    # F149's author-ADDITION correction keeps the same first author and year.
    base, cand = _ref_pair(
        tmp, "addition",
        "Smith J, Jones K. The cohort included 42 participants. Journal of "
        "Widgets. 2020;1:1-10.",
        "Smith J, Jones K, Brown L. The cohort included 42 participants. Journal "
        "of Widgets. 2020;1:1-10.")
    check("F150 an added co-author keeps the same reference identity",
          bool(pp._reference_entry_corrections(base, cand)[0]))
    # A shared DOI is identity evidence even when the author changed.
    base, cand = _ref_pair(
        tmp, "doi",
        "[1] Smith J. A study. doi:10.1000/xyz. 2020.",
        "[1] Brown K. A study. doi:10.1000/xyz. 2020.")
    check("F150 a shared DOI permits the author correction",
          bool(pp._reference_entry_corrections(base, cand)[0]))
    # A DIFFERENT DOI is a different work: no pairing.
    base, cand = _ref_pair(
        tmp, "doi2",
        "[1] Smith J. A study. doi:10.1000/xyz. 2020.",
        "[1] Smith J. A study. doi:10.1000/abc. 2020.")
    pairs, added, removed = pp._reference_entry_corrections(base, cand)
    check("F150 a different DOI is not a correction",
          pairs == [] and added and removed, f"pairs={pairs} added={added}")
    # A year change is a different reference identity (visible, not hidden).
    base, cand = _ref_pair(
        tmp, "year", "[1] Smith J. A study. 2020;1:1-10.",
        "[1] Smith J. A study. 2019;1:1-10.")
    pairs, added, removed = pp._reference_entry_corrections(base, cand)
    check("F150 a changed year is not hidden as a correction",
          pairs == [] and added and removed, f"pairs={pairs}")


# ---------------------------------------------------------------- F173
def test_f173_converter_follows_canonical_evidence_link():
    tmp = scratch("f173_")
    root = tmp / "root"
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "state.json").write_text("{}", encoding="utf-8")
    (root / "non_revised" / "raw_data" / "data.csv").write_text(
        "id,year\n1,2020\n", encoding="utf-8")
    (root / "non_revised" / "manuscript.md").write_text("# M\n\nText.\n",
                                                       encoding="utf-8")
    sandbox = root / "runs" / "r1_guided_review"
    sandbox.mkdir(parents=True)
    (sandbox / "manuscript.md").write_text("# M\n\nText.\n", encoding="utf-8")
    os.symlink("../../non_revised/raw_data", sandbox / "raw_data")
    work = tmp / "work"
    r = subprocess.run([sys.executable, str(CONVERTER),
                        "--submission", str(sandbox), "--work", str(work)],
                       cwd=str(WS), capture_output=True, text=True, timeout=120)
    inv = json.loads((work / "inventory.json").read_text(encoding="utf-8")) \
        if (work / "inventory.json").is_file() else []
    ev = [(row["path"], row["area"]) for row in inv if row["area"] != "submission"]
    check("F173 the canonical symlinked evidence area is inventoried",
          r.returncode == 0 and ev == [("raw_data/data.csv", "raw_data")],
          f"rc={r.returncode} rows={ev} stderr={r.stderr[-300:]}")
    check("F173 its text goes to WORK/evidence, never WORK/corpus",
          (work / "evidence" / "raw_data__data.csv.txt").is_file()
          and not (work / "corpus" / "raw_data__data.csv.txt").exists())
    # A link that is NOT the root's canonical store stays skipped: the name
    # alone never authorizes copying an arbitrary target.
    other = root / "other_store" / "raw_data"
    other.mkdir(parents=True)
    (other / "x.csv").write_text("x\n", encoding="utf-8")
    sandbox2 = root / "runs" / "evil"
    sandbox2.mkdir(parents=True)
    (sandbox2 / "manuscript.md").write_text("# M\n", encoding="utf-8")
    os.symlink("../../other_store/raw_data", sandbox2 / "raw_data")
    work2 = tmp / "work2"
    r2 = subprocess.run([sys.executable, str(CONVERTER),
                         "--submission", str(sandbox2), "--work", str(work2)],
                        cwd=str(WS), capture_output=True, text=True, timeout=120)
    inv2 = json.loads((work2 / "inventory.json").read_text(encoding="utf-8")) \
        if (work2 / "inventory.json").is_file() else []
    check("F173 a non-canonical raw_data link is still skipped",
          r2.returncode == 0
          and all(row["area"] == "submission" for row in inv2),
          f"rows={[(x['path'], x['area']) for x in inv2]}")


def main() -> int:
    test_f007_reference_section_ends_on_heading()
    test_f129_run_bounded_kills_group_on_exception()
    test_f131_separator_only_only_is_an_error()
    test_f132_docx_package_budget_and_notes()
    test_f133_pid_alive_never_kills_on_windows()
    test_f135_nested_fifo_is_skipped()
    test_f146_failed_wipe_is_not_merged()
    test_f150_reference_correction_needs_identity()
    test_f173_converter_follows_canonical_evidence_link()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
