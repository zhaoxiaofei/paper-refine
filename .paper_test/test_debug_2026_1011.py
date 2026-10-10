#!/usr/bin/env python3
"""The 2026-10-11 debug round: FMT-O1/R3/R4, self-closing sectPr, encrypted DOCX,
concern seeds, MCP args, audit rows, manual-steps encoding, judge discovery
vocabulary, MCP containment root and `docxcompare.sh`'s realpath.

Run:  python3 .paper_test/test_debug_2026_1011.py

Every check below is a defect an independent audit of commit `0168944` reported
and this round reproduced on the tree:

  * FMT-O1 read `Figures 1-5` as items 1 and 5 only, so a later `Figure 3`
    looked "first cited out of order", and it read the `2020` of
    `Figure 1, 2020 update` as an item number (a phantom 2020);
  * FMT-R3 called a `/blob/<sha>`-pinned repository URL "no version" while
    FMT-AV2's own `REPO_PIN_RE` already counted `/blob/<sha>` as a pin, and
    FMT-R4 read only the FIRST DOI of an entry (a published DOI before the
    `10.1101/` one was a false row);
  * the template writer put `w:headerReference` AFTER a legal self-closing
    `<w:sectPr .../>`, which is schema-invalid OOXML;
  * an encrypted (or oddly-compressed) .docx leaked `RuntimeError` /
    `NotImplementedError` out of readers whose contract is "unreadable
    package", instead of the documented "cannot parse" answer;
  * `seed_concern_candidates` never split at `1.` / `-` markers (the trailing
    `\\b` cannot match after `.` or `-`), contradicting its docstring;
  * `mcp_server_spec` truncated `args = [...]` at the first `]`, silently
    dropping EVERY argument of the server;
  * `audit_artifact_problems` crashed with AttributeError on a non-object
    `adds` row, where the sibling `dispositions` loop reports it;
  * `count_manual_steps` crashed on a non-UTF-8 MANUAL_STEPS.md;
  * the judge's discovery check rejected the review skill's own canonical clean
    closure spelling (`no anomalies -- checked: <locations>`);
  * `containment.mjs` refused every path when `DOCX_MCP_ALLOWED_ROOTS=/` (the
    "allow everything" spelling), because `/` + separator is `//`;
  * `docxcompare.sh` used `realpath` before its `command -v` guard, so a host
    without it died under `set -e` with no diagnostic.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_dbg1011_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_dbg1011_format", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def _flagged_docx(path: Path, *, flag: int = 0, method: int = None) -> Path:
    """A .docx zip whose entry carries `flag` bits (and optionally `method`).

    zipfile cannot CREATE an encrypted or AES-compressed archive, but it reads
    the header fields: setting bit 0 of the general-purpose flag (local header
    offset 6, central directory offset 8) makes `read()` raise RuntimeError
    ("is encrypted"), and an unsupported compression method raises
    NotImplementedError -- exactly the two exceptions a tolerant reader must
    treat as "unreadable package".
    """
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    buf = bytearray(path.read_bytes())
    i = buf.find(b"PK\x03\x04")
    j = buf.find(b"PK\x01\x02")
    buf[i + 6:i + 8] = struct.pack("<H", flag)
    buf[j + 8:j + 10] = struct.pack("<H", flag)
    if method is not None:
        buf[i + 8:i + 10] = struct.pack("<H", method)
        buf[j + 10:j + 12] = struct.pack("<H", method)
    path.write_bytes(bytes(buf))
    return path


# ---------------------------------------------------------------------------
# FMT-O1 -- ranges date every item; a year is not an item number
# ---------------------------------------------------------------------------
def test_display_order_ranges_and_years():
    print("\n== FMT-O1 range spans and comma-continuation tokens ==")
    mid = ["The dataset is described in Figures 1-5.", "Figure 3 shows the effect."]
    rows = fmt.display_order_rows(mid, order_policy=True)
    check("a middle item covered by a range is not re-dated by a later call-out",
          rows == [], str([r["evidence"] for r in rows]))
    year = ["Figure 1, 2020 update, reports the result.", "Figure 2 shows the effect."]
    rows = fmt.display_order_rows(year, order_policy=True)
    check("a year after a comma is not read as a display item",
          rows == [], str([r["evidence"] for r in rows]))
    # Controls: the rule still fires on a genuine inversion, and an in-order
    # range call-out stays clean.
    bad = ["Table 4 lists them.", "Table 2 lists more."]
    check("a genuine out-of-order first mention is still reported",
          any(r["rule"] == "FMT-O1" for r in fmt.display_order_rows(bad, order_policy=True)))
    good = ["Figures 1-5 show the effect.", "Figure 6 shows more."]
    check("an in-order range call-out is clean",
          fmt.display_order_rows(good, order_policy=True) == [])
    after = ["Figures 5-8 show the effect.", "Figure 3 shows it again."]
    check("an item below a range's span cited later is still reported",
          any(r["rule"] == "FMT-O1" for r in fmt.display_order_rows(after, order_policy=True)))


# ---------------------------------------------------------------------------
# FMT-R3 / FMT-R4 -- the pin and DOI forms the rules must agree on
# ---------------------------------------------------------------------------
def test_reference_pins_and_dois():
    print("\n== FMT-R3 / FMT-R4 ==")
    sha = "0b105331aa1fbbd94832ae308a84e133831fa807"
    blob = [f"See https://github.com/org/tool/blob/{sha}/README.md for details."]
    rows = fmt.reference_entry_rows(blob, [True])
    check("a /blob/<sha> URL counts as a version pin (like REPO_PIN_RE does)",
          rows == [], str([r["evidence"] for r in rows]))
    bare = ["See https://github.com/org/tool for the analysis code."]
    check("a repository URL with no pin is still reported",
          any(r["rule"] == "FMT-R3" for r in fmt.reference_entry_rows(bare, [True])))
    both = ["A preprint, identifier 2024.03.01.123456, published at doi:10.1038/s41586-0000; "
            "the preprint itself is at doi:10.1101/2024.03.01.123456."]
    rows = fmt.reference_entry_rows(both, [True])
    check("any 10.1101 DOI in the entry satisfies FMT-R4",
          not any(r["rule"] == "FMT-R4" for r in rows),
          str([r["evidence"] for r in rows]))
    foreign = ["A preprint, identifier 2024.03.01.123456, carrying doi:10.1038/s41586-0000."]
    check("a server code with only a foreign DOI is still reported",
          any(r["rule"] == "FMT-R4" for r in fmt.reference_entry_rows(foreign, [True])))


# ---------------------------------------------------------------------------
# The template writer's self-closing section
# ---------------------------------------------------------------------------
def test_self_closing_sectpr_with_attributes():
    print("\n== _apply_front_refs: self-closing <w:sectPr attrs/> ==")
    doc = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p>'
           '<w:sectPr w:rsidR="00AA1111" w:rsidSect="00BB2222"/></w:body></w:document>')
    out, applied = fmt._apply_front_refs(doc, {"header_default_rid": "rId9"})
    check("the writer applied the template furniture", applied is True)
    check("the header reference is INSIDE the section element",
          re.search(r"<w:sectPr[^>]*>(?:(?!</w:sectPr>)[\s\S])*<w:headerReference", out)
          is not None,
          out[-220:])
    check("no reference is emitted after the self-closing tag",
          "/><w:headerReference" not in out, out[-220:])


def test_nested_table_paragraphs_are_protected():
    print("\n== the stray-paragraph guard and a NESTED table ==")
    inner_cell = ('<w:tc><w:tbl><w:tr><w:tc>'
                  '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                  '<w:r><w:t>Inner heading</w:t></w:r></w:p>'
                  '</w:tc></w:tr></w:tbl></w:tc>')
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body>'
           '<w:tbl><w:tr>' + inner_cell + '<w:tc><w:p/></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    paras = fmt.paragraphs(xml)
    protected = fmt._table_paragraph_indices(xml, paras)
    check("every paragraph inside the outer table is protected",
          protected == set(range(len(paras))), f"{sorted(protected)} of {len(paras)}")
    groups, _prescribed = fmt.stray_empty_paragraph_groups(
        paras, {"max_empty_paragraph_run": 1}, xml)
    check("the following cell's only paragraph is never scheduled for deletion",
          [i for g, _k in groups for i in g] == [], str(groups))


# ---------------------------------------------------------------------------
# An encrypted / oddly-compressed .docx is unreadable, never a crash
# ---------------------------------------------------------------------------
def test_encrypted_docx_is_unreadable():
    print("\n== an encrypted or unsupported-compression .docx ==")
    enc = _flagged_docx(scratch("dbg_enc_") / "enc.docx", flag=0x0001)
    comp = _flagged_docx(scratch("dbg_comp_") / "comp99.docx", method=99)
    for name, path in (("encrypted", enc), ("unsupported compression", comp)):
        try:
            got = pp._docx_paragraphs(path)
            check(f"{name}: _docx_paragraphs returns None", got is None, repr(got)[:80])
        except Exception as exc:                                     # noqa: BLE001
            check(f"{name}: _docx_paragraphs returns None", False, f"{type(exc).__name__}: {exc}")
        try:
            got = fmt.validate_docx_parts(path)
            check(f"{name}: validate_docx_parts returns ok=False",
                  isinstance(got, dict) and got.get("ok") is False, str(got)[:120])
        except Exception as exc:                                     # noqa: BLE001
            check(f"{name}: validate_docx_parts returns ok=False", False,
                  f"{type(exc).__name__}: {exc}")
        try:
            got = pp._docx_paragraph_texts(path)
            check(f"{name}: _docx_paragraph_texts returns []", got == [], repr(got)[:80])
        except Exception as exc:                                     # noqa: BLE001
            check(f"{name}: _docx_paragraph_texts returns []", False,
                  f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# seed_concern_candidates splits at numbered / bulleted markers
# ---------------------------------------------------------------------------
def test_seed_concern_markers():
    print("\n== seed_concern_candidates markers ==")
    text = ("1. Comment about the abstract\n2. Comment about the figures\n"
            "- Item about references")
    rows = pp.seed_concern_candidates(text)
    check("numbered and bulleted lines each start a candidate row",
          len(rows) == 3, str([r["heading"] for r in rows]))
    heads = " | ".join(r["heading"] for r in rows)
    check("the bullet marker is kept in the heading", "- Item about references" in heads, heads)


# ---------------------------------------------------------------------------
# mcp_server_spec args with a ']' inside a quoted argument
# ---------------------------------------------------------------------------
def test_mcp_server_spec_args():
    print("\n== mcp_server_spec args ==")
    cfg = scratch("dbg_mcp_") / "config.toml"
    cfg.write_text('[mcp_servers.docx]\ncommand = "node"\n'
                   'args = ["--filter", "a]b", "server.js"]\n', encoding="utf-8")
    saved = pp.codex_config_path
    pp.codex_config_path = lambda: cfg
    try:
        spec = pp.mcp_server_spec("docx")
    finally:
        pp.codex_config_path = saved
    check("every argument survives a ']' inside a quoted arg",
          spec.get("args") == ["--filter", "a]b", "server.js"], str(spec))


# ---------------------------------------------------------------------------
# the resume record's argv marker and the discovery-missing message
# ---------------------------------------------------------------------------
def test_resume_and_message_shapes():
    print("\n== resume argv marker / missing-ids message ==")
    tmp = scratch("dbg_resume_")

    class _Ctx:
        root = tmp

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    long_rec = {"id": "r1_a1_revise", "kind": "revise", "round": 1, "sandbox": str(tmp)}
    pp.prepare_resume_session(_Ctx(), long_rec,
                              ["codex", "exec", "--cd", str(tmp), "finish the stage"],
                              "sess1", "the marker was missing")
    argv = long_rec["last_resume"]["argv"]
    check("a truncated resume command records the ellipsis marker",
          argv[-1] == "..." and len(argv) == 4, str(argv))
    short_rec = {"id": "r1_a1_revise", "kind": "revise", "round": 1, "sandbox": str(tmp)}
    pp.prepare_resume_session(_Ctx(), short_rec, ["codex", "exec"], "sess1", "no marker")
    check("a short resume command carries no spurious ellipsis",
          "..." not in short_rec["last_resume"]["argv"], str(short_rec["last_resume"]["argv"]))
    msgs = pp.discovery_ledger_reconciliation_problems(
        tmp / "DIFF_LEDGER.md", [f"X-{i:03d}" for i in range(1, 8)])
    check("a >6 missing-ids message closes its parenthesis",
          bool(msgs) and msgs[0].count("(") == msgs[0].count(")"), str(msgs)[:180])


# ---------------------------------------------------------------------------
# audit_artifact_problems: a non-object adds row is a problem, not a crash
# ---------------------------------------------------------------------------
def test_audit_artifact_problems_non_dict():
    print("\n== audit_artifact_problems non-object adds row ==")
    audit = {"dispositions": [], "adds": ["not-a-row"], "resolves": []}
    try:
        probs = pp.audit_artifact_problems(audit, [])
        check("a non-object adds row is reported", any("adds[0]" in p for p in probs), str(probs))
    except Exception as exc:                                         # noqa: BLE001
        check("a non-object adds row is reported", False, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# count_manual_steps tolerates a non-UTF-8 file
# ---------------------------------------------------------------------------
def test_count_manual_steps_encoding():
    print("\n== count_manual_steps encoding ==")
    p = scratch("dbg_manual_") / "MANUAL_STEPS.md"
    p.write_bytes("Résumé item\n- bullet\n".encode("latin-1"))
    try:
        n = pp.count_manual_steps(p)
        check("a non-UTF-8 MANUAL_STEPS.md still counts its bullets",
              isinstance(n, int) and n >= 1, repr(n))
    except Exception as exc:                                         # noqa: BLE001
        check("a non-UTF-8 MANUAL_STEPS.md still counts its bullets", False,
              f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# M30-NC: the negative claim's SUBJECT is not any nearby table token
# ---------------------------------------------------------------------------
def test_negative_claim_subject():
    print("\n== M30-NC subject attachment ==")
    table = ("query\ttool\tn_cells\n"
             "ACT\tSCYN\t1200\n"
             "ACT\tSCYN\t900\n"
             "Pilot\tSCYN\t150\n"
             "Pilot\tSCYN\t160\n")
    text = ("Samples from the pilot cohort were excluded before the SCYN caller was applied "
            "to the remaining cells.")
    rows = fmt.negative_claim_rows([text], [("fig3_source.csv", table)])
    check("a sentence about excluded SAMPLES produces no 'the tool was not run' row",
          rows == [], str([(r["token"], r["claim"][:60]) for r in rows]))
    chisel_table = ("plot\tdataset\ttool\tn_cells\n"
                    "ACT\tTN1 50bp\tginkgo\t1100\n"
                    "ACT\tTN1 50bp\tchisel\t1100\n"
                    "ACT\tTN2 50bp\tchisel\t1024\n"
                    "ACT\tTN2 50bp\tginkgo\t1024\n")
    control = ["CHISEL could not be run because the phased germline haplotypes are "
               "unavailable."]
    rows = fmt.negative_claim_rows(control, [("Fig3.tsv", chisel_table)])
    check("a real 'could not be run' claim about a tool is still reported",
          any(r["rule"] == "M30-NC" and r["token"] == "chisel" for r in rows),
          str([(r["token"], r["claim"][:60]) for r in rows]))


# ---------------------------------------------------------------------------
# The judge's discovery check accepts the skill's canonical clean closure
# ---------------------------------------------------------------------------
def test_judge_discovery_vocabulary():
    print("\n== judge_discovery_problems vocabulary ==")
    sb = scratch("dbg_judge_")
    dd = sb / "judge_review" / "discovery"
    dd.mkdir(parents=True)
    head = ("| # | candidate | disposition |\n|---|---|---|\n")
    rows = "".join(
        f"| {i} | check class {i} | no anomalies — checked: p{i} |\n" for i in range(1, 7))
    for side in ("target", "w1"):
        (dd / f"{side}.md").write_text(head + rows, encoding="utf-8")
    errs, warns = pp.judge_discovery_problems(sb, {"label_map": {"w1": 1}})
    check("the review skill's `no anomalies` closure is a disposition",
          not any("no disposition cell" in w for w in warns), str(warns)[:200])
    check("a fully spelled-out clean pass carries no errors", errs == [], str(errs)[:200])
    # A bare `clean` states no coverage at all: the review's own D3 check fails
    # a probe closed "no anomalies" with nothing named, so the judge pass must
    # at least warn.
    bare = "".join(f"| {i} | check class {i} | clean |\n" for i in range(1, 7))
    for side in ("target", "w1"):
        (dd / f"{side}.md").write_text(head + bare, encoding="utf-8")
    _errs, warns = pp.judge_discovery_problems(sb, {"label_map": {"w1": 1}})
    check("a `clean` row with no checked locations warns",
          any("without naming the checked locations" in w for w in warns), str(warns)[:200])


# ---------------------------------------------------------------------------
# containment.mjs: DOCX_MCP_ALLOWED_ROOTS=/ means "the whole filesystem"
# ---------------------------------------------------------------------------
def test_mcp_containment_root():
    print("\n== DOCX_MCP_ALLOWED_ROOTS=/ ==")
    node = shutil.which("node")
    if not node:
        skip("DOCX_MCP_ALLOWED_ROOTS=/ allows any path", "node is not installed")
        return
    js = ("import('./containment.mjs').then(m => {"
          "const roots = m.allowedRoots('/');"
          "console.log(JSON.stringify([m.containsPath('/home/x', roots),"
          "m.containsPath('/etc/passwd', roots)]));})")
    for server in ("mcp-docx-converter", "mcp-docx-compare"):
        proc = subprocess.run([node, "-e", js], cwd=str(WS / server),
                              capture_output=True, text=True)
        got = (proc.stdout or "").strip()
        check(f"{server}: a '/' root allows any absolute path",
              proc.returncode == 0 and got == "[true,true]", f"rc={proc.returncode} {got!r}")


# ---------------------------------------------------------------------------
# docxcompare.sh: a missing `realpath` is a diagnostic, not a bare exit
# ---------------------------------------------------------------------------
def test_docxcompare_realpath_guard():
    print("\n== docxcompare.sh realpath guard ==")
    tmp = scratch("dbg_cmp_")
    empty = tmp / "empty-path"
    empty.mkdir()
    a, b = tmp / "a.docx", tmp / "b.docx"
    a.write_bytes(b"PK\x03\x04")
    b.write_bytes(b"PK\x03\x04")
    bash = shutil.which("bash") or "/bin/bash"
    proc = subprocess.run([bash, str(WS / "docxcompare.sh"), str(a), str(b)],
                          env={"PATH": str(empty), "HOME": str(tmp)},
                          capture_output=True, text=True)
    check("a host without realpath gets a named error and exit 1",
          proc.returncode == 1 and "cannot resolve the path" in (proc.stderr or ""),
          f"rc={proc.returncode} stderr={proc.stderr.strip()[:120]!r}")


# ---------------------------------------------------------------------------
# FMT-AV1 "in the meantime" needs an availability context; the cover letter's
# bare `thank you` is the closing, an opener is not
# ---------------------------------------------------------------------------
def test_av_and_cover_letter():
    print("\n== FMT-AV1 context / cover-letter closing ==")
    rows = fmt.availability_rows(["The discussion continues in the meantime with the "
                                 "reviewers."], [False])
    check("an ordinary 'in the meantime' sentence is not an availability locator",
          rows == [], str([r["evidence"] for r in rows]))
    rows = fmt.availability_rows(["The data are available from the lead contact in the "
                                 "meantime."], [False])
    check("the availability 'in the meantime' locator is still reported",
          any(r["rule"] == "FMT-AV1" for r in rows), str(rows)[:160])
    tmp = scratch("dbg_cover_")
    letter = tmp / "cover_letter.md"
    body = " ".join(["persuade"] * 320)
    letter.write_text("Dear Editor,\n\nThank you for considering our manuscript.\n\n"
                      + body + "\n\nSincerely,\nJane Doe\n", encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                           str(letter), "--section", "cover-letter", "--json"],
                          capture_output=True, text=True)
    try:
        rows = [r for r in json.loads(proc.stdout).get("rows", [])
                if r["section"] == "cover letter"]
    except ValueError:
        rows = []
    check("a letter opening with 'Thank you for ...' still counts its persuading body",
          bool(rows) and rows[0]["words"] >= 320, f"rc={proc.returncode} {str(rows)[:160]}")


def test_numbers_and_nocite_sweeps():
    print("\n== extract_numbers p-values / extract_citations \\nocite{*} ==")
    numbers = _load("dbg_extract_numbers",
                    WS / "paper-skills/paper-review/scripts/extract_numbers.py")
    pv = dict(numbers.LABEL_PATTERNS)["p-value"]
    got = [(m.group(1), m.group(0)) for m in pv.finditer(
        "The effect was significant (p = .05); one cohort (p = 0.5) and an e-notation "
        "value (p = 1.2e-3).")]
    check("the leading-dot p-value is inventoried", (".05", "p = .05") in got, str(got))
    check("the zero-padded and e-notation p-values keep their exact value",
          ("0.5", "p = 0.5") in got and ("1.2e-3", "p = 1.2e-3") in got, str(got))
    tmp = scratch("dbg_nocite_")
    (tmp / "corpus").mkdir()
    (tmp / "corpus" / "paper.tex.txt").write_text(
        "\\documentclass{article}\n\\begin{document}\nSee the bibliography.\n\\nocite{*}\n"
        "\\begin{thebibliography}{9}\n\\bibitem{alpha} A. Author. Title one. 2020.\n"
        "\\bibitem{beta} B. Author. Title two. 2021.\n\\end{thebibliography}\n\\end{document}\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                           "--work", str(tmp), "--out", str(tmp / "out")],
                          capture_output=True, text=True)
    art = tmp / "out" / "artifacts" / "M2_citations.md"
    text = art.read_text(encoding="utf-8", errors="replace") if art.is_file() else ""
    check("a `\\nocite{*}` document has no listed-but-never-cited entry",
          "never cited by any \\cite: none" in text,
          f"rc={proc.returncode} " + " | ".join(
              ln for ln in text.splitlines() if "never cited" in ln)[:160])
    # The same corpus WITHOUT the whole-list directive still reports them.
    (tmp / "corpus" / "paper.tex.txt").write_text(
        "\\documentclass{article}\n\\begin{document}\nSee the bibliography.\n"
        "\\begin{thebibliography}{9}\n\\bibitem{alpha} A. Author. Title one. 2020.\n"
        "\\bibitem{beta} B. Author. Title two. 2021.\n\\end{thebibliography}\n\\end{document}\n",
        encoding="utf-8")
    subprocess.run([sys.executable,
                    str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                    "--work", str(tmp), "--out", str(tmp / "out2")],
                   capture_output=True, text=True)
    text = (tmp / "out2" / "artifacts" / "M2_citations.md").read_text(
        encoding="utf-8", errors="replace")
    check("without `\\nocite{*}` the uncited entries are still reported",
          "'alpha'" in text and "'beta'" in text, text[:120])


if __name__ == "__main__":
    try:
        test_display_order_ranges_and_years()
        test_reference_pins_and_dois()
        test_self_closing_sectpr_with_attributes()
        test_nested_table_paragraphs_are_protected()
        test_encrypted_docx_is_unreadable()
        test_seed_concern_markers()
        test_mcp_server_spec_args()
        test_resume_and_message_shapes()
        test_audit_artifact_problems_non_dict()
        test_count_manual_steps_encoding()
        test_negative_claim_subject()
        test_judge_discovery_vocabulary()
        test_mcp_containment_root()
        test_docxcompare_realpath_guard()
        test_av_and_cover_letter()
        test_numbers_and_nocite_sweeps()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
