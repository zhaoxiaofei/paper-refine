#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 1 (run 20261115-220228).

Each check pins one re-validated candidate from the verified findings set.
Hermetic: fake roots under tempfile.mkdtemp(); no network, no agent runs.

Run:  python3 .paper_test/test_fix_bugs_20261115_220228_wave1.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402
import paper_docx_format as fmt      # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


class FakeCtx:
    """The slice of Ctx that prune/retry touch, without a real sandbox tree."""

    def __init__(self, root: Path, runs=None, done_rounds=(), rounds=1):
        self.root = root
        self.runs_dir = root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._runs = list(runs or [])
        self._done = set(done_rounds)
        self._rounds = rounds
        self.saved = 0
        self.logs = []

    def rounds_count(self):
        return self._rounds

    def round_rec(self, r):
        return {"status": "done" if int(r) in self._done else "pending"}

    def round_get(self, r):
        return self.round_rec(r)

    def runs(self):
        return list(self._runs)

    def run(self, rid):
        return next((r for r in self._runs if r.get("id") == rid), None)

    def sandbox_of(self, rec):
        return self.root / "runs" / str(rec["id"])

    def log(self, *a, **k):
        self.logs.append((a, k))

    def save_state(self):
        self.saved += 1


def rec(rid, rnd=1, status="failed"):
    return {"id": rid, "round": rnd, "status": status, "kind": "rewrite"}


def tmpdir(tag):
    p = Path(tempfile.mkdtemp(prefix=f"fb1115w1_{tag}_"))
    return p


# ---------------------------------------------------------------------------
# F032 -- a blocked retry reset is persisted
# ---------------------------------------------------------------------------
def test_f032_blocked_reset_saved():
    print("\n== F032: blocked retry reset is saved ==")
    root = tmpdir("f032")
    r = rec("r1_w1")
    ctx = FakeCtx(root, [r], done_rounds=(), rounds=1)
    old = pp.unmet_deps
    pp.unmet_deps = lambda c, x: ["r1_a1"]
    try:
        pp._cmd_retry_locked(ctx, SimpleNamespace(run="r1_w1", runs=None, all_failed=False))
    finally:
        pp.unmet_deps = old
    check("F032 state.json is saved for a blocked reset", ctx.saved >= 2,
          f"saved={ctx.saved}")
    check("F032 the blocked run is stale", r["status"] == "stale", r["status"])


# ---------------------------------------------------------------------------
# F144 -- prune keeps the last COMPLETED round, not the configured one
# ---------------------------------------------------------------------------
def test_f144_keep_latest_completed():
    print("\n== F144: prune keeps the last completed round ==")
    root = tmpdir("f144")
    r = rec("r1_w1")
    sb = root / "runs" / "r1_w1"
    sb.mkdir(parents=True)
    (sb / "x.txt").write_text("x")
    ctx = FakeCtx(root, [r], done_rounds={1}, rounds=3)
    ctx.run = lambda rid: None
    pp._cmd_prune_locked(ctx, SimpleNamespace(keep_latest="1", yes=True))
    check("F144 the only completed round's sandbox survives --keep-latest 1",
          sb.is_dir(), str(sb))


# ---------------------------------------------------------------------------
# F145 -- prune does not expand a run-id glob
# ---------------------------------------------------------------------------
def test_f145_literal_run_id():
    print("\n== F145: prune treats a run id literally ==")
    root = tmpdir("f145")
    for name in ("a_try1_failed", "b_try2_failed"):
        (root / "runs" / name).mkdir(parents=True)
    r = {"id": "*", "round": 1, "status": "failed", "kind": "rewrite"}
    ctx = FakeCtx(root, [r], done_rounds={1}, rounds=1)
    pp._cmd_prune_locked(ctx, SimpleNamespace(keep_latest="0", yes=True))
    check("F145 unrelated *_try*_failed archives are untouched",
          (root / "runs" / "a_try1_failed").is_dir()
          and (root / "runs" / "b_try2_failed").is_dir())
    # A literal archive is still found and removed.
    root2 = tmpdir("f145b")
    (root2 / "runs" / "r1_w1").mkdir(parents=True)
    (root2 / "runs" / "r1_w1_try1_failed").mkdir(parents=True)
    r2 = rec("r1_w1")
    ctx2 = FakeCtx(root2, [r2], done_rounds={1}, rounds=1)
    ctx2.run = lambda rid: None
    pp._cmd_prune_locked(ctx2, SimpleNamespace(keep_latest="0", yes=True))
    check("F145 the run's own literal archive is still pruned",
          not (root2 / "runs" / "r1_w1_try1_failed").exists())


