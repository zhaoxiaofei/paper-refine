#!/usr/bin/env python3
"""Wave-3 (run 20261115-081714) regression checks for this stage's fixes.

Direct-function tests: each one exercises the exact construct a candidate named.
Run with: python3 .paper_test/test_fix_bugs_20261115_run2_wave3.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402
import paper_docx_format as fmt      # noqa: E402

FAILS = []
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def tmpdir(tag):
    return Path(tempfile.mkdtemp(prefix=f"fb3_{tag}_"))


# ---------------------------------------------------------------------------
# F031: prerequisites and --only validation precede the template-first agent
# ---------------------------------------------------------------------------
def _run_fixture(mode="transfer", rounds=1):
    root = tmpdir("f031") / "root"
    (root / "non_revised").mkdir(parents=True)
    (root / "reports").mkdir()
    ctx = pp.Ctx(root)
    ctx.cfg = {"venue": "fake-venue", "revision_mode": mode, "rounds": rounds}
    ctx.state = {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": {"files": {}, "count": 0},
                 "original_digest": "d0", "config": ctx.cfg}
    return ctx


def _args(only):
    a = SimpleNamespace(
        timeout=None, max_turns=0, manual=True, agent_cmd=None, only=only,
        _insertions_explicit=False, _deletions_explicit=False,
        _prefer_rewrite_over_deletion_explicit=False, no_track=True,
        champion_select=None, no_template_stage=False, agent_harness=None,
        agent_model=None, agent_model_name=None, agent_model_api_key=None,
        agent_model_prep_json=None, judge_agent_cmd=None,
    )
    return a


def _run_locked(ctx, args, extra=None):
    """Run `_cmd_run_locked` with the fixture's expensive checks stubbed."""
    calls = []
    saved = {}
    overrides = {
        "pristine_integrity": lambda c: (True, "ok"),
        "content_edit_policy_note": lambda c: "",
        "journal_has_feedback": lambda c: False,
        "pinned_integrity": lambda c: [],
        "raw_data_advisories": lambda c: [],
        "reconcile_inputs": lambda c: ([], []),
        "backfill_round_raw_scores": lambda c: None,
        "_ensure_template_stage_for_run": lambda c, a: calls.append("template"),
    }
    overrides.update(extra or {})
    for name, value in overrides.items():
        saved[name] = getattr(pp, name)
        setattr(pp, name, value)
    err = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            pp._cmd_run_locked(ctx, args)
    except SystemExit as e:
        code = int(e.code or 0)
    finally:
        for name, value in saved.items():
            setattr(pp, name, value)
    return code, err.getvalue(), calls


def test_f031_ordering():
    print("\n== F031 template stage ordering ==")
    # An invalid --only is refused before the template agent can start.
    ctx = _run_fixture(rounds=1)
    code, err, calls = _run_locked(ctx, _args("2:judge"))
    check("F031 an unknown round is refused before the template stage",
          code == 2 and calls == [] and "round(s) 2 do not exist" in err,
          f"code={code} calls={calls} err={err.strip()[-160:]!r}")

    # A broken pin is refused before the template agent can start, even for a
    # valid selection.
    ctx = _run_fixture(rounds=1)
    code, err, calls = _run_locked(
        ctx, _args("1"), {"pinned_integrity": lambda c: ["pinned/r1/x changed"]})
    check("F031 a broken pin is refused before the template stage",
          calls == [] and "pinned champion content changed" in err,
          f"code={code} calls={calls} err={err.strip()[-160:]!r}")


# ---------------------------------------------------------------------------
# F033: the synthesized cold-start lists carry the real X-9xx rows
# ---------------------------------------------------------------------------
def test_f033_synthesized_lists():
    print("\n== F033 synthesized cold-start lists ==")
    row = {"id": "X-901", "location": "main.md:12", "category": 2,
           "check": "stale sidecar", "severity": "Major",
           "evidence": "the table says 41; the supplement says 14",
           "explanation": "correct the carried table value", "status": "resolvable"}
    ctx = SimpleNamespace()
    saved_rows, saved_scoped = pp.cold_start_findings_rows, pp.journal_is_scoped
    pp.cold_start_findings_rows = lambda c, r: [row]
    pp.journal_is_scoped = lambda c: False
    try:
        sb = tmpdir("f033")
        res = pp.synthesize_frozen_review(ctx, 1, sb)
        md = (sb / "guided_review" / "findings.md").read_text(encoding="utf-8")
        extra = (sb / "guided_review" / "round2" / "findings_extra.md").read_text(
            encoding="utf-8")
        extra_json = json.loads((sb / "guided_review" / "round2" /
                                 "findings_extra.json").read_text(encoding="utf-8"))
    finally:
        pp.cold_start_findings_rows, pp.journal_is_scoped = saved_rows, saved_scoped
    check("F033 a real cold-start row is counted", res["rows"] == 1, str(res))
    check("F033 findings.md names the row and its evidence, never '(untitled)'",
          "X-901" in md and "(untitled)" not in md
          and "main.md:12" in md and "the table says 41" in md,
          md[:400])
    check("F033 findings_extra.md carries the readable row too",
          "X-901" in extra and "the table says 41" in extra, extra[:400])
    check("F033 the machine-readable discovery list still carries the row",
          extra_json["findings"] and extra_json["findings"][0]["id"] == "X-901",
          str(extra_json.get("findings"))[:200])


