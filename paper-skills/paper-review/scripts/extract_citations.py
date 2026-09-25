#!/usr/bin/env python3
"""extract_citations.py — M2 citation ↔ reference-list sweep.

Enumerates every in-text citation call-out (numeric [1] / [1,2] / [1-3] and
author-year "(Smith et al., 2019)", "Smith et al. (2019)", "Smith and Jones
2019") and every reference-list entry, then compares them. One row per
reference entry AND per call-out occurrence in the artifact:

  OUT/artifacts/M2_citations.md / .json

Checks derivable from the artifact: cited-but-not-listed (orphan call-out),
listed-but-never-cited (uncited entry), duplicate entries within one list,
misordered numeric call-outs within one document, and suspect/nonexistent
reference candidates (flag, never guess).

Each file that carries its own numbered list is its own numbering space:
orphans, uncited entries, duplicates and order violations are computed per
document, never merged across documents (a cover letter citing [5] while the
manuscript starts at [1] is not an ordering defect).

stdlib-only. Usage:
  python extract_citations.py --work ./review/work [--out ./review]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

NUM_CIT_RE = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]")
AY_CIT_RE = re.compile(
    r"(?P<a1>[A-Z][A-Za-z'\-]+)\s+et al\.?\s*,?\s*\(?(?P<y1>(?:19|20)\d{2}[a-z]?)\)?"
    r"|(?P<a2>[A-Z][A-Za-z'\-]+)\s+(?:and|&)\s+(?P<a2b>[A-Z][A-Za-z'\-]+)\s*,?\s*"
    r"\(?(?P<y2>(?:19|20)\d{2}[a-z]?)\)?"
    r"|\((?P<a3>[A-Z][A-Za-z'\-]+)(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z'\-]+)?\s*,\s*"
    r"(?P<y3>(?:19|20)\d{2}[a-z]?)\)")
# a bracketed number right after these words is a measurement interval, not a citation
SUSPECT_PRECEDERS = re.compile(
    r"(?:interval|range|between|cut-?off|threshold|score|coordinate|temperature|"
    r"duration|period|dose|concentration|voltage|pressure|radius|band|window|"
    r"percentile|quartile|value|level|age|cycle|time|hour|day|week|month|year|"
    r"size|length|width|volume|mass|weight|height|area|depth|distance|speed|"
    r"unit|replicate|ratio|fold|bound|limit|baseline|score)s?"
    r"\s*(?:of|is|was|:|=|are|were)?\s*$", re.I)
REF_ENTRY_RE = re.compile(r"^\s*\[?(\d{1,3})[\].]\s+(.*)$")
BIB_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,]+),")

REF_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:references?|bibliography|reference\s+list|literature\s+cited)\s*:?\s*$", re.I)
STOP_SECTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s+)?(?:figure\s+legends?|figures?|table\s+legends?|tables?|"
    r"supplementary(?:\s+\w+)?|extended\s+data(?:\s+\w+)?|methods?|materials\s+and\s+methods|"
    r"experimental\s+procedures|results?|discussion|conclusions?|introduction|background|"
    r"abstract|acknowledge?ments?|author\s+contributions?|competing\s+interests?|"
    r"conflicts?\s+of\s+interest|data\s+availability|code\s+availability|funding|"
    r"ethics(?:\s+statement)?|appendix|list\s+of\s+(?:figures|tables))\s*:?\s*$", re.I)
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
# captions carry a separator after the label; "Fig. 1 shows …" is prose
CAP_SEP = r"[.:|–—,](?:\s*\S|\s*$)"
FIG_CAPTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:extended\s+data|supplementary\s+)?fig(?:ure)?s?\.?\s*"
    r"(?:s\d+|\d+[a-z]?)\s*" + CAP_SEP, re.I)
TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:extended\s+data|supplementary\s+)?tables?\.?\s*"
    r"(?:s\d+|\d+[a-z]?)\s*" + CAP_SEP, re.I)
NUM_ENTRY_RE = re.compile(r"^\s*(?:\[?\d{1,3}[\].)]|\d{1,3}[.)])\s+")
BULLET_ENTRY_RE = re.compile(r"^\s*[-*•]\s+\S")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
ENTRY_HINT_RE = re.compile(
    r"(\bdoi\b|https?://|arxiv|biorxiv|medrxiv|preprint|\bet al\.?\b|\bpp?\.\s*\d+)", re.I)
AUTHOR_START_RE = re.compile(r"^\s*[A-Z][A-Za-z'\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)")
# tail of a wrapped entry: "Nature. 2019;570:1-9." / "Science 2020;11:20-30."
JOURNAL_TAIL_RE = re.compile(r"^[A-Z][A-Za-z&.\s]{2,40}[.,;:]?\s*\(?(?:19|20)\d{2}\b")


def looks_like_reference_entry(s):
    if NUM_ENTRY_RE.match(s) or BULLET_ENTRY_RE.match(s):
        return True
    if YEAR_RE.search(s) or ENTRY_HINT_RE.search(s):
        return True
    return bool(AUTHOR_START_RE.match(s))


def classify_context(fname):
    """Role of a corpus file, derived from its name (falls back to main text)."""
    raw = os.path.basename(fname).lower()
    f = re.sub(r"\.(?:txt|md)$", "", raw)
    f = re.sub(r"\.[a-z0-9]{1,5}$", "", f)
    if "cover" in f: return "cover letter"
    if "title" in f: return "title page"
    if re.search(r"(^|[^a-z])ref", f) or "bibliograph" in f or re.search(r"\.bib(\.|$)", raw):
        return "references"
    if "abstract" in f: return "abstract"
    if "supp" in f or "extended_data" in f or "appendix" in f: return "supplementary"
    if "method" in f or "m&m" in f: return "Methods"
    if "fig" in f or "legend" in f: return "figure legend"
    if "table" in f: return "table"
    if "reporting" in f or "summary" in f: return "reporting summary"
    return "main text"


def find_reference_region(lines):
    """(start, end, note) line indices of the reference list, or None.

    The region ends at the next heading/caption, or — when the list is followed
    by a plain paragraph with no heading — at the first paragraph that does not
    look like a reference entry. The note is printed in the artifact so the
    boundary is never a silent cut.
    """
    start = None
    for i, ln in enumerate(lines):
        if REF_HEAD_RE.match(ln.strip()):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    note = "to end of file"
    prev_blank = True
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if not s:
            prev_blank = True
            continue
        if NUM_ENTRY_RE.match(s):
            prev_blank = False
            continue  # a numbered reference entry is never a section heading
        if STOP_SECTION_RE.match(s) or MD_HEADING_RE.match(s) or \
                FIG_CAPTION_RE.match(s) or TABLE_CAPTION_RE.match(s):
            end = j
            note = "ends at the next heading/caption (line %d)" % (j + 1)
            break
        if prev_blank and not looks_like_reference_entry(s) and len(s.split()) >= 5:
            end = j
            note = "ends at the first non-reference paragraph (line %d)" % (j + 1)
            break
        prev_blank = False
    return start, end, note


def ay_callout(m):
    """Normalise an author-year match into (raw, author string, year)."""
    if m.group("y1"):
        return m.group(0), m.group("a1"), m.group("y1")
    if m.group("y2"):
        return m.group(0), "%s and %s" % (m.group("a2"), m.group("a2b")), m.group("y2")
    return m.group(0), m.group("a3"), m.group("y3")


def parse_nums(inner):
    nums = []
    for part in re.split(r"[,;]", inner):
        part = part.strip()
        rm = re.match(r"(\d+)\s*[–-]\s*(\d+)$", part)
        if rm:
            a, b = int(rm.group(1)), int(rm.group(2))
            if 0 < b - a <= 200:
                nums.extend(range(a, b + 1))
            else:
                nums.append(part)
        elif part:
            try:
                nums.append(int(part))
            except ValueError:
                nums.append(part)
    return nums


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    work = os.path.abspath(args.work)
    out = os.path.abspath(args.out) if args.out else os.path.dirname(work.rstrip("/"))
    corpus = os.path.join(work, "corpus")
    art_dir = os.path.join(out, "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    if not os.path.isdir(corpus):
        print("ERROR: corpus dir not found: %s. Run convert_corpus.py first." % corpus)
        sys.exit(2)

    callouts = []       # every in-text citation instance
    ref_entries = []    # every reference-list entry
    bib_entries = []    # .bib entries
    suspect_brackets = []
    reference_notes = []

    for fname in sorted(os.listdir(corpus)):
        if not fname.endswith(".txt"):
            continue
        text = open(os.path.join(corpus, fname), encoding="utf-8", errors="replace").read()
        lines = text.split("\n")
        if fname.endswith(".bib.txt"):
            for m in BIB_ENTRY_RE.finditer(text):
                bib_entries.append({"file": fname, "key": m.group(1).strip()})
            continue

        region = find_reference_region(lines)
        if region is None and classify_context(fname) == "references":
            # Exporters often put the reference list in its own file and drop
            # the "References" heading. Without a region the whole list is
            # swept as prose, every numbered entry is read as a call-out, and
            # the real citations are reported as orphans.
            first = next((i for i, ln in enumerate(lines)
                          if looks_like_reference_entry(ln.strip())), 0)
            region = (first, len(lines), "reference-role file (no heading)")
        prev_line = ""
        if region:
            reference_notes.append("%s lines %d-%d (%s)" % (
                fname, region[0] + 1, region[1], region[2]))
        for li, raw in enumerate(lines, 1):
            in_refs = bool(region and region[0] <= li - 1 < region[1])
            if in_refs:
                em = REF_ENTRY_RE.match(raw)
                if em:
                    ref_entries.append({"file": fname, "line": li, "num": int(em.group(1)),
                                        "text": em.group(2).strip()[:200]})
                elif raw.strip():
                    s = raw.strip()
                    prev = ref_entries[-1] if ref_entries else None
                    if prev and prev["file"] == fname and prev_line.strip() and \
                            (s[:1].islower() or JOURNAL_TAIL_RE.match(s)):
                        prev["text"] = (prev["text"] + " " + s)[:300]  # wrapped entry
                    else:
                        ref_entries.append({"file": fname, "line": li, "num": None,
                                            "text": s[:200]})
                prev_line = raw
                continue
            prev_line = raw
            for m in NUM_CIT_RE.finditer(raw):
                before = raw[:m.start()].rstrip()
                if SUSPECT_PRECEDERS.search(before):
                    suspect_brackets.append({"file": fname, "line": li, "raw": m.group(0),
                                             "excerpt": raw.strip()[:120],
                                             "why": "bracketed range after a measurement word"})
                    continue
                callouts.append({"file": fname, "line": li, "raw": m.group(0),
                                 "refs": parse_nums(m.group(1)),
                                 "excerpt": raw.strip()[:120], "style": "numeric"})
            for m in AY_CIT_RE.finditer(raw):
                raw_cit, author, year = ay_callout(m)
                callouts.append({"file": fname, "line": li, "raw": raw_cit,
                                 "refs": ["%s %s" % (author, year)],
                                 "excerpt": raw.strip()[:120], "style": "author-year"})

    # ---- per-document bookkeeping (each numbered list is its own space)
    lists_by_file = defaultdict(list)
    for e in ref_entries:
        if e["num"] is not None:
            lists_by_file[e["file"]].append(e["num"])
    all_listed = {n for nums in lists_by_file.values() for n in nums}
    cited_by_file = defaultdict(list)
    for c in callouts:
        for r in c["refs"]:
            if isinstance(r, int):
                cited_by_file[c["file"]].append(r)
    all_cited = {n for nums in cited_by_file.values() for n in nums}

    orphan_callouts_by_file = {}
    for f, nums in cited_by_file.items():
        space = set(lists_by_file[f]) if f in lists_by_file else all_listed
        orphans = sorted({n for n in nums if n not in space})
        if orphans:
            orphan_callouts_by_file[f] = orphans
    orphan_callouts = sorted({n for nums in orphan_callouts_by_file.values() for n in nums})

    uncited_by_list = {}
    for f, nums in lists_by_file.items():
        # Per-document numbering space, mirroring the orphan check above: a
        # call-out in another document (cover letter, supplement) must not mask
        # an uncited entry of THIS document's list.
        space = set(cited_by_file[f]) if f in cited_by_file else all_cited
        uncited = sorted({n for n in nums if n not in space})
        if uncited:
            uncited_by_list[f] = uncited
    uncited_entries = sorted({n for nums in uncited_by_list.values() for n in nums})

    duplicate_entries = {}
    for f, nums in lists_by_file.items():
        dupes = {n: c for n, c in Counter(nums).items() if c > 1}
        if dupes:
            duplicate_entries[f] = dupes

    order_violations = []
    prev_by_file = defaultdict(int)
    for c in callouts:
        for r in c["refs"]:
            if isinstance(r, int):
                prev = prev_by_file[c["file"]]
                if r < prev:
                    order_violations.append({"file": c["file"], "line": c["line"],
                                             "raw": c["raw"],
                                             "issue": "citation %d after %d" % (r, prev)})
                prev_by_file[c["file"]] = max(prev, r)

    max_cited = max(all_cited) if all_cited else 0
    md = ["# M2 — CITATION INVENTORY (artifact)", "",
          "Reference-list regions read (boundary is explicit, never silent):",
          ] + (["- " + n for n in reference_notes] or ["- none"]) + [
          "",
          "## Reference-list entries (%d)" % len(ref_entries), "",
          "| # | file | line | entry (truncated) |", "|---|---|---|---|"]
    for e in ref_entries:
        md.append("| %s | %s | %d | %s |" % (e["num"] if e["num"] is not None else "—",
                                             e["file"], e["line"],
                                             e["text"].replace("|", "\\|")))
    md += ["", "## In-text call-outs (%d)" % len(callouts), "",
           "| file | line | call-out | refs | excerpt |", "|---|---|---|---|---|"]
    for c in callouts:
        md.append("| %s | %d | %s | %s | %s |" % (
            c["file"], c["line"], c["raw"].replace("|", "\\|"),
            ", ".join(str(r) for r in c["refs"]), c["excerpt"].replace("|", "\\|")))
    md += ["", "## Bibliography-file entries (%d)" % len(bib_entries), ""]
    for b in bib_entries:
        md.append("- %s :: %s" % (b["file"], b["key"]))
    md += ["", "## Auto-derived mismatches (audit each; one finding per instance)", "",
           "Each numbered reference list is its own numbering space — the checks below are per document.",
           "",
           "- Orphan call-outs (cited, not listed): %s" % (orphan_callouts or "none"),
           "  - per document: %s" % (orphan_callouts_by_file or "none"),
           "- Uncited entries (listed, never cited anywhere): %s" % (uncited_entries or "none"),
           "  - per list: %s" % (uncited_by_list or "none"),
           "- Duplicate entry numbers within one list: %s" % (duplicate_entries or "none"),
           "- Order violations (numeric style, within one document): %d" % len(order_violations),
           "- Max cited number: %d; entries listed: %d (across %d list(s))" % (
               max_cited, len(ref_entries), len(lists_by_file)),
           "- Author-year call-outs cannot be matched to a list mechanically — audit by hand.",
           "- Bracketed numbers skipped as measurement intervals: %d%s" % (
               len(suspect_brackets),
               "" if not suspect_brackets else " (recorded in the JSON as suspect_brackets, not silently dropped)")]

    with open(os.path.join(art_dir, "M2_citations.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(art_dir, "M2_citations.json"), "w", encoding="utf-8") as f:
        json.dump({"ref_entries": ref_entries, "callouts": callouts,
                   "bib_entries": bib_entries,
                   "orphan_callouts": orphan_callouts,
                   "orphan_callouts_by_file": orphan_callouts_by_file,
                   "uncited_entries": uncited_entries,
                   "uncited_entries_by_list": uncited_by_list,
                   "duplicate_entries": duplicate_entries,
                   "order_violations": order_violations,
                   "suspect_brackets": suspect_brackets}, f, indent=2)

    print("M2 artifact: %d ref entries (%d list(s)), %d call-outs. Orphans: %s | Uncited: %s" % (
        len(ref_entries), len(lists_by_file), len(callouts),
        orphan_callouts or "none", uncited_entries or "none"))


if __name__ == "__main__":
    main()