# ---------------------------------------------------------------------------
# F146 -- a materializer exception leaves coherent, persisted state
# ---------------------------------------------------------------------------
def test_f146_rebuild_exception():
    print("\n== F146: rebuild exception is persisted as stale ==")
    root = tmpdir("f146")
    r = rec("r1_w1")
    ctx = FakeCtx(root, [r], done_rounds=(), rounds=1)
    old_deps, old_rebuild = pp.unmet_deps, pp.rebuild_sandbox
    pp.unmet_deps = lambda c, x: []

    def boom(c, x):
        raise RuntimeError("missing base")
    pp.rebuild_sandbox = boom
    code = None
    try:
        pp._cmd_retry_locked(ctx, SimpleNamespace(run="r1_w1", runs=None, all_failed=False))
    except SystemExit as e:
        code = e.code
    finally:
        pp.unmet_deps, pp.rebuild_sandbox = old_deps, old_rebuild
    check("F146 a failed rebuild exits cleanly", code == 1, f"code={code}")
    check("F146 the reset run is marked stale", r.get("status") == "stale", r.get("status"))
    check("F146 the failure reason is recorded",
          "missing base" in str(r.get("stale_reason")), r.get("stale_reason"))
    check("F146 state.json is saved", ctx.saved >= 1, f"saved={ctx.saved}")


# ---------------------------------------------------------------------------
# F234 -- post-parse usage errors use exit code 2
# ---------------------------------------------------------------------------
def test_f234_usage_exit_codes():
    print("\n== F234: post-parse usage errors exit 2 ==")
    root = tmpdir("f234")
    ctx = FakeCtx(root, [], done_rounds=(), rounds=1)
    codes = []
    for fn, args in (
        (pp._cmd_prune_locked, SimpleNamespace(keep_latest="-1", yes=False)),
        (pp._cmd_retry_locked, SimpleNamespace(run=None, runs=None, all_failed=False)),
        (pp._cmd_retry_locked, SimpleNamespace(run="nope", runs=None, all_failed=False)),
        (pp._cmd_retry_locked, SimpleNamespace(run=None, runs="", all_failed=False)),
    ):
        try:
            fn(ctx, args)
        except SystemExit as e:
            codes.append(e.code)
    check("F234 prune --keep-latest -1 exits 2", codes[0] == 2, str(codes))
    check("F234 retry with no selection exits 2", codes[1] == 2, str(codes))
    check("F234 retry --run unknown exits 2", codes[2] == 2, str(codes))
    check("F234 retry --runs '' exits 2", codes[3] == 2, str(codes))



# ---------------------------------------------------------------------------
# p06/p04 postcheck and scanner checks
# ---------------------------------------------------------------------------
def test_f005_verdict_column_quality():
    print("\n== F005: a verdict column gets the disposition bar ==")
    probs = pp.disposition_artifact_problems([{"item": "x", "verdict": "OK"}])
    check("F005 a bare verdict cell is a problem", bool(probs), str(probs))


def test_f006_empty_rename_survivor():
    print("\n== F006: a 0-byte rename survivor cannot absorb a document ==")
    base = tmpdir("f006b")
    sb = tmpdir("f006s")
    (base / "mainText.docx").write_bytes(b"REAL MANUSCRIPT CONTENT")
    (sb / "revised").mkdir(parents=True)
    (sb / "revised" / "mainText-b.docx").write_bytes(b"")
    ctx = SimpleNamespace(sandbox_of=lambda rec: sb)
    res = pp.backfill_missing_files(
        ctx, {"id": "r1_w1", "kind": "revise"}, [(base, "", ())], [])
    check("F006 the missing non-empty document is restored",
          (sb / "revised" / "mainText.docx").is_file(),
          f"restored={res.get('restored')} survived={res.get('survived_other_name')}")


def test_f009_m1b_heading_parser():
    print("\n== F009: M1b detection uses one heading parser ==")
    md = ("| # | acronym | expansion | disposition |\n"
          "|---|---|---|---|\n"
          "ACRONYM INVENTORY\n\n### M1b\n\n"
          "| instance | text | disposition |\n|---|---|---|\n"
          "| 1 | DNA | OK — present |\n")
    check("F009 a level-3 M1b heading is counted",
          pp.m1b_row_count(md) == 1, str(pp.m1b_row_count(md)))
    prose = ("ACRONYM INVENTORY\n\n| # | acronym | expansion | disposition |\n"
             "|---|---|---|---|\n| 1 | DNA | x | OK — present |\n\n"
             "The section headed \"## M1b\" was deleted from this artifact.\n")
    check("F009 a prose mention does not hide the missing section",
          pp.m1b_audit_section_missing(prose) is True)


def test_f017_truncated_pdf_evidence():
    print("\n== F017: a truncated PDF is not render evidence ==")
    d = tmpdir("f017")
    (d / "page1.pdf").write_bytes(b"%PDF-1.7\n")
    check("F017 a 9-byte PDF is not real evidence",
          pp._render_evidence_is_real(d / "page1.pdf") is False)


def test_f053_email_sentence_period():
    print("\n== F053: a sentence-final address is found ==")
    check("F053 x@y.edu. matches without the period",
          pp.EMAIL_ADDRESS_RE.findall("Contact: x@y.edu.") == ["x@y.edu"],
          str(pp.EMAIL_ADDRESS_RE.findall("Contact: x@y.edu.")))


