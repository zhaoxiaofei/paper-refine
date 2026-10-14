#!/usr/bin/env python3
"""`code/` is a NON-SUBMITTED area: the submission and its letter never refer into it

The analysis-code area is revision content (a stage may revise it), but the
author does not submit it by default -- exactly like the `raw_data/` evidence
area. The rules follow, and this suite pins them:

  * `publish_journal_submission` strips `code/` together with the evidence
    areas, and `journal_submission.json` records `code_included: False`;
  * a to-be-submitted document -- the response-to-reviewers letter -- must not
    cite a `code/` path in `changes`/`new_data` (`postcheck_response`), while
    the round's own champion corpus still carries the code;
  * the switch (`setup --submit-code on` / `set-submit-code on`) submits the
    area instead: the re-assembled copy carries `code/`, the manifest says so,
    and the same citation passes;
  * a shipped file that still refers into a stripped area is REPORTED (PKG-2,
    `journal_submission.json.non_submitted_references`), never rewritten and
    never a failure -- and the report disappears once the area ships;
  * the author's own `README*.md` / `README*.txt` files are never submitted
    either (treated like `code/` for submission purposes): the copy drops them
    at any depth, the manifest names them, a shipped reference to one is a
    PKG-2 row, and a letter may not cite one.

Run:  python3 .paper_test/test_submission_code_area.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("journal_revision_modes_lib",
                                               HERE / "journal_revision_modes_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["journal_revision_modes_lib"] = lib
_spec.loader.exec_module(lib)
nb = lib.nb


def test_code_rel_helper():
    print()
    print("== SC0: the code-area predicate ==")
    lib.check("SC0 a code/ path is inside the analysis-code area",
              nb.is_code_rel("code/analysis.py") and nb.is_code_rel("code/nested/x.R"))
    lib.check("SC0 a document, an evidence path and a codex/ directory are not",
              not nb.is_code_rel("manuscript.txt") and not nb.is_code_rel("raw_data/x.tsv")
              and not nb.is_code_rel("codex/analysis.py") and not nb.is_code_rel("figs/code/x.py"))


def test_submission_excludes_code():
    print()
    print("== SC1: the submission package never carries the code/ area ==")
    tmp = lib.scratch("paper_code_area_")
    root = lib.setup_and_run(tmp, "major", with_code=True)
    files = lib.submission_files(root)
    lib.check("SC1 the submission excludes the code/ area",
              not any(f.startswith("code/") for f in files), str(files))
    lib.check("SC1 the to-be-submitted set still carries the documents and the letter",
              "manuscript.txt" in files and "RESPONSE_TO_REVIEWERS.md" in files
              and "response_map.json" in files, str(files))
    sub_manifest = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    lib.check("SC1 the manifest records the absence of raw_data/ AND code/",
              sub_manifest.get("raw_data_included") is False
              and sub_manifest.get("code_included") is False, str(sub_manifest)[:200])
    lib.check("SC1 no code/ file is in the manifest's own file list",
              not any(k.startswith("code/") for k in
                      ((sub_manifest.get("manifest") or {}).get("files") or {})))
    carried = [p for p in root.rglob("code/analysis.py")
               if "journal_submission" not in p.parts]
    lib.check("SC1 the round's own package still carries the analysis code",
              bool(carried), str(carried[:3]))


def test_response_letter_never_cites_code():
    print()
    print("== SC2: the response letter must not refer into code/ ==")
    tmp = lib.scratch("paper_code_letter_")
    root = lib.setup_and_run(tmp, "major", with_code=True)
    ctx = nb.Ctx(root)
    ctx.load()
    rec = ctx.run("r1_response")
    map_path = ctx.sandbox_of(rec) / nb.JOURNAL_RESPONSE_MAP_REL
    data = json.loads(map_path.read_text(encoding="utf-8"))
    rows = [r for r in (data.get("rows") or []) if isinstance(r, dict)]
    lib.check("SC2 the letter cites submission documents only (stub fixture)",
              rows and all(not str(c.get("file") or "").startswith("code/")
                           for r in rows for c in (r.get("changes") or [])),
              json.dumps([r.get("changes") for r in rows])[:200])
    lib.check("SC2 the package the letter is verified against carries the code",
              (ctx.sandbox_of(rec) / "target" / "code" / "analysis.py").is_file())
    prompt = nb.response_prompt(ctx, ctx.sandbox_of(rec), 1, "the final package",
                                {"concerns": []})
    lib.check("SC2 the letter prompt states the rule",
              "`code/` is NOT part of the submission" in prompt
              and "never cite a `code/` path" in prompt)
    ok, errs, _w, _x = nb.postcheck_response(ctx, rec)
    lib.check("SC2 the pristine letter passes the postcheck", ok, str(errs)[:200])
    # A citation into the (present, but never-submitted) code area fails the
    # letter, and the reason names the code area -- not a missing file.
    rows[0]["changes"] = [{"file": "code/analysis.py", "location": "stub",
                           "before": "a", "after": "b"}]
    nb.write_json_atomic(map_path, data)
    ok2, errs2, _w2, _x2 = nb.postcheck_response(ctx, rec)
    lib.check("SC2 a changes[] citation into code/ fails the letter",
              not ok2 and any("points into code/" in e for e in errs2), str(errs2)[:300])
    rows[0]["changes"] = []
    rows[0]["new_data"] = ["code/analysis.py"]
    nb.write_json_atomic(map_path, data)
    ok3, errs3, _w3, _x3 = nb.postcheck_response(ctx, rec)
    lib.check("SC2 a new_data[] citation into code/ fails the letter",
              not ok3 and any("points into code/" in e for e in errs3), str(errs3)[:300])


def test_submit_code_switch():
    print()
    print("== SC3: `code` can be submitted on request ==")
    tmp = lib.scratch("paper_code_switch_")
    root = lib.setup_and_run(tmp, "major", with_code=True)
    r = lib.run_cli("set-submit-code", "--root", str(root))
    lib.check("SC3 `set-submit-code` shows the policy", r.returncode == 0
              and "code/ in the submission: off" in r.stdout, r.stdout[-200:])
    r = lib.run_cli("set-submit-code", "on", "--root", str(root))
    lib.check("SC3 `set-submit-code on` is accepted", r.returncode == 0
              and "code/ in the submission: on" in r.stdout, (r.stdout + r.stderr)[-200:])
    ctx = nb.Ctx(root)
    ctx.load()
    lib.check("SC3 the recorded config carries the policy",
              json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
              .get("submit_code") == "on")
    target, label = nb.journal_final_target(ctx)
    nb.publish_journal_submission(ctx, target, label,
                                  response_dir=ctx.sandbox_of(ctx.run("r1_response")))
    files = lib.submission_files(root)
    lib.check("SC3 the re-assembled submission carries the code/ area",
              "code/analysis.py" in files, str(files))
    sub_manifest = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    lib.check("SC3 the manifest records code_included True",
              sub_manifest.get("code_included") is True
              and sub_manifest.get("raw_data_included") is False, str(sub_manifest)[:200])
    rec = ctx.run("r1_response")
    map_path = ctx.sandbox_of(rec) / nb.JOURNAL_RESPONSE_MAP_REL
    data = json.loads(map_path.read_text(encoding="utf-8"))
    data["rows"][0]["changes"] = [{"file": "code/analysis.py", "location": "stub",
                                   "before": "a", "after": "b"}]
    nb.write_json_atomic(map_path, data)
    ok, errs, _w, _x = nb.postcheck_response(ctx, rec)
    lib.check("SC3 with the policy on, the same citation PASSES the letter",
              ok, str(errs)[:300])
    prompt = nb.response_prompt(ctx, ctx.sandbox_of(rec), 1, "the final package",
                                {"concerns": []})
    lib.check("SC3 with the policy on, the prompt allows a code citation",
              "ships with this submission" in prompt
              and "`code/` is NOT part of the submission" not in prompt)
    r = lib.run_cli("set-submit-code", "off", "--root", str(root))
    lib.check("SC3 the policy flips back off", r.returncode == 0
              and "code/ in the submission: off" in r.stdout, r.stdout[-200:])
    ctx.load()
    ok2, errs2, _w2, _x2 = nb.postcheck_response(ctx, rec)
    lib.check("SC3 with the policy off again, the same citation fails again",
              not ok2 and any("points into code/" in e for e in errs2), str(errs2)[:300])
    # The same switch at setup time.
    src2 = lib.build_source(tmp / "src2", with_code=True)
    root2 = tmp / "root2"
    r = lib.run_cli("setup", "--source", str(src2), "--root", str(root2),
                    "--rounds", "1", "--revision-mode", "major", "--submit-code", "on",
                    "--journal", "iScience")
    lib.check("SC3 `setup --submit-code on` records the policy",
              r.returncode == 0
              and json.loads((root2 / "pipeline_config.json").read_text(encoding="utf-8"))
              .get("submit_code") == "on", (r.stdout + r.stderr)[-200:])


def test_dangling_reference_report():
    print()
    print("== SC4: a pointer at a stripped area is REMOVED from the shipped file (PKG-2) ==")
    # The scan is a pure function of a tree: a plain path is a row, a URL tail
    # (a longer path that merely ends in code/) is not.
    tmp = lib.scratch("paper_code_refs_")
    pkg = tmp / "pkg"
    (pkg / "code").mkdir(parents=True)
    (pkg / "code" / "analysis.py").write_text("print('x')\n", encoding="utf-8")
    (pkg / "manuscript.md").write_text(
        "Methods\nWe ran code/analysis.py to draw Figure 1.\n",
        encoding="utf-8")
    (pkg / "url.md").write_text(
        "See https://github.com/team/repo/tree/main/code/analysis.py for context.\n",
        encoding="utf-8")
    rows = nb.non_submitted_reference_rows(pkg, ("code", "raw_data", "raw_figs"))
    lib.check("SC4 the scan reports the plain code/ path",
              any(r["file"] == "manuscript.md" and r["reference"] == "code/analysis.py"
                  for r in rows), str(rows)[:300])
    lib.check("SC4 the scan ignores a code/ tail inside a URL",
              not any(r["file"] == "url.md" for r in rows), str(rows)[:300])
    (pkg / "data.md").write_text("The tables are in raw_data/tables.tsv.\n", encoding="utf-8")
    input_rows = nb.non_submitted_reference_rows(pkg, ("raw_data",))
    lib.check("SC4 a read-only input's row says it never ships (no `set-submit-code` hint)",
              input_rows and "never ships" in input_rows[0]["detail"]
              and "set-submit-code" not in input_rows[0]["detail"], str(input_rows)[:300])
    lib.check("SC4 the scan reports nothing when the package carries every area",
              nb.non_submitted_reference_rows(pkg, ()) == [])
    # End to end: a document of the corpus that cites code/ reaches the
    # submission with the SENTENCE that carried the pointer removed, and the
    # removal is recorded verbatim (never silent).
    root = lib.setup_and_run(
        tmp / "e2e", "major", with_code=True,
        extra_source_files={"notes.md": "Methods\nWe ran code/analysis.py for Figure 1.\n"
                                        "The benchmark is described in the main text.\n",
                            "data_note.md": "The data live in raw_data/tables.tsv.\n"})
    sub_manifest = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    refs = sub_manifest.get("non_submitted_references") or []
    # The removal runs in the stage postcheck (before the package is pinned) and
    # in the submission assembly: both record it, so the journal manifest is
    # read together with the run record.
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    strips = [r.get("reference_strip") or {} for r in (state.get("runs") or {}).values()]
    removed = [x for s in strips for x in (s.get("files") or [])]
    removed += sub_manifest.get("removed_dangling_references") or []
    lib.check("SC4 the REMOVED pointer is recorded verbatim in the run record",
              any(r.get("file") == "notes.md"
                  and any("code/analysis.py" in s for s in (r.get("removed")
                                                            or r.get("sentences") or []))
                  for r in removed), str(removed)[:400])
    lib.check("SC4 the read-only input's pointer is removed too",
              any(r.get("file") == "data_note.md"
                  and any("raw_data/tables.tsv" in s for s in (r.get("removed")
                                                               or r.get("sentences") or []))
                  for r in removed), str(removed)[:400])
    shipped = (root / "journal_submission" / "notes.md").read_text(encoding="utf-8")
    lib.check("SC4 the shipped document no longer carries the pointer",
              "code/analysis.py" not in shipped, shipped[:200])
    lib.check("SC4 the removal keeps the sentences around it",
              "Methods" in shipped and "described in the main text" in shipped, shipped[:200])
    lib.check("SC4 nothing dangling is left in the submission",
              refs == [], str(refs)[:300])
    # Once the area ships, the code reference resolves (the raw_data/ one, in a
    # read-only input, still does not).
    ctx = nb.Ctx(root)
    ctx.load()
    ctx.cfg["submit_code"] = "on"
    nb.write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.load()
    target, label = nb.journal_final_target(ctx)
    nb.publish_journal_submission(ctx, target, label,
                                  response_dir=ctx.sandbox_of(ctx.run("r1_response")))
    sub_manifest = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    lib.check("SC4 with `submit_code: on` the code reference is no finding",
              sub_manifest.get("code_included") is True
              and not any(str(r.get("reference") or "").startswith("code/")
                          for r in (sub_manifest.get("non_submitted_references") or [])),
              str(sub_manifest.get("non_submitted_references"))[:300])


def test_readme_files_are_never_submitted():
    print()
    print("== SC5: README*.md / README*.txt files are never submitted ==")
    lib.check("SC5 the README glob matches those names (case-insensitively)",
              nb.is_non_submitted_readme_name("README.md")
              and nb.is_non_submitted_readme_name("README-notes.txt")
              and nb.is_non_submitted_readme_name("readme.md")
              and nb.is_non_submitted_readme_name("README-dev.md")
              and not nb.is_non_submitted_readme_name("README.docx")
              and not nb.is_non_submitted_readme_name("myREADME.md")
              and not nb.is_non_submitted_readme_name("README"))
    tmp = lib.scratch("paper_code_readme_")
    root = lib.setup_and_run(
        tmp, "major", with_code=True,
        extra_source_files={
            "README.md": "# author working notes\nrun code/analysis.py\n",
            "docs/README-dev.txt": "developer notes\n",
            "notes.md": "Methods\nSee README.md for how the pipeline ran.\n"
                        "Mirror: https://github.com/team/repo/README.md\n"})
    files = lib.submission_files(root)
    lib.check("SC5 the submission drops every README*.md/.txt file (any depth)",
              not any(nb.is_non_submitted_readme_name(Path(f).name) for f in files), str(files))
    lib.check("SC5 the other documents still ship",
              "manuscript.txt" in files and "notes.md" in files, str(files))
    sub_manifest = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    lib.check("SC5 the manifest names the dropped README files",
              sub_manifest.get("readme_files_excluded") == ["README.md", "docs/README-dev.txt"],
              str(sub_manifest.get("readme_files_excluded")))
    refs = sub_manifest.get("non_submitted_references") or []
    shipped_notes = (root / "journal_submission" / "notes.md").read_text(encoding="utf-8")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    removed = [x for r in (state.get("runs") or {}).values()
               for x in ((r.get("reference_strip") or {}).get("files") or [])]
    removed += sub_manifest.get("removed_dangling_references") or []
    lib.check("SC5 a shipped README reference is REMOVED (PKG-2, bare)",
              any(r.get("file") == "notes.md"
                  and any("README.md" in s for s in (r.get("removed")
                                                     or r.get("sentences") or []))
                  for r in removed)
              and "See README.md" not in shipped_notes, str(removed)[:400])
    lib.check("SC5 a URL that merely ends in a README name survives, and is no row",
              "https://github.com/team/repo/README.md" in shipped_notes
              and not any(str(r.get("reference") or "").startswith("https")
                          for r in refs), f"{shipped_notes[:200]!r} {str(refs)[:200]}")
    lib.check("SC5 the dropped README files really are gone from the copy",
              not (root / "journal_submission" / "README.md").exists()
              and not (root / "journal_submission" / "docs" / "README-dev.txt").exists())
    # A README is not citable by the letter either (the same rule as code/).
    ctx = nb.Ctx(root)
    ctx.load()
    rec = ctx.run("r1_response")
    map_path = ctx.sandbox_of(rec) / nb.JOURNAL_RESPONSE_MAP_REL
    prompt = nb.response_prompt(ctx, ctx.sandbox_of(rec), 1, "the final package",
                                {"concerns": []})
    lib.check("SC5 the letter prompt states the README rule",
              "`README*.md` / `README*.txt` files are NEVER submitted" in prompt)
    data = json.loads(map_path.read_text(encoding="utf-8"))
    data["rows"][0]["changes"] = [{"file": "docs/README-dev.txt", "location": "stub",
                                   "before": "a", "after": "b"}]
    nb.write_json_atomic(map_path, data)
    ok, errs, _w, _x = nb.postcheck_response(ctx, rec)
    lib.check("SC5 a letter citing a README file fails the postcheck",
              not ok and any("README*.md" in e for e in errs), str(errs)[:300])
    # ... and the exclusion is unconditional: submitting the code does not
    # resurrect the README files.
    ctx.cfg["submit_code"] = "on"
    nb.write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.load()
    target, label = nb.journal_final_target(ctx)
    nb.publish_journal_submission(ctx, target, label,
                                  response_dir=ctx.sandbox_of(ctx.run("r1_response")))
    files = lib.submission_files(root)
    lib.check("SC5 `submit_code: on` still does not ship a README",
              "code/analysis.py" in files
              and not any(nb.is_non_submitted_readme_name(Path(f).name) for f in files),
              str(files))


if __name__ == "__main__":
    sys.exit(lib.run_parts(
        [test_code_rel_helper, test_submission_excludes_code,
         test_response_letter_never_cites_code, test_submit_code_switch,
         test_dangling_reference_report, test_readme_files_are_never_submitted],
        "SUBMISSION CODE-AREA CHECKS PASSED"))
