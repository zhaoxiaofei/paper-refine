#!/usr/bin/env python3
"""The 2026-10-15 debug round: the candidates the independent audits of
`2a5bd98` reproduced on this tree.

Every check below is a defect an audit document named and this round
reproduced; each one fails on the tree before its patch:

  * FMT-R1's locator test read prose as an article number ("Volume 11-2020,
    online (2020)" lost its volume and gained no page) and duplicated a
    bracketed one ("Volume 11-2020 (565825)");
  * `load_bib_facts` scanned `%` comments as fields (a commented
    `% pages = {111}` OVERWROTE the live `pages = {7}`, a `}` inside a comment
    closed the entry, an escaped `%` dropped it, and a `}` inside a quoted
    title truncated it);
  * the cover-letter name tests were substring tests: `discovery.docx`,
    `coverage_stats.docx` and `newsletter.docx` named the COVER LETTER, and a
    reply file whose name contained "cover" was forced back into the
    submission runs;
  * the lenient JSON reader returned a trailing in-prose EXAMPLE instead of the
    document;
  * the TOML reader kept escape backslashes, dropped a legal `#` comment inside
    the args array, and did not decode the `command` string;
  * the attempt-history transcript printed `[0]` of a STRING (one character);
  * `_skeleton_titles` inserted an advisory section at an index computed
    against the ORIGINAL list, landing it before its predecessor;
  * the reconciliation accepted two rows for one concern id (set arithmetic);
  * the redlines adapter's class-method probe let a backend `sys.exit(1)` leave
    the partial OUT on disk (the `main` probe already dropped it);
  * `_set_wt_text` left an existing `xml:space="default"` in place while
    writing boundary whitespace, which Word then drops;
  * `extract_occurrences` refused the padded decimal form ("0.0310") its own
    header promises;
  * PKG-2 never opened a `.docx`, dropped a `key=path` reference, truncated a
    `+` or space-carrying path, and could not see a backslash separator;
  * the `.logging-*` fallback walked the base table-deep but the candidate
    top-level only, printing phantom `[BEFORE: ...]` markers for unchanged
    table paragraphs;
  * the content token was NOT stable under the documented token-less append
    (rename `refs.bib` to `refs-<T>.bib`, repoint the bibliography command);
  * `count_words` gave a profile with several article types and no default the
    LAST type's caps (the pipeline's own rule is the first);
  * the scoped (major/minor) round published its winner into a LIVE directory,
    so a stale file in it survived into the published digest;
  * `available_venue_profiles` hid a profile whose id duplicated another's.

`PAPER_WS` retargets the suite at another copy of the tree.
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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
REVIEW_SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
REVISE_SCRIPTS = WS / "paper-skills" / "paper-revise" / "scripts"
STUB = HERE / "stub_agent.py"
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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("nb_dbg1015", WS / "paper_pipeline.py")
fmt = _load("fmt_dbg1015", WS / "paper_docx_format.py")
rt = _load("rt_dbg1015", REVISE_SCRIPTS / "revision_token.py")
cc = _load("cc_dbg1015", REVIEW_SCRIPTS / "convert_corpus.py")
SKILL_MODULES = {
    "count_words.py": ("is_evidence_path", _load("cw_dbg1015", REVIEW_SCRIPTS / "count_words.py")),
    "extract_acronyms.py": ("is_evidence_name",
                            _load("ea_dbg1015", REVIEW_SCRIPTS / "extract_acronyms.py")),
    "extract_citations.py": ("is_non_manuscript",
                             _load("ec_dbg1015", REVIEW_SCRIPTS / "extract_citations.py")),
    "extract_numbers.py": ("is_non_manuscript",
                           _load("en_dbg1015", REVIEW_SCRIPTS / "extract_numbers.py")),
    "extract_occurrences.py": ("is_non_manuscript",
                               _load("eo_dbg1015", REVIEW_SCRIPTS / "extract_occurrences.py")),
    "enumerate_conventions.py": ("_non_manuscript",
                                 _load("env_dbg1015", REVIEW_SCRIPTS / "enumerate_conventions.py")),
}

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def doc(body: str) -> str:
    return f'<w:document {W_NS}><w:body>{body}</w:body></w:document>'


def para(text: str) -> str:
    return f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'


DONG = [{"key": "dong2020", "first_family": "Dong", "author": "Dong, Xiao",
         "title": "SCCNV: a software tool", "year": "2020", "volume": "11",
         "pages": "565825", "doi": "10.3389/fgene.2020.565825"}]


# ---------------------------------------------------------------------------
# 1. FMT-R1: prose is not a locator, a bracketed number is
# ---------------------------------------------------------------------------

def test_fmt_r1_locator():
    print()
    print("== P1 the FMT-R1 locator test ==")
    for tail, want in (
            ("Volume 11-2020, online (2020).", "11, 565825 online (2020)."),
            ("Volume 11-2020, in press (2020).", "11, 565825 in press (2020)."),
            ("Volume 11-2020 (565825).", "11 (565825)."),
            ("Volume 11-2020: 565825 (2020).", "11: 565825 (2020)."),
            ("Volume 11-2020, 565825 (2020).", "11, 565825 (2020)."),
            ("Volume 11-2020, (2020).", "11, 565825 (2020).")):
        xml = doc(para("15.Dong, X. et al. SCCNV tool. Front. Genet. " + tail))
        res = fmt.repair_reference_entries(xml, DONG)
        joined = " ".join(fmt.text_of(p[2]) for p in fmt.paragraphs(res["xml"]))
        got = joined.split("Front. Genet. ")[-1]
        check(f"P1 {tail!r} -> {want!r}", got == want, got)


# ---------------------------------------------------------------------------
# 2. load_bib_facts: comments, escapes, quoted braces
# ---------------------------------------------------------------------------

def test_bib_facts_comments_and_quotes():
    print()
    print("== P2 the .bib parser reads comments, escapes and quoted braces ==")
    tmp = scratch("dbg1015_bib_")
    cases = {
        "commented_field": (
            "@article{a,\n  title = {T},\n  pages = {7},\n  % pages = {111}\n"
            "  volume = {3}, year = {2020}\n}\n", "a", {"pages": "7"}),
        "brace_in_comment": (
            "@article{b,\n  volume = {3}, % TODO: check the } special case\n"
            "  pages = {7},\n  year = {2021}\n}\n", "b", {"pages": "7", "year": "2021"}),
        "escaped_percent": (
            "\\% @article{c,\n  title = {T},\n  pages = {9}, year = {2022}\n}\n",
            "c", {"pages": "9"}),
        "brace_in_quotes": (
            '@article{e,\n  title = "A title with a } brace",\n  pages = {6},\n'
            "  year = {2024}\n}\n", "e", {"title": "A title with a } brace", "pages": "6"}),
        # A `%` INSIDE a brace value is data, not a comment: the entry-body
        # level is where BibTeX allows one, and treating the brace-level `%` as
        # a comment destroyed the field it sits in (and, with the rest of the
        # entry on the next line, its live `pages`/`year` too).
        "percent_in_braces": (
            "@article{g,\n  title = {A 50% effect},\n  pages = {7},\n  year = {2020}\n}\n",
            "g", {"title": "A 50% effect", "pages": "7", "year": "2020"}),
        # An ODD number of quote characters inside a brace value (an inch mark)
        # must not unbalance the entry scan: the quote is a delimiter only at
        # the entry level, so the entries after it are still separate records.
        "inch_mark_in_braces": (
            '@article{h,\n  title = {A 5" incision},\n  pages = {7}, year = {2020}\n}\n'
            '@article{i,\n  title = {Second},\n  pages = {8}, year = {2021}\n}\n',
            "i", {"title": "Second", "pages": "8", "year": "2021"}),
    }
    for label, (text, key, want) in cases.items():
        p = tmp / f"{label}.bib"
        p.write_text(text, encoding="utf-8")
        facts = {r["key"]: r for r in fmt.load_bib_facts([p])}
        got = facts.get(key) or {}
        check(f"P2 {label}", all(got.get(k) == v for k, v in want.items()),
              str({k: got.get(k) for k in want}))
    q = tmp / "inch_mark_in_braces.bib"
    first = {r["key"]: r for r in fmt.load_bib_facts([q])}.get("h") or {}
    check("P2 the inch-mark entry itself keeps its fields",
          first.get("title") == 'A 5" incision' and first.get("pages") == "7",
          str({k: first.get(k) for k in ("title", "pages")}))


# ---------------------------------------------------------------------------
# 3. the cover-letter WORD rule, in the OOXML side and in the six sweeps
# ---------------------------------------------------------------------------

def test_cover_letter_word_rule():
    print()
    print("== P3 a cover letter is a WORD, not a substring ==")
    for name, want in (("cover_letter.docx", True), ("coverLetter.docx", True),
                       ("plainLetter.docx", True),
                       ("letter_to_the_editor.docx", True), ("cover_letters.docx", True),
                       ("response_to_reviewers_letter.docx", False),
                       ("decision_letter.docx", False), ("discovery.docx", False),
                       ("coverage_stats.docx", False), ("newsletter.docx", False),
                       ("recovered_notes.txt", False)):
        got = fmt.is_cover_letter_doc(name)
        check(f"P3 is_cover_letter_doc({name!r}) is {want}", got == want, str(got))

    names = ["cover_letter_response.md", "cover_letter.md", "coverLetter.md",
             "RESPONSE_TO_REVIEWERS.md", "reviewer_response_covering_points.md",
             "methods.md", "discovery.md", "coverage_table.txt",
             "recovered_samples.md", "newsletter.md"]
    verdicts = {n: {s: bool(getattr(m, f)(n)) for s, (f, m) in SKILL_MODULES.items()}
                for n in names}
    check("P3 the six sweeps agree on every name",
          all(len(set(v.values())) == 1 for v in verdicts.values()), str(verdicts))
    for name in ("cover_letter.md", "coverLetter.md", "cover_letter_response.md"):
        check(f"P3 {name} is a submission document everywhere",
              all(not v for v in verdicts[name].values()), str(verdicts[name]))
    for name in ("discovery.md", "coverage_table.txt", "recovered_samples.md", "newsletter.md"):
        check(f"P3 {name} is not a cover letter (not forced into submission)",
              all(not v for v in verdicts[name].values()), str(verdicts[name]))
    check("P3 a reply that merely contains 'cover' stays a reply",
          all(v for v in verdicts["reviewer_response_covering_points.md"].values()),
          str(verdicts["reviewer_response_covering_points.md"]))
    cw = SKILL_MODULES["count_words.py"][1]
    check("P3 count_words.is_cover_letter follows the same rule",
          cw.is_cover_letter("", "coverage_table.md") is False
          and cw.is_cover_letter("", "cover_letter.md") is True)
    check("P3 the pipeline's is_non_manuscript_rel follows the same rule",
          nb.is_non_manuscript_rel("discovery.md") is False
          and nb.is_non_manuscript_rel("coverage_stats.md") is False)
    check("P3 convert_corpus.guess_role follows the same rule",
          cc.guess_role("discovery.md") != "cover letter"
          and cc.guess_role("coverage.csv") != "cover letter"
          and cc.guess_role("coverLetter.docx") == "cover letter")


# ---------------------------------------------------------------------------
# 4. the lenient JSON reader
# ---------------------------------------------------------------------------

def test_json_from_text():
    print()
    print("== P4 the lenient JSON reader returns the DOCUMENT ==")
    cases = [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Here it is: {"a": 1}', {"a": 1}),
        ('The schema is {"example": true}. And the data is: {"n": 12, "ok": true}',
         {"n": 12, "ok": True}),
        ('{"scores":[1,2,3],"decision":"accept"}\n'
         'Note the schema example is {"example": true}',
         {"scores": [1, 2, 3], "decision": "accept"}),
        ('The payload is {"n": 12, "ok": true}. Schema: {"example": true}',
         {"n": 12, "ok": True}),
        ('{"n": 12, "ok": true, "items": [1,2,3,4,5,6]}\n{"a": 1}',
         {"n": 12, "ok": True, "items": [1, 2, 3, 4, 5, 6]}),
        # a real marker file (stochastic-failure suite): prose around a document
        # that carries a nested object -- the OUTER object is the document.
        ('Here is the completion marker:\n'
         '{"stage": "revise", "run_id": "r1_a2_revise", "round": 1, '
         '"status": "complete", "summary": {"findings_total": 1, "fixed": 1}}\n'
         "Done.\n",
         {"stage": "revise", "run_id": "r1_a2_revise", "round": 1,
          "status": "complete", "summary": {"findings_total": 1, "fixed": 1}}),
        ("A" * 1000 + '{"a": 1}' + "B" * 1000, None),
        ('{"a": 1', None),
    ]
    for text, want in cases:
        got = nb._json_from_text(text, True)
        check(f"P4 {text[:48]!r}...", got == want, f"got={got!r} want={want!r}")


# ---------------------------------------------------------------------------
# 5. the TOML MCP reader
# ---------------------------------------------------------------------------

def test_toml_mcp_reader():
    print()
    print("== P5 the TOML MCP reader decodes escapes and comments ==")
    vals = [
        ('["say \\"hi\\"",]', ['say "hi"']),
        ('["C:\\\\Users\\\\foo",]', ["C:\\Users\\foo"]),
        ('["node", # interpreter\n "server.js"]', ["node", "server.js"]),
        ('["node", # a note with ] bracket\n "server.js"]', ["node", "server.js"]),
        ("['node', 'server.js']", ["node", "server.js"]),
        ('["say \'hi\'",]', ["say 'hi'"]),
        ('["\\q"]', None),
    ]
    for raw, want in vals:
        got = nb._toml_array_values(raw)
        check(f"P5 {raw!r}", got == want, f"got={got!r} want={want!r}")
    tmp = scratch("dbg1015_toml_")
    cfg = tmp / "config.toml"
    cfg.write_text(
        "[mcp_servers.docx-converter] # the operator's note\n"
        'command = "C:\\\\Program Files\\\\node.exe"\n'
        'args = ["node", # interpreter\n        "server.js",]\n', encoding="utf-8")
    real = nb.codex_config_path
    nb.codex_config_path = lambda: cfg
    try:
        spec = nb.mcp_server_spec("docx-converter")
    finally:
        nb.codex_config_path = real
    check("P5 a trailing comment on the header does not unconfigure the server",
          spec == {"command": "C:\\Program Files\\node.exe", "args": ["node", "server.js"]},
          str(spec))


# ---------------------------------------------------------------------------
# 6. the attempt-history transcript
# ---------------------------------------------------------------------------

def test_attempt_history_transcript():
    print()
    print("== P6 the attempt history prints the transcript PATH ==")
    tmp = scratch("dbg1015_attempts_")
    root = tmp / "root"
    root.mkdir()
    ctx = nb.Ctx(root)
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "attempts": {}}
    ctx.state["runs"] = {"r1_w1": {
        "id": "r1_w1", "kind": "rewrite", "round": 1, "status": "done",
        "attempts_log": [{
            "attempt": 1, "ok": False, "duration": 1.0, "errors": ["boom"],
            "agent_log": "runs/r1_w1/logs/agent.log",
            "artifacts_lost": True}]}}
    ctx.cfg = {"rounds": 1, "judges": 1}
    lines = nb.attempt_history_lines(ctx)
    joined = "\n".join(lines)
    check("P6 no one-character transcript", "transcript: r\n" not in joined + "\n", joined[-200:])
    check("P6 the path is printed in full",
          "transcript: runs/r1_w1/logs/agent.log" in joined, joined[-200:])


# ---------------------------------------------------------------------------
# 7. the skeleton order
# ---------------------------------------------------------------------------

def test_skeleton_order():
    print()
    print("== P7 advisory sections land at their own positions ==")
    official = {"sections": [{"title": "Introduction", "mean_position": 0.1},
                             {"title": "Methods", "mean_position": 0.2},
                             {"title": "Results", "mean_position": 0.9}]}
    norm = {"sections": [{"title": "Ethics", "mean_position": 0.5},
                         {"title": "Data availability", "mean_position": 0.6}]}
    got = nb._skeleton_titles(norm, official)
    check("P7 the later section is not inserted before the earlier one",
          got == ["Introduction", "Methods", "Ethics", "Data availability", "Results"], str(got))


# ---------------------------------------------------------------------------
# 8. the reconciliation's one-row-per-concern rule
# ---------------------------------------------------------------------------

def test_concern_reconciliation_duplicates():
    print()
    print("== P8 two rows for one concern are refused ==")
    tmp = scratch("dbg1015_reconc_")
    root = tmp / "root"
    sb = tmp / "targeted_review"
    sb.mkdir(parents=True)
    fb_sb = tmp / "fb"
    fb_sb.mkdir(parents=True)

    class FakeCtx:
        def __init__(self):
            self.root = root

        def run(self, rid):
            return {"id": rid}

        def sandbox_of(self, rec):
            return fb_sb

    (fb_sb / "concerns").mkdir(parents=True)
    (fb_sb / "concerns" / "JF_concerns.json").write_text(
        json.dumps({"concerns": [{"id": "C1", "text": "a"}, {"id": "C2", "text": "b"}]}),
        encoding="utf-8")
    (sb / nb.TARGETED_REVIEW_DIR).mkdir(parents=True)
    (sb / nb.TARGETED_REVIEW_DIR / "concerns_reconciled.json").write_text(json.dumps({
        "rows": [{"id": "C1", "status": "manual", "rationale": "x"},
                 {"id": "C2", "status": "manual", "rationale": "y"},
                 {"id": "C2", "status": "not-applicable", "rationale": "z"}]}),
        encoding="utf-8")
    probs = nb.journal_review_coverage_problems(FakeCtx(), {"round": 1}, sb,
                                                {"findings": []})
    check("P8 the duplicate concern row is reported",
          any("MORE THAN ONCE" in p for p in probs), str(probs))


# ---------------------------------------------------------------------------
# 9. the redlines adapter's class-method probe
# ---------------------------------------------------------------------------

def test_redlines_class_systemexit():
    print()
    print("== P9 a backend class that exits leaves no partial OUT ==")
    tmp = scratch("dbg1015_redlines_")
    stubpkg = tmp / "stubpkg"
    stubpkg.mkdir()
    (stubpkg / "redlines.py").write_text(
        "import sys\n"
        "class DocxRedlines:\n"
        "    def __init__(self, base, revised):\n"
        "        pass\n"
        "    def output_docx(self, out):\n"
        "        open(out, 'wb').write(b'PARTIAL')\n"
        "        sys.exit(1)\n", encoding="utf-8")
    (tmp / "base.docx").write_bytes(b"x")
    (tmp / "rev.docx").write_bytes(b"y")
    out = tmp / "out.docx"
    env = dict(os.environ, PYTHONPATH=str(stubpkg))
    proc = subprocess.run([sys.executable, str(WS / "paper_redlines_adapter.py"),
                           "base.docx", "rev.docx", "out.docx"],
                          cwd=str(tmp), env=env, capture_output=True, text=True)
    check("P9 the probe reports the documented 'no supported interface' code",
          proc.returncode == 5, f"rc={proc.returncode} err={proc.stderr[-200:]}")
    check("P9 the partial OUT was dropped", not out.exists(), str(out.exists()))


# ---------------------------------------------------------------------------
# 10. xml:space
# ---------------------------------------------------------------------------

def test_xml_space_default():
    print()
    print("== P10 a 'default' xml:space is rewritten when whitespace is written ==")
    para_xml = ('<w:p><w:r><w:t xml:space="default">Volume 11-2020, </w:t></w:r>'
                '<w:r><w:t>565825 (2020).</w:t></w:r></w:p>')
    out = fmt._replace_text_in_para(para_xml, "Volume 11-2020, ", "11, 565825 ")
    check("P10 the trailing space is preserved now",
          out is not None and 'xml:space="preserve"' in out and "default" not in out,
          str(out)[:200])
    single = ("<w:p><w:r><w:t xml:space='default'>Volume 11-2020, </w:t></w:r>"
              "<w:r><w:t>565825 (2020).</w:t></w:r></w:p>")
    out2 = fmt._replace_text_in_para(single, "Volume 11-2020, ", "11, 565825 ")
    check("P10 the single-quoted spelling is rewritten too",
          out2 is not None and 'xml:space="preserve"' in out2, str(out2)[:200])


# ---------------------------------------------------------------------------
# 11. the padded occurrence form
# ---------------------------------------------------------------------------

def test_occurrence_padded_value():
    print()
    print("== P11 the padded decimal form is an occurrence ==")
    eo = SKILL_MODULES["extract_occurrences.py"][1]
    pat = eo.variant_pattern("0.031", "value")
    check("P11 '0.0310' matches", bool(pat.search("0.0310")))
    check("P11 '.0310' matches", bool(pat.search(".0310")))
    check("P11 '0.03100' matches", bool(pat.search("0.03100")))
    check("P11 '0.0311' is a DIFFERENT value", not pat.search("0.0311"))
    check("P11 'x0.031' is not the value", not pat.search("x0.031"))
    pat12 = eo.variant_pattern("12", "value")
    check("P11 a trailing zero after a whole number still matters",
          bool(pat12.search("12")) and not pat12.search("120"))


# ---------------------------------------------------------------------------
# 12. PKG-2
# ---------------------------------------------------------------------------

def test_pkg2_reference_rows():
    print()
    print("== P12 the PKG-2 scan reads the prose forms and the .docx ==")
    tmp = scratch("dbg1015_pkg2_")
    (tmp / "raw_data").mkdir()
    (tmp / "code").mkdir()
    (tmp / "README.md").write_text("x", encoding="utf-8")
    (tmp / "raw_data" / "tables.tsv").write_text("x", encoding="utf-8")
    (tmp / "code" / "analysis.py").write_text("x", encoding="utf-8")
    (tmp / "notes.md").write_text(
        "Build with SRC=code/analysis.py and see file=README.md.\n"
        "Mirror: https://github.com/team/repo/README.md\n"
        "Query: https://example.com/get?file=README.md\n"
        "See raw_data/my table.tsv and code/foo+bar.py\n"
        "See raw_data\\tables.tsv\n", encoding="utf-8")
    refs = sorted(r["reference"] for r in nb.non_submitted_reference_rows(tmp, ["raw_data", "code"]))
    check("P12 a key=path reference is reported",
          "code/analysis.py" in refs and "README.md" in refs, str(refs))
    check("P12 no URL tail and no URL query value", refs.count("README.md") == 1, str(refs))
    check("P12 a path with '+' is reported in full", "code/foo+bar.py" in refs, str(refs))
    check("P12 a path with a space is reported in full",
          "raw_data/my table.tsv" in refs, str(refs))
    check("P12 a backslash separator is reported",
          any(r.startswith("raw_data") and "tables.tsv" in r for r in refs), str(refs))
    bs = [r for r in nb.non_submitted_reference_rows(tmp, ["raw_data", "code"])
          if r["file"] == "notes.md" and "\\" in r["reference"]]
    check("P12 a backslash reference gets the AREA's advice, not the README rule",
          bool(bs) and all("read-only input" in r["detail"] for r in bs), str(bs[:1])[:300])
    with zipfile.ZipFile(tmp / "manuscript.docx", "w") as z:
        z.writestr("word/document.xml", doc(
            para("See raw_data/tables.tsv and README.md")))
    docx_rows = nb.non_submitted_reference_rows(tmp, ["raw_data", "code"])
    check("P12 the .docx the journal reads is scanned",
          any(r["file"] == "manuscript.docx"
              and r["reference"] == "raw_data/tables.tsv" for r in docx_rows),
          str([r["reference"] for r in docx_rows if r["file"] == "manuscript.docx"]))


# ---------------------------------------------------------------------------
# 13. the .logging-* fallback's traversal
# ---------------------------------------------------------------------------

def _make_docx(path: Path, paras: list, table: list = None) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    if table:
        body += ('<w:tbl><w:tr><w:tc>' + "".join(
            f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in table)
            + '</w:tc></w:tr></w:tbl>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", doc(body))


def test_logging_fallback_tables():
    print()
    print("== P13 an unchanged table paragraph gets no [BEFORE:] marker ==")
    tmp = scratch("dbg1015_fallback_")
    _make_docx(tmp / "base.docx", ["Intro.", "Changed paragraph."],
               table=["Table cell A", "Table cell B"])
    _make_docx(tmp / "cand.docx", ["Intro.", "CHANGED paragraph."],
               table=["Table cell A", "Table cell B"])
    res = nb.write_docx_logging_fallback(tmp / "base.docx", tmp / "cand.docx",
                                         tmp / "out.docx", "original", "stub reason")
    xml = ""
    if res.get("ok") and (tmp / "out.docx").is_file():
        with zipfile.ZipFile(tmp / "out.docx") as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    check("P13 the real difference is still marked",
          "[BEFORE: Changed paragraph.]" in xml and "[AFTER: CHANGED paragraph.]" in xml,
          xml[:300])
    check("P13 no phantom marker for the unchanged table text",
          "[BEFORE: Table cell A]" not in xml and "[BEFORE: Table cell B]" not in xml,
          xml[:400])


# ---------------------------------------------------------------------------
# 14. the content token under the token-less append
# ---------------------------------------------------------------------------

def test_token_append_stability():
    print()
    print("== P14 applying the token (append path) does not change it ==")
    tmp = scratch("dbg1015_token_")
    (tmp / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nSee \\cite{a}.\n"
        "\\bibliography{refs}\n\\end{document}\n", encoding="utf-8")
    (tmp / "refs.bib").write_text("@article{a, title={T}, year={2020}}\n", encoding="utf-8")
    before = rt.revision_token(tmp)["token"]
    twin = nb.revision_token_for_dir(tmp)["token"]
    check("P14 the tool and the pipeline twin agree", before and before == twin,
          f"{before} vs {twin}")
    (tmp / "refs.bib").rename(tmp / f"refs-{before}.bib")
    (tmp / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nSee \\cite{a}.\n"
        f"\\bibliography{{refs-{before}}}\n\\end{{document}}\n", encoding="utf-8")
    check("P14 the token is stable after the append",
          rt.revision_token(tmp)["token"] == before,
          f"{rt.revision_token(tmp)['token']} vs {before}")
    check("P14 the pipeline twin is stable too",
          nb.revision_token_for_dir(tmp)["token"] == before,
          str(nb.revision_token_for_dir(tmp)["token"]))
    prose = scratch("dbg1015_token_prose_")
    (prose / "ms-a.tex").write_text("panel-a discussed in the text\n", encoding="utf-8")
    check("P14 a -a in prose is not a token and does not move the hash",
          nb.revision_token_for_dir(prose)["token"] == rt.revision_token(prose)["token"],
          f"{nb.revision_token_for_dir(prose)['token']}")


# ---------------------------------------------------------------------------
# 15. count_words article-type selection
# ---------------------------------------------------------------------------

def test_count_words_article_type():
    print()
    print("== P15 no default article type means the FIRST type (the pipeline rule) ==")
    tmp = scratch("dbg1015_cw_")
    prof = tmp / "multi.json"
    prof.write_text(json.dumps({
        "id": "multi", "label": "Multi", "article_types": [
            {"id": "brief", "label": "Brief", "length_limits": {
                "abstract": {"base": 110, "relaxation": 1.0},
                "main_text": {"base": 1875, "relaxation": 1.0}}},
            {"id": "research", "label": "Research", "length_limits": {
                "abstract": {"base": 150, "relaxation": 1.0},
                "main_text": {"base": 3000, "relaxation": 1.0}}}]}), encoding="utf-8")
    document = tmp / "m.md"
    document.write_text("Abstract\n" + "word " * 100 + "\nMethods\nrest\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REVIEW_SCRIPTS / "count_words.py"),
                           str(document), "--venue-profile", str(prof), "--json",
                           "--section", "abstract"],
                          capture_output=True, text=True)
    got = json.loads(proc.stdout)["caps"] if proc.returncode == 0 else {}
    check("P15 the first type's caps are used",
          got.get("abstract") == 110 and got.get("main text") == 1875,
          f"rc={proc.returncode} caps={got}")


# ---------------------------------------------------------------------------
# 16. the scoped round publishes atomically
# ---------------------------------------------------------------------------

def test_scoped_winner_is_published_atomically():
    print()
    print("== P16 a stale file in round1_winner does not survive publication ==")
    tmp = scratch("dbg1015_scoped_")
    jr = _load("jr_lib_dbg1015", HERE / "journal_revision_modes_lib.py")
    src = jr.build_source(tmp)
    root = tmp / "root"
    r = jr.run_cli("setup", "--source", str(src), "--root", str(root),
                   "--revision-mode", "major", "--journal", "iScience")
    check("P16 setup succeeds", r.returncode == 0, r.stderr[-200:])
    stale = root / "round1_winner"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "STALE_FROM_A_CRASH.txt").write_text("old bytes\n", encoding="utf-8")
    r = jr.run_cli("run", "--root", str(root),
                   "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                   "--timeout", "300", "--retries", "0")
    check("P16 the scoped round completes", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    names = sorted(p.name for p in stale.iterdir()) if stale.is_dir() else []
    check("P16 the stale file is NOT part of the published winner",
          "STALE_FROM_A_CRASH.txt" not in names, str(names))
    check("P16 the published corpus is there", "manuscript.txt" in names, str(names))
    check("P16 no .tmp staging directory is left behind",
          not (root / "round1_winner.tmp").exists())


# ---------------------------------------------------------------------------
# 17. the venue-profile id collision
# ---------------------------------------------------------------------------

def test_venue_profile_duplicate_id():
    print()
    print("== P17 a profile that duplicates an id is listed, not hidden ==")
    tmp = scratch("dbg1015_venue_")
    d = tmp / "venue_profiles"
    d.mkdir()
    base = json.loads((WS / "venue_profiles" / "example-journal.json").read_text("utf-8"))
    for name, label in (("aaa.json", "First"), ("bbb.json", "Second")):
        prof = json.loads(json.dumps(base))
        prof["label"] = label
        (d / name).write_text(json.dumps(prof), encoding="utf-8")
    found = nb.available_venue_profiles(tmp)
    # Resolution is by FILE NAME (the 2026-10-25 F034 contract): the winner is
    # listed under the id `set-venue aaa` accepts, not under its duplicated
    # internal id.
    check("P17 the winner keeps its file-name id", found["aaa"]["label"] == "First",
          str(found.get("aaa", {}).get("label")))
    check("P17 the shadowed FILE is visible with its reason",
          "bbb" in found and "already provided by" in (found.get("bbb", {}).get("error") or ""),
          str(found.get("bbb", {}))[:200])


# ---------------------------------------------------------------------------
# 18. a proofing marker inside a Zotero field result
# ---------------------------------------------------------------------------

def test_zotero_prooferr_in_result():
    print()
    print("== P18 a w:proofErr inside a field result does not refuse the field ==")
    payload = ('{"citationID":"C1","properties":{"formattedCitation":"2"},'
               '"citationItems":[{"id":"i1","uris":["u/AAAA"]}]}')
    head = ('<w:document ' + W_NS + '><w:body><w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
            + payload + ' </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    tail = ('<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:body></w:document>')
    plain = head + '<w:r><w:t xml:space="preserve">2</w:t></w:r>' + tail
    proofed = (head + '<w:proofErr w:type="spellStart"/>'
               '<w:r><w:t xml:space="preserve">2</w:t></w:r>'
               '<w:proofErr w:type="spellEnd"/>' + tail)
    res_plain = fmt.zotero_refresh_document(plain, para_texts=[])
    check("P18 the plain field still refreshes",
          res_plain.get("changed") and res_plain.get("fields_fixed") == 1,
          str({k: res_plain.get(k) for k in ("changed", "fields_fixed", "skip")}))
    res_proof = fmt.zotero_refresh_document(proofed, para_texts=[])
    check("P18 the proofed field refreshes too (no 'no simple result runs')",
          res_proof.get("changed") and res_proof.get("fields_fixed") == 1,
          str({k: res_proof.get(k) for k in ("changed", "fields_fixed", "skip")}))


# ---------------------------------------------------------------------------
# 19. the XFA export carries every answer the report counts
# ---------------------------------------------------------------------------

def test_xfa_export_is_complete():
    print()
    print("== P19 the XFA export carries every answer the gate counts ==")
    import zlib
    tmp = scratch("dbg1015_xfa_")
    n = 401
    leaves = "".join(f"<f{i}>answer {i}</f{i}>" for i in range(n))
    packet = ("<xfa:datasets><xfa:data><form><Software>" + leaves
              + "</Software></form></xfa:data></xfa:datasets>")
    pdf = tmp / "big.pdf"
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj<</AcroForm 2 0 R/XFA[3 0 R]>>endobj\n"
                    b"stream\n" + zlib.compress(packet.encode("utf-8"))
                    + b"\nendstream\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    is_xfa, counted, _shell = fmt._xfa_dataset_report(pdf)
    exported = fmt.xfa_dataset_answers(pdf, limit=None)
    check("P19 the gate counts every leaf", is_xfa and counted == n, str(counted))
    check("P19 the export carries every counted answer",
          len(exported) == counted, f"{len(exported)} of {counted}")
    check("P19 the readable export names the LAST answer",
          f"answer {n - 1}" in fmt.xfa_export_text(pdf))
    check("P19 the bounded listing still honours its own limit",
          len(fmt.xfa_dataset_answers(pdf)) == 400)


# ---------------------------------------------------------------------------
# 20. the M19 note names the span it counted
# ---------------------------------------------------------------------------

def test_count_words_note_names_the_span():
    print()
    print("== P20 the M19 note does not claim a span that was not counted ==")
    cw = SKILL_MODULES["count_words.py"][1]
    with_heading = cw.sections("Introduction\nWe did a study.\n" + "word " * 300
                               + "\nMethods\nmore\n")
    note = with_heading[0][2]
    check("P20 a main-text heading is named, not 'the start of the document'",
          "after the main-text heading" in note, note)
    check("P20 the count itself is unchanged", with_heading[0][1] == 304,
          str(with_heading[0][1]))


def main() -> int:
    print("== 2026-10-15 debug round: the audit candidates reproduced on this tree ==")
    test_fmt_r1_locator()
    test_bib_facts_comments_and_quotes()
    test_cover_letter_word_rule()
    test_json_from_text()
    test_toml_mcp_reader()
    test_attempt_history_transcript()
    test_skeleton_order()
    test_concern_reconciliation_duplicates()
    test_redlines_class_systemexit()
    test_xml_space_default()
    test_occurrence_padded_value()
    test_pkg2_reference_rows()
    test_logging_fallback_tables()
    test_token_append_stability()
    test_count_words_article_type()
    test_scoped_winner_is_published_atomically()
    test_venue_profile_duplicate_id()
    test_zotero_prooferr_in_result()
    test_xfa_export_is_complete()
    test_count_words_note_names_the_span()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL 2026-10-15 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        cleanup()
    sys.exit(rc)