def test_f061_canonical_replacement_ledger():
    print("\n== F061: only REPLACEMENT_LEDGER.md satisfies the deliverable ==")
    import zipfile
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def docx(path, text):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml",
                       f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>{text}'
                       f'</w:t></w:r></w:p></w:body></w:document>')

    t = tmpdir("f061")
    src, sb = t / "src", t / "sb"
    (sb / "out").mkdir(parents=True)
    src.mkdir()
    docx(src / "main.docx", "Alpha paragraph one content")
    docx(sb / "out" / "main.docx", "Alpha paragraph one content")
    (sb / "out" / "DIFF_LEDGER.md").write_text("# diff\n", encoding="utf-8")
    rep = pp.template_rewrite_postcheck(sb, src, {})
    check("F061 an unrelated ledger does not satisfy the deliverable",
          any("REPLACEMENT_LEDGER.md is missing" in e for e in rep.get("errors") or []),
          str(rep.get("errors")[:2]))


def test_f067_empty_conflict_quote():
    print("\n== F067: an empty conflict quote is rejected ==")
    opinions = [{"target": "t1", "opponent": "v1", "judge_run": "j1",
                 "reason": "reason text", "basis": "basis",
                 "resolved": [], "introduced": []}]
    conflicts = [{"member": "t1", "opponent": "v1", "judges": ["j1"],
                  "summary": "x", "evidence": [{"judge_run": "j1", "text": ""}]}]
    kept, rejected = pp._validate_llm_conflicts(conflicts, opinions)
    check("F067 a conflict with no quoted words is rejected",
          kept == [] and bool(rejected), f"kept={kept} rejected={rejected}")


def test_f068_missing_deliverable_not_any():
    print("\n== F068: a prose alternative cannot excuse a missing deliverable ==")
    sb = tmpdir("f068")
    (sb / "audit").mkdir(parents=True)
    (sb / "audit" / "UNRESOLVED.md").write_text("one observation\n", encoding="utf-8")
    ctx = SimpleNamespace(sandbox_of=lambda rec: sb)
    err = ("audit/audit.json is missing: write the audit ledger; unresolved observations "
           "belong in audit/UNRESOLVED.md")
    got = pp.repair_missing_deliverable(ctx, {"id": "r1_audit", "kind": "audit"}, [err])
    check("F068 the absent audit.json is reported, not excused",
          got == "audit/audit.json", repr(got))


def test_f207_filler_see():
    print("\n== F207: 'OK — see' is filler ==")
    probs = pp.disposition_artifact_problems([{"item": "x", "disposition": "OK — see"}])
    check("F207 'OK — see' is rejected", bool(probs), str(probs))


def test_f208_prompt_dir_cleanup():
    print("\n== F208: prompt cleanup survives a directory ==")
    d = tmpdir("f208")
    target = d / "RESUME_PROMPT.md"
    target.mkdir()
    try:
        pp._safe_remove_prompt(target)
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        print(e)
    check("F208 a directory at the prompt path does not crash", ok)
    check("F208 the directory is removed", not target.exists())

# ---------------------------------------------------------------------------
# CLI-level checks (F035/F142/F143/F147/F148/F237/F240/F241/F244)
# ---------------------------------------------------------------------------
import subprocess  # noqa: E402
import zipfile      # noqa: E402


def run_cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-B", str(ROOT / "paper_pipeline.py"), *args],
                          cwd=str(cwd), capture_output=True, text=True, timeout=180)


def make_src(tag, docx=False):
    d = tmpdir(tag)
    if docx:
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        with zipfile.ZipFile(d / "main.docx", "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml",
                       f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>Some '
                       f'manuscript text.</w:t></w:r></w:p></w:body></w:document>')
    else:
        (d / "a.md").write_text("Some manuscript text.\n", encoding="utf-8")
    return d


def setup_root(src, tag, *extra):
    root = tmpdir(tag)
    r = run_cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
                "--format-fix", "off", "--judges", "1", "--rewrites", "1",
                "--revises", "1", "--integrators", "0x3", *extra)
    return root, r


def test_f035_empty_source():
    print("\n== F035: empty --source is refused ==")
    src = make_src("f035")
    root = tmpdir("f035r")
    r = run_cli("setup", "--source", "", "--root", str(root), "--rounds", "1",
                "--format-fix", "off")
    check("F035 empty --source exits 2", r.returncode == 2, r.stderr[-200:])
    check("F035 no root was created", not (root / "pipeline_config.json").exists())


def test_f240_format_policy_validation():
    print("\n== F240: --format-policy validates keys and types ==")
    src = make_src("f240")
    bad = tmpdir("f240p") / "policy.json"
    bad.write_text('{"url_stlye": "plain"}', encoding="utf-8")
    r = run_cli("setup", "--source", str(src), "--root", str(tmpdir("f240r1")),
                "--rounds", "1", "--format-fix", "off", "--format-policy", str(bad))
    check("F240 an unknown key exits 2", r.returncode == 2, r.stderr[-200:])
    bad.write_text('{"caption_line": "not-an-int"}', encoding="utf-8")
    r = run_cli("setup", "--source", str(src), "--root", str(tmpdir("f240r2")),
                "--rounds", "1", "--format-fix", "off", "--format-policy", str(bad))
    check("F240 a wrong-typed value exits 2", r.returncode == 2, r.stderr[-200:])


