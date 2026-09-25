#!/usr/bin/env python3
"""Console timestamps, anonymized judge views, and metadata preservation.

Run:  python3 .paper_test/test_anonymized_judging.py

Three properties are asserted:

  A. every line the pipeline prints to stdout/stderr starts with the current
     local datetime in "year-month-day hour-minute-second" form, including the
     continuation lines of a multi-line error;
  B. what a JUDGE can see carries no name, path shape, timestamp, permission
     bit, attribute or other metadata that could bias a comparison: views are
     anonymous placeholders ("d01/", "f0001<ext>") with a randomly permuted
     per-view mapping, one mtime and one mode, and no xattrs;
  C. files NO judge sees (the sandbox inputs, pins, published winners, the
     integration views, the pristine copy) keep their names, timestamps, modes
     and attributes.

`PAPER_WS` retargets the suite at a baseline copy of the tree (red there).
"""
from __future__ import annotations

import importlib.util
import base64
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_anon", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_anon"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data, mode: int = None, mtime: float = None):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")
    if mode is not None:
        try:
            os.chmod(p, mode)
        except OSError:
            pass
    if mtime is not None:
        try:
            os.utime(p, (mtime, mtime))
        except OSError:
            pass


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def make_source(tmp: Path, by_products: bool = False) -> Path:
    """A small corpus with distinctive names, times, modes and dirs.

    `by_products` adds what a REAL submission package carries beside its
    sources: the build by-products (whose content names the machine and the
    build date) and Word's "~$" owner file.
    """
    src = tmp / "source"
    old = time.time() - 500 * 86400
    write(src / "manuscript-b.md", "# Title\n\nFigure 1 | A caption.\n", mtime=old)
    write(src / "refs-b.bib", "@article{x}\n", mtime=old)
    write(src / "raw_figs" / "Fig1.png", b"\x89PNG-fake", mtime=old)
    write(src / "raw_figs" / "data.tsv", "a\tb\n", mtime=old)
    write(src / "code" / "analysis.py", "print('x')\n", mode=0o755, mtime=old)
    if by_products:
        # a real source/derived pair: the .bib ships, so its compiled .bbl does
        # not have to (and must not) reach a judge
        write(src / "refs-b.bbl", "\\begin{thebibliography}{1}\n% from refs-b.bib\n", mtime=old)
        # ... and the same for a Word manuscript with its rendered PDF
        write(src / "paper.docx", _docx_with_metadata(), mtime=old)
        write(src / "paper.pdf", _pdf_with_metadata(), mtime=old)
        write(src / "manuscript-b.aux", "\\relax\n", mtime=old)
        write(src / "manuscript-b.log",
              "This is XeTeX ... 20 SEP 2026 11:11\n"
              "(C:\\Users\\Somebody\\AppData\\Local\\MiKTeX\\tex/latex/base/article.cls\n",
              mtime=old)
        # ... while this .bbl has NO .bib beside it: it is the only copy
        write(src / "manuscript-b.bbl", "\\begin{thebibliography}{1}\n", mtime=old)
        write(src / "manuscript-b.synctex.gz", b"\x1f\x8b\x08fake-synctex", mtime=old)
        write(src / "~$manuscript-b.docx", b"OWNER-NAME-LAPTOP7", mtime=old)
    return src


def build_round_root(tmp: Path, rewrites=1, revises=1, judges=1, by_products=False):
    src = make_source(tmp, by_products=by_products)
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(src, root / "non-revised")
    pristine = root / "non-revised"
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": judges, "rewrites": [rewrites], "revises": [revises],
               "source": str(src)}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "anonsalt", "config": ctx.cfg, "source": str(src)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a1")
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, "a1")
    return ctx, src


def register_fresh(ctx, vid, text, mode: int = None, mtime: float = None):
    rid = nb.rid_for_fresh(1, vid)
    kind = nb.arm_of_vid(vid)
    out = ctx.root / "runs" / rid / nb.output_dir_for_vid(vid)
    write(out / "manuscript-p.md", text, mode=mode, mtime=mtime)
    rec = ctx.register(rid, kind, 1, f"runs/{rid}", produces=vid, source_id="a1")
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
    return rec


