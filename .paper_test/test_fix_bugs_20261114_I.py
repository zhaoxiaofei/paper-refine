#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs group I utility fixes.

F86  lenient JSON recovery refuses a nested fragment of a truncated document
F87  the copy fallback of ensure_pristine_input converges on the second call
F88  an unreadable document is reported, not raised, by document_set_check
F89  the template/guideline prompt names every nested .docx the postcheck wants
F90  corpus_dir_manifest and manifest_for_sources agree on one corpus identity
F91  hold_internal_readme_notes never moves a file out of an EVIDENCE area
F92  an unreadable header/footer part is reported as an unverified gap
F93  TimestampedStream.write returns len(text), not the injected prefix
F94  a NUL-prefixed sentinel-looking string survives a write_json/read_json trip
F95  hash_manifest records an unreadable directory instead of silently dropping it

Self-contained and fast: every fixture is built under tempfile.mkdtemp().
Run:  python3 .paper_test/test_fix_bugs_20261114_I.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_fixbugs_i", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_fixbugs_i"] = nb
spec.loader.exec_module(nb)

FAILS: list = []
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def _docx(path: Path, document_xml: str, parts: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document_xml)
        for name, body in (parts or {}).items():
            z.writestr(name, body)


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


# ---------------------------------------------------------------- F86
def test_f86(tmp: Path) -> None:
    print("\n== F86: a truncated document is not its first complete child ==")
    check("F86 malformed array with a trailing comma is refused",
          nb._json_from_text('[{"a":1},]', True) is None)
    check("F86 truncated array is refused",
          nb._json_from_text('[{"a":1}', True) is None)
    check("F86 truncated array with several complete children is refused",
          nb._json_from_text('[{"a":1}, {"b":2}', True) is None)
    check("F86 a truncated fenced array is refused",
          nb._json_from_text('```json\n[{"a":1}', True) is None)
    check("F86 a nested fragment of a truncated array via read_json is None",
          _write_and_read(tmp / "trunc.json", '[{"a":1}') is None)
    check("F86 an unmatched brace in prose still yields the later document",
          nb._json_from_text('prose { unclosed then {"a":1}', True) == {"a": 1})
    check("F86 prose before a later complete document is still recovered",
          nb._json_from_text('{"x": 0}\nprose { oops\n{"a": 1}\n', True) == {"a": 1})
    check("F86 a fenced document is still recovered",
          nb._json_from_text('```json\n{"a": 1}\n```', True) == {"a": 1})


def _write_and_read(path: Path, text: str):
    path.write_text(text, encoding="utf-8")
    return nb.read_json(path, revive=False, lenient=True)


# ---------------------------------------------------------------- F87
def test_f87(tmp: Path) -> None:
    print("\n== F87: the no-symlink copy fallback is idempotent ==")
    root = tmp / "root"
    pristine = root / nb.pristine_dirname(root)
    (pristine / "docs").mkdir(parents=True)
    (pristine / "docs" / "a.txt").write_text("a", encoding="utf-8")
    (pristine / "raw_data").mkdir()
    (pristine / "raw_data" / "x.csv").write_text("1,2\n", encoding="utf-8")
    ctx = nb.Ctx(root)
    real = nb._try_symlink_dir
    nb._try_symlink_dir = lambda target, link: False
    try:
        sb = tmp / "sb_copy"
        first = nb.ensure_pristine_input(ctx, sb)
        second = nb.ensure_pristine_input(ctx, sb)
    finally:
        nb._try_symlink_dir = real
    check("F87 the first call copies the evidence areas",
          first["rebuilt"] is True and first["copied"] == ["raw_data"]
          and not (sb / "raw_data").is_symlink(), str(first))
    check("F87 the second call does NOT rebuild the whole input",
          second["rebuilt"] is False, str(second))
    check("F87 the copied evidence is complete",
          (sb / "raw_data" / "x.csv").read_text(encoding="utf-8") == "1,2\n")