def test_f241_empty_review_scope():
    print("\n== F241: an explicit empty --review-scope is refused ==")
    src = make_src("f241")
    r = run_cli("setup", "--source", str(src), "--root", str(tmpdir("f241r")),
                "--rounds", "1", "--format-fix", "off", "--review-scope", ",")
    check("F241 --review-scope ',' exits 2", r.returncode == 2, r.stderr[-200:])


def test_f244_journal_feedback_exit_code():
    print("\n== F244: a missing --journal-feedback exits 2 ==")
    src = make_src("f244")
    r = run_cli("setup", "--source", str(src), "--root", str(tmpdir("f244r")),
                "--revision-mode", "transfer", "--journal-feedback",
                str(tmpdir("f244") / "nope.pdf"), "--format-fix", "off")
    check("F244 missing feedback exits 2", r.returncode == 2, r.stderr[-200:])


def test_f142_agents_lists_template_for_only_2():
    print("\n== F142: agents --only 2 lists the template stage ==")
    src = make_src("f142", docx=True)
    root, r = setup_root(src, "f142r", "--revision-mode", "init", "--rounds", "3")
    check("F142 init setup succeeds", r.returncode == 0, r.stderr[-300:])
    a = run_cli("agents", "--root", str(root), "--only", "2")
    check("F142 agents --only 2 lists template_rewrite",
          "template_rewrite" in a.stdout, a.stdout[-400:])


def test_f143_continue_does_not_list_template():
    print("\n== F143: a continue root does not list the template stage ==")
    src = make_src("f143", docx=True)
    root, r = setup_root(src, "f143r")
    check("F143 continue setup succeeds", r.returncode == 0, r.stderr[-300:])
    off = root / "venue_profiles" / "nature-biotechnology.official"
    off.mkdir(parents=True, exist_ok=True)
    (off / "Template.docx").write_bytes((src / "main.docx").read_bytes())
    ctx = pp.Ctx(root)
    ctx.load()
    check("F143 fixture really has a venue Word template",
          bool(pp.venue_word_templates(ctx)))
    a = run_cli("agents", "--root", str(root))
    check("F143 a continue root lists no template_rewrite",
          "template_rewrite" not in a.stdout, a.stdout[-400:])


def test_f147_conform_skipped_exits_zero():
    print("\n== F147: a skipped template stage is not 'pending' ==")
    src = make_src("f147")
    letter = tmpdir("f147") / "letter.txt"
    letter.write_text("Dear editor, please accept.", encoding="utf-8")
    root, r = setup_root(src, "f147r", "--revision-mode", "transfer",
                         "--journal-feedback", str(letter))
    check("F147 transfer setup succeeds", r.returncode == 0, r.stderr[-300:])
    c = run_cli("run", "--root", str(root), "--only", "conform", "--manual", "--no-wait")
    check("F147 conform-only on a skipped stage exits 0", c.returncode == 0,
          (c.stdout + c.stderr)[-400:])
    check("F147 the output says it does not apply",
          "does not apply" in (c.stdout + c.stderr))


def test_f148_mixed_conform_selection_refused():
    print("\n== F148: a mixed --only conform,review on continue is refused ==")
    src = make_src("f148", docx=True)
    root, r = setup_root(src, "f148r")
    check("F148 continue setup succeeds", r.returncode == 0, r.stderr[-300:])
    c = run_cli("run", "--root", str(root), "--only", "conform,review",
                "--manual", "--no-wait")
    check("F148 conform,review on continue exits 2", c.returncode == 2,
          (c.stdout + c.stderr)[-400:])


def test_f237_invalid_run_values():
    print("\n== F237: invalid --jobs/--poll are refused ==")
    src = make_src("f237")
    root, r = setup_root(src, "f237r")
    check("F237 setup succeeds", r.returncode == 0, r.stderr[-300:])
    for flag, value in (("--jobs", "0"), ("--poll", "0"), ("--retries", "-1")):
        c = run_cli("run", "--root", str(root), "--only", "1", "--manual", "--no-wait",
                    flag, value)
        check(f"F237 {flag} {value} exits 2", c.returncode == 2,
              (c.stdout + c.stderr)[-300:])


def test_f026_bounded_grid_width():
    print("\n== F026: a huge gridCol width does not crash ==")
    huge = "<w:tblGrid>" + "".join(
        f'<w:gridCol w:w="{"9" * 5000}"/>' for _ in range(2)) + "</w:tblGrid>"
    check("F026 an unparseable grid is skipped, not raised",
          fmt._table_grid_widths(huge) == [], str(fmt._table_grid_widths(huge)[:3]))


def test_f031_scoped_skips_judge_backend():
    print("\n== F031: a scoped run does not demand a judge backend ==")
    src = make_src("f031", docx=True)
    letter = tmpdir("f031") / "letter.txt"
    letter.write_text("Dear editor, please revise.", encoding="utf-8")
    root, r = setup_root(src, "f031r", "--revision-mode", "major",
                         "--journal-feedback", str(letter))
    check("F031 major setup succeeds", r.returncode == 0, r.stderr[-400:])
    c = run_cli("run", "--root", str(root), "--manual", "--no-wait",
                "--judge-agent-cmd", '["/no/such/judge"]')
    text = c.stdout + c.stderr
    check("F031 the unused judge backend is not resolved",
          "judge agent executable not found" not in text, text[-500:])


