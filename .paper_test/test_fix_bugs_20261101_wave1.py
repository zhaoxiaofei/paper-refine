#!/usr/bin/env python3
"""Regression checks for the 2026-11-01 13:30 fix-bugs wave (F02..F79).

Run:  python3 .paper_test/test_fix_bugs_20261101_wave1.py

Every Fxx is a candidate the verify-findings stage kept as a TRUE_POSITIVE and
this wave re-confirmed on the local tree.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp  # noqa: E402

TMPDIRS: list[Path] = []
FAILS: list[str] = []


def scratch(prefix: str) -> Path:
    # Honour the per-suite TMPDIR run_one.sh sets; `WS/tmp` is ignored and does
    # not exist in a fresh checkout, so naming it made the suite non-hermetic.
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def mk(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text)
    return root


def pair(name: str, base_files: dict, cand_files: dict):
    tmp = scratch(f"fbw1_{name}_")
    return mk(tmp / "base", base_files), mk(tmp / "cand", cand_files)


class Ctx:
    def __init__(self, **cfg):
        self.cfg = dict(cfg)
        self.root = None


LONG = "The treatment was effective in the first cohort of patients.\n"


def main() -> int:
    # F05 -- numeric zero is the documented OFF value.
    c = Ctx(insertions=0)
    check("F05 insertions:0 is OFF", pp.insertions_enabled(c) is False)
    c = Ctx(insertions=0.0)
    check("F05 insertions:0.0 is OFF", pp.insertions_enabled(c) is False)
    c = Ctx(insertions=1)
    check("F05 insertions:1 is ON", pp.insertions_enabled(c) is True)
    c = Ctx(deletions=0)
    check("F05 deletions:0 is OFF", pp.deletions_enabled(c) is False)

    # F02 -- a sandbox keeps the policy its prompt states.
    tmp = scratch("fbw1_f02_")
    default_prompt = tmp / "PROMPT.md"
    default_prompt.write_text("default prompt with no policy block\n")
    check("F02 default prompt stays default under a strict invocation",
          pp.content_edit_policy_for_sandbox(Ctx(insertions=False), None,
                                             default_prompt) == (True, True))
    strict_rec = {"content_edit_policy": {"insertions": False, "deletions": True}}
    check("F02 recorded strict policy survives a permissive invocation",
          pp.content_edit_policy_for_sandbox(Ctx(), strict_rec,
                                             tmp / "missing") == (False, True))
    check("F02 an explicit default record is honoured by the postcheck",
          pp.content_edit_policy_allowed(Ctx(insertions=False), {
              "content_edit_policy": {"insertions": True, "deletions": True}}
          ) == (True, True))

    # F16 -- a marker required by author_to_complete:document is allowed.
    b, cnd = pair("f16", {"paper.md": LONG},
                  {"paper.md": LONG + "\n[AUTHOR TO COMPLETE: state the method]\n"})
    check("F16 document-mode marker is not an insertion",
          pp.content_edit_problems(Ctx(author_to_complete="document"), b, cnd, "x",
                                   insertions_allowed=False,
                                   deletions_allowed=True) == [])
    check("F16 readme-mode marker is still an insertion",
          bool(pp.content_edit_problems(Ctx(author_to_complete="readme"), b, cnd, "x",
                                        insertions_allowed=False,
                                        deletions_allowed=True)))

    # F17 -- the readme/off marker cleanup is not a deletion.
    b, cnd = pair("f17",
                  {"paper.md": "The dose was 10 mg per day.\n\n"
                               "[AUTHOR TO COMPLETE: state the method]\n"},
                  {"paper.md": "The dose was 10 mg per day.\n"})
    check("F17 readme-mode marker removal is exempt",
          pp.content_edit_problems(Ctx(author_to_complete="readme"), b, cnd, "x",
                                   insertions_allowed=True,
                                   deletions_allowed=False) == [])
    check("F17 document-mode marker removal is still a deletion",
          bool(pp.content_edit_problems(Ctx(author_to_complete="document"), b, cnd, "x",
                                        insertions_allowed=True,
                                        deletions_allowed=False)))

    # F18 -- the documented mechanical scope is the prose sentence; the broader
    # unit classes are policy guidance, not a claimed mechanical coverage.
    readme = (WS / "README.md").read_text()
    check("F18 README states the sentence-level mechanical scope",
          "mechanical comparison is sentence-level" in readme)

    # F19 -- short claims are content units.
    b, cnd = pair("f19a", {"paper.md": "This is false. " + LONG},
                  {"paper.md": LONG})
    check("F19 short sentence deletion is detected",
          bool(pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                        deletions_allowed=False)))
    b, cnd = pair("f19b", {"paper.md": LONG},
                  {"paper.md": LONG + " Short note.\n"})
    check("F19 short sentence insertion is detected",
          bool(pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=False,
                                        deletions_allowed=True)))

    # F20 -- a heading at the start of a block must not hide its prose.
    for label, ext, heading, prose in (
            ("markdown", ".md", "# Methods",
             "We used the standard assay for every sample in the study."),
            ("latex", ".tex", "\\section{Methods}",
             "We used the standard assay for all samples in the study.")):
        b, cnd = pair("f20_" + label,
                      {"paper" + ext: heading + "\n" + prose + "\n"},
                      {"paper" + ext: heading + "\n"})
        check(f"F20 {label} heading does not hide the prose",
              bool(pp.content_edit_problems(None, b, cnd, "x",
                                            insertions_allowed=True,
                                            deletions_allowed=False)))

    # F26 -- an added citation key is an insertion.
    b, cnd = pair("f26",
                  {"paper.tex": "The assay was done as described.\\cite{smith2020} "
                                "We measured all samples carefully.\n",
                   "refs.bib": "@article{smith2020, title={A}}"},
                  {"paper.tex": "The assay was done as described."
                                "\\cite{smith2020,jones2021} We measured all samples "
                                "carefully.\n",
                   "refs.bib": "@article{smith2020, title={A}}\n"
                               "@article{jones2021, title={B}}"})
    problems = pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=False,
                                        deletions_allowed=True)
    check("F26 a new citation key is an insertion",
          any("jones2021" in p and "citation" in p for p in problems))

    # F28 -- hidden DOCX text is not present text.
    try:
        from docx import Document
    except ImportError:
        Document = None
    if Document is not None:
        tmp = scratch("fbw1_f28_")
        b, cnd = tmp / "base", tmp / "cand"
        b.mkdir()
        cnd.mkdir()

        def make_docx(path: Path, hidden: bool) -> None:
            d = Document()
            p = d.add_paragraph()
            r = p.add_run("The treatment was effective in the first cohort of patients.")
            r.font.hidden = hidden
            d.save(path)

        make_docx(b / "paper.docx", False)
        make_docx(cnd / "paper.docx", True)
        check("F28 hidden DOCX text is counted as a deletion",
              bool(pp.content_edit_problems(None, b, cnd, "x",
                                            insertions_allowed=True,
                                            deletions_allowed=False)))
    else:
        check("F28 python-docx unavailable (skipped)", True)

    # R01 -- hiding the paragraph MARK does not hide the paragraph's run text.
    if Document is not None:
        from docx.oxml.ns import qn

        tmp = scratch("fbw1_r01_")
        b, cnd = tmp / "base", tmp / "cand"
        b.mkdir()
        cnd.mkdir()
        d = Document()
        p = d.add_paragraph("The treatment was effective in the first cohort of patients.")
        ppr = p._p.get_or_add_pPr()
        rpr = ppr.makeelement(qn("w:rPr"), {})
        ppr.append(rpr)
        rpr.append(rpr.makeelement(qn("w:vanish"), {}))
        d.save(b / "paper.docx")
        Document().save(cnd / "paper.docx")
        check("R01 a hidden paragraph mark keeps its visible text a content unit",
              any("treatment was effective" in u["text"]
                  for u in pp._content_unit_sentences(b)))
        check("R01 deleting the visible text behind a hidden mark is a deletion",
              bool(pp.content_edit_problems(None, b, cnd, "x",
                                            insertions_allowed=True,
                                            deletions_allowed=False)))
    else:
        check("R01 python-docx unavailable (skipped)", True)

    # F29 -- an abbreviation is not a sentence boundary.
    b, cnd = pair("f29",
                  {"paper.md": "The method of Smith et al. was used for all assays "
                               "in this study.\n"},
                  {"paper.md": "The method of Smith and colleagues was used for all "
                               "assays in this study.\n"})
    check("F29 'et al.' does not create a fake missing unit",
          pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                   deletions_allowed=False) == [])

    # F30 -- closing quote / citation marker still ends the sentence.
    b, cnd = pair("f30a",
                  {"paper.md": 'He said "the result is significant." The next '
                               "sentence is here in this paragraph.\n"},
                  {"paper.md": 'He said "the result is significant."\n'})
    check("F30 a sentence after a closing quote is seen",
          bool(pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                        deletions_allowed=False)))
    b, cnd = pair("f30b",
                  {"paper.md": "The result was significant.[1] The second claim "
                               "must survive in the paper.\n"},
                  {"paper.md": "The result was significant.[1]\n"})
    check("F30 a sentence after a citation marker is seen",
          bool(pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                        deletions_allowed=False)))

    # F32 -- a Markdown bullet reference list is not manuscript prose.
    b, cnd = pair("f32",
                  {"paper.md": "Results were strong in all groups.\n\n"
                               "- Smith J, Jones K. A prior study of the treatment. "
                               "Journal of Tests 2020.\n"
                               "- Doe A, Roe B. Another prior study of the treatment. "
                               "Journal of Tests 2021.\n"},
                  {"paper.md": "Results were strong in all groups.\n\n"
                               "- Smith J, Jones K. A prior study of the treatment. "
                               "Journal of Tests 2020.\n"})
    check("F32 a bullet reference deletion is not a content deletion",
          pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                   deletions_allowed=False) == [])

    # R02 -- a comment/front-matter/reference marker line must not hide the
    # prose that follows it in the same blank-line block.
    r02_prose = "We used the standard assay for every sample in the study.\n"
    for label, base_text, cand_text in (
            ("latex comment", "% check this line\n" + r02_prose,
             "% check this line\n"),
            ("html comment", "<!-- check this line -->\n" + r02_prose,
             "<!-- check this line -->\n"),
            ("yaml front matter", "---\ntitle: X\n---\n" + r02_prose,
             "---\ntitle: X\n---\n"),
            ("bullet reference", "- Smith J, Jones K. A prior study.\n" + r02_prose,
             "- Smith J, Jones K. A prior study.\n")):
        b, cnd = pair("r02_" + label.replace(" ", "_"),
                      {"paper.md": base_text}, {"paper.md": cand_text})
        check(f"R02 {label} does not hide the prose after it",
              any("standard assay" in u["text"]
                  for u in pp._content_unit_sentences(b)))
        check(f"R02 {label} deleting that prose is a deletion",
              bool(pp.content_edit_problems(None, b, cnd, "x",
                                            insertions_allowed=True,
                                            deletions_allowed=False)))
        empty = scratch("fbw1_r02_audit_")
        empty.mkdir(exist_ok=True)
        rows = pp.deletion_audit_rows(b, empty)
        check(f"R02 {label} is a revision-audit deletion seed",
              any("standard assay" in r["paragraph"] for r in rows))

    # R03 -- scratch() must not depend on the repo's ignored tmp/ directory.
    check("R03 scratch() is not tied to the repo tmp/ directory",
          ('WS / ' + '"tmp"') not in Path(__file__).read_text())

    # F33 -- a global exact pass keeps a short exact copy from being stolen.
    b, cnd = pair("f33",
                  {"paper.md": "The treatment was effective in the first cohort of "
                               "patients. The treatment was effective in the first "
                               "cohort.\n"},
                  {"paper.md": "Patients in the initial group responded well to "
                               "therapy. The treatment was effective in the first "
                               "cohort.\n"})
    problems = pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                        deletions_allowed=False)
    check("F33 the exact short sentence is not reported missing",
          not any("the first cohort.'" in p for p in problems))

    # F36 -- an unscannable file is reported, not silently ignored.
    b, cnd = pair("f36", {"paper.docx": b"not a zip"},
                  {"paper.docx": b"not a zip"})
    problems = pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                        deletions_allowed=False)
    check("F36 a corrupt DOCX is reported as unscannable",
          any("could not be scanned" in p for p in problems))

    # F40 -- merging two PKG-2 reports keeps the first pass's removal.
    tmp = scratch("fbw1_f40_")
    b, cnd = mk(tmp / "base", {"paper.md": "# Title\n\nWe ran the analysis with "
                                            "code/analysis.py.\n\nThe result was "
                                            "significant.\n"}), mk(tmp / "cand", {})
    shutil.copyfile(b / "paper.md", cnd / "paper.md")
    s1 = pp.strip_dangling_references_in_dir(cnd, ["code"], "x")
    s2 = pp.strip_dangling_references_in_dir(cnd, ["code"], "x")
    merged = pp.merge_reference_strips(s1, s2)
    check("F40 the second scan keeps the first removal",
          merged.get("removed") == 1
          and pp.pipeline_removed_sentences({"reference_strip": merged},
                                            with_document=True))

    # F41 -- the revision-audit seed excludes the pipeline's own removal.
    rows = pp.deletion_audit_rows(
        b, cnd,
        exempt_removed=pp.pipeline_removed_sentences(
            {"reference_strip": merged}, with_document=True))
    check("F41 the PKG-2 removal is not an audit row", rows == [])

    # F42 -- a file restored after the strip is re-stripped.
    tmp = scratch("fbw1_f42_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "paper.md").write_text("# Title\n\nWe ran the analysis with "
                                  "code/analysis.py.\n\nThe result was significant.\n")
    rec = {"id": "x", "backfill": {"restored": ["paper.md"]},
           "reference_strip": {"files": [], "removed": 0}}
    pp.restrip_after_backfill(Ctx(), rec, pkg)
    check("F42 a backfilled file is re-stripped",
          rec["reference_strip"].get("removed") == 1)

    # F45/F46/F47 -- the policy block states its precedence over structural
    # mandates (language pass, rewrite transitions, integration ports).
    block = pp.content_edit_policy_block(False, False)
    check("F45/F46/F47 policy precedence is stated",
          "PRECEDENCE:" in block and "language pass" in block
          and "integration port" in block)

    # F48 -- the revision-audit prompt carries the same policy as the repair.
    tmp = scratch("fbw1_f48_")
    prompt = pp.revision_audit_prompt(tmp, "r1_revision_audit", 1,
                                      insertions_allowed=False,
                                      deletions_allowed=True)
    check("F48 revision-audit prompt carries the content policy",
          "=== CONTENT-EDIT POLICY" in prompt and "NO INSERTIONS:" in prompt
          and "NO DELETIONS:" not in prompt)

    # F56 -- a declared not-submitted file is not a content unit.
    b, cnd = pair("f56",
                  {"README.md": "Only `paper*.md` will be submitted.\n",
                   "paper.md": LONG,
                   "notes.md": "A long note sentence that should not count here.\n"},
                  {"README.md": "Only `paper*.md` will be submitted.\n",
                   "paper.md": LONG})
    check("F56 a declared not-submitted file is ignored",
          pp.content_edit_problems(None, b, cnd, "x", insertions_allowed=True,
                                   deletions_allowed=False) == [])

    # F79 -- an exemption is keyed to the document it was removed from.
    b, cnd = pair("f79", {"a.md": LONG, "b.md": LONG},
                  {"a.md": "", "b.md": ""})
    problems = pp.content_edit_problems(
        None, b, cnd, "x", insertions_allowed=True, deletions_allowed=False,
        exempt_removed=[("a.md",
                         "The treatment was effective in the first cohort of patients.")])
    check("F79 a one-file exemption does not hide the other file",
          any("b.md" in p for p in problems) and not any("a.md" in p for p in problems))

    # F59 / F60 -- documentation states the real defaults / contract.
    prelude = (WS / "paper_pipeline_parts" / "p00_prelude.py").read_text()
    check("F59 prelude comment states the real default plan",
          "[2, 0, 0]" in prelude and "[1, 1, 1]" in prelude
          and "default to [2, 1]" not in prelude)
    loader = (WS / "paper_pipeline.py").read_text()
    check("F60 loader contract says M25-M36",
          "M25-M36" in loader and "the M25-M30 artifacts" not in loader)

    # F61 -- --help prints usage and creates no file.
    tmp = scratch("fbw1_f61_")
    r = subprocess.run([sys.executable, str(WS / "scripts" / "env_test_closure.py"),
                        "--help"], cwd=tmp, capture_output=True, text=True)
    check("F61 --help exits 0 and writes no file",
          r.returncode == 0 and "--help" not in [p.name for p in tmp.iterdir()]
          and "out-file" in r.stdout)

    # F66 -- a structural file over the byte budget is skipped, not read.
    tmp = scratch("fbw1_f66_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    with open(pkg / "data.json", "wb") as f:
        f.truncate(70 * 1024 * 1024)
    report = pp.strip_dangling_references_in_dir(pkg, ["code"], "x")
    check("F66 an oversized structural file is skipped",
          report.get("skipped") == 1)

    # F68 -- comparing the staged tool never unbounded-reads the sandbox copy.
    tmp = scratch("fbw1_f68_")
    sb = tmp / "sb"
    sb.mkdir()
    dst = sb / "paper_docx_format.py"
    dst.write_text("agent-planted content\n" * 1000)
    original = Path.read_bytes

    def guard(self):
        if self.resolve() == dst.resolve():
            raise AssertionError("unbounded read of an agent-writable file")
        return original(self)

    Path.read_bytes = guard
    try:
        pp._copy_session_tools(sb)
        copied = True
    except Exception:                                                 # noqa: BLE001
        copied = False
    finally:
        Path.read_bytes = original
    check("F68 session-tool copy avoids the unbounded comparison", copied)

    # F73 -- an invalid tunnel value fails instead of starting ssh.
    import paper_qwen_agent as q  # noqa: E402
    old_probe = q.probe_endpoint
    q.probe_endpoint = lambda cfg: (False, [], "unreachable")
    try:
        err = q.ensure_tunnel({"tunnel": "banana", "base_url": "http://x",
                               "local_port": "1", "ssh_port": "22", "remote": "r",
                               "ssh_host": "h"})
    finally:
        q.probe_endpoint = old_probe
    check("F73 an invalid tunnel value is rejected",
          "invalid PAPER_QWEN_TUNNEL" in err)

    # F76 -- --recreate checks existence, not just a working Python.
    script = (WS / "scripts" / "create-test-env.sh").read_text()
    check("F76 --recreate removes an existing-but-broken environment",
          "env_registered" in script and "env_exists || env_registered" in script)

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL FIX-BUGS 2026-11-01 WAVE-1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
