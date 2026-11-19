#!/usr/bin/env python3
"""fix_bugs wave 2026-11-19-232857, group g3_redline (F014/F015/F016/F018/F019/F034).

One check per confirmed defect on the redline / difference-tracking surface:

  * F014 -- the built-in redline's `_pPr_for` fell back to the BASE pPr when the
    revised paragraph carried none, and then compared that copy with the base,
    so a paragraph style the revision REMOVED was resurrected with no
    `w:pPrChange`: accept-all kept the deleted style.
  * F015 -- `write_docx_logging_fallback` appended its note paragraphs after a
    copied trailing `w:sectPr`; CT_Body requires the body-level sectPr LAST, so
    the fallback wrote schema-invalid OOXML while reporting ok=True.
  * F016 -- a readable but COMPLETELY UNMARKED .docx (own_marked_words == 0 for
    a pair the minimal-weight estimate proves differs) passed the only fidelity
    gate (over-marking) and was announced as the tracked copy.
  * F018 -- p13's `_md_table_cell` escaped only `|`, so text carrying a literal
    backslash before a pipe (`a\\|b`) produced `a\\\\|b`: an escaped backslash
    followed by a real cell separator, which splits the README row.
  * F019 -- `tracking_readme` interpolated a skipped comparison's `reason` raw,
    so a newline in a tool error injected extra Markdown lines.
  * F034 -- `redline --version w99` (a syntactically valid but never
    materialized version) wrote a manifest, printed "0 failed" and exited 0.

The suite is hermetic: DOCX fixtures are built with stdlib zipfile, and the one
CLI test runs `setup` into a temp root.
"""
from __future__ import annotations

import copy
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
from xml.etree import ElementTree as ET

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_redline_g3", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_redline_g3"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SECTPR = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'


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


def make_docx(path: Path, paragraphs: list, sect: bool = False) -> None:
    """`paragraphs` = list of raw `<w:p>` (or other body-child) XML strings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>'
                   + "".join(paragraphs) + (SECTPR if sect else "") + "</w:body></w:document>")


def para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def doc_root(docx: Path):
    return ET.fromstring(zipfile.ZipFile(docx).read("word/document.xml"))


def body_children(docx: Path) -> list:
    return [str(c.tag).rsplit("}", 1)[-1] for c in doc_root(docx).find(W + "body")]


def live_ppr(p):
    """The paragraph's live pPr with the change RECORD peeled off (accept-all)."""
    pr = p.find(W + "pPr")
    live = copy.deepcopy(pr) if pr is not None else None
    if live is not None:
        for ch in live.findall(W + "pPrChange"):
            live.remove(ch)
    return live


def reject_ppr(p):
    """The pPr reject-all restores: the recorded old pPr of the pPrChange."""
    pr = p.find(W + "pPr")
    change = pr.find(W + "pPrChange") if pr is not None else None
    return change.find(W + "pPr") if change is not None else None


def style_of(pr):
    st = pr.find(W + "pStyle") if pr is not None else None
    return None if st is None else st.get(W + "val")


# ---------------------------------------------------------------------------
# F014 -- a style the revision removed must not survive accept-all
# ---------------------------------------------------------------------------
def test_f014_removed_paragraph_style():
    print()
    print("== F014: a removed paragraph style is a tracked paragraph-mark change ==")
    tmp = scratch("g3_f014_")
    base, rev, out = tmp / "base.docx", tmp / "rev.docx", tmp / "out.docx"
    heading = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
               '<w:r><w:t>Hello world</w:t></w:r></w:p>')
    make_docx(base, [heading])
    make_docx(rev, [para("Hello world")])
    nb.builtin_tracked_changes(base, rev, out)
    p = doc_root(out).find(W + "body").find(W + "p")
    pr = p.find(W + "pPr")
    change = pr.find(W + "pPrChange") if pr is not None else None
    check("F014 the redline still parses and keeps the paragraph text",
          nb._para_text(p) == "Hello world", repr(nb._para_text(p)))
    check("F014 accept-all does NOT keep the style the revision removed",
          style_of(live_ppr(p)) is None, f"live pStyle={style_of(live_ppr(p))!r}")
    check("F014 the removed style is recorded in a w:pPrChange",
          change is not None and style_of(reject_ppr(p)) == "Heading1",
          f"change={change is not None} old pStyle={style_of(reject_ppr(p))!r}")
    check("F014 reject-all restores the base heading",
          style_of(reject_ppr(p)) == "Heading1", ET.tostring(pr).decode()[:300])
    check("F014 no base pStyle leaks into the live pPr",
          b"Heading1" not in ET.tostring(live_ppr(p) or ET.Element("x")),
          ET.tostring(pr).decode()[:300])


