#!/usr/bin/env python3
"""Repro/regression tests for the bug candidates ingested from the shared reports.

Run:  python3 .nbt_test/test_candidates.py

Every check here is written to FAIL on the tree as ingested and to PASS once the
matching defect is fixed, so the file doubles as the repro script for each
candidate (see the ledger in the task report for the id -> check mapping).
"""
from __future__ import annotations

import base64
import atexit
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
NP_PATH = WS / "nbt_pipeline.py"
ADAPTER_PATH = WS / "nbt_redlines_adapter.py"
DOCX2PDF = WS / "docx2pdf.sh"

spec = importlib.util.spec_from_file_location("nbtp", str(NP_PATH))
np = importlib.util.module_from_spec(spec)
sys.modules["nbtp"] = np
spec.loader.exec_module(np)

FAILS: list[str] = []

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


_TMPDIRS: list = []


@atexit.register
def _cleanup_tmpdirs() -> None:
    for d in _TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"cand_{tag}_"))
    _TMPDIRS.append(p)
    return p


# =====================================================================
# A1/A2 -- docx2pdf.sh
#
# Word/PowerShell cannot run here, so the tests substitute a fake
# `powershell.exe` (and `wslpath`) on PATH: the fake dumps the PowerShell the
# script *would* execute (A1) and can be told to write nothing at all (A2).
# =====================================================================

PS_SHIM = r'''#!/usr/bin/env python3
import base64, os, sys
argv = sys.argv[1:]
enc = argv[argv.index("-EncodedCommand") + 1]
script = base64.b64decode(enc).decode("utf-16-le")
dump = os.environ.get("PS_DUMP")
if dump:
    open(dump, "w", encoding="utf-8").write(script)
fake = os.environ.get("PS_FAKE_PDF")
if fake:
    open(fake, "wb").write(b"%PDF-1.4\n% fake render\n" + b"x" * 2048)
sys.exit(int(os.environ.get("PS_RC", "0")))
'''

WSLPATH_SHIM = r'''#!/usr/bin/env python3
import sys
args = [a for a in sys.argv[1:] if not a.startswith("-")]
print("C:" + args[0].replace("/", "\\"))
'''


def shim_bin(tmp: Path) -> Path:
    b = tmp / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for name, body in (("powershell.exe", PS_SHIM), ("wslpath", WSLPATH_SHIM)):
        p = b / name
        write(p, body)
        p.chmod(0o755)
    return b


def ps_single_quoted(line: str, prefix: str):
    """(value, trailing_text) for a PowerShell single-quoted string literal.

    Mimics the parser: `''` is an escaped quote, a lone `'` closes the literal.
    A path interpolated without doubling therefore leaves trailing text (and the
    literal decodes to something other than the path) -- which is the defect.
    """
    if not line.startswith(prefix):
        return None, None
    rest = line[len(prefix):]
    if not rest.startswith("'"):
        return None, None
    out, i = [], 1
    while i < len(rest):
        ch = rest[i]
        if ch == "'":
            if i + 1 < len(rest) and rest[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), rest[i + 1:].strip()
        out.append(ch)
        i += 1
    return None, None


def run_docx2pdf(tmp: Path, docx: Path, **env_extra):
    b = shim_bin(tmp)
    env = dict(os.environ)
    env["PATH"] = f"{b}{os.pathsep}{env.get('PATH', '')}"
    env["PS_DUMP"] = str(tmp / "ps_dump.txt")
    env.update({k: str(v) for k, v in env_extra.items()})
    return subprocess.run(["bash", str(DOCX2PDF), str(docx)], cwd=str(tmp), env=env,
                          capture_output=True, text=True)


def test_a1_path_with_single_quote():
    tmp = tmpdir("a1")
    docx = tmp / "paper's $draft [v2].docx"
    pdf = tmp / "paper's $draft [v2].pdf"
    write(docx, b"fake docx bytes")
    proc = run_docx2pdf(tmp, docx, PS_FAKE_PDF=pdf)
    script = (tmp / "ps_dump.txt").read_text(encoding="utf-8") if \
        (tmp / "ps_dump.txt").exists() else ""
    line = next((ln for ln in script.splitlines() if ln.startswith("$docx = ")), "")
    value, tail = ps_single_quoted(line, "$docx = ")
    expected = "C:" + str(docx).replace("/", "\\")
    check("A1 the path stays inside ONE PowerShell string literal",
          proc.returncode == 0 and value == expected and tail == "",
          f"rc={proc.returncode} line={line!r} value={value!r} tail={tail!r}")