# ---------------------------------------------------------------- F88
def test_f88(tmp: Path) -> None:
    print("\n== F88: an unreadable document does not crash document_set_check ==")
    base, cand = tmp / "f88" / "base", tmp / "f88" / "cand"
    base.mkdir(parents=True)
    cand.mkdir(parents=True)
    (base / "main.docx").write_bytes(b"x")
    (cand / "main.docx").write_bytes(b"x")
    os.chmod(base / "main.docx", 0)
    try:
        try:
            res = nb.document_set_check([(base, "", ())], [(cand, "", ())])
            raised = ""
        except OSError as exc:                                         # noqa: BLE001
            res, raised = {}, f"{type(exc).__name__}: {exc}"
    finally:
        os.chmod(base / "main.docx", stat.S_IRUSR | stat.S_IWUSR)
    if IS_ROOT:
        check("F88 (root: chmod-000 is still readable; check skipped)", True)
        return
    check("F88 no PermissionError escapes", not raised, raised)
    check("F88 the unreadable document is still counted",
          res.get("base_count") == 1 and res.get("candidate_count") == 1, str(res))


# ---------------------------------------------------------------- F89
def test_f89(tmp: Path) -> None:
    print("\n== F89: the prompt names every nested .docx the postcheck wants ==")
    src = tmp / "f89" / "source"
    (src / "supp").mkdir(parents=True)
    (src / "main.docx").write_bytes(b"x")
    (src / "supp" / "supp.docx").write_bytes(b"y")
    (src / "work").mkdir()
    (src / "work" / "scratch.docx").write_bytes(b"w")
    (src / "raw_data").mkdir()
    (src / "raw_data" / "evidence.docx").write_bytes(b"e")
    names = nb._prompt_docx_names(src)
    check("F89 the nested supplementary document is in the prompt's set",
          "supp/supp.docx" in names, str(names))
    check("F89 the package document is in the set", "main.docx" in names, str(names))
    check("F89 work scratch and evidence documents are left out",
          "work/scratch.docx" not in names and "raw_data/evidence.docx" not in names,
          str(names))
    check("F89 the prompt's set is exactly the package documents",
          names == ["main.docx", "supp/supp.docx"], str(names))
    ctx = nb.Ctx(tmp / "f89")
    ctx.cfg = {}
    prompt = nb.apply_guideline_conform_prompt(ctx, src)
    check("F89 the rendered prompt carries the nested document",
          "supp/supp.docx" in prompt and "raw_data/evidence.docx" not in prompt)


# ---------------------------------------------------------------- F90
def test_f90(tmp: Path) -> None:
    print("\n== F90: an inert <area>.disabled tree is not corpus identity ==")
    corpus = tmp / "f90" / "corpus"
    (corpus / "docs").mkdir(parents=True)
    (corpus / "docs" / "a.txt").write_text("a", encoding="utf-8")
    (corpus / "raw_data.disabled").mkdir()
    (corpus / "raw_data.disabled" / "x.csv").write_text("x", encoding="utf-8")
    cdm = nb.corpus_dir_manifest(corpus)
    mfs = nb.manifest_for_sources([(corpus, "", ())])
    check("F90 corpus_dir_manifest drops the disabled area",
          sorted(cdm.get("files") or {}) == ["docs/a.txt"], str(cdm.get("files")))
    check("F90 the two corpus identities are equal",
          nb.manifest_digest(cdm) == nb.manifest_digest(mfs))
    dst = tmp / "f90" / "copy"
    nb.copy_into(corpus, dst)
    check("F90 dir_matches accepts the copy against corpus_dir_manifest",
          nb.dir_matches(dst, cdm.get("files") or {}))


# ---------------------------------------------------------------- F91
def test_f91(tmp: Path) -> None:
    print("\n== F91: a README inside EVIDENCE is never moved out ==")
    pkg = tmp / "f91" / "pkg"
    ev = pkg / "raw_data"
    ev.mkdir(parents=True)
    (ev / "README.md").write_text(
        "Data notes\n- see MANUAL_STEPS.md for the rerun\n", encoding="utf-8")
    root_readme = pkg / "README.md"
    root_readme.write_text(
        "Package notes\n- see MANUAL_STEPS.md for the rerun\n", encoding="utf-8")
    held = tmp / "f91" / "held"
    records = nb.hold_internal_readme_notes(pkg, held)
    check("F91 the evidence README is left byte-identical",
          (ev / "README.md").is_file()
          and "MANUAL_STEPS.md" in (ev / "README.md").read_text(encoding="utf-8"),
          str(records))
    check("F91 package-level internal notes are still held back",
          not root_readme.exists()
          and any(r["file"] == "README.md" for r in records), str(records))