# ---------------------------------------------------------------------------
# F015 -- the logging fallback keeps the body-level sectPr LAST
# ---------------------------------------------------------------------------
def test_f015_logging_fallback_sectpr_last():
    print()
    print("== F015: the logging fallback never puts a paragraph after w:sectPr ==")
    tmp = scratch("g3_f015_")
    base, cand, out = tmp / "base.docx", tmp / "cand.docx", tmp / "out.docx"
    make_docx(base, [para("Alpha"), para("Deleted tail paragraph.")], sect=True)
    make_docx(cand, [para("Alpha")], sect=True)
    rep = nb.write_docx_logging_fallback(base, cand, out, "original", "test failure")
    check("F015 the fallback still reports ok", rep.get("ok") is True, str(rep))
    tags = body_children(out)
    check("F015 the body-level w:sectPr is the LAST child",
          bool(tags) and tags[-1] == "sectPr" and tags.count("sectPr") == 1, str(tags))
    note_texts = [nb._para_text(p) for p in
                  doc_root(out).find(W + "body").findall(W + "p")]
    check("F015 the before/after notes were not lost when the sectPr moved",
          any("[LOGGING FALLBACK" in t for t in note_texts)
          and any("Deleted tail paragraph." in t for t in note_texts),
          str(note_texts)[:300])
    check("F015 the revised paragraph is still there", "Alpha" in note_texts,
          str(note_texts)[:300])


# ---------------------------------------------------------------------------
# F016 -- a readable but completely unmarked DOCX is not a redline
# ---------------------------------------------------------------------------
def test_f016_unmarked_copy_is_rejected():
    print()
    print("== F016: an unmarked copy of the base is not accepted as the redline ==")
    tmp = scratch("g3_f016_")
    base, rev, out = tmp / "base.docx", tmp / "rev.docx", tmp / "out.docx"
    make_docx(base, [para("Alpha beta gamma delta.")])
    make_docx(rev, [para("Alpha beta gamma epsilon.")])
    fid = nb.redline_fidelity(base, rev, base)
    check("F016 the fidelity result EXPOSES the under-marking (own markup == 0, change > 0)",
          fid.get("under_marked") is True and fid["own_marked_words"] == 0
          and fid["minimal_words"] > 0 and fid["over_marked"] is False
          and fid.get("unmarked_input_copy") == "base", str(fid))

    copy_cmd = [sys.executable, "-c",
                "import shutil,sys; shutil.copyfile(sys.argv[1], sys.argv[2])",
                "{base}", "{out}"]
    # Only the copy backend in the chain, so the pair's outcome is its outcome.
    res = nb.redline_one_pair("redline-cmd", copy_cmd, base, rev, out)
    check("F016 a chain whose only backend writes an unmarked copy of the base is NOT a winner",
          res["ok"] is False, str(res)[:400])
    attempts = res["attempts"] or [{}]
    check("F016 every copy attempt is recorded as failed with its numbers",
          all(a.get("ok") is False
              and (a.get("fidelity") or {}).get("unmarked_input_copy") == "base"
              and "no w:ins/w:del" in str(a.get("detail")) for a in attempts),
          str(attempts)[:400])
    check("F016 no unmarked file is left at OUT", not out.exists(), str(out))

    # The same defect in the other direction: a backend that hands back the
    # REVISED document unmarked also says "no changes happened".
    rev_copy_cmd = [sys.executable, "-c",
                    "import shutil,sys; shutil.copyfile(sys.argv[1], sys.argv[2])",
                    "{revised}", "{out}"]
    res_rev = nb.redline_one_pair("redline-cmd", rev_copy_cmd, base, rev, out)
    check("F016 a chain whose only backend writes an unmarked copy of the revised is NOT a winner",
          res_rev["ok"] is False
          and ((res_rev["attempts"] or [{}])[0].get("fidelity") or {})
          .get("unmarked_input_copy") == "revised",
          str(res_rev)[:400])


    # Positive control: a real diff on the same pair still wins.
    res2 = nb.redline_one_pair("builtin", [], base, rev, out)
    check("F016 a backend that really marks the change still produces the redline",
          res2["ok"] is True and res2["tool"] == "builtin-ooxml"
          and out.is_file(), str(res2)[:300])


# ---------------------------------------------------------------------------
# F018 -- the redline README cell escaper escapes the ESCAPE CHARACTER first
# ---------------------------------------------------------------------------
def _cells(md_row: str) -> list:
    """Split a Markdown table row the way a reader does: an ODD run of
    backslashes before a pipe escapes the pipe."""
    cells, cur, i = [], [], 0
    while i < len(md_row):
        ch = md_row[i]
        if ch == "|":
            j = i - 1
            n = 0
            while j >= 0 and md_row[j] == "\\":
                n += 1
                j -= 1
            if n % 2 == 0:
                cells.append("".join(cur))
                cur = []
                i += 1
                continue
        cur.append(ch)
        i += 1
    cells.append("".join(cur))
    return cells[1:-1] if len(cells) >= 2 else cells