def run_e2e(tmp: Path) -> Path:
    """Run one real round (setup + run) with the stub agents; returns the root."""
    src = make_source(tmp)
    root = tmp / "e2e_root"
    here = Path(__file__).resolve().parent
    subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                    "--source", str(src), "--root", str(root), "--rounds", "1",
                    "--judges", "1", "--rewrites", "1", "--revises", "1"],
                   capture_output=True, text=True, check=True)
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                           "--root", str(root), "--jobs", "6", "--retries", "0",
                           "--agent-cmd", json.dumps([sys.executable, str(here / "stub_agent.py")]),
                           "--judge-agent-cmd",
                           json.dumps([sys.executable, str(here / "stub_judge.py")])],
                          capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return root


# =====================================================================
# A. stdout/stderr timestamps
# =====================================================================

def test_console_timestamps():
    print("== A. every printed line carries the current datetime ==")
    tmp = scratch("paper_anon_cli_")
    src = make_source(tmp)
    root = tmp / "root"
    before = time.time()
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                           "--source", str(src), "--root", str(root), "--rounds", "1",
                           "--judges", "1", "--rewrites", "1", "--revises", "1"],
                          capture_output=True, text=True, timeout=300)
    after = time.time()
    check("setup succeeds", proc.returncode == 0, proc.stderr[-200:])
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    missing = [ln for ln in lines if not STAMP_RE.match(ln)]
    check("every stdout line starts with a datetime", lines and not missing,
          str(missing[:2]) if missing else f"{len(lines)} lines")
    stamps = [time.mktime(time.strptime(ln[:19], "%Y-%m-%d %H:%M:%S")) for ln in lines]
    check("the datetimes are the CURRENT local time (not a fixed/UTC stamp)",
          all(before - 5 <= s <= after + 5 for s in stamps),
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(min(stamps)))} .. "
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max(stamps)))}")

    # stderr: a multi-line error must be stamped line by line, not once
    bad = scratch("paper_anon_cli2_")
    (bad / "root").mkdir()
    (bad / "root" / "pipeline_config.json").write_text(json.dumps({"rounds": 1, "judges": 1}))
    (bad / "root" / "state.json").write_text(json.dumps(
        {"version": nb.STATE_VERSION, "runs": {"r1_x": {"kind": "judge", "round": 1}},
         "rounds": {}, "pinned": [], "log": []}))
    err = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "status",
                          "--root", str(bad / "root")], capture_output=True, text=True,
                         timeout=300)
    check("the damaged-state command fails", err.returncode != 0)
    err_lines = [ln for ln in (err.stdout + err.stderr).splitlines() if ln.strip()]
    check("every stderr line of a multi-line error is stamped",
          len(err_lines) >= 3 and all(STAMP_RE.match(ln) for ln in err_lines),
          str(err_lines[:3]))
    check("the error text is still readable (message body intact)",
          any("sandbox" in ln for ln in err_lines))

    # --help output also flows through the timestamping stream
    helptext = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "--help"],
                              capture_output=True, text=True, timeout=300).stdout
    help_lines = [ln for ln in helptext.splitlines() if ln.strip()]
    check("--help lines are stamped too",
          help_lines and all(STAMP_RE.match(ln) for ln in help_lines), str(help_lines[:1]))


# =====================================================================
# B. judge views are anonymous
# =====================================================================

def judge_sandbox(ctx):
    field, _dropped = nb.build_field(ctx, 1)
    judge_ids = nb.materialize_judges(ctx, 1, field)
    return ctx.sandbox_of(ctx.run(judge_ids[0]))