def test_a2_missing_pdf_is_a_failure():
    tmp = tmpdir("a2")
    docx = tmp / "paper.docx"
    pdf = tmp / "paper.pdf"
    write(docx, b"fake docx bytes")
    write(pdf, b"%PDF-1.4\nstale render from an earlier run\n")
    proc = run_docx2pdf(tmp, docx)                     # the converter writes nothing
    check("A2 a converter that writes no PDF is not reported as success",
          proc.returncode != 0,
          f"rc={proc.returncode} stdout={proc.stdout.strip()!r}")
    check("A2 the stale PDF does not survive as this run's output", not pdf.exists(),
          f"stale pdf still present: {pdf.read_bytes()[:24]!r}" if pdf.exists() else "")


def test_a2_success_path_still_works():
    tmp = tmpdir("a2ok")
    docx = tmp / "paper.docx"
    pdf = tmp / "paper.pdf"
    write(docx, b"fake docx bytes")
    proc = run_docx2pdf(tmp, docx, PS_FAKE_PDF=pdf)
    check("A2 a real render still exits 0",
          proc.returncode == 0 and pdf.is_file() and pdf.stat().st_size > 0,
          f"rc={proc.returncode} err={proc.stderr.strip()[-160:]!r}")


def test_a2b_pdf_input_is_never_deleted():
    """The output path is DERIVED from the input, so a .pdf argument is its own
    output: the stale-render cleanup must never delete the file it was handed."""
    tmp = tmpdir("a2b")
    src = tmp / "important.pdf"
    write(src, b"%PDF-1.4\nORIGINAL PDF BYTES\n")
    proc = run_docx2pdf(tmp, src)                      # the converter writes nothing
    check("A2b a .pdf input is refused and left intact",
          proc.returncode != 0 and src.is_file()
          and src.read_bytes().startswith(b"%PDF-1.4"),
          f"rc={proc.returncode} exists={src.exists()} err={proc.stderr.strip()[:90]!r}")

    upper = tmp / "REPORT.PDF"
    sibling = tmp / "REPORT.pdf"                       # same file on Windows/drvfs
    write(upper, b"%PDF-1.4\nUPPER CASE INPUT\n")
    write(sibling, b"%PDF-1.4\nLOWER CASE SIBLING\n")
    proc2 = run_docx2pdf(tmp, upper)
    check("A2b (case variant) an uppercase .PDF argument deletes no .pdf path",
          proc2.returncode != 0 and upper.is_file() and sibling.is_file(),
          f"rc={proc2.returncode} upper={upper.exists()} sibling={sibling.exists()}")


# =====================================================================
# B1 -- nbt_redlines_adapter.py
# =====================================================================

def fake_redlines(tmp: Path, body: str) -> Path:
    pkg = tmp / "fakeredlines"
    write(pkg / "redlines.py", body)
    return pkg


def run_adapter(tmp: Path, pkg: Path, base: Path, revised: Path, out: Path):
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{pkg}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return subprocess.run([sys.executable, str(ADAPTER_PATH), str(base), str(revised), str(out)],
                          env=env, capture_output=True, text=True)


def test_b1_adapter_stale_output():
    tmp = tmpdir("b1")
    pkg = fake_redlines(tmp, "def main(argv):\n    return None\n")   # writes nothing
    base, revised = tmp / "base.docx", tmp / "revised.docx"
    out = tmp / "out.docx"
    write(base, b"base")
    write(revised, b"revised")
    write(out, b"PRE-EXISTING STALE CONTENT")
    proc = run_adapter(tmp, pkg, base, revised, out)
    check("B1 a pre-existing output file is not reported as a fresh redline",
          proc.returncode != 0,
          f"rc={proc.returncode} stdout={proc.stdout.strip()!r}")


def test_b1_adapter_absent_output_still_fails():
    tmp = tmpdir("b1b")
    pkg = fake_redlines(tmp, "def main(argv):\n    return None\n")
    base, revised = tmp / "base.docx", tmp / "revised.docx"
    write(base, b"base")
    write(revised, b"revised")
    proc = run_adapter(tmp, pkg, base, revised, tmp / "out.docx")
    check("B1 (regression guard) no output at all is still a failure",
          proc.returncode == 5, f"rc={proc.returncode}")