# ---------------------------------------------------------------------------
# F060: the cold-start review gets the venue norm and the staged template
# ---------------------------------------------------------------------------
def test_f060_cold_start_venue_context():
    print("\n== F060 cold-start venue context ==")
    sb = tmpdir("f060") / "sandbox"
    prompt = pp.cold_start_review_prompt(sb, "r1_cold_start_review", 1,
                                         venue_norm="VENUE_NORM_SENTINEL_42")
    check("F060 the cold-start prompt carries venue_norm",
          "VENUE_NORM_SENTINEL_42" in prompt,
          prompt[-300:])

    class FakeCtx:
        def __init__(self, base):
            self.runs_dir = base / "runs"
            self.runs_dir.mkdir(parents=True)
            self._a1 = base / "a1"

        def run(self, rid):
            if str(rid).endswith("_a1"):
                return {"id": rid, "status": "done"}
            return None

        def sandbox_of(self, rec):
            return self._a1

        def register(self, *a, **k):
            return {}

    base = tmpdir("f060m")
    (base / "a1" / "base").mkdir(parents=True)
    ctx = FakeCtx(base)
    calls = {}
    saved = {}
    overrides = {
        "ensure_copy": lambda src, dst: dst.mkdir(parents=True, exist_ok=True),
        "ensure_pristine_input": lambda c, dst: dst.mkdir(parents=True, exist_ok=True),
        "seed_cold_start_surfaces": lambda c, s, r: None,
        "_copy_session_tools": lambda s: None,
        "stage_venue_template": lambda c, s: calls.setdefault("template", True) or {},
        "venue_profile_of": lambda c: None,
        "venue_norm_for": lambda c: "VENUE_NORM_MATERIALIZER",
        "author_to_complete_mode_of": lambda c: "TODO",
        "execution_profile_of": lambda c: "high",
        "guided_review_enabled": lambda c: True,
        "cold_start_review_prompt": lambda *a, **k: (
            calls.update(prompt_kwargs=k) or "PROMPT"),
    }
    for name, value in overrides.items():
        saved[name] = getattr(pp, name)
        setattr(pp, name, value)
    try:
        pp.materialize_cold_start_review(ctx, 1)
    finally:
        for name, value in saved.items():
            setattr(pp, name, value)
    check("F060 the materializer stages venue_template/",
          calls.get("template") is True, str(calls))
    check("F060 the materializer passes venue_norm to the prompt",
          calls.get("prompt_kwargs", {}).get("venue_norm") == "VENUE_NORM_MATERIALIZER",
          str(calls.get("prompt_kwargs")))


# ---------------------------------------------------------------------------
# F065: scoped/split prompts do not order the discovery round they exclude
# ---------------------------------------------------------------------------
def test_f065_scoped_discovery_prompt():
    print("\n== F065 scope-aware D0-D5 ==")
    common = dict(run_id="r1_guided_review", r=1)

    def prompt(**kw):
        return pp.review_prompt(tmpdir("f065"), **common, **kw)

    full = prompt(scope="full")
    check("F065 the full review still orders D0-D5",
          "4. The discovery round D0-D5" in full
          and "the complete D0-D5 set" in full)
    scoped = prompt(scope="formatting-writing")
    check("F065 a formatting-writing review does not order D0-D5",
          "4. The discovery round D0-D5" not in scoped
          and "the complete D0-D5 set" not in scoped
          and "do NOT run the discovery round D0-D5" in scoped,
          scoped[-500:])
    split_a = prompt(split="a", split_mode="phases")
    check("F065 split-A does not order the discovery round it assigns to B",
          "4. The discovery round D0-D5" not in split_a
          and "the complete D0-D5 set" not in split_a
          and "the discovery round D0-D5" in split_a)
    split_b = prompt(split="b", split_mode="phases")
    check("F065 split-B still owns and orders the discovery round",
          "4. The discovery round D0-D5" in split_b
          and "the complete D0-D5 set" in split_b)


