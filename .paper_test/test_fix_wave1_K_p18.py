#!/usr/bin/env python3
"""Fix-wave-1 regression checks for paper_pipeline_parts/p18_helpers.py (batch K_p18).

  F75  a nested LaTeX include is counted once (master only), not twice
  F96  `--only reviser0` / w0 / i0 dies instead of selecting a no-op session
  F119 a `[mcp_servers.x.env]` line inside a TOML multi-line string is not config
  F180 the _reference_entry_keys docstring no longer claims .bib/.bbl key compare
  F181 a fractional/bool style limit is dropped, not truncated
  F182 a malformed DOCX part yields no text instead of the hidden-run text
  F194 parse_only_stages('2:review') contributes the review stages
  F195 an unknown POSIX signal-0 failure reads as alive (never steal a lock)

Run: python3 .paper_test/test_fix_wave1_K_p18.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
_spec = importlib.util.spec_from_file_location("fbfix1122_k_pp", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(_spec)
sys.modules["fbfix1122_k_pp"] = pp
_spec.loader.exec_module(pp)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def test_f75_nested_include():
    d = scratch("f75_")
    (d / "chapters").mkdir()
    (d / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n"
        "\\input{chapters/intro}\n\\end{document}\n")
    (d / "chapters/intro.tex").write_text(
        "\\section{Intro}\nThis intro has exactly ten words of prose to count here.\n"
        "\\input{chapters/method}\n")
    (d / "chapters/method.tex").write_text(
        "\\section{Introduction}\nWe describe a method with another ten words of prose "
        "to count here.\n")
    r = pp.scan_lengths_in_sources([(d, "", ())], profile=None)
    docs = {row["document"] for row in r["rows"]}
    check("F75: a nested include is not counted as its own document",
          docs == {"main.tex"}, f"docs={sorted(docs)} skipped={r['skipped']}")
    check("F75: both nested children are recorded as included (skipped)",
          {"chapters/intro.tex", "chapters/method.tex"} <= set(r["skipped"]),
          str(r["skipped"]))
    # The direct-include case must keep working (child not double counted).
    d2 = scratch("f75b_")
    (d2 / "main.tex").write_text(
        "\\begin{document}\n\\section{Introduction}\n\\input{intro}\n\\end{document}\n")
    (d2 / "intro.tex").write_text(
        "\\section{Intro}\nTen words of intro prose that only count once total here.\n")
    r2 = pp.scan_lengths_in_sources([(d2, "", ())], profile=None)
    check("F75: a one-level include is still counted once, in the master",
          {row["document"] for row in r2["rows"]} == {"main.tex"}
          and "intro.tex" in r2["skipped"], str(r2["skipped"]))


def test_f96_zero_index():
    for raw in ("reviser0", "2:reviser0", "w0", "i0", "rewriter0"):
        try:
            pp.parse_only_spec(raw)
            died = False
        except SystemExit as e:
            died = e.code == 2
        check(f"F96: --only {raw} is a usage error", died)
    spec = pp.parse_only_spec("reviser1")
    check("F96: reviser1 still maps to the a2 arm",
          spec is not None and spec.sessions == {None: ["a2"]}, repr(spec and spec.sessions))


def test_f119_env_header_in_string():
    real = pp.codex_config_path

    def probe(toml):
        cfg = scratch("f119_") / "config.toml"
        cfg.write_text(toml)
        pp.codex_config_path = lambda: cfg
        return pp.mcp_server_spec("foo")

    try:
        injected = probe(
            "[mcp_servers.foo]\ncommand = \"npx\"\n"
            "args = ['''literal\n[mcp_servers.foo.env]\nEVIL = \"injected\"''', "
            "\"-y\", \"server.js\"]\n")
        check("F119: a header inside a multi-line string injects no env",
              "env" not in injected, repr(injected))
        subtable = probe(
            "[mcp_servers.foo]\ncommand = \"npx\"\nargs = [\"-y\"]\n\n"
            "[mcp_servers.foo.env]\nGOOD = \"yes\"\n")
        check("F119: a real env subtable is still read",
              subtable.get("env") == {"GOOD": "yes"}, repr(subtable))
    finally:
        pp.codex_config_path = real


def test_f180_docstring():
    doc = (pp._reference_entry_keys.__doc__ or "").lower()
    check("F180: the docstring no longer claims .bib/.bbl entries are compared by key",
          "compared by key" not in doc, doc)
    check("F180: the docstring states a .bib/.bbl database is not read here",
          ".bib" in doc and "not read" in doc, doc)


def test_f181_style_limits():
    real = pp.venue_profile_of
    try:
        class Prof:
            data = {"style_limits": {
                "paragraph_words": 3.9,
                "sentence_words": {"body": 12.9, "flag": True, "ok": 12}}}

        pp.venue_profile_of = lambda ctx=None, required=False: Prof()
        got = pp._venue_style_limits(object())
        check("F181: a fractional paragraph cap is dropped, not truncated to 3",
              "paragraph_words" not in got, repr(got))
        check("F181: a fractional/bool sentence bar is dropped; a real int is kept",
              got.get("sentence_words") == {"ok": 12}, repr(got))
    finally:
        pp.venue_profile_of = real


def test_f182_malformed_part():
    valid = (f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Visible</w:t></w:r>'
             '<w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden@example.com</w:t></w:r>'
             '</w:p></w:body></w:document>')
    bad = (f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:rPr><w:vanish/></w:rPr>'
           '<w:t>hidden@example.com</w:t>')
    check("F182: a valid part still returns its visible text only",
          pp._visible_docx_part_texts(valid) == ["Visible"],
          repr(pp._visible_docx_part_texts(valid)))
    check("F182: a malformed part yields no hidden-run text",
          pp._visible_docx_part_texts(bad) == [], repr(pp._visible_docx_part_texts(bad)))


def test_f194_round_qualified_stage():
    review = {"guided_review", "cold_start_review"}
    check("F194: parse_only_stages('2:review') contributes the review stages",
          pp.parse_only_stages("2:review") == review, repr(pp.parse_only_stages("2:review")))
    check("F194: parse_only_stages('review') is unchanged",
          pp.parse_only_stages("review") == review)
    check("F194: a round named in full stays 'every stage' (set())",
          pp.parse_only_stages("1,2:review") == set())


def test_f195_pid_alive_unknown():
    real_os = pp.os

    class FakePosix:
        name = "posix"

        def __init__(self, exc):
            self.exc = exc

        def kill(self, pid, sig):
            raise self.exc

    pp.os = FakePosix(OSError(5, "I/O error"))
    try:
        check("F195: an unknown signal-0 failure reads as alive", pp.pid_alive(4321) is True)
    finally:
        pp.os = FakePosix(ProcessLookupError)
    try:
        check("F195: ProcessLookupError is still the only dead result",
              pp.pid_alive(4321) is False)
    finally:
        pp.os = real_os


def main():
    test_f75_nested_include()
    test_f96_zero_index()
    test_f119_env_header_in_string()
    test_f180_docstring()
    test_f181_style_limits()
    test_f182_malformed_part()
    test_f194_round_qualified_stage()
    test_f195_pid_alive_unknown()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL K_p18 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