def test_b2_adapter_refuses_input_as_out():
    """OUT is written (and now cleared first), so an input path must be refused
    instead of being destroyed when no backend can produce a redline."""
    tmp = tmpdir("b2")
    pkg = fake_redlines(tmp, "def main(argv):\n    return None\n")
    base, revised = tmp / "base.docx", tmp / "revised.docx"
    write(base, b"BASE CONTENT")
    write(revised, b"REVISED CONTENT")
    before = base.read_bytes()
    proc = run_adapter(tmp, pkg, base, revised, base)
    check("B2 an input file is refused as OUT and left intact",
          proc.returncode != 0 and base.is_file() and base.read_bytes() == before,
          f"rc={proc.returncode} exists={base.exists()} stdout={proc.stdout.strip()[:70]!r}")


# =====================================================================
# C1 -- reconcile_inputs must treat a pruned sandbox as unverifiable
# =====================================================================

def build_round_root(tmp: Path) -> Path:
    """A minimal root with one COMPLETED round and one done run of each kind."""
    root = tmp / "root"
    write(root / "pipeline_config.json",
          json.dumps({"rounds": 1, "judges": 1, "source": str(tmp / "src")}))
    write(root / "non-revised" / "manuscript-o.docx", "A")
    write(root / "round1_winner" / "manuscript-o.docx", "A")
    sandboxes = {
        "r1_a2_review": ("review", {"base": "base/manuscript-o.docx"}),
        "r1_a2_revise": ("revise", {"review": "review/findings.json"}),
        "r1_b1": ("cross", {"review": "review/findings.json"}),
        "r1_judge_orig_j1": ("judge", {"field": "field/a2/manuscript-o.docx",
                                       "target": "target/manuscript-o.docx"}),
    }
    for rid, (_kind, files) in sandboxes.items():
        for rel in files.values():
            write(root / "runs" / rid / rel, "A")
    state = {"version": np.STATE_VERSION, "runs": {}, "log": [], "pinned": [],
             "rounds": {"1": {"round": 1, "status": "done",
                              "winner_dir": "round1_winner",
                              "winner_id": "a2", "champion": "a2"}}}
    for rid, (kind, files) in sandboxes.items():
        sb = root / "runs" / rid
        state["runs"][rid] = {
            "id": rid, "kind": kind, "round": 1, "sandbox": f"runs/{rid}", "status": "done",
            "attempts": 1,
            "inputs_manifest": {area + "/": np.hash_manifest(sb / area)
                                for area in files},
        }
    write(root / "state.json", json.dumps(np._json_safe(state)))
    ctx = np.Ctx(root)
    ctx.load()
    # Record the deliverable/target digests exactly as the pipeline would.
    for rid in ("r1_a2_revise", "r1_b1"):
        rec = ctx.state["runs"][rid]
        rec["corpus_digest"] = np.recompute_corpus_digest(ctx, 1, np.freshness_vid(rec))
    judge = ctx.state["runs"]["r1_judge_orig_j1"]
    judge["target_digest"] = np.recompute_corpus_digest(ctx, 1, np.ORIGINAL_ID)
    judge["target_id"] = np.ORIGINAL_ID
    judge["field_digests"] = [{"id": "a2", "digest": np.recompute_corpus_digest(ctx, 1, "a2")}]
    ctx.state["source_manifest"] = np.hash_manifest(ctx.pristine)
    ctx.state["source"] = str(tmp / "src")
    ctx.save_state()
    return root


def test_c1_pruned_sandboxes_do_not_block_run():
    tmp = tmpdir("c1")
    root = build_round_root(tmp)
    ctx = np.Ctx(root)
    ctx.load()
    stale, blocking = np.reconcile_inputs(ctx)
    check("C1 (baseline) intact sandboxes are clean",
          not blocking and not stale, f"blocking={blocking} stale={stale}")
    for rec in ctx.runs():                            # `prune --yes` removes these
        if rec["kind"] != "a1":
            shutil.rmtree(ctx.sandbox_of(rec), ignore_errors=True)
    ctx.save_state()
    stale, blocking = np.reconcile_inputs(ctx)
    check("C1 a pruned (completed) round does not block every later `run`",
          not blocking and not stale, f"blocking={blocking} stale={stale}")


def test_c1_edited_sandbox_is_still_blocking():
    tmp = tmpdir("c1b")
    root = build_round_root(tmp)
    write(root / "runs" / "r1_judge_orig_j1" / "field" / "a2" / "manuscript-o.docx", "TAMPERED")
    ctx = np.Ctx(root)
    ctx.load()
    _stale, blocking = np.reconcile_inputs(ctx)
    check("C1 (regression guard) a sandbox edited after the fact is still blocking",
          bool(blocking), f"blocking={blocking}")


