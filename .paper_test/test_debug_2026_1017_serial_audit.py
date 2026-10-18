#!/usr/bin/env python3
"""Regressions for the 2026-10-17 serial audit.

Run:  python3 .paper_test/test_debug_2026_1017_serial_audit.py

Each check is a minimal reproduction of one candidate from
``audit_data/2026-1017-1123-serial-audit``.  The suite fails on the audited
tree and passes only when the confirmed defect is fixed.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import docx

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pp = _load("paper_serial_audit_pipeline", WS / "paper_pipeline.py")
ps = _load("paper_serial_audit_pairwise", WS / "pairwise_scores.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(path)
    return path


def write_docx(path: Path, paragraphs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(path)


def test_handoff_checklist() -> None:
    print("\n== C01-C03: author hand-off checklist ==")
    root = scratch("serial_c01_")
    readme = root / pp.AUTHOR_TO_COMPLETE_README
    readme.write_text(
        pp.AUTHOR_TO_COMPLETE_README_HEADER
        + "- confirm the IRB protocol ID\n",
        encoding="utf-8",
    )
    record = pp.write_published_handoff_readme(
        root, {"items": []}, {"items": []})
    text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    check("C01 a stage-authored checklist survives publication",
          readme.is_file() and "confirm the IRB protocol ID" in text,
          f"record={record} text={text[:240]}")

    discarded = scratch("serial_c02_")
    record = pp.write_published_handoff_readme(
        discarded,
        {"items": [], "discarded": [{
            "id": "F-9", "status": "discarded", "check": "M13",
            "severity": "Major", "evidence": "unsupported item"}]},
        {"items": []},
    )
    check("C02 an auditor-discarded row is not republished as an author task",
          not record and not (discarded / pp.AUTHOR_TO_COMPLETE_README).exists(),
          str(record))

    residual = scratch("serial_c03_")
    record = pp.write_published_handoff_readme(
        residual,
        {"items": [{"id": "F-1", "status": "manual", "check": "M1",
                    "severity": "Minor", "evidence": "visible item"}]},
        {"items": ["2 hand-off markers could not be parsed in an image-only PDF"]},
    )
    text = (residual / pp.AUTHOR_TO_COMPLETE_README).read_text(encoding="utf-8")
    check("C03 an unparsed-marker residual reaches the checklist beside other rows",
          "hand-off markers" in text and "visible item" in text,
          f"record={record} text={text[:280]}")


def test_duplicate_roles() -> None:
    print("\n== C04: PKG-26 distinct document roles ==")
    root = scratch("serial_c04_")
    write_docx(root / "manuscript.docx", ["clean"])
    write_docx(root / "manuscript-revised.docx", ["revised"])
    write_docx(root / "panel-a.docx", ["a"])
    write_docx(root / "panel-b.docx", ["b"])
    rows = pp.duplicate_submission_role_rows(root)
    check("C04 clean/revised copies and letter-suffixed panels are distinct",
          rows == [], str(rows))
    check("C04 an explicit legacy version token still collapses one role",
          pp._duplicate_role_key("manuscript-v1.docx")
          == pp._duplicate_role_key("manuscript-v2.docx"))


def test_readiness_venue_base() -> None:
    print("\n== C05: readiness uses the venue base limit ==")
    root = scratch("serial_c05_")
    row = {"document": "main.docx", "section": "main text", "words": 3726,
           "base": 3000, "relaxation": 1.25, "cap": 3750,
           "over_base": True, "over_limit": False}
    ready = pp.package_readiness(
        {"path": str(root), "hygiene": {}}, {"items": []},
        author_to_complete="readme",
        lengths={"rows": [row], "over_base": [row], "over_limit": []},
    )
    check("C05 text above the venue base is not submission-ready",
          ready["submission_ready"] is False
          and any(f.get("rule") == "FMT-M19" for f in ready["findings"]),
          json.dumps(ready["findings"])[:500])


def test_stale_driver_guard() -> None:
    print("\n== C06: every mutating command refuses a foreign driver ==")
    root = scratch("serial_c06_")
    (root / "paper_pipeline.py").write_text("# stale\n", encoding="utf-8")
    (root / "pipeline_config.json").write_text("{}\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "version": pp.STATE_VERSION, "runs": {}, "rounds": {},
        "pinned": [], "log": [],
        "pipeline": {"path": str(root / "paper_pipeline.py"),
                     "sha256": "deadbeef", "version": pp.VERSION},
    }), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"),
         "set-submit-code", "on", "--root", str(root)],
        capture_output=True, text=True,
    )
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("C06 set-submit-code refuses before mutating the root",
          proc.returncode == 2 and "submit_code" not in cfg,
          f"rc={proc.returncode} cfg={cfg} output={(proc.stdout + proc.stderr)[-300:]}")


def test_pairwise() -> None:
    print("\n== C07-C10: pairwise workbook ==")
    root = scratch("serial_c07_") / "cnb-demo"
    root.mkdir()
    path = root / "rounds.csv"
    fields = ["round", "member", "credited", "direction", "opponent_id",
              "source_judge_run", "source_judge_index", "sheet_target"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for round_id, score in ((1, 2), (2, 2), (3, 4)):
            writer.writerow({
                "round": round_id, "member": "a1", "credited": score,
                "direction": "own", "opponent_id": "a2",
                "source_judge_run": "j1", "source_judge_index": 1,
                "sheet_target": "a1",
            })
    cubes, _notes = ps.collect(
        [path], how="mean", pool_rounds=True, own_only=True)
    values = cubes[root.name]["all"][("a1", "a2")].values
    check("C07 --pool-rounds keeps repeated scores from different rounds",
          values == [2.0, 2.0, 4.0]
          and abs(sum(values) / len(values) - 8 / 3) < 1e-9,
          str(values))

    names = ["cnb-experiment-alpha-very-long-name-one",
             "cnb-experiment-alpha-very-long-name-two"]
    prefix = ps.shared_name_prefix(sorted(names))
    used = set()
    tabs = [ps.sheet_tab(ps.sheet_stem(name, prefix), "1", used)
            for name in names]
    check("C08 sheet names retain the one/two distinguishing token",
          tabs == ["one_r1", "two_r1"], str(tabs))

    dump = scratch("serial_c09_") / "head.txt"
    dump.write_text(
        "==> /x/cnb-run/reports/round1_raw_scores.csv <==\n"
        "round,member,credited,direction,opponent_id,opponent_label,"
        "source_judge_run,source_judge_index,sheet_target,reason\n"
        "1,a1,2,own,a2,v1,j1,1,a1,cost$\n",
        encoding="utf-8",
    )
    cubes, _notes = ps.collect(
        [dump], how="mean", pool_rounds=False, own_only=True)
    check("C09 a valid head-dump row ending in $ is retained",
          cubes["cnb-run"]["1"][("a1", "a2")].values == [2.0],
          str(dict(cubes)))

    rows = pp._readme_action_rows("| Confirm the ORCID |\n")
    check("C10 a one-row Markdown table counts as one item",
          rows == ["Confirm the ORCID"], str(rows))
    rows = pp._readme_action_rows(
        "| Item | State |\n|---|---|\n| Confirm the ORCID | open |\n")
    check("C10 a normal Markdown table excludes its header and separator",
          rows == ["Confirm the ORCID | open"], str(rows))
    check("C10 a standalone table separator is not a checklist item",
          pp._readme_action_rows("|---|---|\n") == [])


def test_placeholder_selection() -> None:
    print("\n== C11: undeclared placeholder copies ==")
    root = scratch("serial_c11_")
    area = root / "raw_data"
    area.mkdir()
    source = area / "ACT_haplotypes.vcf"
    source.write_text("chr\tpos\n1\t1\n", encoding="utf-8")
    shutil.copy(source, area / "HG008_haplotypes.vcf")
    report = pp.placeholder_files_report(root, area_names=["raw_data"])
    check("C11 neither side of an undeclared duplicate is usable evidence",
          set(report["ignored"]) == {
              "raw_data/ACT_haplotypes.vcf",
              "raw_data/HG008_haplotypes.vcf",
          },
          json.dumps(report)[:600])


def test_document_roles() -> None:
    print("\n== C12: document-role tokens ==")
    roles = {
        name: pp.docx_document_role(name)
        for name in ("recovered_notes.docx", "coverage_table.docx",
                     "newsletter.docx", "support.docx", "support.md")
    }
    check("C12 cover/supp are tokens, not raw substrings",
          all(role == "main" for role in roles.values()), str(roles))
    check("C12 figure-a.pdf is not treated as derived from figure.docx",
          not pp._is_view_excluded_file("figure-a.pdf", ["figure.docx"]))
    check("C12 figure-a.pdf still matches its own figure-a.docx source",
          pp._is_view_excluded_file("figure-a.pdf", ["figure-a.docx"]))


def test_package_scan_false_results() -> None:
    print("\n== C13-C19: package scan precision ==")
    root = scratch("serial_c13_")
    (root / "raw_data").mkdir()
    (root / "other").mkdir()
    (root / "raw_data" / "a.tsv").write_text(
        "method\tvalue\nm\t1\nm\t2\n", encoding="utf-8")
    (root / "other" / "b.tsv").write_text(
        "Method\tvalue\nm\t1\nm\t2\n", encoding="utf-8")
    check("C13 PKG-11 compares tables in one directory",
          pp.scan_column_name_near_misses(root) == [])

    root = scratch("serial_c14_")
    area = root / "raw_data"
    area.mkdir()
    (area / "a_units.tsv").write_text(
        "method\tscore\nGinkgo\t1\nGinkgo\t1\nGinkgo\t1\n",
        encoding="utf-8",
    )
    (area / "z_pooled_units.tsv").write_text(
        "method\tmean\nGinkgo\t70\nGinkgo\t70\nGinkgo\t70\n",
        encoding="utf-8",
    )
    (area / "mcb_pooled.tsv").write_text(
        "method\tn_units\tmean\nGinkgo\t3\t70\n", encoding="utf-8")
    check("C14 PKG-15 uses the matching pooled-units table and mean column",
          pp.scan_pooled_table_mismatches(root) == [])

    root = scratch("serial_c15_")
    (root / "raw_data").mkdir()
    grid = ["dataset\tmethod\tmetric\tmean"]
    for dataset in ("d1", "d2", "d3"):
        grid.extend([
            f"{dataset}\tginkgo\tROC-AUC\t0.40",
            f"{dataset}\tginkgo-uncapped\tROC-AUC\t0.90",
            f"{dataset}\tother\tROC-AUC\t0.50",
        ])
    (root / "raw_data" / "grid.tsv").write_text(
        "\n".join(grid) + "\n", encoding="utf-8")
    (root / "ms.md").write_text(
        "Ginkgo gave the highest average ROC-AUC.\n", encoding="utf-8")
    rows = pp.scan_ranking_claim_conflicts(root)
    check("C15 PKG-18 compares the method the sentence names",
          len(rows) == 1 and "0.900" in rows[0]["detail"],
          str(rows))

    root = scratch("serial_c16_")
    write_docx(root / "ms-main.docx", [
        "Title",
        "Software",
        "We used bedtools 2.1, Seurat 5.0, and cellsnp-lite 1.0; "
        "Eagle v2.4 was used.",
    ])
    write_docx(root / "reporting-summary.docx", [
        "Reporting Summary", "Software: Seurat 5.0 and cellsnp-lite 1.0"])
    refs = {r["reference"] for r in pp.scan_form_software_coverage(root)}
    check("C16 PKG-16 joins a Software heading with its paragraph",
          {"bedtools", "Eagle"}.issubset(refs), str(refs))

    root = scratch("serial_c16b_")
    write_docx(root / "ms-main.docx", [
        "Software. Eagle 2.4 and Other 1.0 were used."])
    write_docx(root / "reporting-summary.docx", [
        "Reporting Summary", "Software: Beagle 5 and Other 1.0"])
    refs = {r["reference"] for r in pp.scan_form_software_coverage(root)}
    check("C16 PKG-16 does not find Eagle inside Beagle",
          refs == {"Eagle"}, str(refs))

    check("C17 a short text is not automatically the same work",
          not pp._same_work(
              "cancer", "single-cell chromatin accessibility atlas"))
    check("C17 two generic shared words are not enough",
          not pp._same_work("cancer patients", "cancer patients outcomes"))

    for text in ("GRCh38", "CHM13", "Python3"):
        check(f"C18 {text} is not read as an inline citation",
              pp.INLINE_CITATION_RE.search(
                  f"Analysed with {text} in the pipeline.") is None)
    citation = pp.INLINE_CITATION_RE.search("the omics43 result")
    check("C18 a genuine word-attached citation is retained",
          citation is not None and citation.group(2) == "43")

    check("C19 a starred p-value parses",
          pp._parse_p("0.115*") == 0.115)
    check("C19 an inequality p-value parses",
          pp._parse_p("<0.001") == 0.001)
    root = scratch("serial_c19_")
    (root / "raw_data").mkdir()
    (root / "raw_data" / "x.plots.stats.mcb.tex").write_text(
        "\\captionof{table}{Small $P$ and an interval excluding 0 both mean "
        "significantly inferior.}\n"
        "\\begin{longtable}{llrrrrrrrr}\n"
        "metric & 3 & 0.80 & 0.00 & [0.20, 0.50] \\\\\n"
        "\\end{longtable}\n",
        encoding="utf-8",
    )
    check("C19 an interval excluding 0 is significant in either direction",
          len(pp.scan_mcb_rule_conflicts(root)) == 1)


def test_declared_submission_set() -> None:
    print("\n== C20: submitted-set declarations ==")
    root = scratch("serial_c20_")
    (root / "README.md").write_text(
        "Only files matching `ms-*.docx` will be submitted. "
        "Also `fig-*.png` and `*.log`.\n",
        encoding="utf-8",
    )
    (root / "README_SUBMISSION.md").write_text(
        "Only files matching `paper-*.docx` will be submitted.\n",
        encoding="utf-8",
    )
    write_docx(root / "ms-1.docx", ["m"])
    write_docx(root / "paper-1.docx", ["p"])
    (root / "fig-1.png").write_bytes(b"x")
    (root / "debug.log").write_text("log", encoding="utf-8")
    declared = pp.declared_submission_set(root)
    files = set(declared.get("files") or [])
    check("C20 every submission declaration contributes, and unrelated globs do not",
          files == {"ms-1.docx", "paper-1.docx"}, json.dumps(declared)[:700])
    after = scratch("serial_c20_after_")
    write_docx(after / "paper-1.docx", ["p"])
    (after / "README.md").write_text(
        "The following files will be submitted: `paper-*.docx`.\n",
        encoding="utf-8")
    declared_after = pp.declared_submission_set(after)
    check("C20 a glob after the declaration hint is parsed",
          declared_after.get("declared") is True
          and declared_after.get("files") == ["paper-1.docx"],
          json.dumps(declared_after)[:500])
    unparsed = scratch("serial_c20_unparsed_")
    write_docx(unparsed / "paper-1.docx", ["p"])
    (unparsed / "README.md").write_text(
        "Only paper-1.docx will be submitted.\n", encoding="utf-8")
    unparsed_decl = pp.declared_submission_set(unparsed)
    check("C20 an unparseable declaration is named instead of silently ignored",
          unparsed_decl.get("declared") is False
          and "no parseable pattern" in str(unparsed_decl.get("ignored_reason")),
          json.dumps(unparsed_decl)[:400])


def _champion_fixture(root: Path):
    field = ["orig", "r1_a2", "w1", "a2", "i1", "i2", "i3"]
    digests = {"orig": "d_orig", "r1_a2": "d_pin", "w1": "a_w1",
               "a2": "z_a2", "i1": "m_i1", "i2": "m_i2", "i3": "m_i3"}
    ctx = pp.Ctx(root)
    ctx.cfg = {
        "rounds": 2, "judges": 1, "caption_limit": 0,
        "rewrites": [1, 1], "revises": [1, 1],
    }
    ctx.state = {
        "version": pp.STATE_VERSION, "runs": {}, "rounds": {},
        "pinned": [{"id": "r1_a2", "round": 1, "digest": digests["r1_a2"],
                    "source_id": "a2", "captions": None}],
        "log": [], "source_manifest": {"files": {}, "count": 0},
        "original_digest": digests["orig"], "config": ctx.cfg,
    }
    ctx.state["runs"]["r2_a1"] = {
        "id": "r2_a1", "kind": "a1", "round": 2, "sandbox": "runs/r2_a1",
        "status": "done", "corpus_digest": digests["r1_a2"],
        "attempts": 1, "summary": None,
    }
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        rid = pp.rid_for_fresh(2, vid)
        ctx.state["runs"][rid] = {
            "id": rid,
            "kind": ("rewrite" if vid.startswith("w")
                     else "revise" if vid.startswith("a") else "integrate"),
            "round": 2, "sandbox": f"runs/{rid}", "status": "done",
            "corpus_digest": digests[vid], "attempts": 1,
            "summary": {"critical_remaining": 0, "manual_items": 0},
        }
    (root / "reports").mkdir(parents=True, exist_ok=True)

    def add_judge(vid):
        others = [item for item in field if item != vid]
        labels = [f"v{i + 1}" for i in range(len(others))]
        token = pp.judge_target_token(2, vid)
        rid = pp.rid_judge(2, token, 1)
        comparisons = []
        for label in labels:
            comparisons.append({
                "opponent_label": label, "score": 0, "reason": "fixture",
                "basis": "none", "resolved": [], "introduced": [],
            })
        ctx.state["runs"][rid] = {
            "id": rid, "kind": "judge", "round": 2, "status": "done",
            "target_id": vid, "judge_index": 1,
            "label_map": dict(zip(labels, others)), "attempts": 1,
            "sandbox": f"runs/{rid}", "finished": "2026-01-01T00:00:01",
            "scores": {"run_id": rid, "round": 2, "target_id": vid,
                       "judge_index": 1, "comparisons": comparisons},
        }
        return rid

    for version in field:
        add_judge(version)
    base_rid = pp.rid_judge(
        2, pp.judge_target_token(2, "r1_a2"), 1)
    base_comps = ctx.state["runs"][base_rid]["scores"]["comparisons"]
    base_comps[0]["introduced"] = [
        {"tier": "formatting", "severity": "minor",
         "evidence": f"base defect {index}"}
        for index in range(8)
    ]
    return ctx, field


def test_champion_prefix() -> None:
    print("\n== C21: the defect prefix orders the field; an exact panel tie keeps the base ==")
    root = scratch("serial_c21_")
    ctx, field = _champion_fixture(root)
    aggregate = pp.aggregate_round(ctx, 2, field)
    selected = pp.select_champion(ctx, 2, aggregate)
    ranking = {row["id"]: row for row in selected["ranking"]}
    # The prefix still ORDERS the rows (the base with 8 defects is last), but the
    # documented incumbent-retention rule overrides it when the base and the
    # leader tie exactly on (median, mean, IQR): a better defect count separates
    # CHALLENGERS, it does not retire a base the panel cannot distinguish from
    # them. See AGENTS.md rule 6 and README "an exact ... tie keeps the incumbent".
    check("C21 the prefix orders the field and an exact panel tie keeps the incumbent base",
          selected["champion"] == "a1"
          and ranking["a1"]["defect_prefix_total"] == 8
          and min(row["defect_prefix_total"] for row in selected["ranking"]) == 0
          and any("incumbent base is retained" in ln for ln in selected["trace"]),
          f"champion={selected['champion']} ranking="
          f"{[(r['id'], r['defect_prefix_total']) for r in selected['ranking']]}")


def test_publication_identity() -> None:
    print("\n== C22: the published package is the scored bytes ==")
    root = scratch("serial_c22_")
    (root / "pipeline_config.json").write_text(
        json.dumps({"rounds": 1, "judges": [1], "source": "/tmp/src",
                    "venue": "generic"}),
        encoding="utf-8",
    )
    winner = root / "round1_winner"
    write_docx(winner / "cnb-11-main-b.docx", ["one"])
    pin_digest = pp.manifest_digest(pp.corpus_dir_manifest(winner))
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    final = {
        "stored": {"winner_dir": "round1_winner", "champion": "a2", "round": 1},
        "pin": {"id": "r1_a2", "digest": pin_digest},
    }
    result = pp.publish_final_clean(ctx, final, True, "")
    published = Path(str(result.get("path") or ""))
    names = sorted(p.name for p in published.rglob("*") if p.is_file()) \
        if published.is_dir() else []
    check("C22 publication serves the pinned names and digest",
          result.get("digest") == pin_digest
          and result.get("pin_digest") == pin_digest
          and names == ["cnb-11-main-b.docx"],
          f"digest={result.get('digest')} pin={result.get('pin_digest')} "
          f"names={names}")
    refused = pp.publish_final_clean(
        ctx, final, True, "", flatten_zotero=True)
    check("C22 a post-pin Zotero flatten is refused rather than changing the package",
          "post-pin" in str(refused.get("skipped")),
          json.dumps(refused)[:400])
    ctx.cfg["format_policy"] = {"unlink_zotero_fields_at_publish": True}
    check("C22 the recorded flatten preference is applied before judging",
          pp.pre_judge_format_policy(ctx).get("unlink_zotero_fields") is True)


def test_journal_mode_and_judge_blinding() -> None:
    print("\n== C23-C24: no-mode feedback and judge provenance ==")
    root = scratch("serial_c23_")
    feedback = root / "non_revised" / "llm_review_feedback"
    feedback.mkdir(parents=True)
    (feedback / "review.md").write_text("feedback", encoding="utf-8")

    class Context:
        cfg = {}
        pristine = root / "non_revised"

    check("C23 an unset mode keeps the historical no-feedback path",
          pp.journal_mode_of(Context()) == "continue",
          pp.journal_mode_of(Context()))
    prompt = pp.judge_prompt(
        scratch("serial_c24_sandbox_"), "run", 1, "token", 1, 1, ["v1"])
    check("C24 the judge prompt reveals no pristine-original reference",
          "original/" not in prompt
          and "pristine original" not in prompt
          and "anti-regression gate" not in prompt)
    legacy_sandbox = scratch("serial_c24_legacy_")
    leak = legacy_sandbox / "original" / "view.docx"
    leak.parent.mkdir(parents=True)
    leak.write_bytes(b"old view")
    legacy_rec = {"inputs_manifest": {"original": {"files": {}}}}
    pp.drop_legacy_judge_original(legacy_sandbox, legacy_rec)
    check("C24 a legacy original/ view is removed when a judge sandbox is reused",
          not (legacy_sandbox / "original").exists()
          and "original" not in legacy_rec["inputs_manifest"],
          json.dumps(legacy_rec))


def test_venue_cover_limit() -> None:
    print("\n== C25: no invented cover-letter cap ==")
    profile = pp.load_venue_profile("nature-biotechnology")
    cover = profile.length_limits()["cover letter"]
    check("C25 Nature Biotechnology carries no 650-word total cap",
          cover.get("total_max") is None, str(cover))


def main() -> int:
    try:
        test_handoff_checklist()
        test_duplicate_roles()
        test_readiness_venue_base()
        test_stale_driver_guard()
        test_pairwise()
        test_placeholder_selection()
        test_document_roles()
        test_package_scan_false_results()
        test_declared_submission_set()
        test_champion_prefix()
        test_publication_identity()
        test_journal_mode_and_judge_blinding()
        test_venue_cover_limit()
    finally:
        for path in TMPDIRS:
            shutil.rmtree(path, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("2026-10-17 SERIAL-AUDIT REGRESSIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
