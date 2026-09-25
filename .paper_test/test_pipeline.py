#!/usr/bin/env python3
"""Validation harness for the paper_pipeline design fixes.

Run:  python3 .paper_test/test_pipeline.py

`PAPER_WS` retargets the harness at a baseline copy of the tree.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WORKSPACE = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paperp", WORKSPACE / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


# ---------------------------------------------------------------- prompts
def test_prompts():
    sb = Path("/tmp/paper_validate/sandbox")
    builders = {
        "review": np.review_prompt(sb, "r1_review", 1),
        "rewrite": np.rewrite_prompt(sb, "r1_w1", 1),
        "revise": np.revise_prompt(sb, "r1_a2_revise", 1),
        "integrate": np.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1", "a2"]),
        "judge": np.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1", "v2", "v3"]),
    }
    for name, text in builders.items():
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
        check(f"prompt[{name}] no unresolved tokens", not unresolved, str(unresolved))
        # The judge gets the same rule in PROVENANCE-NEUTRAL wording (it must not
        # learn that there is a revision stage that writes the token); every
        # other stage gets the pipeline's own wording.
        check(f"prompt[{name}] carries the hand-off placeholder rule",
              ("PLACEHOLDER TEXT IN A PACKAGE" in text) if name == "judge"
              else ("PIPELINE HAND-OFF PLACEHOLDERS" in text))
        check(f"prompt[{name}] carries the auxiliary-file rule",
              "PIPELINE AUXILIARY FILES" in text)
        check(f"prompt[{name}] legends are always enumerated (M18)",
              "check id M18" in text and "legend" in text.lower())
        check(f"prompt[{name}] no-cap legend text records counts and forbids cuts",
              "no proxy cap is configured" in " ".join(text.split()).lower()
              or "NO cap is configured" in text)
    # A configured suggestion still says advisory
    rev = np.revise_prompt(sb, "r1_a2_revise", 1, caption_limit=300)
    check("revise prompt with --caption-limit 300 says SUGGESTION/advisory",
          "SUGGESTION" in rev and "never a gate" in rev.lower())
    jud = np.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"], caption_limit=300)
    check("judge prompt never makes an over-limit version ineligible",
          "never makes a version ineligible" in jud)
    check("judge prompt neutralises stale derived build outputs",
          "DERIVED BUILD OUTPUTS" in jud
          and "never let it decide a comparison" in jud.lower())
    check("revise prompt forbids shipping stale derived build outputs",
          "leave them OUT of revised/" in builders["revise"]
          and "Never ship a derived file that contradicts" in builders["revise"])
    check("integration prompt forbids shipping stale derived build outputs",
          "DERIVED BUILD OUTPUTS" in builders["integrate"])
    check("revise prompt overrides 'copy unchanged from non-revised/'",
          "never from\n     non_revised/" in rev and "REVERT" in rev)
    # parser default
    parser = np.build_parser()
    args = parser.parse_args(["setup", "--source", "/tmp"])
    # The cap now comes from the VENUE PROFILE when the operator does not choose
    # one: unset on the command line, 0 for the default profile (a venue whose
    # profile publishes a legend limit would get that number instead).
    check("setup --caption-limit is unset by default (the venue profile decides)",
          args.caption_limit is None, str(args.caption_limit))
    check("... and the default venue profile's own default is still 'no cap'",
          np.default_venue_profile().caption_default == np.DEFAULT_CAPTION_LIMIT == 0,
          str(np.default_venue_profile().caption_default))
    # SPLIT REVIEW: two scoped sessions, distinct id namespaces, one merged list
    a = np.review_prompt(sb, "r1_review", 1, split="a", split_mode="phases")
    b = np.review_prompt(sb, "r1_review_b", 1, split="b", split_mode="phases")
    check("setup --review-split defaults to off",
          parser.parse_args(["setup", "--source", "/tmp"]).review_split == "off")
    check("a split review prompt (A) carries its scope and FA- ids",
          "SPLIT REVIEW" in a and "MECHANICAL sweeps M1-M17" in a and "FA-001" in a)
    check("a split review prompt (B) carries the complementary scope and FB- ids",
          "SPLIT REVIEW" in b and "JUDGMENT passes J1-J4" in b and "FB-001" in b)
    check("an unsplit review prompt carries no split block", "SPLIT REVIEW" not in
          np.review_prompt(sb, "r1_review", 1))
    split_ctx = make_ctx(Path("/tmp/paper_validate_split"))
    split_ctx.cfg["review_split"] = "phases"
    split_plan = [e["id"] for e in np.round_run_plan(split_ctx, 1)]
    rev = [e for e in np.round_run_plan(split_ctx, 1) if e["kind"] == "revise"][0]
    check("a split round plans two review runs and the revise waits for both",
          "r1_review_b" in split_plan and "r1_review" in split_plan
          and "r1_review_b" in rev["deps"], str(split_plan))
    # Session B consumes session A's OUTPUT (materialize_review copies A's
    # review/ into B's review_a/); with the same deps as A, B was materialized
    # before A had written anything, so its review_a/ held the seeded skeleton
    # at best. B must wait for A.
    b_entry = [e for e in np.round_run_plan(split_ctx, 1)
               if e["id"] == "r1_review_b"][0]
    check("the split review's second session waits for the first (it reads review_a/)",
          "r1_review" in b_entry["deps"], str(b_entry["deps"]))
    # The frozen-review cross-check of the self-reported writing count exists
    # only for the arm that consumes review/ (revise). The integration prompt
    # used to promise it while the integrate sandbox holds no review/ at all.
    check("the integrate prompt does not claim a frozen-review cross-check it cannot run",
          "cross-checks the frozen review's category-2 count" not in builders["integrate"])
    check("the revise prompt keeps the frozen-review cross-check (it consumes review/)",
          "orchestrator cross-checks it against the frozen review" in builders["revise"])
    # ONE defect vocabulary in every session: the five scored classes, the
    # category -> class bridge and the shared severity scale must be identical
    # wherever they appear, so a defect a reviewer calls an improvement cannot
    # read as "no change" to the panel that scores it.
    block = np.defect_class_rule()
    for name, text in builders.items():
        check(f"prompt[{name}] carries the shared defect-class block", block in text)
    check("the defect-class block lists the scored classes in BASIS_TIERS order",
          "  >  ".join(np.BASIS_TIERS) in block, "  >  ".join(np.BASIS_TIERS))
    check("the defect-class block maps all six review categories",
          all(f"category {i}" in block for i in range(6)))
    check("the defect-class block states the shared severity scale",
          all(w in block for w in ("CRITICAL", "MAJOR", "MINOR")))
    check("the defect-class block states the cosmetic rule and the counted-minor rule",
          "cannot be named in this vocabulary is COSMETIC" in " ".join(block.split())
          and "counts 0 for every session" in " ".join(block.split())
          and "never cosmetic" in " ".join(block.split())
          and "Dropping\n    a nameable difference" in block)
    check("the defect-class block keeps systematic wording fixes visible",
          "consistency" in block
          and "a convention is applied in one place and\n        not another" in block)
    check("the judge prompt's priority order is the block's class order",
          "  >  ".join(np.BASIS_TIERS) in builders["judge"])
    skills = WORKSPACE / "paper-skills"
    sweeps = (skills / "paper-review" / "references" / "sweeps.md").read_text(encoding="utf-8")
    ledger = (skills / "paper-revise" / "references" / "ledger.md").read_text(encoding="utf-8")
    check("the review skill documents the same category -> class mapping",
          "correctness > consistency > preservation > completeness > formatting" in sweeps
          and all(f"| {i} " in sweeps for i in range(6)))
    check("the revision skill's ledger ties its category column to the same mapping",
          "correctness > consistency > preservation > completeness >" in ledger)


# ---------------------------------------------------------------- selection
def make_ctx(tmp: Path, judges=1):
    root = tmp / "root"
    root.mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    ctx = np.Ctx(root)
    ctx.cfg = {"rounds": 2, "judges": judges}
    ctx.state = {"version": np.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "original_digest": "d_orig", "config": ctx.cfg}
    return ctx


ROUND2_FIELD = ["orig", "r1_a2", "a2", "i1", "i2"]


def build_round2_ctx(tmp: Path, matrix, judges=1, summaries=None):
    """matrix[(target, opp)] = score (one judge). Returns a ready ctx + agg."""
    ctx = make_ctx(tmp, judges=judges)
    r = 2
    ctx.state["pinned"] = [{"id": "r1_a2", "round": 1, "digest": "d_pin", "source_id": "a2",
                            "captions": None}]
    ctx.state["runs"]["r2_a1"] = {"id": "r2_a1", "kind": "a1", "round": 2,
                                  "sandbox": "runs/r2_a1", "status": "done",
                                  "corpus_digest": "d_pin", "attempts": 1, "summary": None}
    for vid, dig in (("a2", "d_a2"), ("i1", "d_i1"), ("i2", "d_i2")):
        rid = np.rid_for_fresh(r, vid)
        ctx.state["runs"][rid] = {"id": rid, "kind": "revise" if vid == "a2" else "integrate",
                                  "round": r, "sandbox": f"runs/{rid}", "status": "done",
                                  "corpus_digest": dig, "attempts": 1,
                                  "summary": (summaries or {}).get(vid)}
        run_dir = ctx.root / f"runs/{rid}" / np.output_dir_for_vid(vid)
        run_dir.mkdir(parents=True, exist_ok=True)
        write(run_dir / "manuscript-p.docx", b"PK\x03\x04fake")
        (ctx.root / f"runs/{rid}/code").mkdir(parents=True, exist_ok=True)
        if vid == "a2":
            write(run_dir / "MANUAL_STEPS.md", "- step one\n- step two\n")
    # judge runs
    for vid in ROUND2_FIELD:
        others = [w for w in ROUND2_FIELD if w != vid]
        labels = [f"v{i}" for i in range(1, len(others) + 1)]
        for j in range(1, judges + 1):
            rid = np.rid_judge(r, np.judge_target_token(r, vid), j)
            comps = []
            for lab, opp in zip(labels, others):
                comps.append({"opponent_label": lab,
                              "score": int(matrix[(vid, opp)]),
                              "reason": "synthetic"})
            ctx.state["runs"][rid] = {"id": rid, "kind": "judge", "round": r, "status": "done",
                                      "target_id": vid, "judge_index": j,
                                      "label_map": dict(zip(labels, others)),
                                      "scores": {"run_id": rid, "round": r,
                                                 "target_id": vid, "judge_index": j,
                                                 "comparisons": comps},
                                      "attempts": 1, "sandbox": f"runs/{rid}"}
    agg = np.aggregate_round(ctx, r, ROUND2_FIELD)
    return ctx, agg


def symmetric_matrix(pairs, cross):
    m = {}
    for (a, b), v in pairs.items():
        m[(a, b)] = v
    for vid in ROUND2_FIELD:
        for opp in ROUND2_FIELD:
            if vid != opp and (vid, opp) not in m:
                m[(vid, opp)] = cross
    return m


def test_selection():
    # (1) the base (previous champion) wins when it strictly outranks the fresh arms
    tmp = Path(tempfile.mkdtemp(prefix="paper_sel_base_"))
    pairs = {
        ("r1_a2", "orig"): 1, ("r1_a2", "a2"): 2, ("r1_a2", "i1"): 2, ("r1_a2", "i2"): 2,
        ("orig", "r1_a2"): 1, ("a2", "r1_a2"): 0, ("i1", "r1_a2"): 0, ("i2", "r1_a2"): 0,
        ("a2", "orig"): 1, ("orig", "a2"): 0,
        ("i1", "orig"): 1, ("orig", "i1"): 0,
        ("i2", "orig"): 1, ("orig", "i2"): 0,
        ("a2", "i1"): -1, ("i1", "a2"): -1,
        ("a2", "i2"): -1, ("i2", "a2"): -1,
        ("i1", "i2"): 0, ("i2", "i1"): 0,
    }
    ctx, agg = build_round2_ctx(tmp, pairs)
    check("base_rep resolves to the previous pin", agg["base_rep"] == "r1_a2", str(agg["base_rep"]))
    check("base median is the highest row",
          agg["stats"]["r1_a2"]["median"] == 0.5 and
          max(agg["stats"][v]["median"] for v in ("a2", "i1", "i2")) == 0.0)
    sel = np.select_champion(ctx, 2, agg)
    check("round cannot crown a version ranked below its base", sel["champion"] == "a1",
          f"champion={sel['champion']} ranking={[r['id'] for r in sel['ranking']]}")
    check("base row reports vs_base == 0 for itself",
          agg["stats"]["r1_a2"]["vs_base"] is None)
    check("candidate vs_base is reported",
          agg["stats"]["a2"]["vs_base"] == -1.0, str(agg["stats"]["a2"]["vs_base"]))
    shutil.rmtree(tmp, ignore_errors=True)

    # (2) median tie is broken by the arithmetic mean (not by a self-reported number)
    tmp = Path(tempfile.mkdtemp(prefix="paper_sel_mean_"))
    pairs = {
        ("r1_a2", "orig"): 0, ("r1_a2", "a2"): 0, ("r1_a2", "i1"): 0, ("r1_a2", "i2"): 0,
        ("orig", "r1_a2"): 0, ("a2", "r1_a2"): 0, ("i1", "r1_a2"): 0, ("i2", "r1_a2"): 0,
        ("a2", "orig"): 0, ("orig", "a2"): -1,        # a2 gets a +1 received score
        ("i1", "orig"): 0, ("orig", "i1"): 0,
        ("i2", "orig"): 0, ("orig", "i2"): 0,
        ("a2", "i1"): 0, ("i1", "a2"): 0,
        ("a2", "i2"): 0, ("i2", "a2"): 0,
        ("i1", "i2"): 0, ("i2", "i1"): 0,
    }
    summaries = {"a2": {"critical_remaining": 3, "manual_items": 9},
                 "i1": {"critical_remaining": 0, "manual_items": 0},
                 "i2": {"critical_remaining": 0, "manual_items": 0}}
    ctx, agg = build_round2_ctx(tmp, pairs, summaries=summaries)
    check("a2 and i1 tie on the median, a2 has the higher mean",
          agg["stats"]["a2"]["median"] == agg["stats"]["i1"]["median"] == 0.0 and
          agg["stats"]["a2"]["mean"] > agg["stats"]["i1"]["mean"],
          f"a2 mean={agg['stats']['a2']['mean']} i1 mean={agg['stats']['i1']['mean']}")
    sel = np.select_champion(ctx, 2, agg)
    check("mean breaks the median tie even when the other arm reports better numbers",
          sel["champion"] == "a2", f"champion={sel['champion']}")
    check("MANUAL_STEPS.md is reported but not ranked on",
          # The reported count is the marker's self-reported manual_items (9),
          # not the 2 bullet lines in the sandbox file; the sort key must not
          # contain manual_steps at all.
          any(r["id"] == "a2" and r["manual_steps"] == 9 for r in sel["ranking"])
          and "manual_steps" not in np.score_model_doc()["tiebreaks"])
    shutil.rmtree(tmp, ignore_errors=True)

    # (3) an over-limit caption never blocks a version
    tmp = Path(tempfile.mkdtemp(prefix="paper_sel_cap_"))
    pairs = symmetric_matrix({}, 0)
    ctx, agg = build_round2_ctx(tmp, pairs)
    over = {"limit": 300, "rule_enabled": True, "checked": True, "count": 1,
            "over_limit": [{"document": "manuscript-p.docx", "caption": "Figure 1",
                            "words": 400}],
            "suspected_count": 0, "unparsed": []}
    agg["stats"]["a2"]["captions"] = over
    agg["stats"]["a2"]["caption_gate_ok"], agg["stats"]["a2"]["caption_note"] = \
        np.caption_gate(over)
    sel = np.select_champion(ctx, 2, agg)
    check("over-limit caption is reported but never gates", "a2" in sel["eligible"],
          f"eligible={sel['eligible']}")
    check("over-limit caption note says advisory",
          "advisory" in agg["stats"]["a2"]["caption_note"])
    shutil.rmtree(tmp, ignore_errors=True)

    # (4) hand-off placeholders are reported, never a penalty
    tmp = Path(tempfile.mkdtemp(prefix="paper_sel_ph_"))
    pairs = symmetric_matrix({}, 0)
    ctx, agg = build_round2_ctx(tmp, pairs)
    write(ctx.root / "runs/r2_a2_revise/revised/cover_letter-p.docx", b"PK\x03\x04fake")
    write(ctx.root / "runs/r2_a2_revise/revised/notes.txt",
          "Data availability: [AUTHOR TO COMPLETE: accession number]\n")
    agg2 = np.aggregate_round(ctx, 2, ROUND2_FIELD)
    check("hand-off placeholders are counted per version",
          agg2["stats"]["a2"]["author_placeholders"] == 1,
          str(agg2["stats"]["a2"]["author_placeholders"]))
    sel = np.select_champion(ctx, 2, agg2)
    check("a placeholder never makes a version ineligible", "a2" in sel["eligible"])
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- structured output
def test_structured_output_exemption():
    tmp = Path(tempfile.mkdtemp(prefix="paper_so_"))
    ctx = make_ctx(tmp)
    sb = ctx.root / "runs/r1_a2_revise"
    empty = b""
    write(sb / "base/data.json", empty)
    write(sb / "revised/data.json", empty)              # copied verbatim (empty)
    write(sb / "base/weird.xml", b"<a>&nbsp;</a>")       # not well-formed XML
    write(sb / "revised/weird.xml", b"<a>&nbsp;</a>")     # copied verbatim
    write(sb / "revised/brand_new.json", b"")             # the agent's own empty file
    rec = {"kind": "revise", "id": "r1_a2_revise", "round": 1, "sandbox": "runs/r1_a2_revise",
           "inputs_manifest": {"base": np.hash_manifest(sb / "base")}}
    probs = np.structured_output_problems(ctx, rec)
    check("copied-but-empty input file is exempt (by content, not path)",
          not any("revised/data.json" in p for p in probs), str(probs))
    check("copied malformed input file is exempt",
          not any("revised/weird.xml" in p for p in probs), str(probs))
    check("the agent's own empty structured file still fails",
          any("revised/brand_new.json" in p for p in probs), str(probs))
    # A JUDGE's own scratch is not a deliverable: the 2026-09-23 round-1 panel
    # failed two sessions on truncated .docx files the agent had written while
    # normalizing the blinded views into `judge_review/work/`, although their
    # scores.json and their frozen views were intact.
    jsb = ctx.root / "runs/judge_tok_j1"
    write(jsb / "judge_review" / "work" / "norm_target" / "f0001.docx", b"NOT A ZIP")
    write(jsb / "judge_review" / "artifacts" / "broken.docx", b"NOT A ZIP")
    jrec = {"kind": "judge", "id": "judge_tok_j1", "round": 1, "sandbox": "runs/judge_tok_j1",
            "target_id": "w1", "judge_index": 1, "inputs_manifest": {}}
    jprobs = np.structured_output_problems(ctx, jrec)
    check("a truncated .docx in the judge's own work/ scratch is ignored",
          not any("judge_review/work/" in p for p in jprobs), str(jprobs)[:160])
    check("a truncated .docx OUTSIDE the scratch still fails the run",
          any("judge_review/artifacts/broken.docx" in p for p in jprobs), str(jprobs)[:160])
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- corpus rules
def make_docx(path: Path, text: str):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>'
           f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


def test_corpus_rules():
    tmp = Path(tempfile.mkdtemp(prefix="paper_corpus_"))
    ctx = make_ctx(tmp)
    sb = ctx.root / "runs/r1_a2_revise"
    rev = sb / "revised"
    make_docx(rev / "manuscript-p.docx", "Figure 1 | A caption.")
    make_docx(rev / "manuscript-p.tracked.docx", "Figure 1 | A caption.")
    write(rev / "notes.md", "Data: [AUTHOR TO COMPLETE: accession]\n")
    write(rev / "work/scratch.txt", "scratch\n")
    write(rev / "CHANGELOG.md", "placeholder [AUTHOR TO COMPLETE: funding]\n")
    rid = np.rid_for_fresh(1, "a2")
    ctx.state["runs"][rid] = {"id": rid, "kind": "revise", "round": 1, "status": "done",
                              "sandbox": f"runs/{rid}", "corpus_digest": "d", "attempts": 1}
    man = np.corpus_manifest(ctx, 1, "a2")
    check("*.tracked.docx excluded from the version corpus",
          "manuscript-p.tracked.docx" not in man["files"], str(sorted(man["files"])))
    check("revised/work/ still excluded", not any(k.startswith("work/") for k in man["files"]))
    dst = tmp / "corpus_copy"
    np.build_corpus_dir(ctx, 1, "a2", dst)
    check("build_corpus_dir leaves the auxiliary out",
          not (dst / "manuscript-p.tracked.docx").exists()
          and (dst / "manuscript-p.docx").exists())
    ph = np.scan_placeholders_in_sources(np.corpus_sources(ctx, 1, "a2"))
    check("placeholder scan counts the manuscript markers",
          ph["count"] == 1 and ph["files"] == ["notes.md"], str(ph))
    make_docx(rev / "supplement-p.docx", "[AUTHOR TO COMPLETE: author contributions]")
    ph = np.scan_placeholders_in_sources(np.corpus_sources(ctx, 1, "a2"))
    check("placeholder scan reads .docx and ignores bookkeeping files",
          ph["count"] == 2 and "supplement-p.docx" in ph["files"]
          and "CHANGELOG.md" not in ph["files"], str(ph))
    # caption scan still ignores aux files and reports the cap as a suggestion
    cap = np.scan_captions_in_sources(np.corpus_sources(ctx, 1, "a2"), limit=1)
    check("caption scan counts the parent caption once (aux skipped)",
          cap["count"] == 1, str(cap["count"]))
    check("caption scan labels the limit as a suggestion (rule_enabled)",
          cap["rule_enabled"] is True and cap["limit"] == 1)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- round finalize
def test_panel_gaps_cleared():
    tmp = Path(tempfile.mkdtemp(prefix="paper_fin_"))
    ctx = make_ctx(tmp)
    rrec = ctx.round_rec(1)
    rrec["panel_gaps"] = {"gaps": ["a2"], "round": 1}
    round_ids = ["a1", "w1", "w2", "a2", "i1", "i2", "i3", "i4"]   # the default plan
    agg = {"field_size": 4, "scores_per_version": 6,
           "stats": {v: {} for v in round_ids}, "base_rep": "orig", "base_id": "a1",
           "diagnostics": {"sheets_used": 0, "sheets_expected": 0, "unresolved": [],
                           "incomplete_sheets": [], "scores_collected": 0}}
    sel = {"champion": "a2", "champion_rep": "a2", "ranking": [{"id": "a2",
                                                                "critical_remaining": 0,
                                                                "manual_steps": 1}],
           "eligible": ["a2"], "trace": []}
    pin = {"id": "r1_a2", "digest": "d"}
    np.finalize_round(ctx, 1, [{"id": v} for v in round_ids], [], agg, sel, pin)
    check("a decided round no longer carries stale panel_gaps",
          "panel_gaps" not in ctx.round_get(1), str(ctx.round_get(1).get("panel_gaps")))
    check("champion_rep is recorded", ctx.round_get(1).get("champion_rep") == "a2")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_prompts()
    test_selection()
    test_structured_output_exemption()
    test_corpus_rules()
    test_panel_gaps_cleared()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        sys.exit(1)
    print("ALL CHECKS PASSED")