# =====================================================================
# C2 -- setup must copy the script it was launched from
# =====================================================================

def test_c2_setup_from_a_foreign_cwd():
    tmp = tmpdir("c2")
    src, root = tmp / "src", tmp / "root"
    write(src / "manuscript-o.docx", b"fake docx")
    proc = subprocess.run([sys.executable, str(NP_PATH), "setup", "--source", str(src),
                           "--root", str(root), "--rounds", "1", "--judges", "1"],
                          cwd="/tmp", capture_output=True, text=True)
    copied = root / "nbt_pipeline.py"
    check("C2 setup copies the script it was launched from (not a basename in $PWD)",
          proc.returncode == 0 and copied.is_file()
          and copied.read_bytes() == NP_PATH.read_bytes(),
          f"rc={proc.returncode} tail={(proc.stderr or proc.stdout).strip()[-200:]!r}")


def test_c2b_interrupted_setup_can_be_restarted():
    """`setup` that dies part-way (e.g. a transient I/O error on /mnt/c) leaves a
    marker in the root it was building, so the SAME command can simply be re-run
    instead of dying on "--root exists and is not empty" and leaving the operator
    to delete the half-built copy by hand. A root WITHOUT the marker is still
    protected."""
    tmp = tmpdir("c2b")
    src, root = tmp / "src", tmp / "root"
    write(src / "manuscript-o.md", "# pristine\n")
    # simulate the interrupted run: the partial copy plus setup's own marker
    write(root / "non-revised" / "junk.md", "half-written copy\n")
    write(root / "nbt_pipeline.py", "# copied\n")
    write(root / np.SETUP_MARKER, "setup started 2026-09-20 21:04:18\n")
    proc = subprocess.run([sys.executable, str(NP_PATH), "setup", "--source", str(src),
                           "--root", str(root), "--rounds", "1", "--judges", "1"],
                          capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    check("C2b a setup interrupted before state.json is restarted, not refused",
          proc.returncode == 0 and (root / "state.json").is_file()
          and (root / "non-revised" / "manuscript-o.md").is_file()
          and not (root / "non-revised" / "junk.md").exists(),
          f"rc={proc.returncode} tail={out.strip()[-200:]!r}")
    check("C2b the marker is gone once the root is usable",
          not (root / np.SETUP_MARKER).exists())
    # a completed root (or any root we did not create) is still protected
    proc2 = subprocess.run([sys.executable, str(NP_PATH), "setup", "--source", str(src),
                            "--root", str(root), "--rounds", "1", "--judges", "1"],
                           capture_output=True, text=True)
    check("C2b a COMPLETE root is still refused",
          proc2.returncode != 0 and "exists and is not empty" in (proc2.stdout + proc2.stderr),
          f"rc={proc2.returncode}")


# =====================================================================
# C3 -- the built-in redline writer must not emit undeclared mc:Ignorable
#       prefixes
# =====================================================================

def make_docx(path: Path, paragraphs, ignorable="w14 w15 wp14") -> None:
    decls = ('xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
             'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
             'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/'
             'wordprocessingDrawing"')
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}" {decls} '
           f'mc:Ignorable="{ignorable}"><w:body>{body}</w:body></w:document>')
    write(path, b"")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", xml)


