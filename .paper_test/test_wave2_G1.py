#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G1 (run 20261115-220228).

Each check pins one re-validated candidate from `wave2/G1.json` against the
LIVE functions in `paper_pipeline` (p04_utils / p00_prelude). Hermetic: temp
dirs, no network, no Word, no full pipeline.

Run:  python3 -B .paper_test/test_wave2_G1.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS = []
SKIPS: list = []
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
MINIMAL_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    '<w:name w:val="Normal"/></w:style></w:styles>')
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml"/></Types>')
DOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    'officeDocument" Target="word/document.xml"/></Relationships>')


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)



def skip(name: str, detail: str = "") -> None:
    """Report an unexercised check as skipped, never as `[ok ]` (F19)."""
    print(f"[skip] {name}" + (f"  -- {detail}" if detail else ""))
    SKIPS.append(name)

def scratch(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"g1_{tag}_"))


def make_docx(path: Path, paragraphs) -> None:
    """A tiny readable DOCX (document.xml + a minimal styles part)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % text
        for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main"><w:body>' + body + '</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", DOT_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", MINIMAL_STYLES)


# ---------------------------------------------------------------- F056 / C041
def test_f056_lenient_json_stack_is_bounded():
    print("\n== C041/F056: the lenient parser's bracket stack is bounded ==")
    # Run FIRST so ru_maxrss is still near the interpreter baseline.
    import resource
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    t0 = time.time()
    out = pp._json_from_text("{" * 2_000_000, True)
    elapsed = time.time() - t0
    delta_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    check("C041 a 2M-unmatched-brace text is refused", out is None, repr(out))
    check("C041 the refusal does not grow the process by ~100 MB",
          delta_kb < 25_000, f"maxrss delta {delta_kb} KB")
    check("C041 the refusal is immediate, not a full-input allocation",
          elapsed < 3.0, f"{elapsed:.3f}s")
    check("C041 a fenced JSON document still parses",
          pp._json_from_text('```json\n{"a": [1, {"b": 2}]}\n```', True)
          == {"a": [1, {"b": 2}]})
    check("C041 the nesting cap is a documented constant",
          getattr(pp, "JSON_MAX_NESTING", None) == 1000,
          str(getattr(pp, "JSON_MAX_NESTING", None)))


# ---------------------------------------------------------------- F001 / C001
def test_f001_duplicate_rewrap_declarations():
    print("\n== C001/F001: duplicate re-wrap declarations cannot excuse two drops ==")
    tmp = scratch("f001")
    src = tmp / "src"
    sb = tmp / "sb"
    (sb / "out").mkdir(parents=True)
    make_docx(src / "paper.docx",
              ["Alpha paragraph one content", "Alpha paragraph one content"])
    make_docx(sb / "out" / "paper.docx", ["Beta replacement text different"])
    ledger = sb / "out" / "REPLACEMENT_LEDGER.md"
    pair = {"kind": "rewrap", "source": "Alpha paragraph one content",
            "output": "Beta replacement text different", "reason": "template slot"}
    ledger.write_text("```json\n" + json.dumps({"exceptions": [pair, dict(pair)]})
                      + "\n```\n", encoding="utf-8")
    rep = pp.template_rewrite_postcheck(sb, src, {}, policy=None)
    check("C001 two identical re-wrap declarations are refused",
          rep.get("ok") is False and any("coverage is not exact" in e
                                         for e in rep.get("errors") or []),
          str(rep.get("errors"))[:200])
    check("C001 coverage drops to 1/2 (one source occurrence is really lost)",
          (rep.get("coverage") or {}).get("ratio") == 0.5,
          str(rep.get("coverage")))
    check("C001 the unbacked declaration is named",
          any("not backed" in e for e in rep.get("errors") or []),
          str(rep.get("errors"))[:200])
    # ONE declaration for ONE lost occurrence is still a valid re-wrap.
    make_docx(src / "paper.docx", ["Alpha paragraph one content"])
    ledger.write_text("```json\n" + json.dumps({"exceptions": [pair]}) + "\n```\n",
                      encoding="utf-8")
    rep = pp.template_rewrite_postcheck(sb, src, {}, policy=None)
    check("C001 a single backed re-wrap still passes", rep.get("ok") is True,
          str(rep.get("errors"))[:200])


# ---------------------------------------------------------------- F002 / C002
def test_f002_evidence_link_containment():
    print("\n== C002/F002: an evidence link must resolve INSIDE its root ==")
    tmp = scratch("f002")
    outside = tmp / "outside"
    (outside / "non_revised" / "raw_data").mkdir(parents=True)
    (outside / "non_revised" / "raw_data" / "secret.csv").write_text("payload\n")
    fake = tmp / "fake"
    (fake / "non_revised").mkdir(parents=True)
    (fake / "state.json").write_text("{}")
    os.symlink(outside / "non_revised" / "raw_data", fake / "non_revised" / "raw_data")
    os.symlink(outside / "non_revised" / "raw_data", fake / "raw_data")
    check("C002 the planted root is found as an enclosing root",
          pp._enclosing_run_root(fake) == fake)
    check("C002 the canonical-link proof now REFUSES an outside target",
          pp.is_canonical_evidence_link(fake / "raw_data", fake) is False)
    files = sorted(pp.hash_manifest(fake, follow_dir_links=True)["files"])
    check("C002 the manifest no longer hashes the outside file",
          files == ["state.json"], str(files))
    check("C002 the corpus manifest no longer hashes the outside file",
          sorted(pp.corpus_tree_manifest(fake)["files"]) == ["state.json"])
    # The legitimate sandbox link (to THIS root's canonical area) still follows.
    root = tmp / "root"
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "state.json").write_text("{}")
    (root / "non_revised" / "raw_data" / "data.csv").write_text("real\n")
    sb = root / "runs" / "r1" / "input"
    sb.mkdir(parents=True)
    os.symlink(root / "non_revised" / "raw_data", sb / "raw_data")
    check("C002 a canonical in-root evidence link is still followed",
          pp.is_canonical_evidence_link(sb / "raw_data", root) is True
          and sorted(pp.hash_manifest(sb, follow_dir_links=True)["files"])
          == ["raw_data/data.csv"])


# ---------------------------------------------------------------- F003 / C003
def test_f003_provenance_symlink():
    print("\n== C003/F003: work/PROVENANCE.json is not written through a link ==")
    from types import SimpleNamespace
    tmp = scratch("f003")
    sb = tmp / "sb"
    (sb / "work").mkdir(parents=True)
    victim = tmp / "victim.json"
    victim.write_text("ORIGINAL VICTIM CONTENT")
    (sb / "work" / "PROVENANCE.json").symlink_to(victim)
    ctx = SimpleNamespace(cfg={"placeholder_lookup": "off"}, root=tmp)
    pp.seed_provenance_pack(ctx, sb, [], {"numbers": {"rows": []}}, sb / "work")
    check("C003 the outside victim file is untouched",
          victim.read_text() == "ORIGINAL VICTIM CONTENT", victim.read_text()[:40])
    check("C003 the planted link was replaced by a real file",
          (sb / "work" / "PROVENANCE.json").is_symlink() is False)
    payload = json.loads((sb / "work" / "PROVENANCE.json").read_text())
    check("C003 the provenance pack itself was written",
          "numbers" in payload and "identifiers" in payload)


# ---------------------------------------------------------------- F004 / C004
def test_f004_symlinked_destination():
    print("\n== C004/F004: a symlinked package destination is refused (regression pin) ==")
    tmp = scratch("f004")
    root = tmp / "root"
    root.mkdir()
    (root / "state.json").write_text("{}")
    outside = tmp / "outside"
    outside.mkdir()
    dest = root / "template_package"
    os.symlink(outside, dest)
    src = tmp / "src"
    src.mkdir()
    (src / "data.txt").write_text("payload")
    rep = pp.rebuild_package_from_templates({"main": str(tmp / "tpl.docx")},
                                            src, dest, protected=(root,))
    check("C004 the symlinked destination is refused",
          rep.get("ok") is False and "symbolic link" in str(rep.get("error")),
          str(rep.get("error")))
    check("C004 nothing was written through the link",
          list(outside.iterdir()) == [], str(list(outside.iterdir())))


# ---------------------------------------------------------------- F045 / C034
def test_f045_email_fifo_does_not_block():
    print("\n== C034/F045: the e-mail reader refuses a FIFO instead of blocking ==")
    tmp = scratch("f045")
    fifo = tmp / "notes.md"
    os.mkfifo(fifo)
    # A subprocess, so a regression fails the check instead of hanging the suite.
    script = (
        "import sys; sys.path.insert(0, %r); import paper_pipeline as pp; "
        "from pathlib import Path; print(pp._email_texts_in_file(Path(%r)))"
        % (str(ROOT), str(fifo)))
    try:
        proc = subprocess.run([sys.executable, "-B", "-c", script],
                              capture_output=True, text=True, timeout=15)
        check("C034 the FIFO read returns a named gap instead of blocking",
              proc.returncode == 0 and "unreadable" in proc.stdout,
              (proc.stdout or proc.stderr).strip()[:160])
    except subprocess.TimeoutExpired:
        check("C034 the FIFO read returns a named gap instead of blocking", False,
              "the reader BLOCKED on the FIFO (timeout)")
    regular = tmp / "ok.md"
    regular.write_text("contact a@b.org\n")
    texts, gap = pp._email_texts_in_file(regular)
    check("C034 a regular text file is still read", gap == "" and texts
          and "a@b.org" in texts[0], repr((texts, gap)))
    link = tmp / "link.md"
    outside = tmp / "outside.txt"
    outside.write_text("secret\n")
    os.symlink(outside, link)
    check("C034 a symlinked text file is refused, not followed",
          pp._email_texts_in_file(link)[1] != "")


# ---------------------------------------------------------------- F046 / C035
def test_f046_placeholder_email_verification():
    print("\n== C035/F046: a reserved/example address is not a verified correction ==")
    tmp = scratch("f046")
    (tmp / "work").mkdir(parents=True)
    record = {"after": "fake@example.com", "source_url": "https://www.nature.com/",
              "query": "author email", "checked_at": "2026-11-15",
              "evidence": "Corresponding author fake@example.com at the institute."}
    (tmp / "work" / "EMAIL_VERIFICATION.json").write_text(
        json.dumps({"verifications": [record]}))
    records, problems = pp._email_verification_rows(tmp)
    check("C035 the example-domain correction is rejected",
          records == [] and any("reserved/example" in p for p in problems),
          str(problems))
    real = dict(record, after="real.person@university.edu",
                evidence="Corresponding author real.person@university.edu there.")
    (tmp / "work" / "EMAIL_VERIFICATION.json").write_text(
        json.dumps({"verifications": [real]}))
    records, problems = pp._email_verification_rows(tmp)
    check("C035 a real correction is still accepted",
          len(records) == 1 and records[0]["after"] == "real.person@university.edu"
          and problems == [], str((records, problems)))
    before_row = dict(record, after="real.person@university.edu",
                      before="old@example.org",
                      evidence="Corrected to real.person@university.edu now.")
    (tmp / "work" / "EMAIL_VERIFICATION.json").write_text(
        json.dumps({"verifications": [before_row]}))
    records, problems = pp._email_verification_rows(tmp)
    check("C035 a reserved/example `before` is rejected as well",
          records == [] and any("`before`" in p for p in problems), str(problems))


# ---------------------------------------------------------------- F049 / C036
def test_f049_unreadable_scan_dirs():
    print("\n== C036/F049: caption/length scans name an unreadable directory ==")
    if IS_ROOT:
        skip("C036 (root: chmod-000 is still readable)")
        return
    tmp = scratch("f049")
    src = tmp / "src"
    locked = src / "locked"
    locked.mkdir(parents=True)
    make_docx(locked / "paper.docx", ["Figure 1. A legend in a locked directory."])
    os.chmod(locked, 0)
    try:
        cap = pp.scan_captions_in_sources([(src, "", ())])
        lng = pp.scan_lengths_in_sources([(src, "", ())])
        check("C036 the caption scan records the unreadable directory",
              cap.get("unreadable_dirs") == ["locked"], str(cap.get("unreadable_dirs")))
        check("C036 the length scan records the unreadable directory",
              lng.get("unreadable_dirs") == ["locked"], str(lng.get("unreadable_dirs")))
        _ok, cap_note = pp.caption_gate(cap)
        check("C036 the caption note says the legends were NOT verified",
              "NOT verified" in cap_note and "locked" in cap_note, cap_note[-160:])
        len_note = pp.length_note(lng)
        check("C036 the length note is 'not verified', not 'nothing found'",
              "not verified" in len_note and "locked" in len_note, len_note[:180])
    finally:
        os.chmod(locked, 0o755)


# ---------------------------------------------------------------- F050 / C037
def test_f050_code_area_is_not_prose():
    print("\n== C037/F050: the analysis-code area is not scanned as prose ==")
    tmp = scratch("f050")
    code = tmp / "code"
    code.mkdir()
    (code / "notes.md").write_text(
        "# Analysis notes\nA long sentence with enough words to be counted as prose text "
        "in the M20/M19 sweeps.\n[AUTHOR TO COMPLETE: deposit the code DOI]\n"
        "contact: someone@lab.example.edu\n")
    sources = [(code, "code/", ())]
    fmt_rows = pp.scan_format_in_sources(sources)["rows"]
    check("C037 the format sweep files no row against code/notes.md",
          fmt_rows == [], str([(r.get("rule"), r.get("document")) for r in fmt_rows])[:160])
    ph = pp.scan_placeholders_in_sources(sources)
    check("C037 a code hand-off marker is not a submission placeholder",
          ph.get("count") == 0, str(ph))
    addrs, _gaps = pp._email_addresses_in_sources(sources)
    check("C037 a code note's address is not a manuscript contact fact",
          addrs == {}, str(addrs))
    evidence_addrs, _egaps = pp._email_addresses_in_sources(sources, evidence=True)
    check("C037 evidence=True still reads the code area",
          any(k.endswith("someone@lab.example.edu") for k in evidence_addrs),
          str(evidence_addrs))


# ---------------------------------------------------------------- F055 / C040
def test_f055_length_note_names_unmeasured():
    print("\n== C040/F055: length_note names the files it could not measure ==")
    info = {
        "rows": [{"section": "abstract", "words": 100, "over_limit": False},
                 {"section": "main text", "words": 1000, "over_limit": False}],
        "limits": {"abstract": {"cap": 165}, "main text": {"cap": 3750},
                   "cover letter": {"total_max": None, "min": None, "max": None}},
        "unparsed": ["appendix.doc"], "skipped": ["supp.pdf"], "rendered": [],
        "venue": "nature-biotechnology"}
    note = pp.length_note(info)
    check("C040 the note names the unparsed legacy document",
          "appendix.doc" in note, note[-200:])
    check("C040 the note names the skipped rendering", "supp.pdf" in note)
    check("C040 it no longer claims 'all within' a count that skipped sources",
          "all within the relaxed caps" not in note)
    check("C040 it says the count covers only the measured sections",
          "not all sources were counted" in note
          and "covers the measured sections only" in note, note[-200:])
    clean = dict(info, unparsed=[], skipped=[], rendered=[])
    check("C040 a complete scan still says 'within the relaxed caps'",
          "within the relaxed caps" in pp.length_note(clean))


# ---------------------------------------------------------------- F057 / C042
def test_f057_hierarchy_inventory_cap():
    print("\n== C042/F057: the M30 seed reports a truncated producer inventory ==")
    tmp = scratch("f057")
    corpus = tmp / "corpus"
    corpus.mkdir()
    for i in range(41):
        (corpus / f"t{i}.csv").write_text("sample,value\na,1\nb,2\n")
    (corpus / "paper.md").write_text(
        "# Introduction\nWe analysed 15 samples and the mean coverage was 12.\n")
    ctx = type("C", (), {"cfg": {}})()
    ev = pp.code_side_evidence(ctx, corpus, "test")
    hierarchy = ev.get("hierarchy") or {}
    check("C042 the payload records the inventory cap",
          hierarchy.get("table_inventory_cap") == 40, str(hierarchy.get("table_inventory_cap")))
    check("C042 the payload records the truncation",
          hierarchy.get("table_inventory_truncated") is True)
    check("C042 the payload enumerates the omitted producer",
          len(hierarchy.get("producers_omitted") or []) == 1
          and (hierarchy["producers_omitted"][0].endswith(".csv")),
          str(hierarchy.get("producers_omitted")))
    sb = tmp / "sb"
    sb.mkdir()
    pp.seed_evidence_pack(ctx, sb, corpus, "stage")
    m30 = (sb / "work" / "M30_hierarchy_reconciliation.md").read_text()
    check("C042 the M30 artifact names the truncated inventory",
          "PRODUCER INVENTORY IS TRUNCATED" in m30 and "PARTIAL" in m30)


# ---------------------------------------------------------------- F059 / C043
def test_f059_redaction_fail_closed():
    print("\n== C043/F059: a malformed --agent-cmd / upper-case URL keeps no secret ==")
    out = pp.redact_argv(["--agent-cmd", "python tool.py --api-key hunter2hunter2"])
    check("C043 a malformed --agent-cmd masks a generic --api-key value",
          out == ["--agent-cmd", "python tool.py --api-key [REDACTED]"], str(out))
    out = pp.redact_argv(["--agent-cmd", "HTTPS://user:pass@example.org/x"])
    check("C043 an upper-case-scheme URL userinfo is masked",
          out == ["--agent-cmd", "HTTPS://[REDACTED]@example.org/x"], str(out))
    check("C043 a bare upper-case URL userinfo is masked in text",
          pp.redact_secrets("HTTPS://user:pass@example.org/x")
          == "HTTPS://[REDACTED]@example.org/x")
    out = pp.redact_argv(["--agent-cmd",
                          '["python", "tool.py", "--api-key", "hunter2hunter2"]'])
    check("C043 the valid JSON argv list is still masked",
          "hunter2hunter2" not in " ".join(out), str(out))
    check("C043 an ordinary flag is not over-masked",
          pp.redact_secrets("--model gpt-x --name hello") == "--model gpt-x --name hello")


# ---------------------------------------------------------------- F060 / C044
def test_f060_reserved_tmp_identity():
    print("\n== C044/F060: a swapped reserved temporary is refused ==")
    tmp = scratch("f060")
    dst = tmp / "state.json"
    dst.write_text("kept")
    reserved = pp.tmp_path_for(dst)
    # Hold the reserved inode under a second name before unlinking it, so the
    # filesystem cannot hand the SAME inode to the replacement file: on a
    # filesystem that reuses a just-freed inode, an inode-identity check is
    # untestable (and this check flaked under the parallel suite).
    held = reserved.with_name(reserved.name + ".held")
    os.link(reserved, held)
    os.unlink(reserved)
    reserved.write_bytes(b"X" * 100)
    try:
        with pp._open_reserved_tmp(reserved, "wb") as f:
            f.write(b"new")
        refused = False
    except OSError:
        refused = True
    check("C044 a re-created regular temp is refused (inode identity)",
          refused is True)
    check("C044 the destination is untouched", dst.read_text() == "kept")
    # A normal atomic write still installs exactly the bytes written.
    pp.write_text_atomic(dst, "new content")
    check("C044 a normal atomic write still works",
          dst.read_text() == "new content")


# ---------------------------------------------------------------- F062 / C046
def test_f062_docx_part_budget():
    print("\n== C046/F062: the part hashers respect MAX_DOCX_PART_BYTES ==")
    tmp = scratch("f062")
    bomb = tmp / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"A" * (66 * 1024 * 1024))
        z.writestr("word/styles.xml", b"<styles/>")
    with zipfile.ZipFile(bomb) as z:
        declared = z.getinfo("word/document.xml").file_size
        check("C046 the DOCX declares an over-budget part",
              declared > pp.MAX_DOCX_PART_BYTES, str(declared))
        check("C046 _docx_xml_part already refuses it",
              pp._docx_xml_part(z, "word/document.xml") is None)
    hashes = pp._out_part_hashes(bomb)
    check("C046 _out_part_hashes does not decompress the bomb",
          len(hashes) == 1, f"{len(hashes)} hash(es)")
    tpl = tmp / "tpl.docx"
    with zipfile.ZipFile(tpl, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/theme/theme1.xml", b"B" * (66 * 1024 * 1024))
        z.writestr("word/header1.xml", b"<w:hdr/>")
    parts = pp._protected_template_parts(tpl)
    check("C046 the protected-parts helper skips (never reads) the bomb",
          "word/theme/theme1.xml" not in parts
          and "word/header1.xml" in parts, str(sorted(parts)))


# ---------------------------------------------------------------- F063 / C047
def test_f063_zotero_unreadable_base():
    print("\n== C047/F063: an unreadable base directory fails the field gate ==")
    if IS_ROOT:
        skip("C047 (root: chmod-000 is still readable)")
        return
    tmp = scratch("f063")
    base = tmp / "base"
    locked = base / "locked"
    locked.mkdir(parents=True)
    make_docx(locked / "paper.docx", ["Body text with a citation."])
    out = tmp / "out"
    make_docx(out / "paper.docx", ["Body text with a citation."])
    os.chmod(locked, 0)
    try:
        errs, warns = [], []
        rep = pp.zotero_field_continuity_check(base, out, "stage", errs, warns)
        check("C047 the skip message does not claim the base carries no DOCX",
              "carries no DOCX" not in str(rep.get("skipped")),
              str(rep.get("skipped")))
        check("C047 the gate's error count is non-zero", rep.get("errors", 0) > 0,
              str(rep.get("errors")))
        check("C047 the stage error list names the unreadable directory",
              any("locked" in e for e in errs), str(errs)[:200])
        check("C047 the warning is still recorded for the operator",
              any("could not be read" in w for w in warns), str(warns)[:160])
    finally:
        os.chmod(locked, 0o755)


# ---------------------------------------------------------------- F201 / C148
def test_f201_large_registry_origin():
    print("\n== C148/F201: a valid large state.json keeps its recorded origin ==")
    import hashlib
    tmp = scratch("f148")
    holder = tmp / "bigstate"
    holder.mkdir()
    script = holder / "paper_pipeline.py"
    script.write_text("# frozen copy\n")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    record = {"pipeline": {"path": str(script), "version": "3.11.4", "sha256": digest},
              "runs": [], "rounds": [], "pinned": {},
              "pad": "x" * (68 * 1024 * 1024)}
    (holder / "state.json").write_text(json.dumps(record))
    (holder / "non_revised").mkdir()
    check("C148 the fixture is larger than the AGENT-JSON cap",
          (holder / "state.json").stat().st_size > pp.MAX_JSON_BYTES)
    check("C148 the registry reader accepts it",
          (pp.load_state_file(holder / "state.json")[0] or {}).get("pipeline"))
    info = pp.frozen_snapshot_root(script)
    check("C148 frozen_snapshot_root keeps the recorded origin path",
          info.get("origin_path") == str(script), str(info.get("origin_path")))
    check("C148 ... and its recorded version",
          info.get("origin_version") == "3.11.4", str(info.get("origin_version")))


# ---------------------------------------------------------------- F203 / C150
def test_f203_second_caption_on_a_line():
    print("\n== C150/F203: every \\caption on one line becomes an M19 span ==")
    text = ("\\section{Intro}\nBody text.\n\\begin{figure}\n"
            "\\caption{First caption words here.}"
            "\\caption{Second caption leaked words here.}\n"
            "\\end{figure}\n\\section{Methods}\nMethod text.")
    lines, spans, _abstract = pp._tex_length_scan(text)
    check("C150 both captions produce their own line",
          "Second caption leaked words here." in lines, str(lines))
    check("C150 both captions produce a span", spans == [(2, 3, "figure"), (3, 4, "figure")],
          str(spans))
    inventory = pp._tex_caption_units(text)
    check("C150 the M18 inventory and the M19 spans agree",
          len(inventory) == 2 and len(spans) == 2, str(inventory))
    # End to end: with a profile that excludes figure legends, BOTH legends are
    # subtracted, so adding a second legend on the line changes no count.
    one_dir = scratch("f203_one")
    two_dir = scratch("f203_two")
    head = ("\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\n"
            "Abstract words here.\n\\end{abstract}\n\\section{Introduction}\n"
            "Body text one two three.\n\\begin{figure}\n")
    tail = "\\end{figure}\n\\section{Methods}\nMethod text four five.\n\\end{document}\n"
    prof = pp.load_venue_profile("nature-biotechnology")
    (one_dir / "one.tex").write_text(head + "\\caption{First caption words here.}\n" + tail)
    one = [r for r in pp.scan_lengths_in_sources([(one_dir, "", ())],
                                                 profile=prof)["rows"]
           if r["section"] == "main text"][0]
    (two_dir / "two.tex").write_text(
        head + "\\caption{First caption words here.}"
        "\\caption{Second caption leaked words here.}\n" + tail)
    two = [r for r in pp.scan_lengths_in_sources([(two_dir, "", ())],
                                                 profile=prof)["rows"]
           if r["section"] == "main text"][0]
    check("C150 the second legend is not charged to the main text",
          two["words"] == one["words"], f"one={one['words']} two={two['words']}")
    check("C150 both legends' words are recorded as subtracted",
          "9 caption word(s) subtracted" in (two.get("note") or ""),
          (two.get("note") or "")[-160:])


# ---------------------------------------------------------------- F204 / C151
def test_f204_read_text_bounded_descriptor_check():
    print("\n== C151/F204: read_text_bounded fstats the OPEN descriptor ==")
    tmp = scratch("f204")
    swapped = tmp / "swapped.md"
    os.mkfifo(swapped)
    real_lstat = Path.lstat

    def stale_lstat(self):
        st = real_lstat(self)
        if str(self) == str(swapped):
            # A stale regular-file stat, as if the file was swapped after lstat.
            return os.stat_result((0o100644, 0, 0, 1, 0, 0, 10, 0, 0, 0))
        return st

    Path.lstat = stale_lstat
    try:
        got = pp.read_text_bounded(swapped)
    finally:
        Path.lstat = real_lstat
    check("C151 a FIFO swapped in after lstat is refused (None, not '')",
          got is None, repr(got))
    check("C151 a pre-existing FIFO is refused", pp.read_text_bounded(swapped) is None)
    regular = tmp / "ok.txt"
    regular.write_text("hello")
    check("C151 a regular text file still reads", pp.read_text_bounded(regular) == "hello")


def main() -> int:
    test_f056_lenient_json_stack_is_bounded()   # first: keeps the RSS baseline low
    test_f001_duplicate_rewrap_declarations()
    test_f002_evidence_link_containment()
    test_f003_provenance_symlink()
    test_f004_symlinked_destination()
    test_f045_email_fifo_does_not_block()
    test_f046_placeholder_email_verification()
    test_f049_unreadable_scan_dirs()
    test_f050_code_area_is_not_prose()
    test_f055_length_note_names_unmeasured()
    test_f057_hierarchy_inventory_cap()
    test_f059_redaction_fail_closed()
    test_f060_reserved_tmp_identity()
    test_f062_docx_part_budget()
    test_f063_zotero_unreadable_base()
    test_f201_large_registry_origin()
    test_f203_second_caption_on_a_line()
    test_f204_read_text_bounded_descriptor_check()
    print()
    if SKIPS:
        print(f"{len(SKIPS)} check(s) skipped")
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL WAVE-2 G1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
