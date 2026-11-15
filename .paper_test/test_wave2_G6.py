#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G6.

Each check pins one re-validated candidate. Hermetic: temp dirs only; no
network, no Word, no agent runs, no full pipeline.

Run:  python3 -B .paper_test/test_wave2_G6.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def tmpdir(tag):
    return Path(tempfile.mkdtemp(prefix=f"g6w2_{tag}_"))


def setup_args(tmp, *extra):
    src = tmp / "src"
    src.mkdir(exist_ok=True)
    (src / "manuscript.md").write_text("Abstract\n\nBody text.\n", encoding="utf-8")
    root = tmp / "r"
    argv = ["setup", "--source", str(src), "--root", str(root),
            "--rounds", "1", "--judges", "1", "--rewrites", "1",
            "--revises", "1", "--integrators", "0x3", "--format-fix", "off", *extra]
    return pp.build_parser().parse_args(argv), root, src


def quiet_call(fn, *a, **k):
    """Call fn and return (exit_code_or_None, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            fn(*a, **k)
    except SystemExit as e:
        code = e.code
    return code, out.getvalue(), err.getvalue()


def write_config(root: Path, **over):
    cfg = {"rounds": 1, "judges": [1], "rewrites": [1], "revises": [1],
           "integrators": [3], "review_scope": ["full"]}
    cfg.update(over)
    (root / "pipeline_config.json").write_text(json.dumps(cfg), encoding="utf-8")


# ---------------------------------------------------------------------------
# C111 / F150 -- an unreadable source file must be a named code-2 refusal and
# must not leave a half-built root.
# ---------------------------------------------------------------------------
def test_c111_copy_failure():
    print("\n== C111: source copy failure is a clean usage error ==")
    tmp = tmpdir("c111")
    args, root, _src = setup_args(tmp)
    real = pp.shutil.copytree
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise pp.shutil.Error("simulated unreadable source file")

    pp.shutil.copytree = boom
    try:
        code, _out, _err = quiet_call(pp.cmd_setup, args)
    finally:
        pp.shutil.copytree = real
    check("C111 the copy failure is reported as a usage error (exit 2)", code == 2, str(code))
    check("C111 no half-built root is left behind", not root.exists(), str(root))
    check("C111 the copy was actually attempted", calls["n"] == 1, str(calls))


# ---------------------------------------------------------------------------
# C112 / F151 -- an explicitly empty per-round value is a usage error, not the
# expensive default.
# ---------------------------------------------------------------------------
def test_c112_empty_round_values():
    print("\n== C112: empty per-round values are refused, not defaulted ==")
    for flag in ("judges", "rewrites", "revises", "integrators"):
        tmp = tmpdir("c112_" + flag)
        args, root, _src = setup_args(tmp, "--" + flag, "")
        code, _out, err = quiet_call(pp.cmd_setup, args)
        check(f"C112 --{flag} '' exits 2 instead of planning the default",
              code == 2, f"{code} {err[-160:]}")
        check(f"C112 --{flag} '' creates no root", not root.exists())
        check(f"C112 --{flag} '' names the flag", flag in err, err[-160:])
    check("C112 _setup_round_arg distinguishes absent from empty",
          pp._setup_round_arg(types.SimpleNamespace(judges=None), "judges")
          == pp.DEFAULTS["judges"]
          and pp._setup_round_arg(types.SimpleNamespace(judges=""), "judges") == "")


# ---------------------------------------------------------------------------
# C113 / F153 -- template_stage.dir must be contained in the root.
# ---------------------------------------------------------------------------
def test_c113_template_stage_containment():
    print("\n== C113: template_stage.dir cannot escape the root ==")
    tmp = tmpdir("c113")
    root = tmp / "r"
    (root / "runs" / "template_ok").mkdir(parents=True)
    outside = tmp / "outside"
    outside.mkdir()
    (root / "non_revised").mkdir()

    def ctx_for(where):
        return types.SimpleNamespace(
            root=root, pristine=root / "non_revised",
            state={"template_stage": {"ok": True, "dir": where, "digest": "x"}})

    check("C113 an absolute outside dir is refused",
          pp.template_stage_record(ctx_for(str(outside))) == {})
    check("C113 a ../ escape is refused",
          pp.template_stage_record(ctx_for("../outside")) == {})
    inside = pp.template_stage_record(ctx_for("runs/template_ok"))
    check("C113 an inside dir is still accepted", bool(inside), str(inside))
    check("C113 an escaped record falls back to the pristine original",
          pp.working_original_dir(ctx_for(str(outside))) == root / "non_revised")


# ---------------------------------------------------------------------------
# C178 / F238 -- switching to a no-letter mode clears stale feedback keys.
# ---------------------------------------------------------------------------
def test_c178_stale_feedback_keys():
    print("\n== C178: set-revision-mode clears feedback keys the mode cannot read ==")
    tmp = tmpdir("c178")
    root = tmp / "r"
    root.mkdir()
    write_config(root, revision_mode="transfer",
                 journal_feedback=["non_revised/decision_letter.txt"],
                 journal_feedback_from="Editor")
    args = pp.build_parser().parse_args(
        ["set-revision-mode", "--root", str(root), "continue", "--force"])
    code, _out, err = quiet_call(pp.cmd_set_revision_mode, args)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("C178 switching to continue exits 0", code is None, f"{code} {err[-120:]}")
    check("C178 revision_mode is continue", cfg.get("revision_mode") == "continue")
    check("C178 stale journal_feedback is removed", "journal_feedback" not in cfg, str(cfg))
    check("C178 stale journal_feedback_from is removed",
          "journal_feedback_from" not in cfg, str(cfg))
    # Switching back to transfer with NO new letter must not resurrect the old path.
    args = pp.build_parser().parse_args(
        ["set-revision-mode", "--root", str(root), "transfer", "--force"])
    quiet_call(pp.cmd_set_revision_mode, args)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("C178 a later transfer does not silently reuse the stale letter",
          "journal_feedback" not in cfg, str(cfg))


# ---------------------------------------------------------------------------
# C179 / F239 -- set-venue --show with a mutating operand applies it.
# ---------------------------------------------------------------------------
def test_c179_show_with_journal():
    print("\n== C179: set-venue --show --journal NAME applies the journal ==")
    tmp = tmpdir("c179")
    root = tmp / "r"
    root.mkdir()
    write_config(root, venue="nature-biotechnology", journal="Nature Biotechnology",
                 article_type="article")
    args = pp.build_parser().parse_args(
        ["set-venue", "--root", str(root), "--show", "--journal", "Cell"])
    code, out, err = quiet_call(pp.cmd_set_venue, args)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("C179 the invocation exits 0", code is None, f"{code} {err[-120:]}")
    check("C179 the supplied journal is applied", cfg.get("journal") == "Cell", str(cfg))
    check("C179 the mutation is announced", "journal: Cell" in out, out[-200:])
    # A bare --show still just displays.
    args = pp.build_parser().parse_args(["set-venue", "--root", str(root), "--show"])
    code, out, _err = quiet_call(pp.cmd_set_venue, args)
    before = cfg.copy()
    cfg2 = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("C179 a bare --show still displays and does not mutate",
          code is None and "journal: Cell" in out and cfg2 == before)
    # --show --article-type without a venue id is refused, not silently ignored.
    args = pp.build_parser().parse_args(
        ["set-venue", "--root", str(root), "--show", "--article-type", "letter"])
    code, _out, _err = quiet_call(pp.cmd_set_venue, args)
    check("C179 --show with only --article-type is refused (exit 2)", code == 2, str(code))


# ---------------------------------------------------------------------------
# C182 / F242 -- an unbounded --rounds is refused before it allocates.
# ---------------------------------------------------------------------------
def test_c182_rounds_bound():
    print("\n== C182: an absurd --rounds is a usage error ==")
    for fn, arg, flag in ((pp.parse_round_counts, [2], "--judges"),
                          (pp.parse_round_masks, [3], "--integrators")):
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                fn(arg, 10 ** 9, flag)
        except SystemExit as e:
            code = e.code
        check(f"C182 {fn.__name__} refuses rounds beyond MAX_ROUNDS",
              code == 2 and str(pp.MAX_ROUNDS) in err.getvalue(),
              f"{code} {err.getvalue()[-120:]}")
    tmp = tmpdir("c182")
    args, root, _src = setup_args(tmp, "--rounds", str(10 ** 8))
    code, _out, err = quiet_call(pp.cmd_setup, args)
    check("C182 setup --rounds 100000000 exits 2 without a traceback", code == 2, str(code))
    check("C182 no root is created for the refused plan", not root.exists())
    check("C182 the refusal names the bound", str(pp.MAX_ROUNDS) in err, err[-160:])


# ---------------------------------------------------------------------------
# C133 / F178 -- a placement-only display block declares no caption rule.
# ---------------------------------------------------------------------------
def test_c133_display_caption():
    print("\n== C133: placement-only tables do not invent a caption gate ==")
    prof = pp.VenueProfile({"id": "v", "tables": {"placement": "end"}})
    text = pp.display_kind_rule_text(prof, "table", prof.data["tables"])
    check("C133 a placement-only table is not told it needs a caption",
          "is still FMT-TB1" not in text, text[:300])
    check("C133 the renderer says the profile states no caption requirement",
          "no table caption requirement" in text, text[:300])
    check("C133 the placement rule is still rendered", "WHERE TABLES BELONG" in text)
    prof2 = pp.VenueProfile({"id": "v2", "tables": {"placement": "end",
                                                     "caption": "before"}})
    text2 = pp.display_kind_rule_text(prof2, "table", prof2.data["tables"])
    check("C133 a declared caption rule still renders the FMT-TB1 gate",
          "with no caption is FMT-TB1" in text2, text2[:300])


# ---------------------------------------------------------------------------
# C136 / F185 -- a malformed existing row must not become a duplicate item.
# ---------------------------------------------------------------------------
def test_c136_handoff_duplicate():
    print("\n== C136: a refused README row does not duplicate the hand-off item ==")
    tmp = tmpdir("c136")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "MANUAL_STEPS.md").write_text(
        "# Manual steps\n\n- Install the reagent [AUTHOR TO COMPLETE: order reagent kit R-42]\n",
        encoding="utf-8")
    desc = "Install the reagent order reagent kit R-42"
    (pkg / "README-AUTHOR-TO-COMPLETE.md").write_text(
        "# Author to complete\n\n| TODO item ID | importance | author_action | description |\n"
        "|---|---|---|---|\n| T-1 | major | MANUALLY DO/DO_NOT correct without any "
        "LLMs-recommended corrections | " + desc + " |\n", encoding="utf-8")
    ctx = types.SimpleNamespace(cfg={"author_to_complete": "readme"})
    warns = []
    result = pp.ensure_handoff_readme(ctx, pkg, warns=warns)
    body = (pkg / "README-AUTHOR-TO-COMPLETE.md").read_text(encoding="utf-8")
    check("C136 the same item is not appended under a second T-id",
          "T-002" not in body, body)
    check("C136 the merge reports no new item", result == {}, str(result))
    check("C136 the malformed existing row is reported",
          any("T-1" in w for w in warns), str(warns))


# ---------------------------------------------------------------------------
# C140 / F189 -- the displayed relaxation identity must be exact or floored.
# ---------------------------------------------------------------------------
def test_c140_relaxation_math():
    print("\n== C140: the rendered cap arithmetic is not a rounded identity ==")
    prof = pp.VenueProfile({"id": "v", "label": "V", "article_types": [{
        "id": "article", "label": "Article",
        "length_limits": {"abstract": {"base": 100, "relaxation": 1.115}}}]})
    cap = prof.length_limits()["abstract"]["cap"]
    text = pp.length_rule_text(prof)
    check("C140 the enforced cap is floor(100 * 1.115) = 111", cap == 111, str(cap))
    check("C140 the false +12% identity is gone", "+12%" not in text, text[:400])
    check("C140 the exact relaxation is printed", "11.5%" in text, text[:400])
    check("C140 the cap is stated as floor(base*factor)",
          "floor(100 x 1.115)" in text, text[:400])
    band = pp.m19_blocks(prof)["review"]
    check("C140 the M19 band clause does not repeat the false identity",
          "+12%" not in band, band[:400])
    # The shipped integer-percent profile keeps the exact identity wording.
    nbt = pp.default_venue_profile()
    nbt_text = pp.length_rule_text(nbt)
    check("C140 the shipped +10%/+25% identities are unchanged",
          "base 150 +10% = 165" in nbt_text and "base 3000 +25% = 3750" in nbt_text)


# ---------------------------------------------------------------------------
# C141 / F190 -- table-contents is part of the stated counting span.
# ---------------------------------------------------------------------------
def test_c141_table_contents():
    print("\n== C141: the M19 renderers name the table-contents exclusion ==")
    fr = pp.load_venue_profile("frontiers-in-immunology")
    check("C141 the Frontiers profile excludes table-contents",
          "table-contents" in fr.main_text_excludes(), str(fr.main_text_excludes()))
    full = pp.main_text_counting_text(fr)
    short = pp._main_text_counting_short(fr)
    check("C141 main_text_counting_text names table contents", "table contents" in full, full)
    check("C141 _main_text_counting_short names table contents",
          "table contents" in short, short)
    nbt = pp.default_venue_profile()
    check("C141 a profile that does not exclude it is not told to exclude it",
          "table contents" not in pp.main_text_counting_text(nbt))


# ---------------------------------------------------------------------------
# C143 / F193 -- the publisher-side merge reports and does not duplicate.
# ---------------------------------------------------------------------------
def test_c143_published_duplicate():
    print("\n== C143: a refused external row does not duplicate the ledger item ==")
    tmp = tmpdir("c143")
    target = tmp / "README-AUTHOR-TO-COMPLETE.md"
    desc = ("F-001 manual-required M31: figures/FigureS1.png: the artwork is a "
            "read-only PNG; re-render it")
    target.write_text(
        "# Author to complete\n\n| TODO item ID | importance | author_action | description |\n"
        "|---|---|---|---|\n| T-1 | major | MANUALLY DO/DO_NOT correct without any "
        "LLMs-recommended corrections | " + desc + " |\n", encoding="utf-8")
    oi = {"items": [{"id": "F-001", "status": "manual-required", "check": "M31",
                     "severity": "Major", "location": "figures/FigureS1.png",
                     "evidence": "the artwork is a read-only PNG; re-render it"}]}
    result = pp.write_published_handoff_readme(tmp, open_items=oi, target_path=target)
    body = target.read_text(encoding="utf-8")
    check("C143 the same ledger item is not appended under a new T-id",
          body.count("F-001") == 1, body)
    check("C143 no managed block is emitted for it", "pipeline-generated-row-ids" not in body,
          body)
    check("C143 the malformed external row is reported",
          any("T-1" in str(p) for p in result.get("problems") or []), str(result))


# ---------------------------------------------------------------------------
# C194 / F257 -- a total-only cover cap does not contradict a "no rule" line.
# ---------------------------------------------------------------------------
def test_c194_total_only_cover_cap():
    print("\n== C194: a total-only cover cap is not 'no cover-letter word rule' ==")
    prof = pp.VenueProfile({"id": "v", "label": "V", "article_types": [{
        "id": "article", "label": "Article",
        "length_limits": {"cover_letter": {"min": None, "max": None,
                                           "total_max": 650,
                                           "source": "venue guideline"}}}]})
    text = pp.standing_exemptions_text(prof)
    check("C194 the false 'no COVER-LETTER word rule' claim is gone",
          "no COVER-LETTER word rule" not in text, text[:500])
    check("C194 the total cap is still stated", "650 words" in text, text[:500])
    check("C194 the absence of a persuading-part preference is what is stated",
          "no COVER-LETTER persuading-part preference" in text, text[:500])


# ---------------------------------------------------------------------------
# C196 / F262 -- the total cap is the profile's, not the operator's.
# ---------------------------------------------------------------------------
def test_c196_total_cap_provenance():
    print("\n== C196: the TOTAL cover cap is attributed to the venue profile ==")
    prof = pp.VenueProfile({"id": "v", "label": "V", "article_types": [{
        "id": "article", "label": "Article",
        "length_limits": {"cover_letter": {"min": 300, "max": 500, "total_max": 650,
                                           "source": "venue guideline"}}}]})
    guide = pp.cover_letter_guidance_clause(pp.cover_letter_guidance(prof))
    length = pp.length_rule_text(prof)
    standing = pp.standing_exemptions_text(prof)
    check("C196 the guidance clause names the venue profile's cap",
          "venue profile's recorded TOTAL-content cap" in guide, guide)
    check("C196 the length rule names the venue profile's cap",
          "venue profile's recorded TOTAL-content cap" in length, length[-500:])
    for line in standing.splitlines():
        if "650" in line and "TOTAL" in line.upper():
            check("C196 the standing exemption does not call the cap the operator's",
                  "operator's" not in line, line)
    check("C196 no rendered total-cap clause calls it the operator's default",
          "operator's cap" not in guide and "operator's default" not in length,
          guide)


# ---------------------------------------------------------------------------
# C033 / F041 -- rewrite/integrate do not receive the review/revision workflow.
# ---------------------------------------------------------------------------
def test_c033_stage_role_contract():
    print("\n== C033: rewrite/integrate prompts carry no review/revision product ==")
    tmp = tmpdir("c033")
    rewrite = pp.rewrite_prompt(tmp / "sb_w", "r1_w1", 1)
    integrate = pp.integrate_prompt(tmp / "sb_i", "r1_i1", 1, "a1", ["w1"])
    for name, text, out_dir in (("rewrite", rewrite, "rewritten/"),
                                ("integrate", integrate, "integrated/")):
        check(f"C033 {name} names its own output directory", out_dir in text)
        check(f"C033 {name} does not create revised/",
              "create a copy inside a new folder named revised/" not in text)
        check(f"C033 {name} does not run the revision workflow",
              "apply validated findings only" not in text
              and "every finding ID from findings.json" not in text)
        check(f"C033 {name} does not run the Phase 1 review workflow",
              "Run the complete review workflow" not in text)
        check(f"C033 {name} still carries the style/format rules",
              "Micro-formatting and consistency defects" in text
              and "Length rule (withdraws this master prompt" in text)
        check(f"C033 {name} still refuses to edit the read-only base",
              "`base/` and `non_revised/` are READ-ONLY" in text)


def main() -> int:
    test_c111_copy_failure()
    test_c112_empty_round_values()
    test_c113_template_stage_containment()
    test_c178_stale_feedback_keys()
    test_c179_show_with_journal()
    test_c182_rounds_bound()
    test_c133_display_caption()
    test_c136_handoff_duplicate()
    test_c140_relaxation_math()
    test_c141_table_contents()
    test_c143_published_duplicate()
    test_c194_total_only_cover_cap()
    test_c196_total_cap_provenance()
    test_c033_stage_role_contract()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    if FAILS:
        for f in FAILS:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