def test_c3_mc_ignorable_prefixes_stay_declared():
    tmp = tmpdir("c3")
    base, revised, out = tmp / "base.docx", tmp / "revised.docx", tmp / "out.docx"
    make_docx(base, ["one", "two"])
    make_docx(revised, ["one", "TWO"])
    np.builtin_tracked_changes(base, revised, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    root = np.ET.fromstring(xml)                       # must still parse
    ignorable = (root.get("{%s}Ignorable" % MC_NS) or "").split()
    declared = set(re.findall(r"xmlns:([A-Za-z0-9_]+)=", xml[:4000]))
    missing = [p for p in ignorable if p not in declared]
    check("C3 every prefix named in mc:Ignorable is declared on the root",
          bool(ignorable) and not missing,
          f"ignorable={ignorable} missing={missing}")
    check("C3 (regression guard) the built-in writer still writes w:ins/w:del",
          b"<w:ins " in xml.encode() or b"<w:del " in xml.encode())


def test_c3_used_prefix_is_not_declared_twice():
    tmp = tmpdir("c3b")
    base, revised, out = tmp / "base.docx", tmp / "revised.docx", tmp / "out.docx"
    w14 = "http://schemas.microsoft.com/office/word/2010/wordml"
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}" xmlns:w14="{w14}" '
           'mc:Ignorable="w14"><w:body><w:p><w:pPr><w:jc w14:val="left"/></w:pPr>'
           "<w:r><w:t>{t}</w:t></w:r></w:p></w:body></w:document>")
    for path, text in ((base, "A"), (revised, "B")):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
            z.writestr("word/document.xml", xml.format(t=text))
    np.builtin_tracked_changes(base, revised, out)
    with zipfile.ZipFile(out) as z:
        got = z.read("word/document.xml").decode("utf-8")
    np.ET.fromstring(got)                              # must parse (duplicates would not)
    check("C3 (regression guard) a prefix ElementTree already emitted is not declared twice",
          got.count("xmlns:w14=") == 1, f"declarations={got.count('xmlns:w14=')}")


# =====================================================================
# C6 -- a failed backend must not be credited with another backend's file
# =====================================================================

def test_c6_stale_output_is_not_credited():
    tmp = tmpdir("c6")
    base, revised, out = tmp / "base.txt", tmp / "revised.txt", tmp / "out.docx"
    write(base, "a\n")
    write(revised, "b\n")
    # A *readable* OOXML package left behind by an earlier backend: the pipeline's
    # `docx_is_readable` check accepts it, so only "own the output path" stops it
    # being credited to a backend that wrote nothing.
    make_docx(out, ["left over from an earlier backend"])
    res = np.redline_one_pair("builtin", [sys.executable, "-c", "pass"], base, revised, out)
    first = res["attempts"][0]
    check("C6 a backend that writes nothing is not credited with the stale file",
          first.get("ok") is False, f"first_attempt={first}")
    check("C6 no redline file is left behind when every backend failed",
          not res["ok"] and not out.exists(),
          f"ok={res['ok']} out_exists={out.exists()}")


def test_c6_successful_backend_still_writes():
    tmp = tmpdir("c6b")
    base, revised, out = tmp / "base.docx", tmp / "revised.docx", tmp / "out.docx"
    make_docx(base, ["one", "two"])
    make_docx(revised, ["one", "TWO"])
    res = np.redline_one_pair("builtin", [], base, revised, out)
    check("C6 (regression guard) the built-in backend still produces a redline",
          res["ok"] and out.is_file() and np.docx_is_readable(out)[0],
          f"ok={res['ok']} tool={res['tool']}")


# =====================================================================
# C10 -- count_manual_steps: one header row per table, not one per file
# =====================================================================

def test_c10_manual_step_count_with_two_tables():
    tmp = tmpdir("c10")
    p = tmp / "MANUAL_STEPS.md"
    write(p, "- one bullet\n\n"
              "| step | owner |\n|---|---|\n| a | x |\n\n"
              "| step | owner |\n|---|---|\n| b | y |\n")
    n = np.count_manual_steps(p)
    check("C10 two tables subtract two header rows", n == 3, f"counted {n}, expected 3")


# =====================================================================

def main() -> int:
    print("== A1/A2: docx2pdf.sh ==")
    test_a1_path_with_single_quote()
    test_a2_missing_pdf_is_a_failure()
    test_a2_success_path_still_works()
    test_a2b_pdf_input_is_never_deleted()
    print("\n== B1: nbt_redlines_adapter.py ==")
    test_b1_adapter_stale_output()
    test_b1_adapter_absent_output_still_fails()
    test_b2_adapter_refuses_input_as_out()
    print("\n== C1: prune then run ==")
    test_c1_pruned_sandboxes_do_not_block_run()
    test_c1_edited_sandbox_is_still_blocking()
    print("\n== C2: setup copies the running script ==")
    test_c2_setup_from_a_foreign_cwd()
    test_c2b_interrupted_setup_can_be_restarted()
    print("\n== C3: mc:Ignorable ==")
    test_c3_mc_ignorable_prefixes_stay_declared()
    test_c3_used_prefix_is_not_declared_twice()
    print("\n== C6: stale redline output ==")
    test_c6_stale_output_is_not_credited()
    test_c6_successful_backend_still_writes()
    print("\n== C10: MANUAL_STEPS counting ==")
    test_c10_manual_step_count_with_two_tables()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL CANDIDATE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