def test_f034_run_decide_paused_skips_decide():
    print("\n== F034: run-decide after a manual pause writes no decision ==")
    src = make_src("f034")
    root, r = setup_root(src, "f034r")
    check("F034 setup succeeds", r.returncode == 0, r.stderr[-300:])
    c = run_cli("run-decide", "--root", str(root), "--manual", "--no-wait")
    check("F034 run-decide does not write a decision for a paused run",
          not (root / "reports" / "decision.json").exists()
          and not (root / "final_clean_version.readme.md").exists(),
          (c.stdout + c.stderr)[-400:])


def test_f037_trend_refuses_root_output():
    print("\n== F037: trend cannot overwrite a root file ==")
    src = make_src("f037")
    root, r = setup_root(src, "f037r")
    check("F037 setup succeeds", r.returncode == 0, r.stderr[-300:])
    state = root / "state.json"
    before = state.read_bytes()
    c = run_cli("trend", "--root", str(root), "--out", str(state))
    check("F037 trend --out into the root exits 2", c.returncode == 2,
          (c.stdout + c.stderr)[-300:])
    check("F037 state.json is unchanged", state.read_bytes() == before)


def test_f040_recorded_scoped_plan_no_rewrites():
    print("\n== F040: a recorded scoped plan cannot re-enable rewrites ==")
    ctx = SimpleNamespace(cfg={"revision_mode": "major"},
                          round_get=lambda r: {"plan": {"rewrites": 2, "revises": 1}})
    m, n = pp.round_counts(ctx, 1)
    check("F040 a recorded scoped plan forces M=0", (m, n) == (0, 1), f"{(m, n)}")
    check("F040 no rewrite ids are planned",
          not any(str(v).startswith("w") for v in pp.round_pool_ids(m, n)),
          str(pp.round_pool_ids(m, n)))


def test_f010_m20_note_table_not_counted():
    print("\n== F010: a note table cannot restore a seeded rule count ==")
    rd = tmpdir("f010")
    (rd / "artifacts").mkdir(parents=True)
    (rd / "artifacts" / "M20_formatting.md").write_text(
        "| rule | disposition |\n|---|---|\n| FMT-X1 | OK — present |\n\n"
        "| rule | disposition |\n|---|---|\n| FMT-X2 | OK — present |\n",
        encoding="utf-8")
    rep = pp.artifact_quality_report(
        rd, m20_seed_rows=[{"rule": "FMT-X1"}, {"rule": "FMT-X2"}])
    probs = " ".join(rep.get("artifacts/M20_formatting.md") or [])
    check("F010 the deleted seeded FMT-X2 row is reported",
          "FMT-X2" in probs, probs[:300])


def test_f064_blinded_selfcheck_removed():
    print("\n== F064: a blinded sandbox drops the whole selfcheck tree ==")
    sb = tmpdir("f064")
    tool = sb / "selfcheck"
    tool.mkdir()
    (tool / "foreign.txt").write_text("x", encoding="utf-8")
    pp._copy_session_tools(sb, include_driver=False)
    check("F064 a foreign file in selfcheck/ cannot survive",
          not tool.exists(), str(list(tool.iterdir()) if tool.exists() else ""))


def test_f066_each_keyed_block_needs_rows():
    print("\n== F066: one populated block cannot excuse an empty one ==")
    f = tmpdir("f066") / "M25_artwork_parity.md"
    f.write_text("| item | disposition |\n|---|---|\n"
                 "| a | OK — present |\n\n"
                 "| item | disposition |\n|---|---|\n", encoding="utf-8")
    probs = pp._disposition_table_problems(f)
    check("F066 the header-only block is reported",
          any("NO data row" in p for p in probs), str(probs))


def test_f070_fenced_tables_ignored():
    print("\n== F070: fenced tables are not data ==")
    f = tmpdir("f070") / "x.md"
    f.write_text("| item | disposition |\n|---|---|\n| a | OK — present |\n\n"
                 "```\n| item | disposition |\n|---|---|\n| example | OK |\n```\n",
                 encoding="utf-8")
    blocks = pp.parse_markdown_blocks(f)
    check("F070 only the live table is parsed", len(blocks) == 1, str(len(blocks)))
    check("F070 no example row leaks in",
          len(blocks) == 1 and len(blocks[0]["rows"]) == 1)


def test_f071_f072_fenced_proposals_ignored():
    print("\n== F071/F072: fenced proposals are illustrations ==")
    text = ("```\n## M37 — Example sweep\nPurpose: x\nEnumeration: y\n"
            "Artifact: z\nFinding rule: w\n```\n")
    props, probs = pp.parse_sweep_proposals(text)
    check("F071 a fenced proposal is not parsed", props == [], str(props))
    sb = tmpdir("f072")
    (sb / "prior_round").mkdir(parents=True)
    (sb / "prior_round" / "new_sweeps.md").write_text(text, encoding="utf-8")
    check("F072 a fenced prior proposal is not counted",
          pp.prior_proposal_ids(sb) == [], str(pp.prior_proposal_ids(sb)))


