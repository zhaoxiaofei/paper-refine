#!/usr/bin/env python3
"""The 2026-10-15 operator report on the two clean packages.

Run:  python3 .paper_test/test_review_handoff_2026_1015.py

The report named two package-level classes and one process class:

  * the delivered status said "CERTIFIED / submission-ready" while the champion's
    OWN revision had handed the author 7 (neohet) and 9 (cnb) manual items -- and
    the only pointer to them was a path inside `runs/<id>/`, which the package
    does not carry (REV-1/REV-2, the sibling hand-off file);
  * the CopyNumBench Methods names `data3from2.py` (carried nowhere in the
    package) and the NeoHeteroclitic results name `neoheterocliticAggregate.py`
    (PKG-3), the supplement cites `Figure S3` while `figS3.png` lives only under
    `code/out/` (PKG-4), the correspondence line fuses the name and the address
    (`* Correspondence:Zhen Xiezhenxie@tsinghua.edu.cn`, FMT-X2), and the
    Reporting Summary is an XFA shell whose file carries TWO packet sets
    (FMT-PDF4/6) -- the stale one is why the same file reads as "blank" to a
    strict reader;
  * the neohet root ran a two-day-old PIPELINE SNAPSHOT frozen from another
    root, so every later command ran code that predated the fixes (the setup
    guard + `status` staleness note).

Pinned here: the derivation of each row, the readiness/readme carrier, the
mechanical repair that is safe (the label's colon) and the one that is not (the
name/address split), and the setup refusal.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from bundle_source_lib import copy_bundle
WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_handoff_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_handoff_format", WS / "paper_docx_format.py")

FAILS: list = []
TMPDIRS: list = []
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


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


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_docx(path: Path, paras: list) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<w:document {W_NS}><w:body>{body}</w:body></w:document>')


# --------------------------------------------------------------------------
# 1. REV-1/REV-2: the champion's own open items reach the delivered status
# --------------------------------------------------------------------------

def make_root_with_revision(prefix: str) -> Path:
    root = scratch(prefix)
    write(root / "pipeline_config.json",
          json.dumps({"rounds": 1, "judges": [1], "source": "/tmp/src",
                      "venue": "nature-biotechnology", "article_type": "article"}))
    run = {"id": "r1_a2_revise", "kind": "revise", "status": "done",
           "round": 1, "version": "a2",
           "sandbox": str(root / "runs" / "r1_a2_revise")}
    state = {"version": pp.STATE_VERSION, "runs": {"r1_a2_revise": run},
             "rounds": {}, "log": [],
             "pinned": [{"id": "r1_a2", "round": 1, "produced_by_run": "r1_a2_revise",
                         "digest": "a" * 64, "source_id": "a2"}]}
    write(root / "state.json", json.dumps(state))
    out = root / "runs" / "r1_a2_revise" / "revised"
    write(out / "revision_report.json", json.dumps({
        "counts_by_status": {"fixed": 2, "manual-required": 2,
                             "fixed-with-caveat": 1, "discarded": 2},
        "coverage": [
            {"id": "F-001", "final_status": "manual-required",
             "evidence": "the artwork is a read-only PNG; re-render it"},
            {"id": "F-002", "final_status": "fixed-with-caveat",
             "evidence": "text fixed; the figure needs regeneration"},
            {"id": "F-003", "final_status": "fixed", "evidence": "ok"},
            {"id": "X-901", "final_status": "discarded",
             "evidence": "15 rows for a tool the text says was not run"},
            {"id": "X-902", "final_status": "discarded",
             "evidence": "duplicate of F-010"},
        ],
        "findings": [
            {"id": "F-001", "check": "M31", "severity": "Major",
             "location": "figures/FigureS1.png x-axis vs its legend"},
            {"id": "F-002", "check": "M25", "severity": "Major",
             "location": "main text, Figure 3 legend"},
            {"id": "X-901", "check": "M30", "severity": "Major",
             "location": "raw_data/source_data/Fig3.tsv vs Methods"},
            {"id": "X-902", "check": "M19", "severity": "Minor",
             "location": "main text length"},
        ]}))
    write(root / "runs" / "r1_a2_revise" / "audit" / "audit.json", json.dumps({
        "dispositions": [{"id": "X-901", "verdict": "confirm", "reason": "not a duplicate"},
                         {"id": "X-902", "verdict": "drop", "reason": "duplicate of F-010"}]}))
    write(out / "MANUAL_STEPS.md",
          "# MANUAL_STEPS — what the author must do (2 hand-off items, grouped)\n\n"
          "## A. Artwork regeneration (1 item)\n\n"
          "**A1 — Figure S1 x-axis label names another model (F-001).**\n"
          "regenerate Figure S1 with the manuscript's own term.\n")
    return root


def test_review_handoff():
    print("== the champion's own open items ==")
    root = make_root_with_revision("paper_handoff_")
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    final = {"stored": {"pin_id": "r1_a2", "champion": "a2", "round": 1},
             "pin": {"id": "r1_a2"}}
    oi = pp.collect_open_review_items(ctx, final)
    check("the producing run is resolved from the pin", oi["run"] == "r1_a2_revise", str(oi["run"]))
    check("manual-required and fixed-with-caveat rows are open items",
          sorted(i["id"] for i in oi["items"]) == ["F-001", "F-002"],
          str([(i["id"], i["status"]) for i in oi["items"]]))
    check("a discard the auditor did NOT support is reported as its own item",
          [i["id"] for i in oi["discarded"]] == ["X-901"]
          and oi["discarded"][0]["audit_verdict"] == "confirm",
          json.dumps(oi["discarded"]))
    check("an auditor-supported drop is not an item", "X-902" not in [
        i["id"] for i in oi["items"] + oi["discarded"]])
    check("the hand-off list is carried verbatim", (oi["manual_steps_text"] or "").startswith(
        "# MANUAL_STEPS"), (oi["manual_steps_text"] or "")[:40])
    check("its item count is parsed from the file", oi["manual_steps_items"] == 2,
          str(oi["manual_steps_items"]))

    sibling = pp.write_open_items_sibling(ctx, oi)
    sp = Path(sibling["path"])
    check("the hand-off list is written as a SIBLING of the published directory",
          sp.parent == root and sp.name == pp.FINAL_CLEAN_STEPS_NAME, str(sp))
    check("the sibling carries the stage's own steps",
          "regenerate Figure S1" in sp.read_text(encoding="utf-8"))

    rec = {"open_items": oi, "hygiene": {}}
    readiness = pp.package_readiness(rec)
    rules = [f["rule"] for f in readiness["findings"]]
    check("readiness carries REV-1 for the open items and REV-2 for the drop",
          "REV-1" in rules and "REV-2" in rules, str(rules))
    check("a package with open items is NOT submission-ready",
          readiness["submission_ready"] is False and readiness["blocking_findings"] == 3,
          json.dumps({k: v for k, v in readiness.items() if k != "findings"}))
    check("--require-ready turns them into decision problems",
          len(pp.readiness_gate_problems(readiness, True)) == 1)
    check("without the flag they are recorded, never gated",
          pp.readiness_gate_problems(readiness, False) == [])

    cert = {"certified": True, "submission_ready": False,
            "package_findings": readiness["findings"]}
    final_clean = {"files": 9, "digest": "b" * 64, "pin_digest": "c" * 64,
                   "action": "created", "open_items": oi, "hygiene": {}}
    readme = pp.final_clean_readme_text(ctx, cert, dict(final, stored=final["stored"]),
                                        final_clean)
    check("the readme lists the open items and names the sibling file",
          "Open item(s) the champion's own revision handed to the author" in readme
          and pp.FINAL_CLEAN_STEPS_NAME in readme and "F-001" in readme)
    check("the readme no longer claims submission-readiness on its own",
          "Submission readiness: NOT READY" in readme, "")
    report = pp.build_decision_report(ctx, [], {"pristine_ok": True, "pristine_detail": "ok",
                                                "pinned_errors": [], "recovery": []},
                                      [], dict(final, round=1, agg=None),
                                      final_clean=final_clean, certification=cert)
    check("the decision report carries the items AND stops pointing into runs/",
          "Open item(s) the champion's own revision handed to the author" in report
          and f"`{pp.FINAL_CLEAN_STEPS_NAME}`" in report
          and "never that path" in report)


# --------------------------------------------------------------------------
# 2. PKG-3: a file name the package carries NOWHERE
# --------------------------------------------------------------------------

def test_publish_carries_open_items():
    """The real publication path: winner -> final_clean_version + sibling + status."""
    print()
    print("== publish_final_clean carries the hand-off items ==")
    root = make_root_with_revision("paper_pub_")
    winner = root / "round1_winner"
    make_docx(winner / "neo-13-2-mainText-c67dfab.docx", ["Title", "Body text."])
    write(winner / "README.md", "author notes\n")
    final = {"stored": {"winner_dir": "round1_winner", "champion": "a2", "round": 1,
                        "pin_id": "r1_a2"},
             "pin": {"id": "r1_a2"}}
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    rec = pp.publish_final_clean(ctx, final, True, "")
    check("the package is published", not rec.get("skipped") and rec.get("files"),
          json.dumps({k: v for k, v in rec.items() if k not in ("hygiene", "format_fix",
                                                               "open_items")})[:200])
    oi = rec.get("open_items") or {}
    check("the published record carries the open items", len(oi.get("items") or []) == 2,
          json.dumps({k: v for k, v in oi.items() if k != "list"})[:200])
    sib = root / pp.FINAL_CLEAN_STEPS_NAME
    check("the hand-off list is written beside the published directory",
          sib.is_file() and "regenerate Figure S1" in sib.read_text(encoding="utf-8"),
          str(sib))
    check("the checklist is a sibling, so the judged directory stays byte-identical",
          not (Path(rec["path"]) / pp.FINAL_CLEAN_STEPS_NAME).exists()
          and not (Path(rec["path"]) / "MANUAL_STEPS.md").exists()
          and not (Path(rec["path"]) / pp.AUTHOR_TO_COMPLETE_README).exists()
          and (root / pp.FINAL_CLEAN_AUTHOR_README_NAME).is_file(),
          str(sorted(p.name for p in Path(rec["path"]).iterdir())))
    readiness = pp.package_readiness(rec)
    rules = [f["rule"] for f in readiness["findings"]]
    # The publish path also runs the package scans: this fixture's title page does
    # not print the configured content type, so FMT-TP1 is reported ADVISORY -- it
    # is listed, never gated. The publisher also writes the author checklist
    # from the same open items, so AUTH-2 is a blocking readiness row too.
    check("readiness is NOT ready, names the items and keeps the gap advisory",
          readiness["submission_ready"] is False
          and [r for r in rules if r not in ("FMT-TP1", "AUTH-2")]
          == ["REV-1", "REV-1", "REV-2"]
          and "AUTH-2" in rules
          and readiness["blocking_findings"] == 4
          and all(f.get("advisory") for f in readiness["findings"] if f["rule"] == "FMT-TP1"),
          json.dumps({"rules": rules,
                      "blocking": readiness["blocking_findings"],
                      "advisory": readiness["advisory_findings"]}))
    check("--require-ready gates the decision",
          len(pp.readiness_gate_problems(readiness, True)) == 1)



def test_pkg3_unresolvable_names():
    print()
    print("== PKG-3: names the package does not carry at all ==")
    pkg = scratch("paper_pkg3_")
    make_docx(pkg / "cnb-2-mainText-6d29898.docx", [
        "CopyNumBench: a benchmark",
        "Randomization. All randomness was seeded; the custom generators in "
        "data3from2.py are seeded deterministically from run metadata.",
        "The scripts are available at https://github.com/example/repo and the "
        "generators in analysis2.py were run with the same seed.",
        "The benchmark appendix names evaluate_results.R in its inventory.",
    ])
    write(pkg / "cnb-9-suppBench.tex",
          "The pipeline is implemented as a Snakemake workflow "
          "(\\code{snake/new\\_workflow.snake}) and is invoked with one command.\n")
    rows = pp.non_submitted_reference_rows(pkg, ["code", "raw_data"])
    p3 = [r for r in rows if r["rule"] == "PKG-3"]
    check("a bare name the package carries nowhere is one PKG-3 row",
          [r["reference"] for r in p3] == ["data3from2.py"],
          str([(r["reference"], r["file"]) for r in rows]))
    check("the row is advisory (reported, never gated, never removed)",
          p3 and p3[0].get("severity") == "advisory" and p3[0]["fix"] == "manual",
          json.dumps(p3[:1]))
    check("a sentence that locates its material at a repository is not a row",
          all(r["reference"] != "analysis2.py" for r in rows))
    check("a supplementary inventory is out of PKG-3's prose scope",
          all("suppBench" not in r["file"] for r in rows))
    check("PKG-3 never rewrites anything (no removal path)",
          not hasattr(pp, "PKG3_REMOVAL") and all(r["fix"] != "mechanical" for r in rows))
    # The REPAIR report keeps its PKG-2 meaning: `remaining` is what could not be
    # removed (and is a stage postcheck input), while a PKG-3 name travels in
    # `advisory` -- it must never make the repair report itself "not clean".
    strip = pp.strip_dangling_references_in_dir(pkg, ["code", "raw_data"],
                                                "unit test", warns=None)
    check("a PKG-3 name is advisory in the repair report, never `remaining`",
          [r["reference"] for r in strip.get("remaining") or []] == []
          and [r["reference"] for r in strip.get("advisory") or []] == ["data3from2.py"]
          and strip.get("ok") is True,
          json.dumps({k: strip.get(k) for k in ("ok", "remaining", "advisory")})[:300])


# --------------------------------------------------------------------------
# 3. PKG-4: a cited figure the submission does not carry
# --------------------------------------------------------------------------

def test_pkg4_missing_display_item():
    print()
    print("== PKG-4: cited figures the package does not carry ==")
    pkg = scratch("paper_pkg4_")
    write(pkg / "figures" / "Figure1.png", "png\n")
    write(pkg / "figures" / "FigureS1.png", "png\n")
    write(pkg / "code" / "out" / "figS3.png", "png\n")
    make_docx(pkg / "neo-2-mainText-c67dfab.docx", [
        "Results", "We report the mean curves (Figure S3) and the design (Figure 1).",
        "Panels S1A-S1B are cited as Figure S1."])
    rows = pp.package_display_item_rows(pkg, ["code", "raw_data"])
    check("the cited figure with no carried file is one row",
          [r["reference"] for r in rows] == ["Figure S3"],
          str([(r["reference"], r["file"]) for r in rows]))
    check("the row names where the package actually holds it",
          rows and rows[0]["resolves_to"] == ["code/out/figS3.png"],
          json.dumps(rows[:1]))
    check("a carried figure file suppresses its own row",
          all(r["reference"] not in ("Figure 1", "Figure S1") for r in rows))
    embedded = scratch("paper_pkg4b_")
    make_docx(embedded / "cnb-2-mainText-6d29898.docx", ["Fig. 1 shows the design."])
    check("a package that carries no figure FILES reports nothing (its artwork is embedded)",
          pp.package_display_item_rows(embedded, ["code"]) == [])


# --------------------------------------------------------------------------
# 4. FMT-TP1 (the title-page gap), FMT-X2 (the glue), platform junk
# --------------------------------------------------------------------------

def test_front_matter_and_junk():
    print()
    print("== the title-page gap, the glued correspondence line, OS junk ==")
    root = scratch("paper_tp1_")
    write(root / "pipeline_config.json",
          json.dumps({"rounds": 1, "judges": [1], "source": "/tmp/src",
                      "venue": "nature-biotechnology", "article_type": "article"}))
    write(root / "state.json", json.dumps({"version": pp.STATE_VERSION, "runs": {},
                                           "rounds": {}, "log": [], "pinned": []}))
    pkg = root / "final_clean_version_root"
    make_docx(pkg / "cnb-2-mainText-6d29898.docx",
              ["CopyNumBench", "Authors", "Abstract"])
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    gaps = pp.front_matter_gap_rows(ctx, pkg)
    check("a title page that does not name the configured content type is a GAP row",
          len(gaps) == 1 and gaps[0]["rule"] == "FMT-TP1"
          and "states NO rule" in gaps[0]["detail"], json.dumps(gaps[:1]))
    make_docx(pkg / "cnb-2-mainText-6d29898.docx",
              ["CopyNumBench", "Authors — Article", "Abstract"])
    check("a title page that names it is clean",
          pp.front_matter_gap_rows(ctx, pkg) == [])

    spans = fmt.hygiene_spans('<w:p><w:r><w:t>* Correspondence:Zhen '
                              'Xiezhenxie@tsinghua.edu.cn</w:t></w:r></w:p>')
    check("FMT-X2 inserts the missing space after the label's colon",
          any(sp["rule"] == "FMT-X2" and sp["fix"] == "mechanical" and sp["repl"] == " "
              and sp["start"] == 17 for sp in spans),
          str([(s["rule"], s["start"], s["repl"]) for s in spans]))
    check("FMT-X2 does NOT guess inside a fused name+address token",
          not any(sp["start"] > 20 for sp in spans))
    rows = fmt.correspondence_glue_rows(["* Correspondence:Zhen Xiezhenxie@tsinghua.edu.cn"],
                                        [False])
    check("the unsplittable glue stays a REPORTED row", len(rows) == 1 and rows[0]["rule"] == "FMT-X2")
    check("the clean form is untouched",
          fmt.hygiene_spans('<w:p><w:r><w:t>* Correspondence: Zhen Xie '
                            '(zhenxie@tsinghua.edu.cn)</w:t></w:r></w:p>') == [])
    check("platform junk is recognised",
          pp.is_platform_junk_name("figures/figS3.png:Zone.Identifier")
          and pp.is_platform_junk_name(".DS_Store")
          and pp.is_platform_junk_name("Thumbs.db")
          and not pp.is_platform_junk_name("figures/figS3.png"))
    check("platform junk is never a document",
          pp.is_non_document_name("~$file.docx")
          and pp.is_non_document_name("x.csv:Zone.Identifier")
          and not pp.is_non_document_name("main.docx"))
    docs = pp.collect_documents([(pkg, "", ())])
    check("a junk file is not part of the document set",
          all("Zone.Identifier" not in k for k in docs), str(sorted(docs))[:120])


# --------------------------------------------------------------------------
# 5. The XFA form: which packet the form READS, and the stale duplicate
# --------------------------------------------------------------------------

def _mini_xfa_pdf(path: Path, live_answers: int, stale_answers: int) -> None:
    """A minimal PDF with an AcroForm /XFA array and two dataset packets."""
    def leaves(n):
        return "".join(f"<f{i} >answer {i}</f{i} >" for i in range(n))

    live = f"<xfa:datasets ><xfa:data ><form >{leaves(live_answers)}</form ></xfa:data ></xfa:datasets >"
    stale = f"<xfa:datasets ><xfa:data ><form >{leaves(stale_answers)}</form ></xfa:data ></xfa:datasets >"

    def stream(text):
        data = text.encode()
        return b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"

    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R /AcroForm 4 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
        4: (b"<< /Fields [] /SigFlags 2 /XFA [(datasets) 5 0 R] >>"),
        5: stream(live),
        6: stream(stale),
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in objs.items():
        offsets[num] = len(out)
        out += str(num).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for num in sorted(objs):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    path.write_bytes(bytes(out))


def test_xfa_live_packet():
    print()
    print("== the mandatory form: the packet the form READS ==")
    tmp = scratch("paper_xfa_")
    filled = tmp / "rs-filled.pdf"
    _mini_xfa_pdf(filled, live_answers=3, stale_answers=0)
    live = fmt.xfa_live_packets(filled)
    check("the /XFA array resolves the packet the form reads",
          live["resolved"] and live["live_datasets"] == ["datasets"],
          json.dumps({k: v for k, v in live.items() if k != "packets"})[:200])
    check("the live packet's answers are exported",
          len(fmt.xfa_dataset_answers(filled, limit=None)) == 3,
          str(fmt.xfa_dataset_answers(filled, limit=None)))
    summary = fmt._xfa_packet_summary(filled)
    check("the summary counts the live answers and the stale packet",
          summary["live_answers"] == 3 and summary["stale_answers"] == 0
          and summary["packets"] == 2, json.dumps(summary))
    unfilled = tmp / "rs-unfilled.pdf"
    _mini_xfa_pdf(unfilled, live_answers=0, stale_answers=2)
    rows = {r["rule"] for r in fmt.pdf_artifact_rows(unfilled)}
    check("a live dataset with NO answers while a copy carries them is FMT-PDF5",
          "FMT-PDF5" in rows, str(sorted(rows)))
    blank = tmp / "rs-blank.pdf"
    _mini_xfa_pdf(blank, live_answers=0, stale_answers=0)
    rows = {r["rule"] for r in fmt.pdf_artifact_rows(blank)}
    check("a genuinely unfilled form stays FMT-PDF2", "FMT-PDF2" in rows, str(sorted(rows)))


# --------------------------------------------------------------------------
# 4b. What the package's own README declares as submitted
# --------------------------------------------------------------------------

DECL = ("# What will be submitted\n\n"
        "Only files whose names match the following Bash extglob pattern will be submitted to "
        "the venue/journal:\n\n`neo-*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]"
        ".@(docx|pdf)`\n\nAll other files will not be submitted. For example, this README file.\n\n"
        "- Submitted files must not refer to any non-submitted files.\n")


def test_declared_submission_set():
    print()
    print("== the package's own README declares the submitted set ==")
    pkg = scratch("paper_decl_")
    make_docx(pkg / "neo-2-mainText-abcdef0.docx", [
        "A title",
        "Methods. The per-figure numbers are in supplementary_source_files/table.tsv and the "
        "generators in analysis_notes.py.",
        "See also the compiled supplement."])
    write(pkg / "supplementary_source_files" / "table.tsv", "a\tb\n1\t2\n")
    write(pkg / "code" / "analysis_notes.py", "print()\n")
    write(pkg / "neo-9-suppSource-abcdef0.tex",
          "The supplement is rebuilt from supplementary_source_files/table.tsv beside this file.\n")
    write(pkg / "README.md", DECL)
    decl = pp.declared_submission_set(pkg)
    check("the declaration is read from the package's own README",
          decl["declared"] and decl["readme"] == "README.md"
          and decl["files"] == ["neo-2-mainText-abcdef0.docx"],
          json.dumps({k: v for k, v in decl.items() if k != "carried_not_submitted"})[:240])
    check("everything else the package carries is listed as not submitted",
          set(decl["carried_not_submitted"]) >=
          {"README.md", "supplementary_source_files/table.tsv", "code/analysis_notes.py",
           "neo-9-suppSource-abcdef0.tex"},
          str(sorted(decl["carried_not_submitted"])))
    rows = pp.non_submitted_reference_rows(pkg, ["code", "raw_data"])
    refs = sorted(r["reference"] for r in rows)
    check("a submitted document pointing at a carried-but-not-declared file is a PKG-2 row",
          "supplementary_source_files/table.tsv" in refs, json.dumps(refs))
    check("the row's advice names the declaration",
          any("package's own README declares only" in str(r.get("detail"))
              for r in rows if "supplementary_source_files" in str(r.get("reference"))),
          json.dumps([r.get("detail") for r in rows])[:200])
    check("a NON-submitted source file's own pointers are not rows (the 2026-10-15 MS1 case)",
          all("suppSource" not in str(r.get("file")) for r in rows),
          json.dumps([(r.get("file"), r.get("reference")) for r in rows])[:240])
    # An implausible declaration must be IGNORED, never applied silently.
    bad = scratch("paper_decl_bad_")
    make_docx(bad / "main.docx", ["Title"])
    write(bad / "README.md",
          "# What will be submitted\n\nOnly files matching `nothing-*.xyz` will be submitted.\n")
    bd = pp.declared_submission_set(bad)
    check("a declaration matching nothing is ignored WITH a reason",
          bd["declared"] is False and bd["ignored_reason"]
          and "match no file" in bd["ignored_reason"], json.dumps(bd)[:200])
    _decl, is_sub = pp.declared_submission_filter(bad)
    check("the scans fall back to the pipeline's own model",
          is_sub("main.docx") is True and is_sub("anything/else.txt") is True)
    # The journal-submission ASSEMBLY is narrowed to the declared set too: what it
    # copies is what ships, and a `.tex` source or figure asset the journal never
    # receives must not sit in the submission folder pretending to.
    root = make_root_with_revision("paper_decl_asm_")
    winner = root / "round1_winner"
    make_docx(winner / "neo-2-mainText-abcdef0.docx", ["Title", "Body"])
    write(winner / "neo-9-suppSource-abcdef0.tex", "source\n")
    write(winner / "README.md", DECL)
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    out = pp.publish_journal_submission(ctx, winner, "test-label")
    shipped = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    man = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    check("the journal submission carries only the declared files",
          shipped == ["neo-2-mainText-abcdef0.docx"], str(shipped))
    check("the manifest names what the declaration kept out",
          set(man.get("not_submitted_by_declaration") or []) ==
          {"README.md", "neo-9-suppSource-abcdef0.tex"}
          and man.get("declared_submission_patterns"), json.dumps(
              man.get("not_submitted_by_declaration")))


# --------------------------------------------------------------------------
# 4c. PKG-5: two shipped surfaces disagree about a display item's producer
# --------------------------------------------------------------------------

def test_pkg5_producer_contradiction():
    print()
    print("== PKG-5: the resources table vs the legend ==")
    pkg = scratch("paper_pkg5_")
    make_docx(pkg / "neo-2-mainText-abcdef0.docx", [
        "Results", "The design is shown in Figure 1.",
        "Table 1. Resources used in this study.",
        "Matplotlib, seaborn (Figures 2, 4 and S2)",
        "BioRender (Figures 1 and S2)",
        "Figure S2. A candidate mechanism for the substitution effect.",
        "Schematic free-energy profile. Neither axis is quantitative."])
    make_docx(pkg / "neo-3-supplement-abcdef0.docx", [
        "Figure S2. A candidate mechanism for the substitution effect.",
        "A schematic of the proposed preorganization, drawn as an instability energy. "
        "Created with BioRender.com."])
    write(pkg / "README.md", DECL)
    rows = pp.display_provenance_rows(pkg, ["code", "raw_data"])
    check("the contradiction is one row, naming both sides and the tools",
          len(rows) == 1 and rows[0]["item"] == "figure s2"
          and "Matplotlib" in rows[0]["reference"] and "seaborn" in rows[0]["reference"]
          and "BioRender" in rows[0]["detail"],
          json.dumps(rows)[:300])
    # Silence: no legend producer, and a legend that names the SAME tool.
    agree = scratch("paper_pkg5b_")
    make_docx(agree / "neo-2-mainText-abcdef0.docx", [
        "Matplotlib, seaborn (Figures 2 and S2)",
        "Figure S2. A data figure.", "Values are plotted; created with matplotlib."])
    check("a legend naming the same tool is not a contradiction",
          pp.display_provenance_rows(agree, ["code"]) == [],
          json.dumps(pp.display_provenance_rows(agree, ["code"]))[:200])
    quiet = scratch("paper_pkg5c_")
    make_docx(quiet / "neo-2-mainText-abcdef0.docx", [
        "Matplotlib, seaborn (Figure 2)",
        "Figure 2. A data figure.", "Every cell prints its value."])
    check("an item whose legend names no producer is not a row",
          pp.display_provenance_rows(quiet, ["code"]) == [])
    prose = scratch("paper_pkg5d_")
    make_docx(prose / "neo-2-mainText-abcdef0.docx", [
        "Matplotlib, seaborn (Figure 2)",
        "Figure 2. A data figure.",
        "The variants generated by substituting MHC-anchor residues were ranked above chance, "
        "and the logos were plotted in bits."])
    check("a lowercase participle is not read as a producer (the case-sensitivity trap)",
          pp.display_provenance_rows(prose, ["code"]) == [],
          json.dumps(pp.display_provenance_rows(prose, ["code"]))[:200])
    rec = {"hygiene": {"display_provenance": rows}, "open_items": {}}
    readiness = pp.package_readiness(rec)
    check("PKG-5 is BLOCKING in readiness (not advisory)",
          readiness["submission_ready"] is False
          and [f["rule"] for f in readiness["findings"]] == ["PKG-5"]
          and not readiness["findings"][0].get("advisory"),
          json.dumps(readiness["findings"])[:200])


# --------------------------------------------------------------------------
# 5b. The seeds reach the sessions that can ACT on them
# --------------------------------------------------------------------------

def test_seeds_reach_the_sessions():
    print()
    print("== the new rows are seeded into the agent evidence ==")
    root = make_root_with_revision("paper_seed_")
    corpus = root / "round1_winner"
    write(corpus / "figures" / "Figure1.png", "png\n")
    write(corpus / "code" / "out" / "figS3.png", "png\n")
    make_docx(corpus / "neo-2-mainText-c67dfab.docx", [
        "A manuscript title",
        "All values were produced by neoheterocliticAggregate.py with the seed fixed in it.",
        "The mean curves are in Figure S3 and the design in Figure 1."])
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    ev = pp.code_side_evidence(ctx, corpus, "test:seed")
    check("the pack carries the display-item rows",
          [r["reference"] for r in (ev.get("display_items") or {}).get("rows") or []]
          == ["Figure S3"], json.dumps((ev.get("display_items") or {}).get("rows"))[:200])
    check("the pack carries the title-page gap rows",
          bool((ev.get("front_matter_gaps") or {}).get("rows")),
          json.dumps(ev.get("front_matter_gaps"))[:160])
    check("the pack's reference rows include the PKG-3 shape",
          any(r.get("rule") == "PKG-3" for r in
              (ev.get("submission_references") or {}).get("rows") or []),
          json.dumps((ev.get("submission_references") or {}).get("rows"))[:200])
    summary = pp.evidence_pack_summary(ev)
    check("the pack summary reports both new counts",
          "PKG-4 missing display items" in summary and "FMT-TP1" in summary, summary)
    sb = scratch("paper_seed_sb_")
    pp.seed_evidence_pack(ctx, sb, corpus, "stage")
    pack = (sb / "EVIDENCE_PACK.md").read_text(encoding="utf-8")
    check("the written pack has the display-item section",
          "Display items the submission does not carry (PKG-4)" in pack
          and "`Figure S3`" in pack, pack[-600:])
    check("the pack explains the PKG-3 shape and its no-removal rule",
          "PKG-3" in pack and "will NOT touch it" in pack)
    check("the pack prints the title-page gap",
          "Title-page gaps (FMT-TP1)" in pack)
    check("the M31/M33 sweeps name the new code-side seeds",
          "PKG-4 rows" in pp.EVIDENCE_INTEGRITY_REVIEW
          and "`PKG-3` row" in pp.EVIDENCE_INTEGRITY_REVIEW)


# --------------------------------------------------------------------------
# 6. The stale PIPELINE SNAPSHOT (why the neohet run re-found fixed defects)
# --------------------------------------------------------------------------

def test_setup_snapshot_guard():
    print()
    print("== setup must not freeze another root's pipeline snapshot ==")
    tmp = scratch("paper_snapshot_")
    old_root = tmp / "old-root"
    old_root.mkdir()
    copy_bundle(WS, old_root)
    write(old_root / "state.json", json.dumps({
        "version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "log": [], "pinned": [],
        "pipeline": {"path": str(WS / "paper_pipeline.py"), "sha256": "0" * 64,
                     "version": pp.VERSION}}))
    src = tmp / "src"
    write(src / "neo-1-coverLetter-abc1234.md", "# Cover letter\n\nDear Editors,\n")
    new_root = tmp / "new-root"
    cmd = [sys.executable, str(old_root / "paper_pipeline.py"), "setup",
           "--root", str(new_root), "--source", str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    blob = (proc.stdout or "") + (proc.stderr or "")
    check("setup refuses to freeze the snapshot", proc.returncode == 2, f"rc={proc.returncode}")
    check("the refusal names the snapshot root, the origin and the override flag",
          "PIPELINE SNAPSHOT" in blob and str(old_root) in blob
          and str(WS / "paper_pipeline.py") in blob and "--pipeline-snapshot-ok" in blob,
          blob[:300])
    check("nothing was created for the refused root", not new_root.exists())
    proc2 = subprocess.run(cmd + ["--pipeline-snapshot-ok"], capture_output=True, text=True,
                           timeout=600)
    blob2 = (proc2.stdout or "") + (proc2.stderr or "")
    check("the explicit flag proceeds and WARNs",
          proc2.returncode == 0 and "WARNING: freezing a PIPELINE SNAPSHOT" in blob2,
          f"rc={proc2.returncode} {blob2[-300:]}")
    if new_root.is_dir():
        ctx = pp.Ctx(new_root)
        ctx.load(need_cfg=False)
        note = pp.pipeline_snapshot_note(ctx)
        check("status says which code the root runs", "pipeline snapshot" in note
              or "runs the pipeline" in note, note)
        state = json.loads((new_root / "state.json").read_text(encoding="utf-8"))
        check("the exception is recorded with its origin",
              state["pipeline"].get("snapshot_of") == str(old_root)
              and state["pipeline"].get("snapshot_origin") == str(WS / "paper_pipeline.py"),
              json.dumps(state.get("pipeline")))


def main():
    test_review_handoff()
    test_publish_carries_open_items()
    test_pkg3_unresolvable_names()
    test_pkg4_missing_display_item()
    test_declared_submission_set()
    test_pkg5_producer_contradiction()
    test_front_matter_and_junk()
    test_xfa_live_packet()
    test_seeds_reach_the_sessions()
    test_setup_snapshot_guard()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL 2026-10-15 PACKAGE/HAND-OFF CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
