#!/usr/bin/env python3
"""Regressions for wave 2 of the 2026-10-26 fix-bugs stage (F-082..F-215).

Every fixture is built in a temp dir; no network, no Word, no writes outside
the temp tree. Run:
    python3 .paper_test/test_fix_bugs_20261026_wave2.py
`PAPER_WS` retargets the harness at a baseline copy (pre-fix -> red).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_lib_spec = importlib.util.spec_from_file_location(
    "wave2_docx_lib", str(WS / ".paper_test" / "docx_format_lib.py"))
dfl = importlib.util.module_from_spec(_lib_spec)
sys.modules["wave2_docx_lib"] = dfl
_lib_spec.loader.exec_module(dfl)
fmt = dfl.fmt
pp = load("wave2_pp", WS / "paper_pipeline.py")


# ---------------------------------------------------------------- F-082
def test_emphasis_span():
    print("\n== F-082: emphasis only inside the reported label span ==")
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
  <w:p><w:r><w:t xml:space="preserve">Contact (Co-corresponding author; alice@example.edu)</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">Lead (Co-corresponding author; </w:t></w:r>
    <w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">bob@example.edu) and this tail remains italic.</w:t></w:r></w:p>
  <w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
</w:body></w:document>""".replace("{W}", dfl.P[1:-1])
    tmp = scratch("wave2_emphasis_")
    src = dfl.make_package(tmp / "main.docx", xml)
    rep = fmt.fix_package(src, tmp / "out.docx", fmt.load_policy(None))
    with zipfile.ZipFile(tmp / "out.docx") as z:
        fixed = z.read("word/document.xml").decode("utf-8")
    tail = re.search(r"<w:r\b[^>]*>(?:(?!</w:r>)[\s\S])*?and this tail remains italic\."
                     r"(?:(?!</w:r>)[\s\S])*?</w:r>", fixed)
    check("F-082 the fix verifies", bool(rep.get("ok")), str(rep.get("verified"))[:200])
    check("F-082 the italic tail outside the label keeps its italics",
          tail is not None and "<w:i/>" in tail.group(0),
          tail.group(0)[:200] if tail else "tail run not found")
    label_run = re.search(r"<w:r\b[^>]*>(?:(?!</w:r>)[\s\S])*?"
                          r"<w:t[^>]*>bob@example\.edu</w:t>(?:(?!</w:r>)[\s\S])*?</w:r>",
                          fixed)
    check("F-082 the label half itself is made roman",
          label_run is not None and "<w:i/>" not in label_run.group(0),
          label_run.group(0)[:220] if label_run else "label run not found")
    check("F-082 the document text is unchanged",
          rep.get("verified", {}).get("text_identical") is True,
          str(rep.get("verified"))[:200])
    footnoted = ('<w:r><w:rPr><w:i/></w:rPr><w:t>label text</w:t>'
                 '<w:footnoteReference w:id="1"/></w:r>')
    check("F-082 a run carrying a footnote reference is refused, not replicated",
          fmt.split_run_text_span(footnoted, 0, 5) is None,
          str(fmt.split_run_text_span(footnoted, 0, 5)))