def test_f073_unreadable_pristine_file():
    print("\n== F073: an unreadable pristine file is a mismatch, not a crash ==")
    sb = tmpdir("f073")
    area = sb / "non_revised"
    area.mkdir()
    bad = area / "x.md"
    bad.write_text("x", encoding="utf-8")
    bad.chmod(0)
    ctx = SimpleNamespace(sandbox_of=lambda rec: sb, source_manifest={"x.md": "diff"})
    errs = []
    try:
        pp._check_pristine_copy(ctx, {"id": "r1_w1", "kind": "rewrite"}, "non_revised", errs)
        crashed = False
    except PermissionError:
        crashed = True
    finally:
        bad.chmod(0o600)
    check("F073 no PermissionError escapes", not crashed)
    check("F073 a mismatch is reported", bool(errs), str(errs))


def test_f076_signal_directory_squat():
    print("\n== F076: a directory squat does not swallow the stray marker ==")
    sb = tmpdir("f076")
    sb.mkdir(exist_ok=True)
    (sb / "_pipeline_done.json").mkdir()
    (sb / "rewritten").mkdir()
    stray = sb / "rewritten" / "_pipeline_done.json"
    stray.write_text('{"stage": "rewrite", "run_id": "r1_w1"}', encoding="utf-8")
    ctx = SimpleNamespace(sandbox_of=lambda rec: sb)
    notes = pp.relocate_stray_signal(ctx, {"id": "r1_w1", "kind": "rewrite"})
    check("F076 the stray marker is not moved into the directory", stray.is_file())
    check("F076 no ADOPTED claim is made",
          not any("ADOPTED" in n for n in notes), str(notes))


def test_f079_toml_inline_comma_required():
    print("\n== F079: a TOML inline table needs commas ==")
    check("F079 a missing comma is rejected",
          pp._toml_inline_table_values('{ A = "1" B = "2" }') is None,
          str(pp._toml_inline_table_values('{ A = "1" B = "2" }')))
    check("F079 a comma is accepted",
          pp._toml_inline_table_values('{ A = "1", B = "2" }') == {"A": "1", "B": "2"},
          str(pp._toml_inline_table_values('{ A = "1", B = "2" }')))


def test_f092_exact_large_integers():
    print("\n== F092: large integer facts stay distinct ==")
    a = pp._fact_survival_key("123456789012345678")
    b = pp._fact_survival_key("123456789012345679")
    check("F092 two >2^53 integers get different keys", a != b, f"{a} vs {b}")
    check("F092 the historic small-integer key is unchanged",
          pp._fact_survival_key("-55") == "-55.0")


def test_f096_gap_denial_rejected():
    print("\n== F096: a named gap cannot be denied ==")
    errs = pp.concern_coverage_problems(
        {"coverage": [{"check": "scope", "gap": "none found"}]}, False)
    check("F096 'gap: none found' is refused", bool(errs), str(errs))


def test_f209_not_applicable_cannot_cite_work():
    print("\n== F209: a not-applicable row cannot cite completed work ==")
    sb = tmpdir("f209")
    (sb / "response").mkdir(parents=True)
    (sb / "target").mkdir()
    (sb / "target" / "main.md").write_text("x", encoding="utf-8")
    (sb / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "## C1\n\n**Comment:** a concern\n\n**Response:** not applicable.\n",
        encoding="utf-8")
    (sb / "response" / "response_map.json").write_text(__import__("json").dumps({
        "rows": [{"id": "C1", "status": "not-applicable", "response": "not applicable.",
                  "changes": [{"file": "main.md", "operation": "edit"}]}]}),
        encoding="utf-8")
    errs = pp.response_local_problems(sb, sb / "target")
    check("F209 completed changes are refused for not-applicable",
          any("must not list completed" in e for e in errs), str(errs))


def test_f210_not_applicable_reason_rejected():
    print("\n== F210: 'not applicable' is not a named reason ==")
    check("F210 out-of-scope -- not applicable is refused",
          pp._audit_disposition_ok("out of scope -- not applicable") is False)
    check("F210 a named out-of-scope reason is accepted",
          pp._audit_disposition_ok("out of scope -- the letter has no statistics") is True)


def test_f211_feedback_dir_is_not_a_file():
    print("\n== F211: an empty subdirectory is not feedback ==")
    sb = tmpdir("f211")
    (sb / "feedback" / "files" / "empty_subdir").mkdir(parents=True)
    errs = pp.feedback_files_problems(sb)
    check("F211 a directory-only feedback area is refused", bool(errs), str(errs))


def test_f216_short_deposit_claim():
    print("\n== F216: a short deposit claim is still a claim ==")
    rows = fmt.availability_claim_rows(["Data were deposited."], "x")
    check("F216 the short claim produces an FMT-AV3 row",
          any(r.get("rule") == "FMT-AV3" for r in rows), str(rows))


def test_f219_one_confusable_row():
    print("\n== F219: ranking/score is one row ==")
    rows = fmt.confusable_pair_rows(["We report the ranking and score."])
    check("F219 one concept yields one row",
          sum(1 for r in rows if r.get("rule") == "FMT-T9d") == 1, str(rows))


