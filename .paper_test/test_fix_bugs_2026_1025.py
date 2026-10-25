#!/usr/bin/env python3
"""Regressions for the confirmed findings of the 2026-10-25 fix-bugs round.

Run:  python3 .paper_test/test_fix_bugs_2026_1025.py

Every check is a repro that failed on the pre-fix tree (or a direct assertion of
the corrected invariant). The suite is hermetic: temp dirs only, no network, no
Word/LibreOffice.
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
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


fmt = load("fixbugs_fmt", WS / "paper_docx_format.py")
pp = load("fixbugs_pp", WS / "paper_pipeline.py")
cw = load("fixbugs_cw", WS / "paper-skills/paper-review/scripts/count_words.py")
en = load("fixbugs_en", WS / "paper-skills/paper-review/scripts/extract_numbers.py")
ec = load("fixbugs_ec", WS / "paper-skills/paper-review/scripts/extract_citations.py")
eo = load("fixbugs_eo", WS / "paper-skills/paper-review/scripts/extract_occurrences.py")
ps = load("fixbugs_ps", WS / "pairwise_scores.py")


# ---------------------------------------------------------------- docx format
def test_docx():
    print("\n== DOCX formatting defects ==")
    check("invalid roman numerals are not given a value",
          fmt._roman_value("IIX") is None and fmt._roman_value("IL") is None
          and fmt._roman_value("VV") is None and fmt._roman_value("IIII") is None)
    check("valid roman numerals keep their value",
          fmt._roman_value("IV") == 4 and fmt._roman_value("VIII") == 8
          and fmt._roman_value("XL") == 40)

    for text in ("Figure 3 is cited before Figure 1 in the same paragraph.",
                 "Figures 3 and 1 are both cited here."):
        rows = fmt.display_order_rows([text], order_policy=True)
        check(f"within-paragraph citation inversion is reported: {text[:34]!r}",
              bool(rows) and rows[0]["rule"] == "FMT-O1", str(rows))

    check("a four-digit year is not a display-item number",
          fmt.display_order_rows(["Figure 2020 shows the trend.", "Figure 1."],
                                 order_policy=True) == [])
    check("Supplementary Information names the supplementary family",
          fmt._display_family_prefix("Supplementary Information ") == "supp")
    check("a wide range records no phantom far endpoint",
          fmt.display_order_rows(["Figures 1-200.", "Figure 2."], order_policy=True) == [])
    check("a descending range is not itself a numbering violation",
          fmt.display_order_rows(["Figures 5 to 3.", "Figure 4."], order_policy=True) == [])

    check("an escaped '&#38;' is decoded exactly once",
          fmt.unesc("&amp;#38;") == "&#38;", repr(fmt.unesc("&amp;#38;")))
    check("a quoted reference still decodes to a quote",
          fmt.unesc("&amp;quot;") == "&quot;")
    check("an out-of-range character reference stays literal",
          fmt.unesc("&#x110000;") == "&#x110000;")

    for phrase in ("four species were collected", "five series were recorded"):
        rows = fmt.word_number_rows(phrase)
        check(f"a real plural noun counts: {phrase!r}", bool(rows), str(rows))
    rows = fmt.word_number_rows("one of the five donors was excluded")
    check("'one of the five' keeps both count rows",
          [r["number"] for r in rows] == ["1", "5"], str(rows))

    check("'data.' ends a sentence",
          [t for t in [fmt.sentence_spans(
              "We deposited the sequence data. The next claim is independent.")]][0]
          and len(fmt.sentence_spans(
              "We deposited the sequence data. The next claim is independent.")) == 2)
    check("'Mr.' does not end a sentence before a name",
          fmt.sentence_spans("Contact Mr. Smith for the map. Then stop.")[0][1]
          == len("Contact Mr. Smith for the map."))

    check("a quoted comma is one CSV cell",
          fmt._simple_table('a,b\n"Smith, Jr.",x\nc,y\n')
          == (["a", "b"], [["Smith, Jr.", "x"], ["c", "y"]]))
    unlinked, n = fmt._unlink_fields(
        '<w:p><w:fldSimple w:instr=" ADDIN ZOTERO_ITEM "><w:r><w:t>[1]</w:t>'
        '</w:r></w:fldSimple><w:r><w:t> text</w:t></w:r></w:p>')
    check("a w:fldSimple field is unlinked, its result text kept",
          n == 1 and "w:fldSimple" not in unlinked
          and fmt.text_of(unlinked) == "[1] text", unlinked)

    para = ('<w:p><w:r><w:t xml:space="preserve">the</w:t></w:r><w:br/>'
            '<w:r><w:t xml:space="preserve">the same</w:t></w:r></w:p>')
    spans = [sp for sp in fmt.hygiene_spans(para) if sp["rule"] == "FMT-G1"]
    check("the doubled-word repair keeps a soft line break",
          bool(spans))
    if spans:
        new, _applied = fmt.rewrite_text_spans(
            para, [(spans[0]["start"], spans[0]["end"], spans[0]["repl"])])
        check("the doubled-word repair deletes only the duplicate",
              fmt.text_of(new) == "the\nsame", repr(fmt.text_of(new)))



# ------------------------------------------------------------------ pipeline
def test_pipeline_text():
    print("\n== pipeline text / role defects ==")
    check("an unbalanced TeX caption does not swallow the file",
          pp._tex_captions(r"\caption{broken" + "\n" * 5 + "tail") == [])
    check("an escaped brace does not close a TeX caption",
          pp._tex_captions(r"\caption{a \} b} tail") == [r"a \} b"])
    check("Supp1.docx is supplementary, not the main manuscript",
          pp.docx_document_role("Supp1.docx") == "supp"
          and pp.docx_document_role("main.docx") == "main")
    check("bash [!a] is a negation class",
          pp._extglob_to_regex("[!a]*.docx").match("b.docx") is not None
          and pp._extglob_to_regex("[!a]*.docx").match("a.docx") is None)
    check("a version id containing j<digits> is not split",
          pp.judge_item_parts("proj2") == (None, "proj2", None),
          str(pp.judge_item_parts("proj2")))
    check("the documented w2_j1 split still works",
          pp.judge_item_parts("w2_j1") == (None, "w2", 1))
    check("numeric probe values compare exactly",
          pp._probe_value_equal("0.912", "0.9120") is True
          and pp._probe_value_equal("0.912", "0.9121") is False)
    pdf = (b"%PDF-1.7\n1 0 obj\n<< /ID [<AABB><CCDD>] >>\nendobj\n"
           b"stream\n/ID [<EEFF><0011>]\nendstream\ntrailer\n"
           b"<< /ID [(abc)(def)] >>\n%%EOF")
    out_pdf, _notes = pp._sanitize_pdf_bytes(pdf)
    check("a PDF /ID at the head is blanked",
          b"<0000><0000>" in out_pdf, out_pdf[:120])
    check("a PDF /ID literal inside a stream is left alone",
          b"<EEFF><0011>" in out_pdf)
    check("a string-form PDF /ID is blanked", b"(   )(   )" in out_pdf)

    # A non-UTF-8 store README must not crash add-venue after publishing.
    d = scratch("fixbugs_readme_") / "store"
    d.mkdir()
    readme = d / "README.md"
    readme.write_bytes(b"# venue store\n\xff\xfe\n")
    out = pp._merge_readme_row(None, readme, "demo", {"label": "Demo"})
    check("a non-UTF-8 store README is merged without a crash",
          isinstance(out, str) and bool(out), str(out))


def test_counting():
    print("\n== M19 counting defects ==")
    text = """Abstract