# ---------------------------------------------------------------- F-112
def test_inflight_symlink_key():
    print("\n== F-112: one real output path, one in-flight key ==")
    node = shutil.which("node")
    if node is None:
        check("F-112 node is available", False)
        return
    d = scratch("wave2_keys_")
    allowed = d / "allowed"
    allowed.mkdir()
    (allowed / "orig.docx").write_bytes(b"x")
    (allowed / "rev.docx").write_bytes(b"x")
    (allowed / "linkdir").symlink_to(allowed, target_is_directory=True)
    mod = WS / "mcp-docx-compare" / "derived-output.mjs"
    script = (
        "import { inFlightKey } from " + json.dumps(str(mod)) + ";\n"
        "const a = inFlightKey(" + json.dumps(str(allowed / "orig.docx")) + ","
        + json.dumps(str(allowed / "rev.docx")) + ","
        + json.dumps(str(allowed / "out.docx")) + ");\n"
        "const b = inFlightKey(" + json.dumps(str(allowed / "orig.docx")) + ","
        + json.dumps(str(allowed / "rev.docx")) + ","
        + json.dumps(str(allowed / "linkdir" / "out.docx")) + ");\n"
        "console.log(JSON.stringify([a, b]));\n")
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          cwd=str(WS), text=True, capture_output=True)
    try:
        a, b = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        a = b = None
    check("F-112 a symlinked spelling of the output shares the real path's key",
          proc.returncode == 0 and a == b and a and a.endswith("out.docx"),
          (proc.stdout + proc.stderr)[-300:])
    script2 = (
        "import { realOrResolved } from "
        + json.dumps(str(WS / "mcp-docx-compare" / "containment.mjs")) + ";\n"
        "console.log(realOrResolved(" + json.dumps(str(allowed / "linkdir" / "out.docx"))
        + "));\n")
    proc2 = subprocess.run([node, "--input-type=module", "-e", script2],
                           cwd=str(WS), text=True, capture_output=True)
    check("F-112 a not-yet-existing output resolves through the symlinked directory",
          proc2.returncode == 0
          and proc2.stdout.strip() == str(allowed / "out.docx"),
          (proc2.stdout + proc2.stderr)[-300:])


# ---------------------------------------------------------------- F-117
def test_redline_process_group():
    print("\n== F-117: a timed-out redline backend leaves no grandchild ==")
    if os.name != "posix":
        check("F-117 POSIX process-group check is applicable", True)
        return
    d = scratch("wave2_redline_")
    sentinel = d / "grandchild-survived.txt"
    parent = d / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c',\n"
        "    'import sys, time; time.sleep(1.5); '\n"
        "    'open(sys.argv[1], \"w\").write(\"late\")', sys.argv[1]])\n"
        "time.sleep(30)\n", encoding="utf-8")
    started = time.time()
    result = pp._run_redline_cmd([sys.executable, str(parent), str(sentinel)],
                                 d / "redline.docx", timeout=1)
    elapsed = time.time() - started
    time.sleep(2.0)                            # the grandchild's write is due now
    check("F-117 the timeout is reported", result["rc"] is None
          and "timeout" in result["detail"], str(result)[:200])
    check("F-117 the call returns near its timeout", elapsed < 10, f"{elapsed:.1f}s")
    check("F-117 the backend's grandchild is killed with the group",
          not sentinel.exists(), sentinel.read_text() if sentinel.exists() else "")
    ok = pp._run_redline_cmd([sys.executable, "-c", "print('ok')"],
                             d / "missing.docx", timeout=30)
    check("F-117 a normal command still runs and returns its rc",
          ok["rc"] == 0 and "ok" in ok["detail"], str(ok)[:200])