def test_f222_thin_space_and_sign_quantities():
    print("\n== F222: thin-space and signed quantities are counted ==")
    rows = fmt.number_format_rows(["Values were 12\u2009000 and 15000."])
    check("F222 thin-space vs plain produces FMT-T9h",
          any(r.get("rule") == "FMT-T9h" for r in rows), str(rows))
    rows = fmt.number_format_rows(["Values were 12,000 and -15000."])
    check("F222 a signed plain value counts on the plain side",
          any(r.get("rule") == "FMT-T9h" for r in rows), str(rows))


def test_f054_policy_off_normalized():
    print("\n== F054: 'off' is a boolean policy value ==")
    src = make_src("f054")
    root, r = setup_root(src, "f054r")
    check("F054 setup succeeds", r.returncode == 0, r.stderr[-200:])
    ctx = pp.Ctx(root)
    ctx.load()
    ctx.cfg["format_policy"] = {"unlink_zotero_fields": "off"}
    pol = pp.format_policy_of(ctx)
    check("F054 'off' becomes False", pol.get("unlink_zotero_fields") is False,
          repr(pol.get("unlink_zotero_fields")))


def test_f200_dangling_symlink_destination():
    print("\n== F200: a dangling symlink destination is refused ==")
    t = tmpdir("f200")
    src = t / "src"
    src.mkdir()
    tpl = make_src("f200d", docx=True) / "main.docx"
    (src / "main.docx").write_bytes(tpl.read_bytes())
    dest = t / "dest"
    dest.symlink_to(t / "missing-target")
    rep = pp.rebuild_package_from_templates({"main": tpl}, src, dest)
    check("F200 the rebuild reports an error", rep.get("ok") is False, str(rep)[:200])
    check("F200 the symlink is not followed", not (t / "missing-target").exists())


def test_f202_no_cap_note():
    print("\n== F202: no cap does not claim 'within the caps' ==")
    info = {"rows": [{"section": "main text", "words": 10, "over_limit": False,
                      "within_preference": True}],
            "limits": {"abstract": {}, "main text": {}, "cover letter": {}}}
    note = pp.length_note(info)
    check("F202 no false 'within the relaxed caps'", "all within the relaxed caps" not in note,
          note)
    check("F202 says counts only", "counts only" in note, note)


def test_f249_empty_versions_means_none():
    print("\n== F249: an explicit empty versions list means no versions ==")
    src = make_src("f249")
    root, r = setup_root(src, "f249r")
    check("F249 setup succeeds", r.returncode == 0, r.stderr[-200:])
    ctx = pp.Ctx(root)
    ctx.load()
    red = pp.run_redlines(ctx, versions=[])
    track = pp.run_difference_tracking(ctx, versions=[])
    check("F249 redline processes no versions", len(red.get("versions") or []) == 0,
          str(red.get("versions")))
    check("F249 tracking processes no versions", len(track.get("versions") or []) == 0,
          str(track.get("versions")))


def test_f251_garbage_manifest_does_not_crash():
    print("\n== F251: a non-object manifest is empty, not a crash ==")
    check("F251 the PDF reader tolerates an array",
          pp._pdf_previous_records(["x"]) == {}, str(pp._pdf_previous_records(["x"])))
    check("F251 the redline index tolerates an array",
          pp.redline_index(["x"]) == {}, str(pp.redline_index(["x"])))


def test_f252_missing_integration_record():
    print("\n== F252: a missing integration record has no a1 fallback ==")
    ctx = SimpleNamespace(run=lambda rid: {})
    token, srcs, note = pp.tracking_previous_baseline(ctx, 1, "i1")
    check("F252 no baseline is invented", token == "" and srcs == [], f"{token} {srcs}")
    check("F252 the reason is recorded", "UNKNOWN" in note, note)


def test_f253_open_items_not_capped():
    print("\n== F253: the sibling hand-off list is not capped at 40 ==")
    items = [{"id": f"O{i}", "status": "manual", "check": "M1"} for i in range(41)]
    text = pp.open_items_text({"items": items})
    check("F253 all 41 items are written", text.count("* O") == 41, str(text.count("* O")))


def test_f254_semicolon_csv():
    print("\n== F254: a semicolon-delimited CSV is scanned ==")
    f = tmpdir("f254") / "table.csv"
    f.write_text("alpha;beta\n1;2\n", encoding="utf-8")
    header, rows = pp._read_delimited_table(f)
    check("F254 the header has two columns", header == ["alpha", "beta"], str(header))
    check("F254 the row has two cells", rows == [["1", "2"]], str(rows))


def test_f255_missing_in_package_copy_not_rewired():
    print("\n== F255: a missing in-package copy is not rewired ==")
    sb = tmpdir("f255")
    ctx = SimpleNamespace(root=sb)
    row = {"ok": True, "tool": "builtin", "fallback": None,
           "in_package": "missing.docx", "revised_rel": "main.docx", "baseline": "a1",
           "ext": ".docx"}
    pp.compile_tracking_pdfs(ctx, {"comparisons": [row]})
    check("F255 the missing copy is recorded on the row",
          "missing" in str(row.get("pdf_error") or ""), str(row.get("pdf_error")))