First paragraph of the abstract with nine words here.

Second paragraph of the abstract with eight words.

Introduction

intro words here today

Methods

method words five six seven eight

Figure 1 | a caption of five words

Results

result words

References

ref one two
"""
    rows = {name: words for name, words, _note in cw.sections(text)}
    check("a multi-paragraph abstract is not cut at the first blank line",
          rows.get("abstract") == 17, str(rows))
    check("the count resumes after an excluded Methods section",
          rows.get("main text") == 6, str(rows))
    prow = {r["section"]: r["words"] for r in pp._length_rows_for_lines(
        text.splitlines(), "ms.md")}
    check("the pipeline's code-side scan agrees with the tool",
          prow.get("abstract") == 17 and prow.get("main text") == 6, str(prow))


def test_extractors():
    print("\n== skill extractor defects ==")
    pv = dict(en.LABEL_PATTERNS)["p-value"]
    for text, want in (("p<=0.05", "0.05"), ("p>=.01", ".01"),
                       ("p-value = 0.04", "0.04"), ("P-value < 0.001", "0.001")):
        m = pv.search(text)
        check(f"p-value operator/label parses: {text!r}", m and m.group(1) == want,
              (m.group(0) if m else None))
    auc = dict(en.LABEL_PATTERNS)["AUC"]
    check("AUC = 1 is inventoried",
          (auc.search("AUC = 1") or [None]) and auc.search("AUC = 1").group(1) == "1")

    m = ec.REF_ENTRY_RE.match("[1]Smith J. Nature 2019.")
    check("a numbered entry needs no space after the number",
          m is not None and m.group(1) == "1", str(m))

    term = eo.variant_pattern("copy-number", "term")
    check("term mode matches the en/em-dash spellings",
          all(term.search(s) for s in ("copy-number", "copy number", "copy–number",
                                       "copy—number")))

    # A commented-out numeric citation must not become a callout.
    root = scratch("fixbugs_tex_")
    corpus = root / "corpus"
    corpus.mkdir()
    (corpus / "paper.tex.txt").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Real \\cite{alpha}. A commented phantom % see [7]\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{alpha} A. Author. Title one. 2020.\n"
        "\\end{thebibliography}\n\\end{document}\n", encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                           "--work", str(root), "--out", str(root / "out")],
                          capture_output=True, text=True)
    art = root / "out" / "artifacts" / "M2_citations.json"
    data = json.loads(art.read_text(encoding="utf-8")) if art.is_file() else {}
    check("a commented-out [7] is not a callout",
          proc.returncode == 0 and not any(
              c.get("style") == "numeric" for c in data.get("callouts") or []),
          f"rc={proc.returncode} {data.get('callouts')!r}")

    # A non-numeric profile base is a clean no-cap row, not a traceback.
    ms = root / "ms.md"
    ms.write_text("Abstract\n\none two\n\nIntroduction\n\nintro words\n", encoding="utf-8")
    prof = root / "venue.json"
    prof.write_text(json.dumps({"schema_version": 1, "id": "t", "label": "T",
                                "length_limits": {"abstract": {"base": "abc",
                                                               "relaxation": 1.1}}}),
                    encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                           str(ms), "--venue-profile", str(prof), "--json"],
                          capture_output=True, text=True)
    ok = proc.returncode == 0
    try:
        payload = json.loads(proc.stdout)
        ok = ok and payload["caps"]["abstract"] is None
    except ValueError:
        ok = False
    check("a non-numeric profile base is a clean no-cap row", ok,
          f"rc={proc.returncode} {proc.stderr[-200:]}")


def test_pairwise():
    print("\n== pairwise score defects ==")
    base = scratch("fixbugs_pairwise_") / "run"
    (base / "reports").mkdir(parents=True)
    fields = ["round", "member", "credited", "direction", "opponent_id",
              "source_judge_run", "source_judge_index", "sheet_target",
              "score_as_written"]
    rows = [
        dict(round=1, member="a2", credited="", direction="received",
             opponent_id="a1", source_judge_run="j1", source_judge_index=1,
             sheet_target="a1", score_as_written=2),
        dict(round=1, member="a1", credited=5, direction="own", opponent_id="a3",
             source_judge_run="", source_judge_index="", sheet_target="a1",
             score_as_written=5),
        dict(round=1, member="a1", credited=5, direction="own", opponent_id="a3",
             source_judge_run="", source_judge_index="", sheet_target="a1",
             score_as_written=5),
    ]
    import csv
    with (base / "reports" / "round1_raw_scores.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    cubes, _notes = ps.collect([base], how="mean", pool_rounds=False, own_only=False)
    check("a received row with a blank credited column is negated",
          cubes[base.name]["1"][("a2", "a1")].values == [-2.0],
          str(cubes[base.name]["1"][("a2", "a1")].values))
    check("blank-identity judges are not deduped away",
          cubes[base.name]["1"][("a1", "a3")].values == [5.0, 5.0],
          str(cubes[base.name]["1"][("a1", "a3")].values))


def _env_with(path_entries):
    return dict(os.environ, PATH=os.pathsep.join(path_entries + [os.environ["PATH"]]))


def test_installer():
    print("\n== install-codex-mcp defects ==")
    node = shutil.which("node")
    if node is None:
        check("node is available for the installer regression", False)
        return
    root = scratch("fixbugs_installer_")
    home = root / "dsh"
    prof = home / "profiles" / "headless"
    prof.mkdir(parents=True)
    (prof / "cordis.patch.yml").write_text(
        "# header\nkeep: yes\n\n\n\n"
        "# >>> codex-mcp-import (managed block; regenerate with install-codex-mcp.mjs) >>>\n"
        "- insert:\n    - id: \"old\"\n      name: \"pkg\"\n"
        "      config:\n        transport: \"stdio\"\n        serverName: \"old\"\n"
        "# <<< codex-mcp-import <<<\nother: 1\n", encoding="utf-8")
    (prof / "package.json").write_text(json.dumps(
        {"name": "profile", "dependencies": {"@deepseek-ai/dsh-mcp-client": "1.2.3"}}),
        encoding="utf-8")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    dsh = bin_dir / "dsh"
    dsh.write_text("#!/bin/sh\necho 'dsh 1.2.3'\n")
    dsh.chmod(0o755)
    servers = root / "servers.json"
    servers.write_text(json.dumps([
        {"name": "alpha", "transport": {"type": "stdio", "command": "echo"}},
        {"name": "beta", "enabled": False,
         "transport": {"type": "stdio", "command": "echo"}},
        {"name": "gamma", "transport": {"type": "stdio", "command": "echo",
                                        "env": {"__proto__": "kept"}}}]), encoding="utf-8")
    env = _env_with([str(bin_dir)])

    def run(*args):
        return subprocess.run([node, str(WS / "scripts/install-codex-mcp.mjs"), *args],
                              cwd=str(WS), env=env, text=True, capture_output=True)

    proc = run("--dsh-home", str(home), "--servers-json", str(servers), "--dry-run")
    check("a server with no `enabled` field is imported",
          proc.returncode == 0 and 'serverName: "alpha"' in proc.stdout,
          proc.stderr[-200:])
    check("an explicit enabled:false server is still skipped",
          "skipped beta" in proc.stdout + proc.stderr)
    check("a `__proto__` env name reaches the generated config",
          '"__proto__": "kept"' in proc.stdout, proc.stdout[-400:])

    proc = run("--dsh-home", str(home), "--remove", "--dry-run")
    check("removing the block preserves user newlines outside the markers",
          "\n\n\n" in proc.stdout, repr(proc.stdout))

    # A directory named `dsh` earlier on PATH must not shadow the real binary.
    decoy = root / "decoy"
    decoy.mkdir()
    (decoy / "dsh").mkdir()
    proc = subprocess.run(
        [node, str(WS / "scripts/install-codex-mcp.mjs"), "--dsh-home", str(home),
         "--servers-json", str(servers), "--dry-run"],
        cwd=str(WS), env=_env_with([str(decoy), str(bin_dir)]),
        text=True, capture_output=True)
    check("a directory named dsh on PATH is not treated as the executable",
          proc.returncode == 0, proc.stderr[-200:])

    # Two changing runs in the same second must produce two backups.
    (prof / "cordis.patch.yml").write_text("keep: yes\n", encoding="utf-8")
    for prefix in ("a-", "b-"):
        run("--dsh-home", str(home), "--servers-json", str(servers),
            "--prefix", prefix, "--no-verify")
    backups = sorted(prof.glob("cordis.patch.yml.bak-codex-mcp-*"))
    check("two same-second backups are both kept", len(backups) >= 2,
          [b.name for b in backups])


def test_derived_output():
    print("\n== docx-compare derived output ==")
    node = shutil.which("node")
    if node is None:
        return
    root = scratch("fixbugs_derived_")
    orig = root / "base.docx"
    r1 = root / "a" / "rev.docx"
    r2 = root / "b" / "rev.docx"
    for p in (orig, r1, r2):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    script = (
        "import { derivedOutput } from "
        + json.dumps(str(WS / "mcp-docx-compare" / "derived-output.mjs"))
        + ";\n"
        + f"const a = derivedOutput({json.dumps(str(orig))}, {json.dumps(str(r1))});\n"
        + f"const b = derivedOutput({json.dumps(str(orig))}, {json.dumps(str(r2))});\n"
        + "console.log(a); console.log(b); console.log(a === b ? 'SAME' : 'DIFF');\n")
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          cwd=str(WS), text=True, capture_output=True)
    check("two revised files with one basename derive one output path",
          proc.returncode == 0 and proc.stdout.strip().endswith("SAME"),
          proc.stdout + proc.stderr[-200:])


def main():
    try:
        test_docx()
        test_pipeline_text()
        test_counting()
        test_extractors()
        test_pairwise()
        test_installer()
        test_derived_output()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} failed")
        for name in FAILS:
            print(f"  FAILED: {name}")
        return 1
    print("ALL 2026-10-25 FIX-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