def test_f018_md_table_cell_backslash():
    print()
    print("== F018: a backslash before a pipe cannot split the README row ==")
    raw = "a\\|b"                                       # a literal backslash + pipe
    esc = nb._md_table_cell(raw)
    run = re.match(r"a(\\*)\|", esc)
    check("F018 the escaped cell leaves an ODD run of backslashes before the pipe",
          run is not None and len(run.group(1)) % 2 == 1, repr(esc))
    check("F018 the shared helper and the README helper agree",
          esc == nb.md_table_cell(raw), f"{esc!r} vs {nb.md_table_cell(raw)!r}")
    row = f"| {esc} | second |"
    check("F018 a Markdown reader still sees exactly two cells",
          _cells(row) == [f" {esc} ", " second "], f"{_cells(row)!r}")


# ---------------------------------------------------------------------------
# F019 -- a skipped reason cannot inject Markdown lines
# ---------------------------------------------------------------------------
def test_f019_skipped_reason_escaped():
    print()
    print("== F019: a newline in a skipped reason stays on the same bullet ==")
    manifest = {
        "generated": "2026-11-19T00:00:00Z", "tool": "auto",
        "versions": [{"round": 1, "version": "w1", "comparisons": [], "skipped": [
            {"baseline": "original", "base_rel": "main.docx",
             "reason": "latexdiff failed: boom\n- INJECTED BULLET: NOT a result"}]}],
        "notes": [],
    }
    text = nb.tracking_readme(manifest)
    lines = text.splitlines()
    start = lines.index("## Skipped")
    section = lines[start:start + 4]
    check("F019 the reason does not create a new Markdown line",
          "- INJECTED BULLET: NOT a result" not in lines, str(section))
    check("F019 the whole reason stays on the skip's own bullet",
          any(ln.startswith("- r1 w1:") and "INJECTED BULLET" in ln for ln in section),
          str(section))
    piped = nb._md_cell("a|b")
    check("F019 a pipe in the reason cannot split a rendered bullet",
          _cells(f"| {piped} | second |") == [f" {piped} ", " second "],
          f"{piped!r} -> {_cells(f'| {piped} | second |')!r}")


# ---------------------------------------------------------------------------
# F034 -- a requested-but-unmaterialized version is a failed redline run
# ---------------------------------------------------------------------------
def test_f034_unmaterialized_version_fails():
    print()
    print("== F034: `redline --version w99` on a root without w99 exits non-zero ==")
    tmp = scratch("g3_f034_")
    src, root = tmp / "src", tmp / "root"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n", encoding="utf-8")
    setup = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root), "--rounds", "3"],
        capture_output=True, text=True, timeout=900)
    check("F034 setup produced a pipeline root", setup.returncode == 0,
          (setup.stdout + setup.stderr)[-400:])
    # Other agents edit sibling parts while this suite runs; the root refuses to
    # be driven from a bundle that changed after `setup`. Re-sync and retry on
    # exactly that refusal (it is not the defect under test).
    proc, output = None, ""
    for _attempt in range(6):
        subprocess.run(
            [sys.executable, str(WS / "paper_pipeline.py"), "sync-code",
             "--root", str(root)], capture_output=True, text=True, timeout=300)
        proc = subprocess.run(
            [sys.executable, str(WS / "paper_pipeline.py"), "redline",
             "--root", str(root), "--version", "w99"],
            capture_output=True, text=True, timeout=300)
        output = proc.stdout + proc.stderr
        if proc.returncode == 2 and "STALE sibling module" in output:
            continue
        break
    check("F034 a never-materialized requested version exits non-zero",
          proc is not None and proc.returncode != 0,
          f"rc={getattr(proc, 'returncode', None)} out={output[-300:]}")
    check("F034 the report names the version that was never materialized",
          "w99" in output and "materialized" in output, output[-400:])


if __name__ == "__main__":
    try:
        test_f014_removed_paragraph_style()
        test_f015_logging_fallback_sectpr_last()
        test_f016_unmarked_copy_is_rejected()
        test_f018_md_table_cell_backslash()
        test_f019_skipped_reason_escaped()
        test_f034_unmaterialized_version_fails()
    except Exception as e:                                        # noqa: BLE001
        import traceback
        traceback.print_exc()
        check("the suite completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("G3 REDLINE FIXES PASSED")