def test_judge_views_are_anonymous():
    print()
    print("== B. judge views carry no name or path information ==")
    tmp = scratch("paper_anon_b_")
    ctx, src = build_round_root(tmp)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx, vid, f"# {vid}\n\nbody {vid}\n")
    sb = judge_sandbox(ctx)
    corpus = nb.corpus_files_for_view(ctx, 1, "a1")
    original_names = {Path(rel).name for rel, _p in corpus}
    original_stems = {Path(rel).stem for rel, _p in corpus}
    original_dirs = {Path(rel).parent.as_posix() for rel, _p in corpus} - {"."}
    view_paths = {}
    for area in ("target", "original", "field"):
        for p in sorted((sb / area).rglob("*")):
            if p.is_file():
                view_paths.setdefault(area, []).append(p.relative_to(sb / area).as_posix())
    all_paths = [p for paths in view_paths.values() for p in paths]
    check("judge views exist and carry files", bool(all_paths), str(len(all_paths)))
    check("no ORIGINAL file name survives in any judge view",
          not any(Path(p).name in original_names for p in all_paths),
          str(sorted(original_names)))
    check("no ORIGINAL file stem survives in any judge view",
          not any(Path(p).stem in original_stems for p in all_paths), str(sorted(original_stems)))
    check("no ORIGINAL directory name survives in any judge view",
          not any(part in original_dirs for p in all_paths for part in Path(p).parts),
          str(sorted(original_dirs)))
    anon_re = r"(?:v\d+/)?(?:d\d{2}/)?f\d{4}(?:\.[A-Za-z0-9]+)?"
    check("every judge path is an anonymous placeholder",
          all(re.fullmatch(anon_re, p) for p in all_paths),
          str([p for p in all_paths if not re.fullmatch(anon_re, p)][:3]))
    # the CONTENT and the file types survive (after the view transform:
    # references rewritten, metadata sanitized)
    want = nb.expected_view_digest(
        ctx, 1, "a1", f"{nb.judge_view_seed_for(ctx, 1, 'a1', 1)}|target")
    target_files = [p for p in (sb / "target").rglob("*") if p.is_file()]
    got = sorted(nb.sha256_file(p) for p in target_files)
    check("the anonymous target carries exactly the base's documents (content multiset)",
          got == want, f"{len(got)} vs {len(want)} document(s)")
    check("the extensions (file types) are preserved",
          sorted(p.suffix for p in target_files)
          == sorted(Path(rel).suffix for rel, _p in corpus),
          str(sorted(p.suffix for p in target_files)))
    depth_by_name = {Path(p).name: len(Path(p).parts) for p in all_paths}
    check("the tree SHAPE is preserved (nested files stay nested)",
          any(len(Path(p).parts) == 2 for p in all_paths) and
          any(len(Path(p).parts) == 1 for p in all_paths), str(sorted(depth_by_name.items())[:4]))
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    check("the judge prompt explains the anonymization and the reference carve-out",
          "ANONYMIZED PLACEHOLDERS" in prompt and "PACKAGING ARTIFACT" in prompt
          and "by CONTENT and ROLE" in prompt)
    check("the judge prompt no longer promises that original names are carried",
          "version tokens are carried\nthrough every arm" not in prompt
          and "project's own version tokens are carried" not in prompt)


def _png_1x1() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
        "hKmMIQAAAABJRU5ErkJggg==")


def test_by_products_never_reach_a_view():
    print()
    print("== B. build by-products never reach a judge view ==")
    tmp = scratch("paper_anon_byprod_")
    ctx, _src = build_round_root(tmp, by_products=True)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx, vid, f"# {vid}\n\nbody {vid}\n")
    sb = judge_sandbox(ctx)
    areas = [sb / "target", sb / "original"] + sorted((sb / "field").iterdir())
    per_view = {p.relative_to(sb).as_posix(): sorted(q.suffix.lower()
                                                    for q in p.rglob("*") if q.is_file())
                for p in areas}
    leaked = {k: [s for s in v if s.endswith(nb.VIEW_STRIP_DERIVED_SUFFIXES)]
              for k, v in per_view.items()}
    check("no judge view carries a build by-product (.aux/.log/.synctex.gz)",
          not any(leaked.values()), str({k: v for k, v in leaked.items() if v}))
    check("the .bbl with no .bib beside it stays (it is the only copy)",
          per_view["target"].count(".bbl") == 1 and per_view["original"].count(".bbl") == 1,
          str(per_view))
    check("a .bbl whose .bib ships is dropped, the .bib stays",
          per_view["target"].count(".bib") == 1 and per_view["target"].count(".bbl") == 1,
          str(per_view))
    check("a PDF rendered from a shipped .docx is dropped, the .docx stays",
          per_view["target"].count(".docx") == 1 and ".pdf" not in per_view["target"]
          and per_view["original"].count(".docx") == 1 and ".pdf" not in per_view["original"],
          str(per_view))
    view_bytes = b"".join(q.read_bytes() for p in areas for q in p.rglob("*") if q.is_file())
    check("the build log's machine path and build date reach NO judge view",
          b"Somebody" not in view_bytes and b"20 SEP 2026" not in view_bytes)
    check("Word's '~$' owner file (its author's name) reaches NO judge view",
          b"OWNER-NAME-LAPTOP7" not in view_bytes)
    # The rule is symmetric: the pristine original's view and a version's view
    # cannot be told apart by which by-products survived a rebuild.
    check("the pristine view and the target view expose the same file-type surface",
          per_view["original"] == per_view["target"], str(per_view))


