#!/usr/bin/env python3
"""convert_corpus.py — Phase 1 setup for the paper-review skill.

Recursively inventories SUBMISSION_DIR, converts every text-based editable file
(doc/docx/tex/bib/md/txt/xlsx/csv, plus pdf via pdftotext when available) to
plain text under WORK/corpus/, and writes:
  WORK/inventory.md     — human-readable inventory table
  WORK/inventory.json   — machine-readable inventory
  WORK/corpus/<rel>.txt — converted plain text (structure-aware)

Conversion details that matter downstream:
  * .docx — body paragraphs, plus header/footer and footnote/endnote parts,
    each introduced by a `### HEADER (word/header1.xml)` style marker so
    metadata living outside the body is never invisible to M12/M14.
    Zotero/live field instructions are kept as `[[FIELD: ...]]`; tracked
    changes and residual comments are recorded in the inventory notes.
  * .xlsx — shared strings are resolved to their text (a stream of raw shared
    string indexes would poison M15's column sums) and sheet names are mapped
    through workbook relationships, not by sorted file name.
  * .rtf — converted with a small stdlib stripper (formatting is not
    preserved); flagged read-only because editing RTF as plain text corrupts it.

Why this exists: sweeps must run over a uniform plain-text corpus so that every
enumeration is deterministic and reproducible. Conversion failures are RECORDED,
never skipped silently.

stdlib-only by design (docx/xlsx read via zipfile + XML) so it runs in any
Python 3.8+ environment, including sandboxed Codex sandboxes.

Usage:
  python convert_corpus.py --submission ./non-revised --work ./review/work
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from html import unescape as _html_unescape

EDITABLE_EXTS = {".doc", ".docx", ".tex", ".ltx", ".bib", ".md", ".txt", ".xlsx", ".csv",
                 ".tsv", ".rtf"}
BINARY_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".svg", ".eps", ".zip",
               ".gz", ".tar", ".xlsx.lock", ".py", ".r", ".ipynb", ".xls", ".pptx", ".docx~"}

ROLE_PATTERNS = [
    ("cover letter", re.compile(r"cover|letter_to_editor|tocover", re.I)),
    ("title page", re.compile(r"title|titlepage|first_page", re.I)),
    ("abstract", re.compile(r"abstract", re.I)),
    ("main text", re.compile(r"manuscript|main|article|paper|(?:^|[_\-. ])ms(?:[_\-. ]|$)", re.I)),
    ("methods", re.compile(r"methods|m&m", re.I)),
    ("references", re.compile(r"\brefs?\b|\breferences?\b|bibliograph|\.bib$", re.I)),
    ("supplementary", re.compile(r"supp|extended_?data|appendix", re.I)),
    ("figure", re.compile(r"\bfig|figure|legend", re.I)),
    ("table", re.compile(r"table", re.I)),
    ("reporting summary", re.compile(r"reporting|summary", re.I)),
    ("code", re.compile(r"\.py$|\.r$|\.ipynb$|code|script|(?:^|[_\-. ])src(?:[_\-. ]|$)", re.I)),
    ("data", re.compile(r"\.csv$|\.tsv$|data", re.I)),
]


def guess_role(rel_path: str) -> str:
    base = os.path.basename(rel_path).lower()
    for role, pat in ROLE_PATTERNS:
        if pat.search(base):
            return role
    return "other"


# ---------------------------------------------------------------- docx / xlsx

TEXT_RUN_RE = re.compile(r"<w:(?:instrText|t)(?:\s[^>]*)?>(.*?)</w:(?:instrText|t)>", re.S)


def docx_part_to_lines(xml: str):
    """Paragraph lines + notes for one WordprocessingML part."""
    notes, out_lines = [], []
    for para in re.split(r"</w:p>", xml):
        if "<w:ins " in para:
            notes.append("tracked-insertion present in a paragraph")
        if "<w:del " in para:
            notes.append("tracked-deletion present in a paragraph")
        texts = []
        for m in TEXT_RUN_RE.finditer(para):
            tag = m.group(0)
            content = _html_unescape(m.group(1))
            if "instrText" in tag:
                texts.append("[[FIELD: %s]]" % content.strip())
                notes.append("live field instruction present (possible Zotero citation)")
            else:
                texts.append(content)
        line = "".join(texts).strip()
        if line:
            out_lines.append(line)
    return out_lines, notes


def docx_to_text(path: str) -> tuple:
    """Return (text, notes) — body plus headers/footers/footnotes/endnotes."""
    notes = []
    out_lines = []
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return "", ["docx-unreadable: %s" % e]
    with z:
        try:
            body = z.read("word/document.xml").decode("utf-8", errors="replace")
        except Exception as e:
            return "", ["docx-unreadable: %s" % e]
        lines, part_notes = docx_part_to_lines(body)
        out_lines.extend(lines)
        notes.extend(part_notes)
        names = z.namelist()
        extra_parts = []
        for pattern, kind in ((r"word/header\d*\.xml$", "HEADER"),
                              (r"word/footer\d*\.xml$", "FOOTER"),
                              (r"word/footnotes\.xml$", "FOOTNOTES"),
                              (r"word/endnotes\.xml$", "ENDNOTES")):
            extra_parts.extend((n, kind) for n in sorted(names) if re.match(pattern, n))
        for name, kind in extra_parts:
            try:
                xml = z.read(name).decode("utf-8", errors="replace")
            except Exception:
                continue
            part_lines, part_notes = docx_part_to_lines(xml)
            if part_lines:
                # lowercase marker: an all-caps marker would itself be inventoried as an acronym
                out_lines.append("### %s (%s)" % (kind.lower(), name))
                out_lines.extend(part_lines)
                notes.append("%s text included: %s" % (kind.lower(), name))
            notes.extend(part_notes)
        try:
            if any(n.startswith("word/comments") for n in names):
                notes.append("word/comments*.xml present — residual comments in docx")
            if "docProps/core.xml" in names:
                core = z.read("docProps/core.xml").decode("utf-8", errors="replace")
                for tag in ("lastModifiedBy", "creator"):
                    m = re.search(r"<[^>]*%s[^>]*>(.*?)</[^>]*%s" % (tag, tag), core, re.S)
                    if m and m.group(1).strip():
                        notes.append("docx property %s = %r (metadata/PII check)" % (tag, m.group(1)[:60]))
        except Exception:
            pass
    return "\n".join(out_lines), notes


CELL_RE = re.compile(r"<c(?P<attrs>\s[^>]*)?(?:(?:/>)|>(?P<body>.*?)</c>)", re.S)
ROW_RE = re.compile(r"<row[^>]*>(.*?)</row>", re.S)
SHEET_TAG_RE = re.compile(r"<sheet\b[^>]*/?>")


def _xlsx_shared_strings(z):
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = z.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
        for si in re.findall(r"<si>(.*?)</si>", ss, re.S):
            # Shared strings carry XML entities ("A&amp;B", "caf&eacute;") and the
            # inline-string path already unescapes them; leaving them literal here
            # made the two paths disagree and poisoned the corpus with "&amp;".
            shared.append(_html_unescape(
                "".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", si, re.S))))
    return shared


def _xlsx_sheet_plan(z):
    """[(sheet name, worksheet path)] in workbook order, via the rels map."""
    try:
        wb = z.read("xl/workbook.xml").decode("utf-8", errors="replace")
    except KeyError:
        return []
    rels = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        rx = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", errors="replace")
        for m in re.finditer(r"<Relationship\b[^>]*/?>", rx):
            tag = m.group(0)
            rid = re.search(r'Id="([^"]*)"', tag)
            tgt = re.search(r'Target="([^"]*)"', tag)
            typ = re.search(r'Type="([^"]*)"', tag)
            if not (rid and tgt):
                continue
            if typ and "worksheet" not in typ.group(1):
                continue
            t = tgt.group(1).replace("\\", "/")
            if t.startswith("/"):
                t = t.lstrip("/")
            elif not t.startswith("xl/"):
                t = "xl/" + t
            rels[rid.group(1)] = t
    plan = []
    for m in SHEET_TAG_RE.finditer(wb):
        tag = m.group(0)
        name = re.search(r'name="([^"]*)"', tag)
        rid = re.search(r'r:id="([^"]*)"', tag)
        plan.append((_html_unescape(name.group(1)) if name else None,
                     rels.get(rid.group(1)) if rid else None))
    return plan


def _xlsx_cell_value(attrs, body, shared):
    if body is None:
        return ""
    tm = re.search(r"<t(?:\s[^>]*)?>(.*?)</t>", body, re.S)
    if tm:
        return _html_unescape(tm.group(1))
    vm = re.search(r"<v(?:\s[^>]*)?>(.*?)</v>", body, re.S)
    if not vm:
        return ""
    v = _html_unescape(vm.group(1))
    if re.search(r't="s"', attrs or "") and v.strip().isdigit():
        idx = int(v)
        if 0 <= idx < len(shared):
            return shared[idx]
        return ""      # dangling shared-string index: never its own number
    return v


CELL_REF_RE = re.compile(r"^\s*([A-Za-z]{1,3})(\d{1,7})\s*$")


def _col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _xlsx_row_cells(row_xml, shared):
    """{column index: value} for one row, keyed by the cell reference."""
    cells = {}
    for m in CELL_RE.finditer(row_xml):
        ref = re.search(r'r="([^"]*)"', m.group("attrs") or "")
        col = 0
        if ref:
            rm = CELL_REF_RE.match(ref.group(1))
            if rm:
                col = _col_index(rm.group(1))
        value = _xlsx_cell_value(m.group("attrs"), m.group("body"), shared)
        if col:
            cells[col] = value
        else:
            cells[len(cells) + 1] = value
    return cells


def xlsx_to_text(path: str) -> tuple:
    notes = []
    try:
        with zipfile.ZipFile(path) as z:
            shared = _xlsx_shared_strings(z)
            names = z.namelist()
            plan = _xlsx_sheet_plan(z)
            known = {p for _n, p in plan if p in names}
            leftovers = [n for n in sorted(n for n in names
                                            if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
                         if n not in known]
            resolved = []
            for name, p in plan:
                if p in names:
                    resolved.append((name, p))
                elif leftovers:
                    resolved.append((name, leftovers.pop(0)))
            for p in leftovers:
                resolved.append((None, p))
            lines = []
            for name, sf in resolved:
                sname = name or sf
                lines.append("### sheet: %s" % sname)
                sh = z.read(sf).decode("utf-8", errors="replace")
                rows = []
                max_col = 0
                for rm in re.finditer(r"<row\b([^>]*)>(.*?)</row>", sh, re.S):
                    cells = _xlsx_row_cells(rm.group(2), shared)
                    if not cells:
                        continue
                    rn = re.search(r'r="(\d+)"', rm.group(1))
                    row_idx = int(rn.group(1)) if rn else len(rows) + 1
                    rows.append((row_idx, cells))
                    max_col = max(max_col, max(cells))
                # pad every row to the widest column so a sparse row (data only in
                # column C, or a merged/omitted cell) cannot silently shift values
                # into the wrong column when the table is summed downstream (M15)
                for _row_idx, cells in sorted(rows):
                    lines.append(" | ".join(cells.get(c, "") for c in range(1, max_col + 1)))
            if not resolved:
                notes.append("xlsx: no worksheet parts found")
            return "\n".join(lines), notes
    except Exception as e:
        notes.append("xlsx-unreadable: %s" % e)
        return "", notes


# ------------------------------------------------------------------- generic

def plain_copy(path: str) -> tuple:
    raw = open(path, "rb").read()
    # A BOM is authoritative: Word/Notepad exports a .txt as UTF-16 on Windows,
    # and reading it as UTF-8 "succeeded" with NUL-separated mojibake that then
    # fed the corpus sweeps as if it were text.
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
                     (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            try:
                return raw.decode(enc), []
            except UnicodeDecodeError as e:
                return "", ["unable — %s decode failed: %s" % (enc, e)]
    return raw.decode("utf-8", errors="replace"), []


RTF_META_WORDS = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
                  "themedata", "datastore", "generator", "listtable", "listoverridetable"}


def rtf_to_text(path: str) -> tuple:
    """Small stdlib RTF -> text stripper (formatting is not preserved)."""
    notes = []
    try:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            raw = f.read()
    except Exception as e:
        return "", ["rtf-unreadable: %s" % e]
    out, i, depth, skip_depth = [], 0, 0, None
    pending_high = None
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "{":
            depth += 1
            i += 1
        elif ch == "}":
            depth -= 1
            if skip_depth is not None and depth < skip_depth:
                skip_depth = None
            i += 1
        elif ch == "\\":
            i += 1
            if i >= n:
                break
            nxt = raw[i]
            if nxt in "\\{}":
                if skip_depth is None:
                    out.append(nxt)
                i += 1
            elif nxt == "*":
                skip_depth = depth
                i += 1
            elif nxt == "'":
                try:
                    if skip_depth is None:
                        out.append(bytes.fromhex(raw[i + 1:i + 3]).decode("cp1252", errors="replace"))
                except ValueError:
                    pass
                i += 3
            elif nxt == "u":
                m = re.match(r"u(-?\d+)\D?", raw[i:])
                if m:
                    code = int(m.group(1))
                    if code < 0:
                        code += 65536
                    if skip_depth is None:
                        try:
                            if 0xD800 <= code <= 0xDBFF:
                                if pending_high is not None:
                                    out.append(chr(pending_high))
                                pending_high = code
                            elif 0xDC00 <= code <= 0xDFFF and pending_high is not None:
                                out.append(chr(0x10000 + ((pending_high - 0xD800) << 10)
                                               + (code - 0xDC00)))
                                pending_high = None
                            else:
                                if pending_high is not None:
                                    out.append(chr(pending_high))
                                    pending_high = None
                                out.append(chr(code))
                        except ValueError:
                            pending_high = None
                    i += len(m.group(0))
                else:
                    i += 1
            else:
                m = re.match(r"([A-Za-z]+)(-?\d+)?[ ]?", raw[i:])
                if m:
                    word = m.group(1)
                    if skip_depth is None:
                        if word in ("par", "line", "sect", "page"):
                            out.append("\n")
                        elif word == "tab":
                            out.append("\t")
                    if word in RTF_META_WORDS:
                        skip_depth = depth
                    i += len(m.group(0))
                else:
                    i += 1
        else:
            if skip_depth is None and depth > 0:
                out.append(ch)
            i += 1
    if pending_high is not None:
        out.append(chr(pending_high))
    text = "".join(out)
    # A lone surrogate (unpaired \u escape) would crash the utf-8 corpus write;
    # replace it here so one malformed escape cannot abort the whole run.
    text = text.encode("utf-8", "replace").decode("utf-8")
    text = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    notes.append("rtf converted by stdlib stripper (formatting not preserved) — "
                 "read-only here; edit the submission in a word processor")
    if not text:
        notes.append("rtf produced no extractable text")
    return text, notes


def pdf_to_text(path: str) -> tuple:
    notes = []
    if shutil.which("pdftotext"):
        try:
            proc = subprocess.run(["pdftotext", "-layout", path, "-"],
                                  capture_output=True, timeout=60)
            text = proc.stdout.decode("utf-8", errors="replace")
            if not text.strip():
                notes.append("pdftotext produced no text (scanned/image PDF?) — "
                             "visually unverifiable; first stderr: %s"
                             % proc.stderr.decode("utf-8", errors="replace").strip()[:120])
            return text, notes
        except Exception as e:
            notes.append("pdftotext-failed: %s" % e)
            return "", notes
    notes.append("pdf-unconvertible: pdftotext not available — read-only/unreadable")
    return "", notes


def convert_one(path: str, rel: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if path.lower().endswith(".xlsx.lock"):
        # splitext reports ".lock" here, so the BINARY_EXTS entry never matched
        # and an Office lock file was bucketed as "read-only/unknown-ext"
        # instead of the read-only/binary bucket it is listed under.
        ext = ".xlsx.lock"
    text, notes = "", []
    status = "not-attempted"
    if ext in (".md", ".txt", ".tex", ".ltx", ".bib", ".csv", ".tsv"):
        text, notes = plain_copy(path)
        status = "converted" if text else "converted-empty"
    elif ext == ".rtf":
        text, notes = rtf_to_text(path)
        status = "converted" if text else "converted-empty"
    elif ext == ".docx":
        text, notes = docx_to_text(path)
        status = "converted" if text else ("converted-empty" if not notes else "failed")
    elif ext == ".xlsx":
        text, notes = xlsx_to_text(path)
        status = "converted" if text else ("converted-empty"
                                           if any("unreadable" not in n for n in notes) else "failed")
    elif ext == ".doc":
        status = "needs-conversion-to-docx"
        notes.append(".doc is legacy binary — convert to .docx before editing; treat as read-only here")
    elif ext == ".pdf":
        text, notes = pdf_to_text(path)
        status = "converted" if text.strip() else "read-only/unreadable"
    elif ext in BINARY_EXTS:
        status = "read-only/binary"
        if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".svg", ".eps"):
            notes.append("image — visually unverifiable without OCR/VLM")
        if ext in (".py", ".r", ".ipynb"):
            notes.append("code file — reviewed only if code findings are in scope; "
                         "copy into CODE/ before editing")
    else:
        status = "read-only/unknown-ext"
    return {"path": rel, "abs": path, "ext": ext, "text": text, "notes": notes,
            "status": status}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", required=True, help="SUBMISSION_DIR")
    ap.add_argument("--work", required=True, help="WORK dir (e.g. ./review/work)")
    args = ap.parse_args()

    sub = os.path.abspath(args.submission)
    work = os.path.abspath(args.work)
    if not os.path.isdir(sub):
        print("ERROR: SUBMISSION_DIR %s does not exist. Stop and ask the user." % sub)
        sys.exit(2)
    corpus_dir = os.path.join(work, "corpus")
    os.makedirs(corpus_dir, exist_ok=True)

    files = []
    for root, dirs, names in os.walk(sub):
        dirs.sort()
        for n in sorted(names):
            p = os.path.join(root, n)
            files.append(os.path.relpath(p, sub))
    if not files:
        print("ERROR: SUBMISSION_DIR %s is empty. Stop and ask the user." % sub)
        sys.exit(2)

    inventory = []
    corpus_names = set()      # flattened corpus stems written so far
    for rel in files:
        p = os.path.join(sub, rel)
        entry = convert_one(p, rel)
        entry["role"] = guess_role(rel)
        entry["editable"] = os.path.splitext(rel)[1].lower() in EDITABLE_EXTS and \
            entry["status"] in ("converted", "converted-empty")
        entry["size_bytes"] = os.path.getsize(p)
        inventory.append(entry)
        if entry["status"] in ("converted", "converted-empty"):
            stem = rel.replace(os.sep, "__")
            out_txt = os.path.join(corpus_dir, stem + ".txt")
            if stem in corpus_names:
                # Two files can flatten to one corpus name ("figs/notes.md" and
                # "figs__notes.md"): the second used to overwrite the first, so a
                # document silently vanished from the review corpus.
                suffix = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:8]
                out_txt = os.path.join(corpus_dir, "%s.__%s.txt" % (stem, suffix))
                entry["notes"].append(
                    "corpus text written as %s.__%s.txt -- another file converts to the "
                    "same flattened corpus name" % (stem, suffix))
            corpus_names.add(stem)
            os.makedirs(os.path.dirname(out_txt), exist_ok=True)
            with open(out_txt, "w", encoding="utf-8") as f:
                f.write(entry["text"] if entry["text"] else "(empty file)")

    md = ["# File inventory", "",
          "| path | role | ext | editable | size | conversion status | notes |",
          "|---|---|---|---|---|---|---|"]
    for e in inventory:
        notes = "; ".join(sorted(set(e["notes"]))) or "—"
        md.append("| %s | %s | %s | %s | %d | %s | %s |" % (
            e["path"], e["role"], e["ext"], "yes" if e["editable"] else "no",
            e["size_bytes"], e["status"], notes.replace("|", "\\|")))
    with open(os.path.join(work, "inventory.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    js = [{"path": e["path"], "role": e["role"], "ext": e["ext"],
           "editable": e["editable"], "size_bytes": e["size_bytes"],
           "status": e["status"], "notes": sorted(set(e["notes"]))}
          for e in inventory]
    with open(os.path.join(work, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, indent=2)

    print("Inventoried %d files. Converted text corpus in %s" % (len(inventory), corpus_dir))
    print("Artifacts: inventory.md, inventory.json")
    n_fail = sum(1 for e in inventory if e["status"] in ("failed", "read-only/unreadable"))
    if n_fail:
        print("WARNING: %d files could not be converted — recorded (never skipped)." % n_fail)


if __name__ == "__main__":
    main()