# ---------------------------------------------------------------- F92
def test_f92(tmp: Path) -> None:
    print("\n== F92: an unreadable header part is an unverified gap ==")
    d = tmp / "f92"
    tpl = d / "tpl.docx"
    out = d / "out.docx"
    section = ('<w:document %s><w:body><w:sectPr>'
               '<w:headerReference w:type="default" r:id="rId1"/>'
               '</w:sectPr></w:body></w:document>' % W)
    _docx(tpl, section, {"word/header1.xml":
                         '<!DOCTYPE x [<!ENTITY a "b">]><w:hdr %s>ACME</w:hdr>' % W})
    _docx(out, section, {"word/header1.xml": "<w:hdr %s></w:hdr>" % W})
    want, got = nb._docx_hf_signature(tpl), nb._docx_hf_signature(out)
    check("F92 the refused part is marked unreadable, not 'no furniture'",
          want.get("unreadable") is True, str(want))
    check("F92 the conformance gap is reported, not skipped",
          bool(nb._hf_gap(want, got)), str(nb._hf_gap(want, got)))
    plain = d / "plain.docx"
    _docx(plain, section, {"word/header1.xml": "<w:hdr %s></w:hdr>" % W})
    check("F92 a readable document with matching furniture is still gap-free",
          nb._hf_gap(nb._docx_hf_signature(plain), nb._docx_hf_signature(out)) == {})


# ---------------------------------------------------------------- F93
def test_f93() -> None:
    print("\n== F93: TimestampedStream.write obeys the TextIOBase contract ==")
    raw = _Capture()
    ts = nb.TimestampedStream(raw)
    check("F93 a one-line write returns the input length", ts.write("hi\n") == 3,
          str(ts.write("hi\n")))
    check("F93 the timestamp is still injected",
          "hi\n" in raw.text and raw.text != "hi\n", repr(raw.text))
    n = ts.write("two\nthree\n")
    check("F93 a multi-line write returns the input length", n == len("two\nthree\n"),
          str(n))
    check("F93 both lines are stamped",
          raw.text.count(" ") >= 3 and "three\n" in raw.text, repr(raw.text))


class _Capture:
    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text
        return len(text)

    def flush(self):
        pass


# ---------------------------------------------------------------- F94
def test_f94(tmp: Path) -> None:
    print("\n== F94: NUL-prefixed sentinel-looking strings round-trip ==")
    p = tmp / "f94.json"
    payload = {"s": "\u0000NaN", "t": "NaN", "nul": "\u0000plain",
               "n": float("nan"), "i": float("inf")}
    nb.write_json_atomic(p, payload)
    got = nb.read_json(p)
    check("F94 the literal '\\x00NaN' string survives byte-for-byte",
          got.get("s") == "\u0000NaN" and isinstance(got.get("s"), str), repr(got))
    check("F94 a plain 'NaN' string stays a string", got.get("t") == "NaN", repr(got))
    check("F94 another NUL-prefixed string survives", got.get("nul") == "\u0000plain",
          repr(got))
    nan, inf = got.get("n"), got.get("i")
    check("F94 the float sentinels are still revived",
          isinstance(nan, float) and nan != nan and inf == float("inf"), repr(got))


# ---------------------------------------------------------------- F95
def test_f95(tmp: Path) -> None:
    print("\n== F95: an unreadable directory is recorded in the manifest ==")
    corpus = tmp / "f95" / "corpus"
    (corpus / "ok").mkdir(parents=True)
    (corpus / "ok" / "a.txt").write_text("a", encoding="utf-8")
    (corpus / "locked").mkdir()
    (corpus / "locked" / "secret.txt").write_text("s", encoding="utf-8")
    os.chmod(corpus / "locked", 0)
    try:
        man = nb.hash_manifest(corpus)
    finally:
        os.chmod(corpus / "locked", stat.S_IRWXU)
    if IS_ROOT:
        check("F95 (root: chmod-000 is still readable; check skipped)", True)
        return
    check("F95 the readable files are still present",
          "ok/a.txt" in (man.get("files") or {}), str(man))
    check("F95 the unreadable directory is named in the manifest",
          man.get("unreadable_dirs") == ["locked"], str(man))
    clean = tmp / "f95" / "clean"
    (clean / "ok").mkdir(parents=True)
    (clean / "ok" / "a.txt").write_text("a", encoding="utf-8")
    check("F95 a complete walk carries no gap key",
          "unreadable_dirs" not in nb.hash_manifest(clean))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fixbugs_I_"))
    try:
        test_f86(tmp)
        test_f87(tmp)
        test_f88(tmp)
        test_f89(tmp)
        test_f90(tmp)
        test_f91(tmp)
        test_f92(tmp)
        test_f93()
        test_f94(tmp)
        test_f95(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL GROUP-I FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