def _docx_with_metadata() -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.'
                   'openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   "<dc:creator>Jane Doe</dc:creator>"
                   "<cp:lastModifiedBy>Jane Doe</cp:lastModifiedBy>"
                   "<dcterms:created>2026-09-15T14:01:31Z</dcterms:created>"
                   "</cp:coreProperties>")
        z.writestr("docProps/app.xml",
                   "<Properties><Company>Acme Corp</Company>"
                   "<Application>Microsoft Word</Application></Properties>")
        z.writestr("docProps/custom.xml",
                   "<Properties><property name='Reviewer'>Prof. Smith</property></Properties>")
        z.writestr("word/document.xml", "<w:document><w:body/></w:document>")
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def _pdf_with_metadata() -> bytes:
    return (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"2 0 obj\n<< /Author (Jane Doe) /Producer (Word 2021) "
            b"/CreationDate (D:20260915140131+08'00') >>\nendobj\n"
            b"trailer\n<< /Size 3 /Root 1 0 R /Info 2 0 R >>\nstartxref\n0\n%%EOF\n")


def test_view_references_and_metadata():
    print()
    print("== B. judge views stay COMPILABLE and their metadata is sanitized ==")
    tmp = scratch("paper_anon_refs_")
    ctx, _src = build_round_root(tmp)
    base = ctx.root / "runs" / nb.rid_a1(1) / "base"
    write(base / "paper.tex",
          "\\documentclass{article}\n\\usepackage{graphicx}\n"
          "\\begin{document}\n\\includegraphics{fig1.png}\n\\end{document}\n")
    (base / "fig1.png").write_bytes(_png_1x1())
    (base / "doc.docx").write_bytes(_docx_with_metadata())
    (base / "figure.pdf").write_bytes(_pdf_with_metadata())
    rec = ctx.run(nb.rid_a1(1))
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a1")
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, "a1")
    seed = f"{nb.judge_view_seed_for(ctx, 1, 'a1', 1)}|target"
    dst = tmp / "view"
    nb.build_judge_view(ctx, 1, "a1", dst, time.time(), seed)
    texes = list(dst.rglob("*.tex"))
    pngs = list(dst.rglob("*.png"))
    check("B. the view carries the .tex and at least the fixture figure",
          len(texes) == 1 and len(pngs) >= 1, f"{texes} {pngs}")
    tex_text = texes[0].read_text(encoding="utf-8")
    ref = re.search(r"\\includegraphics\{([^}]*)\}", tex_text)
    check("B. the LaTeX reference was rewritten to the anonymous figure name",
          ref is not None and ref.group(1) == pngs[0].name,
          f"{ref.group(1) if ref else None} vs {pngs[0].name}")
    check("B. no original filename survives in the rewritten LaTeX",
          "fig1" not in tex_text and "paper" not in tex_text, tex_text[:80])
    if shutil.which("pdflatex"):
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                               texes[0].name], cwd=str(texes[0].parent),
                              capture_output=True, text=True, timeout=180)
        check("B. the anonymized LaTeX package compiles as-is", proc.returncode == 0,
              (proc.stdout or "")[-200:])
    else:
        print("[skip] B. pdflatex not available")
    docx = next(dst.rglob("*.docx"))
    with zipfile.ZipFile(docx) as z:
        core = z.read("docProps/core.xml").decode("utf-8")
        app = z.read("docProps/app.xml").decode("utf-8")
        custom = z.read("docProps/custom.xml").decode("utf-8")
        times = {i.date_time for i in z.infolist()}
    check("B. OOXML personal properties are neutralized",
          "Jane Doe" not in core and "Jane Doe" not in app and "Acme Corp" not in app
          and "Prof. Smith" not in custom and "author" in core,
          f"{core[:80]!r} {app[:80]!r}")
    check("B. every OOXML zip entry carries the fixed timestamp",
          times == {(2020, 1, 1, 0, 0, 0)}, str(times))
    pdf = next(dst.rglob("*.pdf"))
    data = pdf.read_bytes()
    check("B. PDF /Info identifying values are blanked IN PLACE",
          b"Jane Doe" not in data and b"Word 2021" not in data
          and len(data) == len(_pdf_with_metadata()), f"{len(data)} bytes")


