#!/usr/bin/env python3
"""Regression checks for the confirmed findings of the 2026-10-02 1653 audit.

Sources: `audit_data/2026-1002-1653-general-audit/` (the four read-only
reports). Every check below reproduces a defect confirmed on the cc07eef tree
and fails before its fix. Unreproduced suggestions are NOT pinned here; see the
hand-off ledger.

Run:  python3 .paper_test/test_general_audit_fixes_2026_1002c.py
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
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("paper_docx_format_audit_c", WS / "paper_docx_format.py")
nb = load("paper_pipeline_audit_c", WS / "paper_pipeline.py")


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


# ---- pipeline integrity ---------------------------------------------------

def test_decide_never_uses_the_digest_cache():
    """decide rewrites files it hashed, so the stat-keyed cache must stay off."""
    root = scratch("pr_cache_probe_")
    note = nb.configure_hash_cache_for_command("decide", root)
    check("configure_hash_cache_for_command('decide') leaves the cache off",
          nb.HASH_CACHE_ENABLED is False, f"enabled={nb.HASH_CACHE_ENABLED} note={note!r}")
    f = root / "manuscript.tex"
    f.write_text("pdflatex cnb-11-main.tex\n", encoding="utf-8")
    before = nb.sha256_file(f)
    f.write_text("pdflatex cnb-12-main.tex\n", encoding="utf-8")   # same length, same tick
    after = nb.sha256_file(f)
    check("a same-tick, same-size rewrite is re-hashed while the cache is off",
          before != after, f"digests equal: {before[:12]} == {after[:12]}")
    nb.HASH_CACHE_ENABLED = False


def test_official_skeleton_keeps_pinned_mandatory_sections():
    records = [{"sections": [{"level": 1, "title": "Introduction"},
                             {"level": 1, "title": "Methods"}],
                "documentclass": "article", "statements": [], "file": "a.tex",
                "format": "tex", "sha256": "x"}]
    out = nb.official_skeleton(records, {"mandatory_sections": ["Data Availability"]})
    check("official_skeleton honours operator-pinned mandatory sections",
          "Data Availability" in out["mandatory_sections"],
          str(out["mandatory_sections"]))


def test_upstream_deps_with_none_manifest():
    rec = {"id": "r1_revise_x", "kind": "revise", "round": 1, "sandbox": "/tmp/x",
           "inputs_manifest": None, "upstream_run_id": None}
    try:
        deps = nb.upstream_deps(rec)
        ok, detail = isinstance(deps, list), str(deps)
    except Exception as e:                      # noqa: BLE001 -- the defect is the exception
        ok, detail = False, f"{type(e).__name__}: {e}"
    check("upstream_deps tolerates a registered run whose inputs_manifest is None",
          ok, detail)


def test_make_tree_writable_never_descends_a_symlinked_root():
    tmp = scratch("pr_mtw_probe_")
    target = tmp / "shared"
    target.mkdir()
    f = target / "evidence.txt"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, 0o444)
    os.chmod(target, 0o555)
    link = tmp / "link"
    os.symlink(target, link)
    plan = nb.make_tree_writable(link)
    check("make_tree_writable does not chmod through a symlinked root",
          plan == [] and (target.stat().st_mode & 0o777) == 0o555
          and (f.stat().st_mode & 0o777) == 0o444,
          f"plan={plan} dir={oct(target.stat().st_mode & 0o777)} "
          f"file={oct(f.stat().st_mode & 0o777)}")


def test_invalid_submission_formats_are_rejected():
    data = json.loads((WS / "venue_profiles/example-journal.json").read_text(encoding="utf-8"))
    data["submission"]["formats"] = "PDF"       # invalid: must be a list
    try:
        nb.normalize_venue_profile(data, origin="fixture")
        ok, detail = False, "invalid formats was silently accepted"
    except Exception as e:                      # noqa: BLE001 -- rejection is the fix
        ok, detail = "formats" in str(e), str(e)[:160]
    check("an invalid submission.formats is rejected by the validator", ok, detail)


def test_symlink_manifest_does_not_double_count_a_self_link():
    tmp = scratch("pr_selflink_probe_")
    canon = tmp / "canon"
    canon.mkdir()
    (canon / "a.txt").write_text("a", encoding="utf-8")
    (canon / "sub").mkdir()
    (canon / "sub" / "b.txt").write_text("b", encoding="utf-8")
    os.symlink(canon, canon / "loop")           # a link to the tree itself
    got = sorted(nb.hash_manifest(canon, follow_dir_links=True)["files"])
    check("a self-referential directory link does not duplicate the manifest",
          got == ["a.txt", "sub/b.txt"], str(got))


def test_run_log_path_is_unique_per_invocation():
    root = scratch("pr_log_probe_")
    first = nb.start_run_log("run", root, ["run"])
    second = nb.start_run_log("run", root, ["run"])
    check("two same-second invocations do not share (and truncate) one run log",
          str(first) != str(second) and first.is_file() and second.is_file(),
          f"first={first.name} second={second.name}")


def test_final_clean_reason_matches_certification_blockers():
    helper = getattr(nb, "final_clean_reason", None)
    if helper is None:
        check("final_clean_reason helper exists", False, "not defined")
        return
    rounds = [{"round": 1, "mismatch": "round 1: recomputed champion differs"},
              {"round": 2, "mismatch": None}]
    reason = helper(rounds[-1], rounds, 2, None, True, False, {}, [])
    check("an earlier round's recomputation mismatch blocks the clean-copy verdict too",
          bool(reason), repr(reason))
    ok_reason = helper(rounds[-1], [{"round": 2, "mismatch": None}], 2, None, True, False, {}, [])
    check("a healthy decision still carries no clean-copy blocker", ok_reason == "", repr(ok_reason))


# ---- prompt / skill scripts ----------------------------------------------

def test_review_mandate_has_no_words_word():
    for name in ("nature-biotechnology", "generic", "frontiers-in-immunology"):
        prof = nb.load_venue_profile(name)
        review = " ".join(nb.m19_blocks(prof)["review"].split())
        check(f"the M19 review mandate for {name} is not 'words-word'",
              "words-word" not in review and "word-word" not in review, review[-200:])


def test_count_words_does_not_invent_a_total_cap():
    letter = scratch("pr_cw_probe_") / "cover_letter.txt"
    letter.write_text("Dear Editor,\n\nWe submit our work.\n\nSincerely,\nA. Author\n",
                      encoding="utf-8")
    script = str(WS / "paper-skills/paper-review/scripts/count_words.py")
    for name in ("generic", "example-journal"):
        proc = subprocess.run([sys.executable, script, str(letter), "--venue-profile",
                               str(WS / f"venue_profiles/{name}.json"),
                               "--section", "cover-letter"],
                              capture_output=True, text=True, timeout=120)
        out = proc.stdout + proc.stderr
        check(f"count_words.py invents no 650-word cap for {name}",
              proc.returncode == 0 and "650" not in out, out[-220:])
    # Frontiers: max-only preference must be described as such, not as "no preference".
    proc = subprocess.run([sys.executable, script, str(letter), "--venue-profile",
                           str(WS / "venue_profiles/frontiers-in-immunology.json"),
                           "--section", "cover-letter"],
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    check("a max-only cover preference is not reported as 'no preference'",
          "at most 200" in out and "configures no cover-letter preference" not in out,
          out[-260:])


def test_count_words_does_not_borrow_another_types_caps():
    prof = json.loads((WS / "venue_profiles/example-journal.json").read_text(encoding="utf-8"))
    entry = prof["article_types"][1]
    entry["length_limits"] = {"source": "fixture",
                              "abstract": {"base": 250, "relaxation": 1.1}}
    pdir = scratch("pr_cw_borrow_")
    profile_path = pdir / "profile.json"
    profile_path.write_text(json.dumps(prof), encoding="utf-8")
    paper = pdir / "paper.md"
    paper.write_text("# Abstract\n" + "word " * 100 + "\n\n# Introduction\n" + "word " * 100,
                     encoding="utf-8")
    proc = subprocess.run([sys.executable, str(WS / "paper-skills/paper-review/scripts/"
                                               "count_words.py"),
                           str(paper), "--venue-profile", str(profile_path),
                           "--article-type", entry["id"], "--json"],
                          capture_output=True, text=True, timeout=120)
    try:
        caps = json.loads(proc.stdout)["caps"]
        ok = caps.get("main text") is None
    except Exception as e:                      # noqa: BLE001
        ok, caps = False, f"{type(e).__name__}: {e} / {proc.stdout[:120]}"
    check("count_words.py reports no main-text cap for a type that states none", ok, str(caps))
    # The same rule for a section stated as an empty block or with only a base:
    # the validator requires base+relaxation together, so neither may borrow.
    for stated in ({}, {"base": 250}):
        prof2 = json.loads(json.dumps(prof))
        entry2 = prof2["article_types"][1]
        entry2["length_limits"] = {"source": "fixture", "abstract": stated}
        ppath2 = pdir / "profile2.json"
        ppath2.write_text(json.dumps(prof2), encoding="utf-8")
        proc2 = subprocess.run([sys.executable, str(WS / "paper-skills/paper-review/scripts/"
                                                   "count_words.py"),
                                str(paper), "--venue-profile", str(ppath2),
                                "--article-type", entry2["id"], "--json"],
                               capture_output=True, text=True, timeout=120)
        try:
            caps2 = json.loads(proc2.stdout)["caps"]
            ok2 = caps2.get("abstract") is None and caps2.get("main text") is None
        except Exception as e:                  # noqa: BLE001
            ok2, caps2 = False, f"{type(e).__name__}: {e} / {proc2.stdout[:120]}"
        check(f"count_words.py borrows nothing for a section stated as {stated!r}",
              ok2, str(caps2))


def test_self_closing_rpr_stays_well_formed():
    import xml.etree.ElementTree as ET
    out, changed = fmt._rpr_set_emphasis('<w:rPr w:rsidR="00112233"/>', True)
    try:
        ET.fromstring('<root xmlns:w="http://x">' + out + "</root>")
        ok = True
    except ET.ParseError as e:
        ok = False
        out = f"{out}  ({e})"
    check("adding w:i to a self-closing w:rPr stays well-formed",
          ok and changed and "<w:i/>" in out, str(out))


def test_convert_corpus_instrtext_is_a_tag_not_text():
    cc = load("cc_audit_c", WS / "paper-skills/paper-review/scripts/convert_corpus.py")
    visible = ('<w:body><w:p><w:r><w:t>the instrText element is described here</w:t>'
               '</w:r></w:p></w:body>')
    lines, notes = cc.docx_part_to_lines(visible)
    check("visible text that mentions instrText is not a fake field marker",
          lines == ["the instrText element is described here"]
          and not any("field" in n.lower() for n in notes), f"{lines} {notes}")
    real = ('<w:body><w:p><w:r><w:instrText> ADDIN ZOTERO_ITEM </w:instrText>'
            '<w:t>Smith 2020</w:t></w:r></w:p></w:body>')
    lines2, notes2 = cc.docx_part_to_lines(real)
    check("a real w:instrText is still marked as a field",
          any("[[FIELD:" in ln for ln in lines2) and any("field" in n.lower() for n in notes2),
          f"{lines2} {notes2}")


def test_enumerate_conventions_escapes_variants():
    ec = load("ec_audit_c", WS / "paper-skills/paper-review/scripts/enumerate_conventions.py")
    pat = ec.word_pattern("C++")
    check("a variant with regex metacharacters matches literally",
          pat is not None and pat.search("C++ is a language") is not None
          and pat.search("C is a language") is None,
          f"C++ match={bool(pat and pat.search('C++ is a language'))} "
          f"C match={bool(pat and pat.search('C is a language'))}")


# ---- docs ----------------------------------------------------------------

def test_docs_counts_and_cross_references():
    readme = (WS / "README.md").read_text(encoding="utf-8")
    suites = sorted(p.name for p in (WS / ".paper_test").glob("test_*.py"))
    count = len(suites)
    check(f"README's suite count matches the tree ({count})",
          f"{count} suites" in readme and "53 suites" not in readme, str(count))
    check("the exit-code table documents code 4",
          re.search(r"^\|\s*4\s*\|", readme, re.M) is not None)
    check("the stale 'The two input areas' cross-reference is gone",
          "The two input areas" not in readme)
    test_readme = (WS / ".paper_test/README.md").read_text(encoding="utf-8")
    check(".paper_test/README.md lists the new regression suite",
          "test_general_audit_fixes_2026_1002c.py" in test_readme)
    check("the CLI help no longer claims the clean copy is written only when certified",
          "only for a CERTIFIED champion" not in readme
          and "only for a CERTIFIED champion" not in _pipeline_help())
    # The docs must not contradict the code they describe: the attempt-history
    # table kept a removed 60-message cap, and the CLI list that editing agents
    # read first (AGENT.md) was missing `conform`/its aliases.
    check("the README's attempts_log row matches _attempt_messages (no removed message cap)",
          len(nb._attempt_messages([f"m{i}" for i in range(80)])) == 80
          and "60 messages each" not in readme and "no message-count cap" in readme)
    agent_md = (WS / "AGENT.md").read_text(encoding="utf-8")
    usage = re.search(r"^\s*\{([a-z0-9,\-]+)\}\s*$", _pipeline_help(), re.MULTILINE)
    commands = usage.group(1).split(",") if usage else []
    missing = [c for c in commands if f"`{c}`" not in agent_md]
    check("AGENT.md's CLI list names every subcommand the parser offers",
          bool(commands) and not missing, f"missing={missing}")


def _pipeline_help() -> str:
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "--help"],
                          capture_output=True, text=True, timeout=120)
    return proc.stdout + proc.stderr


def main() -> int:
    try:
        test_decide_never_uses_the_digest_cache()
        test_official_skeleton_keeps_pinned_mandatory_sections()
        test_upstream_deps_with_none_manifest()
        test_make_tree_writable_never_descends_a_symlinked_root()
        test_invalid_submission_formats_are_rejected()
        test_symlink_manifest_does_not_double_count_a_self_link()
        test_run_log_path_is_unique_per_invocation()
        test_final_clean_reason_matches_certification_blockers()
        test_review_mandate_has_no_words_word()
        test_count_words_does_not_invent_a_total_cap()
        test_count_words_does_not_borrow_another_types_caps()
        test_self_closing_rpr_stays_well_formed()
        test_convert_corpus_instrtext_is_a_tag_not_text()
        test_enumerate_conventions_escapes_variants()
        test_docs_counts_and_cross_references()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} 2026-10-02c CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL 2026-10-02c GENERAL-AUDIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
