#!/usr/bin/env python3
"""Assert the FIXED behaviour of the findings in nbt_round_pipeline_issue_findings.md.

Run:  python3 .nbt_test/test_fixes.py

`NBT_WS` retargets the harness at a baseline copy of the tree.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xfix as xf  # noqa: E402  (shared fixture shapes)

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbtp", WS / "nbt_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["nbtp"] = np
spec.loader.exec_module(np)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_ctx(tmp):
    (tmp / "runs").mkdir(parents=True, exist_ok=True)
    (tmp / "reports").mkdir(parents=True, exist_ok=True)
    ctx = np.Ctx(tmp)
    ctx.cfg = {"rounds": 1, "judges": 1, "caption_limit": 0}
    ctx.state = {"version": np.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": {"files": {}, "count": 0}, "original_digest": "d",
                 "config": ctx.cfg}
    return ctx


def full_coverage(caption=False):
    rows = [{"check": c, "disposition": "clean -- basis: x"} for c in
            [f"M{i}" for i in range(1, 18)] + [f"J{i}" for i in range(1, 5)]]
    rows.append({"check": "M19", "disposition": "0 findings -- within the relaxed caps"})
    rows.append({"check": "M18", "disposition": "0 findings"})
    rows.append({"check": "M20", "disposition": "0 findings -- formatting rows disposed"})
    for cid in ("M21", "M22", "M23", "M24"):
        rows.append({"check": cid, "disposition": f"clean -- basis: fixture {cid}"})
    return rows


def review_sandbox(tmp, submission_dir="./base", coverage=None, artifacts=True,
                   ids=("F-001",), vis=True, word_doc=False):
    (tmp / "runs").mkdir(exist_ok=True)
    (tmp / "reports").mkdir(exist_ok=True)
    sb = tmp / "runs/r1_a2_review"
    (sb / "base").mkdir(parents=True, exist_ok=True)
    (sb / "base/manuscript-o.md").write_text("text\n", encoding="utf-8")
    if word_doc:
        import zipfile as _zip
        ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        with _zip.ZipFile(sb / "base/manuscript-o.docx", "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml",
                       f'<?xml version="1.0"?><w:document {ns}><w:body><w:p><w:r>'
                       f'<w:t>text</w:t></w:r></w:p></w:body></w:document>')
    (sb / "non-revised").mkdir(parents=True, exist_ok=True)
    (sb / "non-revised/manuscript-o.md").write_text("text\n", encoding="utf-8")
    (sb / "review").mkdir(parents=True, exist_ok=True)
    findings = [{"id": i, "location": "base/manuscript-o.md", "category": 0, "check": "M1",
                 "severity": "Minor", "evidence": "e", "explanation": "x",
                 "status": "resolvable"} for i in ids]
    (sb / "review/findings.json").write_text(json.dumps(
        {"submission_dir": submission_dir, "guidelines_source": "x", "findings": findings,
         "artifacts": {}, "coverage": full_coverage() if coverage is None else coverage}),
        encoding="utf-8")
    (sb / "review/findings.md").write_text("# stub\n", encoding="utf-8")
    if artifacts:
        (sb / "review/artifacts").mkdir(parents=True, exist_ok=True)
        (sb / "review/artifacts/M1.md").write_text("|row|\n", encoding="utf-8")
        if vis:
            (sb / "review/artifacts/VIS_visual.md").write_text("# vis\n", encoding="utf-8")
    np.write_json_atomic(sb / np.MARKER_FILE, {"stage": "review", "run_id": "r1_a2_review",
                                               "round": 1, "status": "complete"})
    return sb


print("=" * 70)
print("F02/F03 - review contract is enforced")
tmp = Path(tempfile.mkdtemp())
ctx = make_ctx(tmp)
sb = review_sandbox(tmp)
ctx.state["source_manifest"] = np.hash_manifest(sb / "non-revised")
rec = ctx.register("r1_a2_review", "review", 1, "runs/r1_a2_review")
rec["inputs_manifest"] = {"base": np.hash_manifest(sb / "base"),
                          "non-revised": np.hash_manifest(sb / "non-revised")}
ok, errs, warns, _ = np.postcheck_review(ctx, rec)
check("well-formed review passes", ok, str(errs)[:120])
for label, kw in (("wrong submission_dir", dict(submission_dir="./non-revised")),
                  ("missing coverage rows",
                   dict(coverage=[{"check": "M1", "disposition": "clean"}])),
                  ("no artifacts dir", dict(artifacts=False)),
                  ("duplicate finding ids", dict(ids=("F-001", "F-001"))),
                  ("no visual record (Word document present)",
                   dict(vis=False, word_doc=True))):
    tmp2 = Path(tempfile.mkdtemp())
    ctx2 = make_ctx(tmp2)
    sb2 = review_sandbox(tmp2, **kw)
    ctx2.state["source_manifest"] = np.hash_manifest(sb2 / "non-revised")
    r2 = ctx2.register("r1_a2_review", "review", 1, "runs/r1_a2_review")
    r2["inputs_manifest"] = {"base": np.hash_manifest(sb2 / "base"),
                             "non-revised": np.hash_manifest(sb2 / "non-revised")}
    ok2, errs2, _w, _ = np.postcheck_review(ctx2, r2)
    check(f"review with {label} FAILS", not ok2, str(errs2)[:110])
    shutil.rmtree(tmp2, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 70)
print("F07 - the ledger deliverables are required")
for kind, files, expect_fail in (("revise", ["revision_report.json"], False),
                                 ("revise", [], True),
                                 ("integrate", ["revision_report.json", "DIFF_LEDGER.md"], False),
                                 ("integrate", ["revision_report.json"], True)):
    tmp = Path(tempfile.mkdtemp())
    ctx = make_ctx(tmp)
    rid = "r1_a2_revise" if kind == "revise" else "r1_i1"
    out_dir = np.output_dir_for_kind(kind)
    sb = tmp / "runs" / rid
    (sb / out_dir).mkdir(parents=True)
    xf.write_language_pass(sb / out_dir)          # every package stage owes L1-L11
    (sb / out_dir / "manuscript.md").write_text("x\n", encoding="utf-8")
    (sb / out_dir / "CHANGELOG.md").write_text("x\n", encoding="utf-8")
    (sb / "non-revised").mkdir()
    for f in files:
        (sb / out_dir / f).write_text(json.dumps({"ok": 1}) if f.endswith(".json") else "x",
                                      encoding="utf-8")
    area = "self" if kind == "integrate" else "base"
    (sb / area).mkdir()
    (sb / area / "manuscript.md").write_text("x\n", encoding="utf-8")
    np.write_json_atomic(sb / np.MARKER_FILE, {"stage": kind, "run_id": rid, "round": 1,
                                               "status": "complete"})
    rec = ctx.register(rid, kind, 1, f"runs/{rid}")
    rec["inputs_manifest"] = {"non-revised": np.hash_manifest(sb / "non-revised")}
    if kind == "integrate":
        rec["inputs_manifest"]["self"] = np.hash_manifest(sb / "self")
        # an integration run consumes the WHOLE pool: it always has others/
        (sb / "others" / "w1").mkdir(parents=True)
        (sb / "others" / "w1" / "manuscript.md").write_text("d\n", encoding="utf-8")
        rec["inputs_manifest"]["others"] = np.hash_manifest(sb / "others")
        rec["other_ids"] = ["w1"]
        ok, errs = np.postcheck_integrate(ctx, rec)[:2]
    else:
        rec["inputs_manifest"]["base"] = np.hash_manifest(sb / "base")
        ok, errs = np.postcheck_revise(ctx, rec)[:2]
    check(f"{kind} with files={files or '[]'} -> ok={ok} (expect ok={not expect_fail})",
          bool(ok) != expect_fail, str(errs)[:110])
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 70)
print("F06/F10 - auxiliary names and content fingerprint")
check("*.before-after.docx is an auxiliary", np._is_aux_doc("x.before-after.docx"))
check("*.tracked.docx is an auxiliary", np._is_aux_doc("x.tracked.docx"))
tmp = Path(tempfile.mkdtemp())
dir_a = tmp / "a"
dir_b = tmp / "b"
dir_a.mkdir()
dir_b.mkdir()
(dir_a / "manuscript-b.md").write_text("same text\n", encoding="utf-8")
(dir_b / "manuscript-c.md").write_text("same text\n", encoding="utf-8")
(dir_a / "CHANGELOG.md").write_text("report A\n", encoding="utf-8")
(dir_b / "CHANGELOG.md").write_text("report B differs\n", encoding="utf-8")
fp_a = np.corpus_content_set_fingerprint([(dir_a, "", ())])
fp_b = np.corpus_content_set_fingerprint([(dir_b, "", ())])
check("rename+bookkeeping-only twins share a fingerprint", fp_a == fp_b,
      f"{fp_a[:12]} vs {fp_b[:12]}")
shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 70)
print("F12 - salted judge token")
tmp = Path(tempfile.mkdtemp())
ctx = make_ctx(tmp)
ctx.state["judge_salt"] = "s3cret"
t_salted = np.judge_token_for(ctx, 1, "a2")
unsalted_match = [v for v in ("orig", "a1", "a2", "b1", "b2")
                  if np.judge_target_token(1, v) == t_salted]
check("salted token is not brute-forceable from (round, vid)",
      not unsalted_match and t_salted != np.judge_target_token(1, "a2"),
      f"salted={t_salted} unsalted={np.judge_target_token(1, 'a2')}")
tmp3 = Path(tempfile.mkdtemp())
check("legacy root keeps the unsalted token",
      np.judge_token_for(make_ctx(tmp3), 1, "a2") == np.judge_target_token(1, "a2"))
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp3, ignore_errors=True)

print()
print("=" * 70)
print("F15/F17/F18/F20/F21/F22/F26 - supporting fixes")
caps = np._tex_captions(r"\caption[short]{long one}\caption{plain two}")
check("F20 optional short-caption argument is found", len(caps) == 2, str(caps))
units = np._caption_units_from_lines(["Figure 1 | Short legend.", "Body prose right after.",
                                      "", "Figure 2 | Another."])
check("F21 prose after a sentence-final legend is not merged",
      np.count_caption_words(units[0][1]) == 5, str(units))
p = Path(tempfile.mkdtemp()) / "agent.json"
p.write_text(json.dumps({"evidence": "NaN", "notes": "Infinity"}), encoding="utf-8")
check("F22 agent JSON keeps literal strings", np.read_json(p, revive=False)["evidence"] == "NaN")
check("F22 pipeline state still revives sentinels", np.read_json(p)["notes"] == float("inf"))
tmp = Path(tempfile.mkdtemp())
out = tmp / "not_a_docx.docx"
out.write_text("plain text\n", encoding="utf-8")
res = np._run_redline_cmd([sys.executable, "-c", "pass"], out)
check("F17 a non-OOXML redline output is FAILED", not res["ok"], str(res.get("detail"))[:90])
ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(path, cell):
    doc = (f'<?xml version="1.0"?><w:document {ns}><w:body><w:p><w:r><w:t>p</w:t></w:r></w:p>'
           f'<w:tbl><w:tr><w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           f'</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)


b_doc, r_doc, o_doc = tmp / "b.docx", tmp / "r.docx", tmp / "o.docx"
_docx(b_doc, "42")
_docx(r_doc, "43")
info = np.builtin_tracked_changes(b_doc, r_doc, o_doc)
check("F18 built-in writer reports un-represented table changes",
      info.get("non_paragraph_changed") is True and bool(info.get("warning")), str(info))
check("F18 built-in output is readable OOXML", np.docx_is_readable(o_doc)[0])
shutil.rmtree(tmp, ignore_errors=True)
rec = {"status": "failed", "attempts": 3, "postcheck": {"ok": False}, "scores": None,
       "summary": None, "placeholders": {"count": 2}, "critical_findings_input": 1,
       "target_digest": "x", "field_digests": [1]}
np.reset_run_record(rec)
check("F26 reset clears placeholders/critical input/judge digests",
      all(k not in rec for k in ("placeholders", "critical_findings_input",
                                 "target_digest", "field_digests")))

print()
print("=" * 70)
print("F29 - visual rule is in every prompt")
sb = Path("/tmp/x")
for name, text in (("review", np.review_prompt(sb, "r1_review", 1)),
                   ("revise", np.revise_prompt(sb, "r1_a2_revise", 1)),
                   ("integrate", np.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1", "a2"])),
                   ("judge", np.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]))):
    check(f"{name} prompt demands render-then-look",
          "RENDER FIRST, THEN LOOK" in text and "pdftoppm" in text)
    check(f"{name} prompt names its visual artifact",
          ("VIS_visual.md" in text) or ("VISUAL_CHECK.md" in text))

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL FIX CHECKS PASSED")