def test_each_view_gets_its_own_mapping():
    print()
    print("== B. every view is permuted separately (no cross-view correlation) ==")
    tmp = scratch("paper_anon_seeds_")
    ctx, _src = build_round_root(tmp, rewrites=1, revises=1, judges=1)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx, vid, f"# {vid}\n")
    seeds = []
    real = nb.ensure_judge_view

    def spy(ctx_, r, vid, dst, stamp, seed):
        seeds.append((vid, seed))
        return real(ctx_, r, vid, dst, stamp, seed)

    nb.ensure_judge_view = spy
    try:
        judge_sandbox(ctx)
    finally:
        nb.ensure_judge_view = real
    targets = [s for v, s in seeds if v == "a1"]
    field_seeds = [s for v, s in seeds if v != "a1"]
    check("the target and its opponents use DIFFERENT view seeds",
          len(set(targets + field_seeds)) == len(targets + field_seeds) and len(seeds) >= 6,
          str(seeds))
    check("every field label has its own seed",
          len({s for _v, s in seeds}) == len(seeds), f"{len(seeds)} views")


def test_judge_metadata_is_uniform():
    print()
    print("== B. judge views share one timestamp/mode and carry no attributes ==")
    tmp = scratch("paper_anon_meta_")
    ctx, src = build_round_root(tmp)
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        register_fresh(ctx, vid, f"# {vid}\n")
    sb = judge_sandbox(ctx)
    entries = [p for area in ("target", "original", "field")
               for p in (sb / area).rglob("*")]
    mtimes = {round(p.stat().st_mtime) for p in entries}
    modes = {stat.S_IMODE(p.stat().st_mode) for p in entries}
    source_mtime = round((src / "manuscript-b.md").stat().st_mtime)
    check("exactly ONE mtime across every judge-view entry", len(mtimes) == 1,
          f"{len(mtimes)} distinct: {sorted(mtimes)[:3]}")
    check("the author's real mtime does NOT appear in any judge view",
          source_mtime not in mtimes, f"source={source_mtime} views={sorted(mtimes)}")
    check("only two permission modes (0644 files / 0755 dirs)",
          modes == {0o644, 0o755}, str(sorted(oct(m) for m in modes)))
    check("the source's executable bit does not travel into a judge view",
          all(stat.S_IMODE(p.stat().st_mode) == (0o755 if p.is_dir() else 0o644)
              for p in entries))
    if hasattr(os, "listxattr"):
        with_xattr = []
        for p in entries:
            try:
                if os.listxattr(p):
                    with_xattr.append(str(p.relative_to(sb)))
            except OSError:
                pass
        check("no extended attributes survive into a judge view", not with_xattr,
              str(with_xattr[:3]))
    else:
        print("[skip] xattrs are not supported on this platform")


def test_judge_view_tampering_is_detected():
    print()
    print("== B. a tampered judge view is detected (content, not paths) ==")
    tmp = scratch("paper_anon_tamper_")
    root = run_e2e(tmp)
    ctx = nb.Ctx(root)
    ctx.load()
    judge_runs = [rec["id"] for rec in ctx.runs(kind="judge", round_no=1)]
    check("the end-to-end round produced judge runs", bool(judge_runs), str(len(judge_runs)))
    healthy = nb.revalidate_round_inputs(ctx, 1)
    check("an untouched round is left alone", not healthy, str(healthy))
    sb = ctx.sandbox_of(ctx.run(judge_runs[0]))
    victim = [p for p in sorted((sb / "target").rglob("*")) if p.is_file()][0]
    victim.write_bytes(victim.read_bytes() + b"\nTAMPERED\n")
    reset = nb.revalidate_round_inputs(ctx, 1)
    # every judge session has its OWN copy of the field, so only the tampered
    # sandbox is reset; the untouched sessions are left exactly as they were
    check("a one-byte edit inside an anonymized view resets THAT judge run",
          reset == [judge_runs[0]], f"reset={reset} judges={judge_runs}")


