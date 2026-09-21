#!/usr/bin/env python3
"""extract_numbers.py — M4 numbers & metrics consistency sweep.

Enumerates every labeled metric (p-values, n, AUC, percentages, CI, R²,
fold-changes), accession numbers, and software versions across the corpus, then
flags same-label / different-value conflicts across contexts (abstract vs
results vs figure legend vs supplementary).

Same-label, different-value conflicts (e.g. a p-value given as 0.021 in one
place and 0.031 in another for the same test) are the classic long-range miss;
the artifact makes them enumerable.

Contexts are derived from in-file section headings ("Abstract", "Results",
"Methods", "Figure legends", "Table 12", ...) with the filename role as
fallback, so a single-file manuscript still separates abstract from legends.
Reference-list regions are skipped, and detection resumes after them.

  OUT/artifacts/M4_numbers.md / .json

stdlib-only. Usage:
  python extract_numbers.py --work ./review/work [--out ./review]
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

LABEL_PATTERNS = [
    ("p-value", re.compile(r"\b[pP]\s*[=<>≤≥]\s*(\d+\.?\d*(?:[eE][+-]?\d+)?)")),
    ("n", re.compile(r"\b[nN]\s*=\s*(\d+)\b")),
    ("AUC", re.compile(r"\bAU(?:C|ROC)\s*(?:was|is|of|=|:|approximately)?\s*(0?\.\d+|\d\.\d+)\b", re.I)),
    ("percentage", re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")),
    ("CI", re.compile(r"\bCI\s*[:=,]?\s*(\d+\.?\d*)\s*(?:[–-]|to)\s*(\d+\.?\d*)", re.I)),
    # The exponent is mandatory: without it a plain Pearson "r = 0.8" was
    # inventoried as R², and the M4 label was simply wrong.
    ("R2", re.compile(r"\bR(?:\^?2|²)\s*[:=]\s*(0?\.\d+|\d\.\d+)\b", re.I)),
    ("fold", re.compile(r"\b(\d+\.?\d*)[- ]?fold\b", re.I)),
]
ACCESSION_RE = re.compile(r"\b(GSE\d+|PRJNA\d+|SR[APRX]\d+|E-MTAB-\d+|zenodo\.\d+)\b", re.I)
VERSION_RE = re.compile(r"\b(?:v(?:er(?:sion)?)?\.?\s?)(\d+(?:\.\d+)+)\b", re.I)

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
# "Fig. 1 |" / "Fig. 1." / "Table 2:" are captions; "Fig. 1 shows …" is prose
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


def looks_like_reference_entry(s):
    if NUM_ENTRY_RE.match(s) or BULLET_ENTRY_RE.match(s):
        return True
    if YEAR_RE.search(s) or ENTRY_HINT_RE.search(s):
        return True
    return bool(AUTHOR_START_RE.match(s))

SECTION_PATTERNS = [
    ("cover letter", re.compile(r"^(?:cover letter|dear editor)\b", re.I)),
    ("title page", re.compile(r"^(?:title|title page|running title)\b", re.I)),
    ("abstract", re.compile(r"^abstract\b", re.I)),
    ("introduction", re.compile(r"^(?:introduction|background)\b", re.I)),
    ("main text", re.compile(r"^(?:results?|discussion|conclusions?)\b", re.I)),
    ("Methods", re.compile(r"^(?:methods?|materials and methods|experimental procedures|star methods)\b", re.I)),
    # End-anchored: a prose line that merely starts with "References are …"
    # is not a heading and must stay in the sweep (its numbers were silently
    # dropped when the prefix alone was enough).
    ("references", re.compile(r"^(?:references?|bibliography|reference list|literature cited)\s*$", re.I)),
    ("supplementary", re.compile(r"^(?:supplementary|extended data|appendix)\b", re.I)),
    ("figure legend", re.compile(r"^(?:figure legends?|legends?)\b", re.I)),
    ("table", re.compile(r"^(?:tables?|table legends?)\b", re.I)),
    # synthetic corpus markers written by convert_corpus.py
    ("table", re.compile(r"^sheet\b", re.I)),
    ("header", re.compile(r"^header\b", re.I)),
    ("footer", re.compile(r"^footer\b", re.I)),
    ("footnotes", re.compile(r"^footnotes?\b", re.I)),
    ("endnotes", re.compile(r"^endnotes?\b", re.I)),
]


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


def classify_context(fname):
    """Role of a corpus file, derived from its name (falls back to main text)."""
    raw = os.path.basename(fname).lower()
    f = re.sub(r"\.(?:txt|md)$", "", raw)
    f = re.sub(r"\.[a-z0-9]{1,5}$", "", f)
    if "cover" in f: return "cover letter"
    if "title" in f: return "title page"
    # A bibliography is a bibliography even when it belongs to the supplement:
    # "suppAll-d.bib" matched the "supp" heuristic below and was swept as
    # supplementary text, so cited papers' percentages and p-values entered the
    # M4 inventory as if they were the authors' own numbers.
    if re.search(r"(^|[^a-z])ref", f) or "bibliograph" in f or re.search(r"\.bib(\.|$)", raw):
        return "references"
    if "abstract" in f: return "abstract"
    if "supp" in f or "extended_data" in f or "appendix" in f: return "supplementary"
    if "method" in f or "m&m" in f: return "Methods"
    if "fig" in f or "legend" in f: return "figure legend"
    if "table" in f: return "table"
    if "reporting" in f or "summary" in f: return "reporting summary"
    return "main text"


def section_label(raw):
    """In-file section heading or display-item caption, else None."""
    s = raw.strip()
    if not s or len(s) > 60:
        return None
    if FIG_CAPTION_RE.match(raw):
        return "figure legend"
    if TABLE_CAPTION_RE.match(raw):
        return "table"
    s = re.sub(r"^#{1,6}\s*", "", s).rstrip(":.").strip()
    for label, pat in SECTION_PATTERNS:
        if pat.match(s):
            return label
    return None


def _similar_sentences(occs1, occs2):
    """Heuristic: same normalized sentence with different values, or same test
    name appears in both excerpts."""
    def norm(ex):
        ex = re.sub(r"\d", "#", ex)
        return re.sub(r"[^a-z#]", "", ex.lower())
    for o1 in occs1[:3]:
        for o2 in occs2[:3]:
            n1, n2 = norm(o1["excerpt"]), norm(o2["excerpt"])
            if n1 and (n1 == n2 or (len(n1) > 40 and n1[:40] == n2[:40])):
                return True
            toks1 = set(re.findall(r"[A-Za-z]{4,}", o1["excerpt"].lower()))
            toks2 = set(re.findall(r"[A-Za-z]{4,}", o2["excerpt"].lower()))
            shared = toks1 & toks2
            if len(shared) >= 4 and "respectively" not in (o1["excerpt"] + o2["excerpt"]):
                return True
    return False


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
        print("ERROR: corpus dir not found: %s" % corpus)
        sys.exit(2)

    metrics = defaultdict(list)     # (label, value) -> occurrences
    accessions = defaultdict(list)
    versions = defaultdict(list)
    reference_notes = []

    for fname in sorted(os.listdir(corpus)):
        if not fname.endswith(".txt"):
            continue
        role = classify_context(fname)
        if role == "references":
            continue  # a reference list is not the authors' own metric source
        lines = open(os.path.join(corpus, fname), encoding="utf-8", errors="replace").read().split("\n")
        region = find_reference_region(lines)
        if region:
            reference_notes.append("%s lines %d-%d (%s)" % (
                fname, region[0] + 1, region[1], region[2]))
        current = role
        for li, raw in enumerate(lines, 1):
            if region and region[0] <= li - 1 < region[1]:
                continue
            label = section_label(raw)
            if label == "references":
                continue  # heading line; the region covers the list itself
            if label:
                current = label
            elif current == "references":
                current = role  # never stay stuck on the reference section
            if raw.lstrip().startswith("### "):
                continue  # synthetic corpus marker (sheet/header/footer)
            ctx = current
            for label, pat in LABEL_PATTERNS:
                for m in pat.finditer(raw):
                    val = m.group(1) if m.lastindex else m.group(0)
                    if label == "percentage" and re.match(
                            r"\s*(?:CI|confidence)\b", raw[m.end():], re.I):
                        continue  # "95% CI" is a confidence level, not a metric
                    if label == "CI" and m.lastindex and m.group(2):
                        val = "%s-%s" % (m.group(1), m.group(2))
                    metrics[(label, str(val))].append({
                        "file": fname, "line": li, "context": ctx,
                        "excerpt": raw.strip()[:120]})
            for m in ACCESSION_RE.finditer(raw):
                accessions[m.group(1)].append({"file": fname, "line": li,
                                               "excerpt": raw.strip()[:120]})
            for m in VERSION_RE.finditer(raw):
                versions[m.group(1)].append({"file": fname, "line": li,
                                             "excerpt": raw.strip()[:120]})

    # conflicts: same label, different values, in different contexts/files
    by_label = defaultdict(lambda: defaultdict(list))
    for (label, val), occs in metrics.items():
        by_label[label][val].extend(occs)
    conflicts = []
    candidates = []
    for label, vals in by_label.items():
        if len(vals) < 2:
            continue
        # 1) near-identical sentences with different values → strong conflict
        for v1, o1 in vals.items():
            for v2, o2 in vals.items():
                if v1 < v2 and _similar_sentences(o1, o2):
                    conflicts.append({"label": label, "values": [v1, v2],
                                      "occ1": o1[0], "occ2": o2[0]})
        # 2) same label, different values across contexts → audit candidate
        #    (abstract vs results vs legend is the classic long-range miss)
        if label in ("p-value", "AUC", "R2", "CI", "n"):
            vals_by_ctx = {}
            for v, occs in vals.items():
                for o in occs:
                    vals_by_ctx.setdefault(o["context"], set()).add(v)
            multi = any(len(v) > 1 for v in vals_by_ctx.values())
            differs_across = len({frozenset(v) for v in vals_by_ctx.values()}) > 1
            if multi or differs_across:
                candidates.append({
                    "label": label,
                    "values_by_context": {k: sorted(v) for k, v in vals_by_ctx.items()},
                    "note": "same label reported with different values across contexts — audit against the conflict priority"})

    md = ["# M4 — NUMBERS & METRICS INVENTORY (artifact)", "",
          "Reference-list regions skipped (boundary is explicit, never silent):",
          ] + (["- " + n for n in reference_notes] or ["- none"]) + [
          "",
          "## Labeled metrics", "",
          "| label | value | occurrences (file:line, context) |", "|---|---|---|"]
    for (label, val), occs in sorted(metrics.items()):
        locs = "; ".join("%s:%d (%s)" % (o["file"], o["line"], o["context"]) for o in occs[:12])
        md.append("| %s | %s | %s |" % (label, val, locs.replace("|", "\\|")))
    md += ["", "## Accession numbers", "", "| accession | occurrences |", "|---|---|"]
    for acc, occs in sorted(accessions.items()):
        locs = "; ".join("%s:%d" % (o["file"], o["line"]) for o in occs[:12])
        md.append("| %s | %s |" % (acc, locs))
    md += ["", "## Software versions", "", "| version | occurrences |", "|---|---|"]
    for v, occs in sorted(versions.items()):
        locs = "; ".join("%s:%d" % (o["file"], o["line"]) for o in occs[:12])
        md.append("| %s | %s |" % (v, locs))
    md += ["", "## Auto-flagged same-label value conflicts (audit each)", ""]
    if conflicts:
        for c in conflicts:
            md.append("- **%s**: %s vs %s — %s:%d vs %s:%d" % (
                c["label"], c["values"][0], c["values"][1],
                c["occ1"]["file"], c["occ1"]["line"], c["occ2"]["file"], c["occ2"]["line"]))
    else:
        md.append("- none auto-flagged.")
    md += ["", "## Cross-context value divergences (audit each against the conflict priority)", ""]
    if candidates:
        for c in candidates:
            md.append("- **%s** — %s" % (c["label"], "; ".join(
                "%s: [%s]" % (ctx, ", ".join(vs)) for ctx, vs in c["values_by_context"].items())))
    else:
        md.append("- none.")

    with open(os.path.join(art_dir, "M4_numbers.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(art_dir, "M4_numbers.json"), "w", encoding="utf-8") as f:
        json.dump({"metrics": [{"label": k[0], "value": k[1], "occurrences": v}
                               for k, v in sorted(metrics.items())],
                   "accessions": dict(accessions), "versions": dict(versions),
                   "auto_conflicts": conflicts,
                   "cross_context_divergences": candidates}, f, indent=2)
    print("M4 artifact: %d metric values, %d accessions, %d versions, %d conflicts, %d cross-context divergence candidates." % (
        len(metrics), len(accessions), len(versions), len(conflicts), len(candidates)))


if __name__ == "__main__":
    main()