# ---------------------------------------------------------------- F-207
def test_hyphen_noun_use():
    print("\n== F-207: hyphenation leaves the compound's noun use open ==")
    body = ("We used single-cell RNA-seq. Each single cell expressed the marker. "
            "The copy number increased despite copy-number variation. "
            "We compared copy number profiles and single cell data.")
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
<w:p><w:r><w:t>{body}</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
</w:body></w:document>""".replace("{W}", dfl.P[1:-1]).replace("{body}", body)
    tmp = scratch("wave2_hyphen_")
    src = dfl.make_package(tmp / "main.docx", xml)
    policy = fmt.load_policy(None)
    rows = [r for r in fmt.scan_paths([src], policy)["rows"] if r["rule"] == "FMT-T8e"]
    check("F-207 the scanner counts only the two attributive open forms",
          len(rows) == 2 and all("x1" in r["evidence"] for r in rows), str(rows)[:300])
    rep = fmt.fix_package(src, tmp / "out.docx", policy)
    with zipfile.ZipFile(tmp / "out.docx") as z:
        fixed = z.read("word/document.xml").decode("utf-8")
    text = " ".join(fmt.text_of(p[2]) for p in fmt.paragraphs(fixed))
    check("F-207 'single cell expressed' stays open", "Each single cell expressed" in text,
          text[:260])
    check("F-207 'copy number increased' stays open", "The copy number increased" in text,
          text[:260])
    check("F-207 a real attributive open form is still hyphenated",
          "copy-number profiles" in text and "single-cell data" in text, text[:260])
    check("F-207 the fix verifies", bool(rep.get("ok")), str(rep.get("verified"))[:200])


# ---------------------------------------------------------------- F-209
def test_email_glue():
    print("\n== F-209: the e-mail glue repair leaves healthy addresses alone ==")

    def para(text):
        return ('<w:p><w:r><w:t xml:space="preserve">' + text
                + '</w:t></w:r></w:p>')

    for addr in ("emailaddress@journal.com", "contactjohn@university.edu"):
        spans = [s for s in fmt.hygiene_spans(para("Contact: " + addr))
                 if s["rule"] == "FMT-X2"]
        check(f"F-209 {addr} is not split by the mechanical repair", not spans, str(spans))
    glue = "lead contactzhenxie@tsinghua.edu.cn"
    spans = [s for s in fmt.hygiene_spans(para(glue)) if s["rule"] == "FMT-X2"]
    check("F-209 the documented 'lead contact<name>@' glue is still repaired",
          len(spans) == 1 and spans[0]["repl"] == " "
          and glue[:spans[0]["start"]] == "lead contact",
          str(spans))
    m = fmt.EMAIL_RE.search(glue)
    check("F-209 the cut offset sits at the role/name boundary",
          fmt._email_glue_cut(glue, m) == (glue.index("zhenxie"), "before"),
          str(fmt._email_glue_cut(glue, m)))


# ---------------------------------------------------------------- F-215
def test_roman_caption_label():
    print("\n== F-215: a single capital after 'Figure' is not a roman caption ==")
    check("F-215 'Figure C.' is not a caption label",
          fmt.LEGEND_RE.match("Figure C. We next tested the assay in mice.") is None)
    check("F-215 'Fig. I.' is not a caption label",
          fmt.LEGEND_RE.match("Fig. I. We next tested the assay in mice.") is None)
    check("F-215 a real roman caption 'Figure IV.' is still a caption",
          fmt.LEGEND_RE.match("Figure IV. A real caption title.") is not None)
    check("F-215 a digit caption is still a caption",
          fmt.LEGEND_RE.match("Figure 1. A real caption title.") is not None)
    rows = fmt.display_order_rows(
        ["Figure C shows the control before Figure 1 and Figure 2."], order_policy=True)
    check("F-215 'Figure C' does not become figure 100 in the order check",
          rows == [], str(rows)[:240])
    body = "Figure C. We next tested the assay in mice."
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
<w:p><w:r><w:t>{body}</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
</w:body></w:document>""".replace("{W}", dfl.P[1:-1]).replace("{body}", body)
    tmp = scratch("wave2_roman_")
    src = dfl.make_package(tmp / "main.docx", xml)
    done = dfl.fmt.fix_package(src, tmp / "out.docx", dfl.fmt.load_policy(None))
    with zipfile.ZipFile(tmp / "out.docx") as z:
        para = re.search(r"<w:p(?:(?!</w:p>)[\s\S])*?Figure C\.[\s\S]*?</w:p>",
                         z.read("word/document.xml").decode("utf-8"))
    check("F-215 a body sentence that opens 'Figure C.' gets no caption spacing",
          para is not None and "<w:spacing" not in para.group(0),
          (para.group(0)[:300] if para else "paragraph not found"))


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_emphasis_span, test_inflight_symlink_key, test_redline_process_group,
               test_hyphen_noun_use, test_email_glue, test_roman_caption_label):
        try:
            fn()
        except Exception:                                             # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append(fn.__name__)
    cleanup()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