# =====================================================================
# C. metadata is preserved for files no judge sees
# =====================================================================

def test_non_judged_copies_preserve_metadata():
    print()
    print("== C. non-judged copies keep names, timestamps, modes and attributes ==")
    tmp = scratch("paper_anon_keep_")
    ctx, src = build_round_root(tmp)
    old = time.time() - 300 * 86400
    rec = register_fresh(ctx, "w1", "# rewritten\n", mode=0o600, mtime=old)
    sb = ctx.sandbox_of(rec)
    kept = sb / "rewritten" / "manuscript-p.md"
    check("the sandbox keeps the agent's own file name and mode",
          kept.is_file() and stat.S_IMODE(kept.stat().st_mode) == 0o600,
          f"{kept} {oct(stat.S_IMODE(kept.stat().st_mode))}")
    # the pristine copy made by `setup` preserves the source metadata
    check("the pristine non-revised/ copy preserves the source mtime",
          round((ctx.pristine / "manuscript-b.md").stat().st_mtime)
          == round((src / "manuscript-b.md").stat().st_mtime))
    check("the pristine copy preserves the source executable bit",
          stat.S_IMODE((ctx.pristine / "code" / "analysis.py").stat().st_mode) == 0o755)
    # pin + published winner preserve them too (they are NOT judge views)
    rank_row = {"id": "w1", "rep": "w1", "is_base": False, "n": 10, "median": 1.0,
                "mean": 1.0, "iqr": 0.0, "vs_original": 1.0, "vs_base": 1.0,
                "critical_remaining": 0, "manual_steps": 0, "author_placeholders": 0,
                "captions": None}
    agg = {"round": 1, "field": ["orig", "w1"], "field_size": 2, "scores_per_version": 2,
           "stats": {"w1": {"n": 2, "expected_n": 2, "complete": True, "median": 1.0,
                            "mean": 1.0, "iqr": 0.0, "vs_original": 1.0, "vs_base": 1.0,
                            "anti_regression_ok": True, "author_placeholders": 0,
                            "caption_gate_ok": True, "caption_note": "", "captions": None}},
           "diagnostics": {}, "base_id": "a1", "base_rep": "orig",
           "generated": nb.utcnow()}
    sel = {"champion": "w1", "champion_rep": "w1", "eligible": ["w1"], "ranking": [rank_row],
           "trace": []}
    pin = nb.pin_champion(ctx, 1, "w1", agg)
    pinned = ctx.pins_dir / pin["id"] / "documents" / "manuscript-p.md"
    check("the pinned copy keeps the file name", pinned.is_file(),
          str(sorted(p.name for p in (ctx.pins_dir / pin["id"] / "documents").rglob("*"))))
    check("the pinned copy keeps the agent's mtime (no normalization anywhere)",
          round(pinned.stat().st_mtime) == round(old),
          f"pinned={round(pinned.stat().st_mtime)} source={round(old)}")
    check("the pinned copy keeps the agent's permission bits",
          stat.S_IMODE(pinned.stat().st_mode) == 0o600,
          oct(stat.S_IMODE(pinned.stat().st_mode)))
    nb.publish_winner(ctx, 1, "w1", pin, agg)
    winner = ctx.root / nb.WINNER_DIR_FMT.format(r=1) / "manuscript-p.md"
    check("the published winner keeps the same name/time/mode",
          winner.is_file() and round(winner.stat().st_mtime) == round(old)
          and stat.S_IMODE(winner.stat().st_mode) == 0o600,
          f"{winner} {oct(stat.S_IMODE(winner.stat().st_mode)) if winner.is_file() else '-'}")


def main() -> int:
    sections = (("A", test_console_timestamps),
                ("B", test_judge_views_are_anonymous),
                ("B", test_by_products_never_reach_a_view),
                ("B", test_view_references_and_metadata),
                ("B", test_each_view_gets_its_own_mapping),
                ("B", test_judge_metadata_is_uniform),
                ("B", test_judge_view_tampering_is_detected),
                ("C", test_non_judged_copies_preserve_metadata))
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
    print("ALL ANONYMIZED-JUDGING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
