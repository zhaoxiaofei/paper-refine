#!/usr/bin/env python3
"""The integration stage's diagnostics: the donor index, the ledger reader, the repair guard.

Run:  python3 .nbt_test/test_integrate_diagnostics.py

Three defects of one real run (r1_i3, 2026-09-22) are pinned here:

  1. the prompt told the session to read FOUR complete corpora in full and not to
     use any diff tool. Two attempts ended after 366k / 204k tokens without one
     bookkeeping file. The orchestrator now seeds the mechanical difference index
     (`integrated/work/DIFF_MATRIX.md` + `integrated/work/diffs/<donor>_vs_self.md`)
     and the prompt starts the session there (`donor_diff_pack`).
  2. the ledger READER took the FIRST table of DIFF_LEDGER.md. A session that
     opened the file with an orientation table (`| version | payload files | ... |`)
     had those four rows parsed AS the ledger and failed with "4 ledger row(s)
     carry no `artifact`" although its ledger was complete (`integration_ledger_rows`).
  3. the repair-scope guard counted `__pycache__/*.pyc` -- written by RUNNING the
     helper scripts the prompts tell the session to run -- as an out-of-scope edit
     and failed a repair that had cleared every problem it was given
     (`is_bytecode_cache`).
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_integrate_diag", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_integrate_diag"] = nb
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


def docx_bytes(paragraphs: list) -> bytes:
    """A minimal but REAL .docx whose word/document.xml carries these paragraphs."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def matrix_of(sb: Path) -> str:
    return (sb / "integrated" / "work" / "DIFF_MATRIX.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. the ledger reader picks the LEDGER table, not the session's summary table
# ---------------------------------------------------------------------------
def test_ledger_table_selection():
    print()
    print("== DIFF_LEDGER.md: the ledger is the table with the ledger's columns ==")
    out = scratch("nbt_int_led_") / "integrated"
    (out / "work" / "diffs").mkdir(parents=True)
    (out / "work" / "diffs" / "L-001.md").write_text("before/after pair", encoding="utf-8")
    (out / "DIFF_LEDGER.md").write_text(
        "# DIFF_LEDGER\n\n"
        "## 0. State of the package (orientation)\n\n"
        "| version | payload files | differing | M20 rows |\n"
        "|---|---|---|---|\n"
        "| integrated/ | 29 | - | 68 |\n"
        "| others/a1/ | 38 | 7 | 127 |\n"
        "| others/w2/ | 30 | 7 | 119 |\n\n"
        "## 1. The ledger\n\n"
        "| id | donor | location | size | donor says | self says | verdict | why | effect | "
        "artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| L-001 | a1 | cover letter p5 | small | the donor's sentence | the base's sentence | "
        "keep-self | base wins | none | `integrated/work/diffs/L-001.md` | none |\n"
        "| L-002 | w2 | main text headings | large | a different tree | the base tree | "
        "keep-self | no M20 row attaches to it | none | `integrated/work/diffs/L-001.md` | none |\n",
        encoding="utf-8")
    rep = nb.integration_ledger_report(out, ["a1", "w2"], True)
    check("the 3-row orientation table is NOT read as the ledger",
          rep["rows"] == 2, f"rows={rep['rows']}")
    check("every ledger row's artifact is found",
          rep["missing_artifact"] == [] and rep["missing_finding"] == [],
          f"missing_artifact={rep['missing_artifact']} missing_finding={rep['missing_finding']}")
    check("both donors and both size classes are read from the LEDGER",
          rep["donors_absent"] == [] and rep["both_levels"] is True,
          f"absent={rep['donors_absent']} sizes={rep['sizes']}")
    # A file that really has no ledger table still reports the rows it does have.
    out2 = scratch("nbt_int_led2_") / "integrated"
    out2.mkdir(parents=True)
    (out2 / "DIFF_LEDGER.md").write_text(
        "| version | payload files |\n|---|---|\n| integrated/ | 29 |\n| others/a1/ | 38 |\n",
        encoding="utf-8")
    rep2 = nb.integration_ledger_report(out2, ["a1"], False)
    check("a file with no ledger columns keeps the old (failing) reading",
          rep2["rows"] == 2 and len(rep2["missing_artifact"]) == 2,
          f"rows={rep2['rows']} missing={rep2['missing_artifact']}")


# ---------------------------------------------------------------------------
# 2. a repair that runs the seeded tools is not "out of scope"
# ---------------------------------------------------------------------------
def test_repair_guard_ignores_bytecode():
    print()
    print("== repair scope: `__pycache__/*.pyc` is a cache of RUNNING a tool, not an edit ==")
    sb = scratch("nbt_int_guard_")
    (sb / "integrated" / "work").mkdir(parents=True)
    (sb / "integrated" / "DIFF_LEDGER.md").write_text("| donor | artifact |\n|---|---|\n", encoding="utf-8")
    (sb / "nbt_docx_format.py").write_text("# the seeded tool\n", encoding="utf-8")
    guard = {"kind": "integrate", "files": nb._repair_guard_files(sb, "integrate")}
    # what the session's own tool runs produce, plus one REAL violation
    (sb / "__pycache__").mkdir()
    (sb / "__pycache__" / "nbt_docx_format.cpython-312.pyc").write_bytes(b"pyc")
    (sb / "integrated" / "work" / "__pycache__").mkdir()
    (sb / "integrated" / "work" / "__pycache__" / "helper.pyc").write_bytes(b"pyc")
    (sb / "integrated" / "work" / "helper.pyo").write_bytes(b"pyc")
    (sb / "EVIL.md").write_text("a real out-of-scope create", encoding="utf-8")
    problems = nb.repair_guard_problems(sb, guard, {"kind": "integrate"})
    check("bytecode caches are ignored, a real out-of-scope file is still caught",
          len(problems) == 1 and "EVIL.md" in problems[0], str(problems))
    check("a `__pycache__` created inside the package is ignored too",
          not any("pyc" in p or "__pycache__" in p for p in problems), str(problems))


# ---------------------------------------------------------------------------
# 3. the orchestrator's mechanical donor index
# ---------------------------------------------------------------------------
def test_donor_diff_pack():
    print()
    print("== donor_diff_pack: the difference index the session starts from ==")
    sb = scratch("nbt_int_pack_")
    self_d, other_d = sb / "self", sb / "others" / "a1"
    self_d.mkdir(parents=True)
    other_d.mkdir(parents=True)
    (self_d / "manuscript.md").write_text("Abstract\n\nwe used 3 cells.\n", encoding="utf-8")
    (other_d / "manuscript.md").write_text("Abstract\n\nwe used 4 cells.\n", encoding="utf-8")
    (self_d / "mainText.docx").write_bytes(docx_bytes(["Results", "we used 3 cells.", "Done."]))
    (other_d / "mainText.docx").write_bytes(docx_bytes(["Results", "we used 4 cells.", "Done.",
                                                        "A new limitation."]))
    (self_d / "fig1.png").write_bytes(b"\x89PNG-identical")
    (other_d / "fig1.png").write_bytes(b"\x89PNG-identical")
    (other_d / "only-in-donor.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    # Every arm names its documents with ITS OWN 7-hex token, so the comparison
    # must be name-insensitive: path-for-path these two would look like two
    # unrelated corpora ("only in donor" / "only in self") instead of one changed
    # document.
    (self_d / "cover-aaaaaaa.docx").write_bytes(docx_bytes(["the base's cover"]))
    (other_d / "cover-bbbbbbb.docx").write_bytes(docx_bytes(["the donor's cover"]))
    (self_d / "work").mkdir()                      # scratch is not payload
    (self_d / "work" / "junk.txt").write_text("x", encoding="utf-8")
    summary = nb.donor_diff_pack(sb, "w2", ["a1"])
    check("the per-donor summary counts differ / identical / only-in-donor",
          summary.get("a1") == {"identical": 1, "differing": 3, "only_in_donor": 1,
                                "only_in_self": 0}, str(summary))
    check("differently named documents are matched by their TOKEN-STRIPPED name",
          "`cover-aaaaaaa.docx`" in matrix_of(sb) and "`cover-bbbbbbb.docx`" in matrix_of(sb)
          and "cover-bbbbbbb.docx" in (sb / "integrated" / "work" / "diffs"
                                       / "a1_vs_self.md").read_text(encoding="utf-8"),
          matrix_of(sb)[:120])
    check("`work/` scratch is not compared as payload",
          "junk.txt" not in (sb / "integrated" / "work" / "diffs" / "a1_vs_self.md").read_text(),
          "work/junk.txt leaked into the index")
    matrix = (sb / "integrated" / "work" / "DIFF_MATRIX.md").read_text(encoding="utf-8")
    detail = (sb / "integrated" / "work" / "diffs" / "a1_vs_self.md").read_text(encoding="utf-8")
    check("the index names the differing files, the donor-only file and the detail path",
          "`manuscript.md`" in matrix and "`mainText.docx`" in matrix
          and "only in donor `a1`: `only-in-donor.tex`" in matrix
          and "integrated/work/diffs/a1_vs_self.md" in matrix,
          matrix[:160])
    check("the detail carries a text diff AND an aligned paragraph diff of the .docx",
          "```diff" in detail and "we used 3 cells" in detail and "we used 4 cells" in detail
          and "paragraphs: self 3 · donor 4" in detail and "A new limitation" in detail,
          detail[-240:])
    check("both files are inside the package (`artifact` cells can cite them)",
          (sb / "integrated" / "work" / "DIFF_MATRIX.md").is_file()
          and (sb / "work" / "DONOR_DIFFS.md").is_file())


# ---------------------------------------------------------------------------
# 4. the integration prompt starts from the index
# ---------------------------------------------------------------------------
def test_integrate_prompt_points_at_the_index():
    print()
    print("== the integration prompt: start from the index, adjudicate on the material ==")
    p = nb.integrate_prompt(Path("/tmp/nbt_sb"), "r1_i3", 1, "w2", ["a1", "w1", "a2"],
                            caption_limit=0, zotero="edit")
    check("no unresolved placeholder is left in the prompt",
          not __import__("re").search(r"@@[A-Z_]+@@", p))
    check("the prompt names the difference index and the per-donor detail files",
          "integrated/work/DIFF_MATRIX.md" in p and "integrated/work/diffs/<donor>_vs_self.md" in p)
    check("the prompt no longer demands reading every donor corpus IN FULL",
          "IN FULL YOURSELF" not in p and "Do NOT\nrely on a shell `diff`" not in p)
    check("every difference is still adjudicated on the REAL material",
          "adjudicated on the REAL material" in p and "Never decide a row from the diff text alone" in p)
    check("the ledger is written as the session goes (an early end leaves a readable ledger)",
          "WRITE THE BOOKKEEPING AS YOU GO" in p
          and "one `unable` row per donor" in " ".join(p.split()))
    rep = nb.repair_prompt(type("C", (), {"sandbox_of": lambda self, rec: Path("/tmp")})(), 
                           {"id": "r1_i3", "kind": "integrate", "round": 1},
                           ["integrated/DIFF_LEDGER.md is missing: x"])
    check("the repair prompt states the ledger columns and the artifact rule",
          "`donor` and `artifact` above all" in rep and "DIFF_MATRIX.md" in rep)


# ---------------------------------------------------------------------------
# 5. the seeded index must not look like agent work
# ---------------------------------------------------------------------------
def test_seeded_index_is_not_agent_work():
    print()
    print("== a sandbox materialized with the index is still clean/unstarted ==")
    root = scratch("nbt_int_left_")
    sb = root / "runs" / "r1_i1"
    (sb / "integrated" / "work" / "diffs").mkdir(parents=True)
    (sb / "integrated" / "work" / "DIFF_MATRIX.md").write_text("index", encoding="utf-8")
    (sb / "integrated" / "work" / "diffs" / "a2_vs_self.md").write_text("detail", encoding="utf-8")
    ctx = nb.Ctx(root)
    rec = {"kind": "integrate", "sandbox": "runs/r1_i1"}
    check("a freshly materialized integration sandbox is NOT 'already worked in'",
          nb.leftovers_present(ctx, rec) is False)
    (sb / "integrated" / "DIFF_LEDGER.md").write_text("a real ledger", encoding="utf-8")
    check("an agent's ledger next to the package DOES count as work already done",
          nb.leftovers_present(ctx, rec) is True)
    (sb / "integrated" / "DIFF_LEDGER.md").unlink()
    (sb / "code").mkdir()
    (sb / "code" / "run.sh").write_text("x", encoding="utf-8")
    check("code/ still counts as work already done",
          nb.leftovers_present(ctx, rec) is True)


def main() -> int:
    try:
        test_ledger_table_selection()
        test_repair_guard_ignores_bytecode()
        test_donor_diff_pack()
        test_integrate_prompt_points_at_the_index()
        test_seeded_index_is_not_agent_work()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} INTEGRATION-DIAGNOSTICS CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL INTEGRATION-DIAGNOSTICS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