def test_f245_not_materialized_keeps_old_rows():
    print("\n== F245: a placeholder does not erase accumulated redline rows ==")
    import json as _json
    src = make_src("f245")
    root, r = setup_root(src, "f245r")
    check("F245 setup succeeds", r.returncode == 0, r.stderr[-200:])
    rd = root / "redlines"
    rd.mkdir(exist_ok=True)
    old = {"round": 1, "version": "w1", "status": "1/1 written", "skipped": [],
           "comparisons": [{"ok": True, "source": "from-base", "base_rel": "a.md",
                            "revised_rel": "a.md", "basis": "line", "tool": "builtin"}]}
    (rd / "manifest.json").write_text(_json.dumps({"versions": [old]}), encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.load()
    pp.run_redlines(ctx, rounds=[1], versions=["w1"], tool="none")
    versions = _json.loads((rd / "manifest.json").read_text(encoding="utf-8"))["versions"]
    kept = next((v for v in versions if v.get("version") == "w1"), {})
    check("F245 the real comparison row survives", len(kept.get("comparisons") or []) == 1,
          str(versions))


def test_f166_failed_zip_not_announced():
    print("\n== F166: a failed final-clean zip is not announced as written ==")
    ctx = SimpleNamespace(root=tmpdir("f166"))
    text = pp.final_clean_readme_text(
        ctx, {}, {},
        {"zip": {"path": "/x/final.zip", "ok": False, "error": "boom"}})
    check("F166 the failure is named", "NO package archive was written" in text, text[-400:])
    check("F166 it is not called compressed", "compressed at" not in text)


def test_f205_report_write_does_not_follow_symlink():
    print("\n== F205: the sibling report write is atomic ==")
    import zipfile
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    t = tmpdir("f205")
    src = t / "src"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    tpl = t / "template.docx"
    with zipfile.ZipFile(tpl, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/styles.xml", f'<w:styles xmlns:w="{ns}"/>')
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{ns}"><w:body/></w:document>')
    dest = t / "dest"
    sentinel = t / "sentinel"
    sentinel.write_text("KEEP", encoding="utf-8")
    rep = t / "dest.template_report.md"
    rep.symlink_to(sentinel)
    r = pp.rebuild_package_from_templates({"main": tpl}, src, dest)
    check("F205 the rebuild succeeds", r.get("ok") is True, str(r)[:200])
    check("F205 the symlink target keeps its bytes", sentinel.read_text() == "KEEP")
    check("F205 the report path is a real file", rep.is_file() and not rep.is_symlink())


def main():
    test_f032_blocked_reset_saved()
    test_f144_keep_latest_completed()
    test_f145_literal_run_id()
    test_f146_rebuild_exception()
    test_f234_usage_exit_codes()
    test_f005_verdict_column_quality()
    test_f006_empty_rename_survivor()
    test_f009_m1b_heading_parser()
    test_f017_truncated_pdf_evidence()
    test_f053_email_sentence_period()
    test_f061_canonical_replacement_ledger()
    test_f067_empty_conflict_quote()
    test_f068_missing_deliverable_not_any()
    test_f207_filler_see()
    test_f208_prompt_dir_cleanup()
    test_f026_bounded_grid_width()
    test_f031_scoped_skips_judge_backend()
    test_f034_run_decide_paused_skips_decide()
    test_f037_trend_refuses_root_output()
    test_f040_recorded_scoped_plan_no_rewrites()
    test_f010_m20_note_table_not_counted()
    test_f064_blinded_selfcheck_removed()
    test_f066_each_keyed_block_needs_rows()
    test_f070_fenced_tables_ignored()
    test_f071_f072_fenced_proposals_ignored()
    test_f073_unreadable_pristine_file()
    test_f076_signal_directory_squat()
    test_f079_toml_inline_comma_required()
    test_f092_exact_large_integers()
    test_f096_gap_denial_rejected()
    test_f209_not_applicable_cannot_cite_work()
    test_f210_not_applicable_reason_rejected()
    test_f211_feedback_dir_is_not_a_file()
    test_f216_short_deposit_claim()
    test_f219_one_confusable_row()
    test_f222_thin_space_and_sign_quantities()
    test_f054_policy_off_normalized()
    test_f200_dangling_symlink_destination()
    test_f202_no_cap_note()
    test_f249_empty_versions_means_none()
    test_f251_garbage_manifest_does_not_crash()
    test_f252_missing_integration_record()
    test_f253_open_items_not_capped()
    test_f254_semicolon_csv()
    test_f255_missing_in_package_copy_not_rewired()
    test_f245_not_materialized_keeps_old_rows()
    test_f166_failed_zip_not_announced()
    test_f205_report_write_does_not_follow_symlink()
    test_f035_empty_source()
    test_f240_format_policy_validation()
    test_f241_empty_review_scope()
    test_f244_journal_feedback_exit_code()
    test_f142_agents_lists_template_for_only_2()
    test_f143_continue_does_not_list_template()
    test_f147_conform_skipped_exits_zero()
    test_f148_mixed_conform_selection_refused()
    test_f237_invalid_run_values()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    if FAILS:
        for f in FAILS:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
