#!/usr/bin/env python3
"""The code-side evidence pack in EVERY session (review / rewrite / revise / integrate / judge).

Run:  python3 .nbt_test/test_evidence_pack.py

The orchestrator measures the corpus with the same functions everywhere:
M18 legend counts, M19 abstract/main-text lengths, M20 OOXML formatting rows,
the hand-off placeholder count and the corpus identity (digest, files, revision
token). This suite pins that

  * the pack is written for each of the five session layouts, with the M18/M19/
    M20 artifact tables seeded for the review and the judge,
  * the seeded files are treated as INPUTS by the "sandbox already has work"
    guard (never as agent output),
  * every prompt carries the evidence-pack block,
  * the materialized sandboxes of a real stub round each contain their pack, and
  * the review's and the judge's numbers agree (same corpus, same functions),
  * a stage records its own before/after evidence delta.
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

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_evidence", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_evidence"] = nb
spec.loader.exec_module(nb)
fmt_spec = importlib.util.spec_from_file_location("nbt_fmt_ev", str(WS / "nbt_docx_format.py"))
fmt = importlib.util.module_from_spec(fmt_spec)
sys.modules["nbt_fmt_ev"] = fmt
fmt_spec.loader.exec_module(fmt)

STUB = WS / ".nbt_test" / "stub_agent.py"
STUB_JUDGE = WS / ".nbt_test" / "stub_judge.py"
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


def make_corpus(dirp: Path) -> None:
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 90).strip() + "\n\nIntroduction\n\n"
        + ("text " * 120).strip() + "\n\nFigure 1 | A legend here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    # a small docx with a mechanical defect (a break-only paragraph) + a plain URL
    body = [
        "<w:p><w:r><w:t>Title</w:t></w:r></w:p>",
        "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>",
        "<w:p><w:r><w:t xml:space=\"preserve\">See https://example.org/a for the code.</w:t></w:r></w:p>",
        "<w:p><w:pPr><w:pStyle w:val=\"Bibliography\"/></w:pPr>"
        "<w:r><w:t>1. Chen, C. et al.</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>et al.</w:t></w:r></w:p>",
    ]
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>" + "".join(body) + "</w:body></w:document>")
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              "</w:styles>")
    with zipfile.ZipFile(dirp / "supplement.docx", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)


def make_text_corpus(dirp: Path) -> None:
    """A Word-free corpus for the stub e2e part: the stub does not render pages,
    and a .docx in the corpus would (correctly) trip the visual-artifact gate."""
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 90).strip() + "\n\nIntroduction\n\n"
        + ("text " * 120).strip() + "\n\nFigure 1 | A legend here.\n\nMethods\n\nx\n",
        encoding="utf-8")


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def run_only(root: Path, only: str):
    return cli("run", "--root", str(root), "--only", only,
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "0")


def test_seeding_layouts():
    print()
    print("== the pack is written for every session layout ==")
    tmp = scratch("nbt_ev_unit_")
    corpus = tmp / "corpus"
    make_corpus(corpus)
    ctx = type("C", (), {"cfg": {}})()
    for where, sub in (("review", "review"), ("stage", "work")):
        sb = tmp / f"run_{where}"
        sb.mkdir()
        ev = nb.seed_evidence_pack(ctx, sb, corpus, where)
        work = sb / "work" if where == "stage" else sb / sub / "work"
        check(f"{where}: CODE_SCANS.json is written",
              (work / "CODE_SCANS.json").is_file())
        check(f"{where}: the pack carries all five evidence families",
              all(k in ev for k in ("captions", "lengths", "format", "placeholders",
                                    "corpus_identity"))
              and (ev["captions"].get("count") or 0) >= 1
              and (ev["lengths"].get("rows") or []) and (ev["format"].get("rows") or [])
              and ev["corpus_identity"].get("digest"),
              nb.evidence_pack_summary(ev)[:160])
        check(f"{where}: EVIDENCE_PACK.md is written for humans",
              (work / "EVIDENCE_PACK.md").is_file() and (sb / "EVIDENCE_PACK.md").is_file())
        check(f"{where}: FORMAT_SCAN.json mirrors the formatting scan",
              json.loads((work / "FORMAT_SCAN.json").read_text(encoding="utf-8"))
              .get("rows") is not None)
        if where in ("review",):
            art = sb / sub / "artifacts"
            for name in ("M18_caption_words.md", "M19_length.md", "M20_formatting.md",
                         "M4_numbers.md", "M8_terms.md", "OUTLINE.md", "PLACEHOLDERS.md"):
                check(f"{where}: the {name} table is seeded",
                      (art / name).is_file() and "| disposition |"
                      in (art / name).read_text(encoding="utf-8"))
        for key in ("numbers", "terms", "outline", "placeholder_ledger"):
            check(f"{where}: the pack carries the {key} artifact engine",
                  isinstance(ev.get(key), dict) and (
                      "rows" in (ev.get(key) or {}) or "error" in (ev.get(key) or {})),
                  json.dumps(ev.get(key))[:120])
        if where == "stage":
            check("the stage pack is the sandbox-level work/ layout (no artifacts/ dir)",
                  not (sb / "artifacts").exists())
        # the guard must treat every seeded file as an INPUT
        seeded = {p.resolve() for p in nb.seeded_evidence_paths(sb)}
        written = {p.resolve() for p in sb.rglob("*") if p.is_file()}
        check(f"{where}: every seeded file is declared as an input (not agent work)",
              written <= seeded, f"undeclared: "
              f"{sorted(str(p.relative_to(sb)) for p in written - seeded)}")


def test_prompts():
    print()
    print("== every prompt carries the evidence-pack block ==")
    tmp = Path("/tmp/nbt_ev_prompts")
    prompts = {
        "review": nb.review_prompt(tmp, "r1_review", 1),
        "revise": nb.revise_prompt(tmp, "r1_a2_revise", 1),
        "rewrite": nb.rewrite_prompt(tmp, "r1_w1", 1),
        "integrate": nb.integrate_prompt(tmp, "r1_i1", 1, "a1", ["w1"]),
        "judge": nb.judge_prompt(tmp, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]),
    }
    for stage, text in prompts.items():
        check(f"{stage}: no unresolved evidence token", "@@EVIDENCE_PACK_RULE@@" not in text)
    for stage in ("review", "revise", "rewrite", "integrate"):
        check(f"{stage}: evidence-pack block present",
              "CODE-SIDE EVIDENCE PACK" in prompts[stage]
              and "CODE_SCANS.json" in prompts[stage])
    check("the judge prompt carries the blinding rule INSTEAD of a pack",
          "BLINDING RULE" in prompts["judge"]
          and ("no orchestrator scan" in prompts["judge"]
               or "no orchestrator measurements" in prompts["judge"])
          and "no pre-computed check rows" in prompts["judge"]
          and "CODE_SCANS.json" not in prompts["judge"])
    check("the judge prompt still tells the judge to derive its own rows",
          "nbt_docx_format.py scan" in prompts["judge"]
          and "judge_review/artifacts/" in prompts["judge"])
    check("the review prompt names the seeded artifact tables",
          "review/artifacts/M18_caption_words.md" in prompts["review"])
    check("a stage prompt points at its sandbox-level pack",
          "work/CODE_SCANS.json" in prompts["revise"])


def test_pack_scans_the_corpus_not_the_scratch():
    """A stage writes its process scratch INSIDE its output directory
    (`revised/work/`), so a raw walk of that directory counted the agent's own
    snapshots, renders and notes as manuscript documents: a real run reported
    "this stage left MORE over-cap section(s) (0 -> 7)" and "hand-off
    placeholders 4 -> 73" from its own work/ copies, and the pack carried a
    corpus digest no other part of the pipeline used."""
    print()
    print("== the pack scans the CORPUS, never the session's own work/ ==")
    tmp = scratch("nbt_ev_scratch_")
    pkg = tmp / "revised"
    make_corpus(pkg)
    work = pkg / "work" / "render"
    work.mkdir(parents=True)
    (work / "mainText.txt").write_text(
        "Abstract\n\n" + ("filler " * 9000) + "\n\nIntroduction\n\n" + ("text " * 9000),
        encoding="utf-8")
    (work / "STATE.md").write_text("pending: [AUTHOR TO COMPLETE: accession number]\n",
                                   encoding="utf-8")
    shutil.copyfile(pkg / "supplement.docx", work / "supplement.docx")
    ctx = nb.Ctx(tmp)
    ctx.cfg = {"caption_limit": 0, "format_policy": {}}
    ctx.state = {"config": ctx.cfg}
    ev = nb.code_side_evidence(ctx, pkg, "scratch:test")
    files = list((ev.get("corpus_identity") or {}).get("files") or [])
    check("the pack's file list has no work/ entries",
          files and not any(f.startswith("work/") for f in files), str(files))
    check("the pack's placeholder count ignores the session's notes",
          (ev.get("placeholders") or {}).get("count") == 0,
          str((ev.get("placeholders") or {}).get("count")))
    rows = list((ev.get("lengths") or {}).get("rows") or [])
    check("the pack's length rows ignore the session's own renderings",
          rows and not any(str(r.get("document", "")).startswith("work/") for r in rows),
          str([r.get("document") for r in rows]))
    check("no over-cap section comes from the scratch copy",
          not ((ev.get("lengths") or {}).get("over_limit")),
          str((ev.get("lengths") or {}).get("over_limit")))
    check("the pack's digest IS the corpus identity the pipeline records",
          (ev.get("corpus_identity") or {}).get("digest")
          == nb.manifest_digest(nb.corpus_dir_manifest(pkg, exclude_top=nb.CORPUS_EXCLUDE_TOP))
          and (ev.get("corpus_identity") or {}).get("digest") != nb.corpus_tree_digest(pkg),
          str((ev.get("corpus_identity") or {}).get("digest"))[:16])


def test_stub_round_sessions():
    print()
    print("== a real stub round: every session sandbox gets its pack ==")
    tmp = scratch("nbt_ev_e2e_")
    src = tmp / "src"
    make_text_corpus(src)
    root = tmp / "root"
    setup = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
                "--rewrites", "1", "--revises", "1", "--judges", "1")
    check("setup succeeds", setup.returncode == 0, (setup.stdout + setup.stderr)[-200:])
    p = run_only(root, "rewrite")
    check("--only rewrite seeds the rewrite session's pack",
          (root / "runs" / "r1_w1" / "work" / "CODE_SCANS.json").is_file(),
          (p.stdout + p.stderr)[-160:])
    p = run_only(root, "review")
    rev_sb = root / "runs" / "r1_review"
    check("--only review seeds the review's pack + the three artifact tables",
          (rev_sb / "review" / "work" / "CODE_SCANS.json").is_file()
          and all((rev_sb / "review" / "artifacts" / n).is_file() for n in
                  ("M18_caption_words.md", "M19_length.md", "M20_formatting.md",
                   "M4_numbers.md", "M8_terms.md", "OUTLINE.md", "PLACEHOLDERS.md")))
    p = run_only(root, "audit")          # the auditor sits between review and revise
    check("--only audit seeds the auditor's pack and the frozen review",
          (root / "runs" / "r1_audit" / "work" / "CODE_SCANS.json").is_file()
          and (root / "runs" / "r1_audit" / "review" / "findings.json").is_file(),
          (p.stdout + p.stderr)[-160:])
    p = run_only(root, "revise")
    check("--only revise seeds the revise session's pack",
          (root / "runs" / "r1_a2_revise" / "work" / "CODE_SCANS.json").is_file(),
          (p.stdout + p.stderr)[-160:])
    p = run_only(root, "merge")
    inst = [root / "runs" / f"r1_i{k}" for k in (1, 2, 3)]
    check("--only merge seeds every integration session's pack",
          all((sb / "work" / "CODE_SCANS.json").is_file() for sb in inst))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = (state.get("runs") or {}).get("r1_i1") or {}
    check("an integration run records its before/after evidence delta",
          bool(rec.get("evidence_after")) and "format_rows" in (rec.get("evidence_delta") or {}),
          json.dumps(rec.get("evidence_delta") or {})[:200])
    check("a stage records its deliverable validation (DOCX XML + LaTeX)",
          (rec.get("validation") or {}).get("docx_ok") is True
          and "files" in (rec.get("validation") or {}),
          json.dumps(rec.get("validation") or {})[:200])
    check("a stage's pack identity IS the corpus digest the run records",
          (rec.get("evidence_after") or {}).get("corpus_identity", {}).get("digest")
          == rec.get("corpus_digest"),
          f"{(rec.get('evidence_after') or {}).get('corpus_identity', {}).get('digest')} vs "
          f"{rec.get('corpus_digest')}")
    check("the integration sandbox keeps the re-scan artifacts",
          (root / "runs" / "r1_i1" / "CODE_SCANS_after.json").is_file()
          and (root / "runs" / "r1_i1" / "CODE_SCANS_before.json").is_file())
    # judge sandboxes: materialize before running the judge wave
    ctx = nb.Ctx(root)
    ctx.load()
    field, _dropped = nb.build_field(ctx, 1)
    judge_ids = nb.materialize_judges(ctx, 1, field)
    check("the judge wave materialized", len(judge_ids) == len(field), str(judge_ids))
    first = ctx.sandbox_of(ctx.run(judge_ids[0]))
    # BLINDING: a judge sandbox must hold ONLY the blinded packages (plus the
    # prompt, the run's own marker and the public stateless tool its prompt names)
    # -- no orchestrator scan, no digest, no review artifacts, no evidence pack.
    leaked = []
    for p in first.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(first).as_posix()
        if rel.startswith(("target/", "field/", "original/")) \
                or rel in ("PROMPT.md", nb.DOCX_FORMAT_MODULE):
            continue
        leaked.append(rel)
    check("the judge sandbox contains no orchestrator artifact (blinding)",
          leaked == [], f"leaked: {leaked[:6]}")
    check("no review/ directory is handed to a judge",
          not (first / "review").exists())
    check("the judge prompt in the sandbox carries the blinding rule",
          "BLINDING RULE" in (first / "PROMPT.md").read_text(encoding="utf-8"))
    check("a freshly materialized judge sandbox is not treated as started",
          nb.leftovers_present(ctx, ctx.run(judge_ids[0])) is False)
    # finish the round with the judge wave and confirm it still passes its contract
    p = run_only(root, "judge")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("--only judge completes the round with the seeded packs in place",
          (state.get("rounds", {}).get("1") or {}).get("status") == "done",
          (p.stdout + p.stderr)[-200:])
    # The orchestrator verifies the judge's own rows afterwards, from ITS side:
    # the scan lives in reports/ (never in the sandbox) and a judge that produced
    # no M18/M19/M20 artifact is warned about, not failed.
    jrec = None
    for rid, rec in (state.get("runs") or {}).items():
        if rec.get("kind") == "judge" and rec.get("judge_evidence"):
            jrec = (rid, rec)
            break
    check("the orchestrator recorded its own scan of a blinded judge target",
          jrec is not None, "no judge run carries judge_evidence")
    if jrec:
        rid, rec = jrec
        check("the judge evidence scan is written outside the sandbox",
              (root / "reports" / f"judge_evidence_{rid}.json").is_file())
        warns = (rec.get("postcheck") or {}).get("warnings") or []
        check("a judge that produced no M18/M19/M20 artifact gets an auditable warning",
              any("BLIND JUDGE GROUNDING" in w for w in warns), str(warns[:1])[:160])
        check("the judge run still passed its contract (the warning is not a gate)",
              rec.get("status") == "done", str(rec.get("status")))


def main() -> int:
    try:
        test_seeding_layouts()
        test_prompts()
        test_pack_scans_the_corpus_not_the_scratch()
        test_stub_round_sessions()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} EVIDENCE-PACK CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL EVIDENCE-PACK CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
