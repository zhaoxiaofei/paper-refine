#!/usr/bin/env python3
"""Regression checks for the confirmed findings of the 2026-10-02 0331 audit.

Sources: `audit_data/2026-1002-0331-general-audit/` (the three read-only
reports). Every check below reproduces a defect that was confirmed against the
tree at a94235f (not merely reported by an audit), and each one fails before
its fix. The audit suggestions that could not be reproduced are NOT pinned
here; see the ledger in the hand-off report.

Run:  python3 .paper_test/test_general_audit_fixes_2026_1002b.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("paper_docx_format_audit_b", WS / "paper_docx_format.py")
nb = load("paper_pipeline_audit_b", WS / "paper_pipeline.py")


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
    for left in Path(tempfile.gettempdir()).glob("paper_tex_check_*"):
        shutil.rmtree(left, ignore_errors=True)


def test_spans_recovers_from_stray_close():
    """A hand-edited package with one unmatched close tag must not hide the rest."""
    xml = ('<w:body><w:p><w:r><w:t>ALPHA</w:t></w:r></w:p></w:p>'
           '<w:p><w:r><w:t>BRAVO</w:t></w:r></w:p></w:body>')
    texts = [fmt.text_of(p[2]) for p in fmt.paragraphs(xml)]
    check("a stray paragraph close does not drop every later paragraph",
          texts == ["ALPHA", "BRAVO"], str(texts))


def test_revision_mark_coverage():
    """FMT-S4 must see revision marks that are not run-level w:ins/w:del."""
    pol = fmt.load_policy(None)
    body = (
        '<w:p><w:pPr><w:pPrChange w:id="1" w:author="A" w:date="D"/></w:pPr>'
        '<w:r><w:t>a</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:rPrChange w:id="2"/></w:rPr><w:t>b</w:t></w:r></w:p>'
        '<w:tbl><w:tblPr><w:tblPrChange w:id="3"/></w:tblPr>'
        '<w:tr><w:trPr><w:trPrChange w:id="4"/></w:trPr>'
        '<w:tc><w:tcPr><w:cellDel w:id="5"/></w:tcPr>'
        '<w:p><w:r><w:t>c</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    res = fmt.analyse_document(f"<w:body>{body}</w:body>", {}, pol, "t.docx")
    rows = [r for r in res["rows"] if r["rule"] == "FMT-S4"]
    check("FMT-S4 flags table- and property-level revision marks",
          bool(rows) and "5" in str(rows[0].get("evidence")), str(rows[:1]))


def test_hanging_indent_not_first_line():
    hang = '<w:p><w:pPr><w:ind w:hanging="360"/></w:pPr><w:r><w:t>x</w:t></w:r></w:p>'
    first = ('<w:p><w:pPr><w:ind w:firstLine="360"/></w:pPr>'
             '<w:r><w:t>x</w:t></w:r></w:p>')
    got = fmt.paragraph_first_line_indent(hang)
    check("a hanging indent is not reported as a first-line indent", got == 0, str(got))
    got2 = fmt.paragraph_first_line_indent(first)
    check("a real first-line indent is still reported", got2 == 360, str(got2))


def test_validate_latex_scratch_cleanup():
    """A compile pass must not leak one full project copy per .tex file."""
    if fmt.latex_engine() is None:
        print("[skip] validate_latex scratch cleanup needs a TeX engine")
        return
    work = scratch("pr_tex_probe_")
    tex = work / "doc.tex"
    tex.write_text(r"\documentclass{article}\begin{document}Hi\end{document}",
                   encoding="utf-8")
    tmp_root = Path(tempfile.gettempdir())
    before = set(tmp_root.glob("paper_tex_check_*"))
    res = fmt.validate_latex(tex)
    leaked = set(tmp_root.glob("paper_tex_check_*")) - before
    check("validate_latex removes the scratch copy it created",
          not leaked and res.get("ok") is True,
          f"leaked={sorted(str(p) for p in leaked)} detail={res.get('detail')!r}")


def test_score_model_default_judges():
    text = str(nb.score_model_doc().get("scores_per_version"))
    check("the score model names the actual default (2 judges), not 3",
          "default 2 judges" in text and "default 3 judges" not in text, text[:160])


def test_cover_letter_total_cap_follows_profile():
    generic = nb.load_venue_profile("generic")
    nbt = nb.load_venue_profile("nature-biotechnology")
    standing = nb.standing_exemptions_text(generic)
    try:
        rule = nb.defect_class_rule(generic)
    except TypeError as e:                 # pre-fix signature: no profile argument
        rule = ""
        print(f"[note] defect_class_rule(profile) not available yet: {e}")
    check("a profile with no total-word cap never states the default venue's 650",
          "650" not in standing and "650" not in rule,
          str([ln.strip() for ln in standing.splitlines() if "650" in ln][:2]))
    try:
        nbt_rule = nb.defect_class_rule(nbt)
    except TypeError as e:
        nbt_rule = ""
        print(f"[note] defect_class_rule(profile) not available yet: {e}")
    nbt_standing = nb.standing_exemptions_text(nbt)
    check("Nature Biotechnology still states its 650-word cover-letter cap",
          "650" in nbt_rule and "650" in nbt_standing)
    check("the shared class rule keeps its pinned wording for the default venue",
          "keep its TOTAL content" in " ".join(nbt_rule.split())
          and "within 650 words" in " ".join(nbt_rule.split()))
    example = nb.load_venue_profile("example-journal")
    mandates = " ".join(" ".join(v.split()) for v in nb.m19_blocks(example).values())
    check("a profile with no cover-letter total cap is not told to hit 'the configured cap'",
          "the configured cap words" not in mandates
          and "within its words" not in mandates
          and "its configured cap words" not in mandates
          and "the user's configured preference" not in mandates)


def test_m19_cover_tail_article():
    frontiers = nb.load_venue_profile("frontiers-in-immunology")
    flat = " ".join(nb.m19_blocks(frontiers)["revise"].split())
    check("the M19 revise mandate uses the venue-appropriate indefinite article",
          "not a Front Immunol requirement" in flat and "not an Front Immunol" not in flat,
          flat[flat.find("not a"):flat.find("not a") + 60] if "not a" in flat else "missing")
    nbt = nb.load_venue_profile("nature-biotechnology")
    flat_nbt = " ".join(nb.m19_blocks(nbt)["revise"].split())
    check("Nature Biotechnology keeps its 'not an NBT requirement'",
          "not an NBT requirement" in flat_nbt)


def test_explicit_null_cover_letter_is_none():
    data = json.loads((WS / "venue_profiles/example-journal.json")
                      .read_text(encoding="utf-8"))
    default = data.get("default_article_type")
    for entry in data["article_types"]:
        if entry.get("id") == default:
            entry.setdefault("length_limits", {})["cover_letter"] = {
                "min": 300, "max": 500, "total_max": 650,
                "source": "default-type preference"}
    other = next(t for t in data["article_types"] if t.get("id") != default)
    other.setdefault("length_limits", {})["cover_letter"] = {
        "min": None, "max": None, "total_max": None,
        "source": "this type states no cover preference"}
    prof = nb.VenueProfile(copy.deepcopy(data), origin="fixture",
                           article_type_id=other["id"])
    lm = prof.length_limits()["cover letter"]
    check("an explicit null cover-letter preference is not replaced by the default type's",
          lm["min"] is None and lm["max"] is None and lm["total_max"] is None
          and lm["source"] == "this type states no cover preference", str(lm))
    omitted = copy.deepcopy(data)
    other2 = next(t for t in omitted["article_types"] if t.get("id") != default)
    other2["length_limits"].pop("cover_letter", None)
    lm2 = nb.VenueProfile(omitted, origin="fixture",
                          article_type_id=other2["id"]).length_limits()["cover letter"]
    check("a type that states no cover_letter at all still inherits the default preference",
          lm2["min"] == 300 and lm2["max"] == 500 and lm2["total_max"] == 650, str(lm2))


def test_skill_docs_cover_letter_invocation():
    for rel in ("paper-skills/paper-review/references/sweeps.md",
                "paper-skills/prompts/identify_issues.prompt.md"):
        text = (WS / rel).read_text(encoding="utf-8")
        check(f"{rel} does not document a nonexistent --cover-letter flag",
              "--cover-letter" not in text)
    letter = scratch("pr_letter_probe_") / "cover_letter.txt"
    letter.write_text("Dear Editor,\n\nWe submit our work.\n\nSincerely,\nA. Author\n",
                      encoding="utf-8")
    script = str(WS / "paper-skills/paper-review/scripts/count_words.py")
    right = subprocess.run([sys.executable, script, str(letter),
                            "--section", "cover-letter"],
                           capture_output=True, text=True, timeout=120)
    check("count_words.py accepts the documented --section cover-letter",
          right.returncode == 0, right.stdout[-160:] + right.stderr[-120:])
    wrong = subprocess.run([sys.executable, script, str(letter), "--cover-letter"],
                           capture_output=True, text=True, timeout=120)
    check("count_words.py rejects the old --cover-letter flag the docs named",
          wrong.returncode != 0)


def test_nested_dir_symlink_in_manifest():
    tmp = scratch("pr_symlink_probe_")
    canon = tmp / "canonical"
    canon.mkdir()
    (canon / "notes.txt").write_text("note", encoding="utf-8")
    external = tmp / "external"
    external.mkdir()
    (external / "measure.csv").write_text("m", encoding="utf-8")
    os.symlink(external, canon / "linked_dir")
    sandbox = tmp / "sandbox"
    sandbox.mkdir()
    os.symlink(canon, sandbox / "raw_data")
    want = {f"raw_data/{k}"
            for k in nb.hash_manifest(canon, follow_dir_links=True)["files"]}
    got = set(nb.hash_manifest(sandbox, follow_dir_links=True)["files"])
    check("the manifest follows a directory symlink nested inside the evidence link",
          want == got, f"missing={sorted(want - got)} extra={sorted(got - want)}")


def test_decide_respects_root_lock():
    """decide writes reports/decision.json, so it must take the root lock."""
    root = scratch("pr_decide_lock_probe_")
    (root / "pipeline_config.json").write_text(
        json.dumps({"rounds": 3, "venue": "nature-biotechnology"}), encoding="utf-8")
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (root / nb.LOCK_FILE).write_text(json.dumps(
            {"pid": holder.pid, "what": "run", "since": "2026-10-02T00:00:00Z",
             "root": str(root)}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(WS / "paper_pipeline.py"), "decide", "--root", str(root)],
            capture_output=True, text=True, timeout=120)
        out = proc.stdout + proc.stderr
        check("decide refuses to run while a live process holds the root lock",
              proc.returncode != 0
              and "another pipeline process is already working on this root" in out,
              f"rc={proc.returncode} out={out[-200:]!r}")
    finally:
        holder.terminate()
        holder.wait(timeout=15)


def main() -> int:
    try:
        test_spans_recovers_from_stray_close()
        test_revision_mark_coverage()
        test_hanging_indent_not_first_line()
        test_validate_latex_scratch_cleanup()
        test_score_model_default_judges()
        test_cover_letter_total_cap_follows_profile()
        test_m19_cover_tail_article()
        test_explicit_null_cover_letter_is_none()
        test_skill_docs_cover_letter_invocation()
        test_nested_dir_symlink_in_manifest()
        test_decide_respects_root_lock()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} 2026-10-02b CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL 2026-10-02b GENERAL-AUDIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
