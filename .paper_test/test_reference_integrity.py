#!/usr/bin/env python3
"""Reference integrity (M2's seed): the identifiers a reference list carries.

Run:  python3 .paper_test/test_reference_integrity.py

A reference entry can be perfectly formatted and still carry an identifier
belonging to a DIFFERENT work: a one-character corruption of a DOI
(`10.1890` -> `10.1891`, `gb-2019` -> `gb-2119`) leaves author, title, journal
and year untouched, so every format check passes and the citation sweep's
call-out/entry pairing sees nothing wrong. The class is only reachable two
ways, and this suite pins both:

  * the LOCAL signals -- reference_entries() reading each list shape the corpus
    hands over (numbered markers inside ONE joined paragraph, author-year
    entries inside one paragraph, `\\bibitem`, `@type{key,`, DOCX paragraphs the
    style map flags as the bibliography, and prose that must yield NOTHING);
    doi_year_token_signal() firing on the corrupted-year family only (never on
    a registrant prefix such as `10.1111` beside a 2011 entry); the same DOI on
    two entries; an entry that says it carries a DOI and states a broken one;
  * the RESOLVER side -- whats returned by lookup_kind() for a DOI (Crossref
    first, then the second registration agency, because a DataCite DOI is not
    an absent DOI), the probe that decides whether the engine runs at all (an
    HTTP error IS an answer -- the old probe named a 404ing record and turned
    the whole engine off, blaming the operator's network), and the comparison
    between the returned record and the entry (a record with a longer title
    must not make a correct, abbreviated entry look wrong; a record naming
    another work must).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TESTDIR = WS / ".paper_test"
spec = importlib.util.spec_from_file_location("paper_refint", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_refint"] = nb
spec.loader.exec_module(nb)
fmt = nb._format_module()

FAILS = []
TMPDIRS = []


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


def docs_of(text: str, name: str = "manuscript.md"):
    """The shape corpus_text_documents() hands over: one row per paragraph."""
    return [(name, [(p, False, False) for p in text.split("\n\n")])]


# ---------------------------------------------------------------------------
# 1. the list shapes the code can read
# ---------------------------------------------------------------------------
def test_parsing():
    print()
    print("== every reference-list shape the corpus hands over ==")
    joined = ("[1] Berg JK. Forest dynamics. Ecology 2016; 97:1-9. doi:10.1890/15-0001.1 "
              "[2] Smith A. Soil carbon. Genome Biol 2019; 20:1. doi:10.1186/gb-2119-0002 "
              "[3] Rossi P. Tree growth. Trees 2014; 28:1-8. doi:10.1007/s11295-014-0004")
    got = fmt.reference_entries(docs_of("## References\n\n" + joined))
    check("a numbered list inside ONE paragraph is split into entries",
          [l for _d, l, _b in got] == ["1", "2", "3"]
          and "Forest dynamics" in got[0][2] and "Soil carbon" in got[1][2],
          str([l for _d, l, _b in got]))
    check("each entry keeps its OWN year",
          [fmt._entry_year(b) for _d, _l, b in got] == ["2016", "2019", "2014"],
          str([fmt._entry_year(b) for _d, _l, b in got]))
    ay = ("Berg, J. K. (2016). Forest dynamics. Ecology, 97, 1-9. doi:10.1890/15-0001.1 "
          "Smith, A. (2019). Soil carbon. Genome Biology, 20, 1. doi:10.1186/gb-2019-0002")
    got_ay = fmt.reference_entries(docs_of("References\n\n" + ay))
    check("an author-year list inside ONE paragraph is split into entries",
          len(got_ay) == 2 and fmt._entry_year(got_ay[0][2]) == "2016"
          and fmt._entry_year(got_ay[1][2]) == "2019",
          str([(l, fmt._entry_year(b)) for _d, l, b in got_ay]))
    tex = ("\\begin{thebibliography}{9}\n"
           "\\bibitem{berg2016} Berg JK. Forest dynamics. Ecology 2016. doi:10.1890/15-0001.1\n"
           "\\bibitem{smith2019} Smith A. Soil carbon. Genome Biol 2019. doi:10.1186/gb-2019-0002\n"
           "\\end{thebibliography}")
    got_tex = fmt.reference_entries([("ms.tex", [(l, False, False) for l in tex.splitlines()])])
    check("`\\bibitem` keys label their own entries",
          [l for _d, l, _b in got_tex] == ["berg2016", "smith2019"],
          str([l for _d, l, _b in got_tex]))
    bib = ("@article{berg2016,\n  title={Forest dynamics},\n  doi={10.1890/15-0001.1}\n}\n"
           "@article{smith2019,\n  title={Soil carbon},\n  doi={10.1186/gb-2019-0002}\n}")
    got_bib = fmt.reference_entries([("refs.bib", [(l, False, False) for l in bib.splitlines()])])
    check("a .bib file yields its entries without any heading",
          [l for _d, l, _b in got_bib] == ["berg2016", "smith2019"],
          str([l for _d, l, _b in got_bib]))
    flagged = [("Berg, J. K. (2016). Forest dynamics. doi:10.1890/15-0001.1", True, False),
               ("Smith, A. (2019). Soil carbon. doi:10.1186/gb-2019-0002", True, False)]
    got_docx = fmt.reference_entries([("ms.docx", flagged)])
    check("DOCX paragraphs flagged as the bibliography are entries of their own",
          len(got_docx) == 2 and fmt._entry_year(got_docx[1][2]) == "2019")
    check("prose with no heading, no marker and no flagged paragraph yields NOTHING",
          fmt.reference_entries(docs_of("Some prose.\n\nMore prose with a year 2019.")) == [])
    mixed = docs_of("## References\n\n" + joined + "\n\n## Supplementary\n\n[1] Not an entry.")
    check("the region ends at the next section heading",
          len(fmt.reference_entries(mixed)) == 3, str(len(fmt.reference_entries(mixed))))


# ---------------------------------------------------------------------------
# 2. the local signals
# ---------------------------------------------------------------------------
def test_local_signals():
    print()
    print("== what the code can establish without the network ==")
    check("the corrupted-century DOI is caught (2019 entry, 2119 inside the DOI)",
          "2119" in fmt.doi_year_token_signal("10.1186/gb-2119-0002", "2019"),
          fmt.doi_year_token_signal("10.1186/gb-2119-0002", "2019"))
    check("a registrant PREFIX that looks like the year is never read as one",
          fmt.doi_year_token_signal("10.1111/2041-210X.00111", "2011") == "")
    check("a clean DOI whose suffix carries no year token stays silent",
          fmt.doi_year_token_signal("10.1890/15-0001.1", "2016") == ""
          and fmt.doi_year_token_signal("10.3732/apps.1600008", "2016") == "")
    check("a suffix token with different last two digits is a series number, not a year",
          fmt.doi_year_token_signal("10.1139/x07-108", "2007") == "")
    joined = ("[1] Berg JK. Forest dynamics. Ecology 2016. doi:10.1890/15-0001.1 "
              "[2] Berg JK. Forest dynamics. Ecology 2016. doi:10.1890/15-0001.1 "
              "[3] Smith A. Soil carbon. Genome Biol 2019. doi:10.1186/gb-2119-0002")
    rows = fmt.reference_integrity_rows(docs_of("## References\n\n" + joined))
    check("the same DOI on two entries is a signal on BOTH rows",
          [bool(r["signal"].startswith("duplicate-doi") or "duplicate-doi" in r["signal"])
           for r in rows[:2]] == [True, True]
          and rows[2]["signal"].startswith("the DOI's own year token"),
          str([r["signal"][:40] for r in rows]))
    check("each row carries the entry's own text for the resolver comparison",
          "Soil carbon" in rows[2]["text"] and "Forest dynamics" in rows[0]["text"])
    broken = fmt.reference_integrity_rows(docs_of(
        "## References\n\n[1] Doe J. A study. J Tests 2020. doi:SOMETHING-ELSE"))
    check("an entry that says it carries a DOI without stating a readable one is a signal",
          broken and broken[0]["identifier"] == "" and broken[0]["signal"] == "doi-malformed",
          str(broken[:1]))


# ---------------------------------------------------------------------------
# 3. the comparison between the resolver's record and the entry
# ---------------------------------------------------------------------------
def test_hit_comparison():
    print()
    print("== the resolved record against the entry's own text ==")
    entry = ("Chen L. Differential impacts of the southern pine beetle. "
             "Can J For Res 2007; 37:1-8. doi:10.1139/x07-008")
    long_record = {"date": 2007, "title": "Differential impacts of the southern pine beetle, "
                                          "<i>Dendroctonus frontalis</i>, on pine species in "
                                          "the southeastern United States"}
    check("a longer record title does NOT make a correct, abbreviated entry look wrong",
          fmt.reference_entry_hit_signal(entry, long_record) == "",
          fmt.reference_entry_hit_signal(entry, long_record))
    other = {"date": 2007, "title": "Growth and nutrient dynamics of Douglas-fir seedlings"}
    sig = fmt.reference_entry_hit_signal(entry, other)
    check("a record naming a DIFFERENT work is a signal, with the missing words named",
          "is not this entry's" in sig and "Growth" in sig, sig)
    check("a record whose year is two or more years away is a signal",
          "disagrees with the entry's 2007" in
          fmt.reference_entry_hit_signal(entry, {"date": 1999, "title": long_record["title"]}))
    check("one year apart is normal production lag, not a signal",
          fmt.reference_entry_hit_signal(entry, {"date": 2008, "title": long_record["title"]}) == "")
    check("a record too thin to judge stays silent",
          fmt.reference_entry_hit_signal(entry, {"date": 2007, "title": "Data"}) == ""
          and fmt.reference_entry_hit_signal(entry, {}) == "")


# ---------------------------------------------------------------------------
# 4. the lookup engine: DOI resolution, the second agency, and the probe
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(mapping: dict):
    """urlopen stub: the first key found in the URL decides the response.

    A value that is an Exception is RAISED (an HTTPError is how urllib reports
    a 404), anything else becomes a 200 response with that JSON body.
    """
    real = urllib.request.urlopen

    def fake(rq, timeout=None, **kw):
        url = getattr(rq, "full_url", str(rq))
        for frag, val in mapping.items():
            if frag in url:
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"unexpected URL {url}")

    urllib.request.urlopen = fake
    return real


def _http404(url="https://api.crossref.org/works/x"):
    return urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def _http404_with_body(url: str, payload: dict):
    """A 404 whose BODY carries the answer (how the handle registry replies)."""
    import io
    return urllib.error.HTTPError(url, 404, "Not Found", {},
                                  io.BytesIO(json.dumps(payload).encode("utf-8")))


def test_lookup_engine():
    print()
    print("== the DOI resolver, the second registration agency and the probe ==")
    real = _install_fake_urlopen({
        "api.crossref.org/works/10.9999/nope": _http404(),
        "api.crossref.org/works/10.1111/medra": _http404(),
        "api.crossref.org/works/10.5281/zenodo.1": _http404(),
        "doi.org/api/handles/10.9999/nope": _http404_with_body(
            "https://doi.org/api/handles/10.9999/nope", {"responseCode": 100}),
        "doi.org/api/handles/10.1111/medra": {
            "responseCode": 1,
            "values": [{"index": 1, "type": "URL",
                        "data": {"format": "string", "value": "https://example.org/medra"}}]},
        "api.datacite.org/dois/10.9999/nope": _http404(),
        "api.datacite.org/dois/10.1111/medra": _http404(),
        "api.datacite.org/dois/10.5281/zenodo.1": {
            "data": {"id": "10.5281/zenodo.1",
                     "attributes": {"titles": [{"title": "A real deposit"}],
                                    "publicationYear": 2020, "publisher": "Zenodo"}}},
        "api.crossref.org/works/10.1139/x07-008": {
            "message": {"title": ["Differential impacts of the southern pine beetle"],
                        "DOI": "10.1139/x07-008", "issued": {"date-parts": [[2007]]}}},
    })
    try:
        r = fmt.lookup_kind("doi", "10.1139/x07-008", timeout=5)
        check("a Crossref record is found, with its own year and title",
              r["verdict"] == "found" and r["hits"][0]["source"] == "crossref"
              and r["hits"][0]["date"] == 2007, str(r["hits"])[:120])
        r = fmt.lookup_kind("doi", "10.5281/zenodo.1", timeout=5)
        check("a DataCite DOI Crossref does not serve is FOUND, not absent",
              r["verdict"] == "found" and r["hits"][0]["source"] == "datacite"
              and r["hits"][0]["date"] == 2020, str(r)[:160])
        r = fmt.lookup_kind("doi", "10.9999/nope", timeout=5)
        check("`absent` is claimed only when both metadata agencies AND the "
              "handle registry answered no",
              r["verdict"] == "absent", str(r)[:120])
        r = fmt.lookup_kind("doi", "10.1111/medra", timeout=5)
        check("a DOI of another registration agency (mEDRA/CNKI/JaLC) is not `absent`",
              r["verdict"] == "found" and r["hits"][0]["source"] == "doi.org"
              and r["hits"][0]["url"] == "https://example.org/medra", str(r)[:160])
        # The probe: an HTTP error is an ANSWER (the API is reachable). The old
        # probe named a record that 404s and read the raised HTTPError as "no
        # network", which turned every lookup of every run into `skipped`.
        real2 = _install_fake_urlopen({"api.crossref.org/works?rows=0": {"message": {}}})
        try:
            nb._LOOKUP_PROBE.clear()
            check("a 200 answer means available", nb.lookup_network_available() is True)
            _install_fake_urlopen({"api.crossref.org/works?rows=0": _http404()})
            nb._LOOKUP_PROBE.clear()
            check("an HTTP error is still an ANSWER: the API is reachable",
                  nb.lookup_network_available() is True)
            _install_fake_urlopen({"api.crossref.org/works?rows=0":
                                   urllib.error.URLError("dns")})
            nb._LOOKUP_PROBE.clear()
            check("a connection failure is NOT available",
                  nb.lookup_network_available() is False)
        finally:
            urllib.request.urlopen = real2
            nb._LOOKUP_PROBE.clear()
    finally:
        urllib.request.urlopen = real


# ---------------------------------------------------------------------------
# 5. the seeded decision table and its gate
# ---------------------------------------------------------------------------
def test_seed_and_gate():
    print()
    print("== the seeded M2_references table, offline, and the disposition gate ==")
    tmp = scratch("paper_refint_seed_")
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "# Test\n\n## References\n\n"
        "[1] Berg JK. Forest dynamics. Ecology 2016. doi:10.1890/15-0001.1 "
        "[2] Smith A. Soil carbon. Genome Biol 2019. doi:10.1186/gb-2119-0002\n",
        encoding="utf-8")
    root = tmp / "root"
    import subprocess
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                           "--source", str(src), "--root", str(root), "--rounds", "1",
                           "--rewrites", "1", "--revises", "0", "--judges", "1",
                           "--integrators", "0x0", "--placeholder-lookup", "off"],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    ctx = nb.Ctx(root)
    ctx.load()
    sb = tmp / "sb"
    sb.mkdir()
    prov = nb.seed_provenance_pack(ctx, sb, [(root / "non_revised", "", nb.CORPUS_EXCLUDE_TOP)],
                                   {}, sb / "review" / "work",
                                   art=sb / "review" / "artifacts", where="review")
    art = sb / "review" / "artifacts" / "M2_references.md"
    work = sb / "review" / "work" / "M2_references.md"
    check("the seed counts one row per entry carrying a DOI",
          prov.get("references") == 2, str(prov.get("references")))
    check("the table is seeded into work/ and the review's artifacts/ alike",
          art.is_file() and work.is_file())
    body = art.read_text(encoding="utf-8")
    check("with the lookups off every row says `skipped` (never silently clean)",
          body.count("| skipped |") == 2, body.split("| # |")[-1][:200])
    check("the year-token signal reaches the seeded row",
          "2119" in body)
    check("the table is a gated decision table",
          "artifacts/M2_references.md" in nb.DECISION_ARTIFACTS)
    rep = nb.artifact_quality_report(sb / "review")
    check("the disposition gate flags the undisposed rows",
          "EMPTY disposition" in (rep.get("artifacts/M2_references.md") or [""])[0],
          str(rep.get("artifacts/M2_references.md"))[:120])
    filled = []
    for line in body.splitlines():
        cells = [c for c in line.strip("|").split("|")] if line.startswith("| ") else None
        if not cells or set(cells[0].strip()) <= set("-: ") or cells[0].strip() == "#":
            filled.append(line)
            continue
        while len(cells) < 9:
            cells.append(" ")
        cells[-1] = " OK — skipped (lookups off): re-derived by hand, resolves "
        filled.append("|" + "|".join(cells) + "|")
    art.write_text("\n".join(filled) + "\n", encoding="utf-8")
    rep2 = nb.artifact_quality_report(sb / "review")
    check("a disposed table passes the same gate",
          not rep2.get("artifacts/M2_references.md"),
          str(rep2.get("artifacts/M2_references.md"))[:120])


def main() -> int:
    try:
        test_parsing()
        test_local_signals()
        test_hit_comparison()
        test_lookup_engine()
        test_seed_and_gate()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} REFERENCE-INTEGRITY CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL REFERENCE-INTEGRITY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