# ---------------------------------------------------------------------------
# F036: OOXML prefix aliases are canonicalised before the readers run
# ---------------------------------------------------------------------------
def _write_package(path: Path, document: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" '
                   'ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml",
                   f'<?xml version="1.0"?><w:styles xmlns:w="{W_NS}">'
                   f'<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
                   f'<w:name w:val="Normal"/></w:style></w:styles>')


def test_f036_ooxml_namespace_aliases():
    print("\n== F036 OOXML namespace aliases ==")
    alias_doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<word:document xmlns:word="{W_NS}"><word:body>'
        f'<word:p><word:pPr><word:pStyle word:val="Heading1"/></word:pPr>'
        f'<word:r><word:t>Alpha - Beta  double</word:t></word:r></word:p>'
        f'</word:body></word:document>')
    canon = fmt.canonicalize_ooxml_prefixes(alias_doc)
    check("F036 an aliased w: package canonicalises to w:",
          "word:" not in canon and "<w:p" in canon and 'xmlns:w=' in canon)
    check("F036 the canonicalised document reads its paragraph and text",
          len(fmt.paragraphs(canon)) == 1 and fmt.text_of(canon) == "Alpha - Beta  double",
          str(fmt.paragraphs(canon))[:200])
    check("F036 an aliased attribute is canonicalised too",
          fmt.para_style(fmt.paragraphs(canon)[0][2]) == "Heading1",
          str(fmt.para_style(fmt.paragraphs(canon)[0][2])))

    pkg = tmpdir("f036") / "alias.docx"
    _write_package(pkg, alias_doc)
    res = fmt.analyse_package(pkg, fmt.load_policy(None))
    check("F036 the scan reports the aliased package's text findings",
          res["by_rule"].get("FMT-P2") == 1 and res["by_rule"].get("FMT-P3") == 1,
          str(res["by_rule"]))
    out = tmpdir("f036out") / "fixed.docx"
    fixed = fmt.fix_package(pkg, out, fmt.load_policy(None))
    check("F036 the fixer writes a readable package from the aliased source",
          fixed.get("ok") is True and out.is_file(), str(fixed.get("error"))[:200])
    if out.is_file():
        with zipfile.ZipFile(out) as z:
            written = z.read("word/document.xml").decode("utf-8")
        check("F036 the fixed document keeps one canonical namespace spelling",
              "word:" not in written and "<w:p" in written, written[:200])

    mc_doc = (
        f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}" xmlns:x="{MC_NS}">'
        f'<w:body><w:p><w:r><w:t>live</w:t></w:r><x:AlternateContent>'
        f'<x:Choice><w:r><w:t>choice</w:t></w:r></x:Choice>'
        f'<x:Fallback><w:r><w:t>fallback</w:t></w:r></x:Fallback>'
        f'</x:AlternateContent></w:p></w:body></w:document>')
    mc_canon = fmt.canonicalize_ooxml_prefixes(mc_doc)
    check("F036 an aliased mc:AlternateContent is masked like the literal prefix",
          "mc:AlternateContent" in mc_canon and "x:" not in mc_canon
          and fmt.text_of(mc_canon) == "livechoice",
          repr(fmt.text_of(mc_canon)))

    # R01/F036: a DEFAULT-namespace WordprocessingML part with an XML
    # declaration is legal OOXML. The declaration must be added to the first
    # ELEMENT, not the first tag-shaped match (the XML declaration).
    default_doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<document xmlns="{W_NS}"><body>'
        f'<p><r><t>Alpha - Beta  double</t></r></p>'
        f'</body></document>')
    default_canon = fmt.canonicalize_ooxml_prefixes(default_doc)
    check("F036 a default-namespace part keeps a bound w: declaration",
          "xmlns:w=" in default_canon and "<w:document" in default_canon,
          default_canon[:200])
    pkg_def = tmpdir("f036def") / "default.docx"
    _write_package(pkg_def, default_doc)
    res_def = fmt.analyse_package(pkg_def, fmt.load_policy(None))
    check("F036 a legal default-namespace package is read, not FMT-X1",
          "FMT-X1" not in res_def["by_rule"]
          and res_def["by_rule"].get("FMT-P2") == 1
          and res_def["by_rule"].get("FMT-P3") == 1,
          str(res_def["by_rule"]))


def main() -> int:
    test_f031_ordering()
    test_f033_synthesized_lists()
    test_f060_cold_start_venue_context()
    test_f065_scoped_discovery_prompt()
    test_f036_ooxml_namespace_aliases()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL WAVE-3 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
