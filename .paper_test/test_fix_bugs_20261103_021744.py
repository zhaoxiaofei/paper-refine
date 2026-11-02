#!/usr/bin/env python3
"""Regression checks for the 2026-11-03 02:17:44 fix-bugs wave (F01-F80).

Run:  python3 .paper_test/test_fix_bugs_20261103_021744.py

Every check names the verified candidate it pins. The candidates came from
`debug_runs/20261103-021744/02_verify_findings/verified_findings/`; each was
re-validated on this tree before the patch. The checks are the minimal runtime
proof that the defect is gone (a source pin is used only where a full run root
or a prompt render would duplicate an existing suite's fixture).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS: list[str] = []
TMPDIRS: list[Path] = []


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fix_bugs_pipeline_1103", WS / "paper_pipeline.py")


# ---------------------------------------------------------------------------
# F01 -- an unknown prefer-rewrite config string must NOT turn the mode on.
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, **cfg):
        self.cfg = dict(cfg)


def test_f01_unknown_prefer_string() -> None:
    print("\n== F01: unknown prefer-rewrite config strings ==")
    values = {
        "on": True, "true": True, "yes": True, "1": True, "enabled": True,
        "off": False, "false": False, "no": False, "0": False,
        "random": False, "enable": False, "": False, "  OFF  ": False,
    }
    for raw, want in values.items():
        got = pp.prefer_rewrite_over_deletion(Ctx(prefer_rewrite_over_deletion=raw))
        check(f"F01 {raw!r} -> {want}", got is want, f"got {got!r}")
    # A boolean/absent key keeps the historical behaviour.
    check("F01 absent key is off", pp.prefer_rewrite_over_deletion(Ctx()) is False)
    check("F01 boolean true stays on",
          pp.prefer_rewrite_over_deletion(Ctx(prefer_rewrite_over_deletion=True)) is True)


# ---------------------------------------------------------------------------
# F02 -- insertions-only strict mode must not claim deletions are forbidden.
# ---------------------------------------------------------------------------
def test_f02_insertions_only_policy() -> None:
    print("\n== F02: insertions-only prefer-rewrite wording ==")
    block = pp.content_edit_policy_block(False, True, True)
    check("F02 insertions-only still says NO INSERTIONS", "NO INSERTIONS:" in block)
    check("F02 insertions-only does not say a deletion is never allowed",
          "A deletion is never a" not in block)
    check("F02 insertions-only does not say the unit must survive unconditionally",
          "but the unit must survive." not in block)
    check("F02 insertions-only allows a best deletion",
          "A deletion is a last resort" in block)
    both = pp.content_edit_policy_block(False, False, True)
    check("F02 deletions-forbidden keeps the strict sentence",
          "A deletion is never a" in both and "NO DELETIONS:" in both)
    soft = pp.content_edit_policy_block(True, True, True)
    check("F02 soft mode is unchanged",
          "A deletion is a last resort" in soft and "NO DELETIONS:" not in soft)


# ---------------------------------------------------------------------------
# R01 -- the policy block must key each ban on the direction it forbids.
# ---------------------------------------------------------------------------
def test_r01_policy_direction_wording() -> None:
    print("\n== R01: policy block bans are keyed by direction ==")
    flat = lambda text: " ".join(text.split())          # noqa: E731
    insertions_only = flat(pp.content_edit_policy_block(False, True, True))
    check("R01 insertions-only does not ban removal",
          "rather than removing or adding text" not in insertions_only)
    check("R01 insertions-only does not override removal instructions",
          "would add or remove a unit" not in insertions_only)
    check("R01 insertions-only still bans addition",
          "rather than adding text" in insertions_only
          and "would add a unit" in insertions_only)
    deletions_only = flat(pp.content_edit_policy_block(True, False, True))
    check("R01 deletions-only does not ban addition",
          "rather than removing or adding text" not in deletions_only
          and "would add or remove a unit" not in deletions_only)
    check("R01 deletions-only still bans removal",
          "rather than removing text" in deletions_only
          and "would remove a unit" in deletions_only)
    both = flat(pp.content_edit_policy_block(False, False, True))
    check("R01 both directions keep the combined wording",
          "rather than removing or adding text" in both
          and "would add or remove a unit" in both)


# ---------------------------------------------------------------------------
# F03 -- the run synopsis must not claim a previous run persists the flag.
# ---------------------------------------------------------------------------
def test_f03_cli_usage() -> None:
    print("\n== F03: run synopsis prefer-rewrite persistence ==")
    src = (WS / "paper_pipeline_parts" / "p17_cli.py").read_text("utf-8")
    check("F03 no 'previous run turned it on' claim",
          "a previous run turned it on" not in src)
    check("F03 names the invocation flag",
          "this invocation's flag" in src and "`setup` recorded it on" in src)


# ---------------------------------------------------------------------------
# F09 -- the audit prompt must be disposition-only (no AU-* instructions).
# ---------------------------------------------------------------------------
def test_f09_audit_no_au_rows() -> None:
    print("\n== F09: audit prompt AU-* instructions ==")
    sb = scratch("f09_")
    text = pp.audit_prompt(sb, "r1_audit", 1)
    check("F09 keeps the adds-empty override", "`adds` MUST be `[]`" in text)
    for phrase in ("as your own `AU-` finding", "is an AU-finding",
                   "as `AU-` findings", "each is an `AU-` finding"):
        check(f"F09 no positive instruction {phrase!r}", phrase not in text)
    check("F09 sends new defects to UNRESOLVED.md", "audit/UNRESOLVED.md" in text)
    # The gate itself still rejects an adds row.
    audit = {"adds": [{"id": "AU-1", "check": "M1"}]}
    errs = pp.audit_artifact_problems(audit, []) if hasattr(pp, "audit_artifact_problems") else []
    check("F09 the audit gate rejects a non-empty adds list", bool(errs), str(errs)[:120])


# ---------------------------------------------------------------------------
# F14 -- the integration rescan must include the adopted M21-M24 checks.
# ---------------------------------------------------------------------------
def test_f14_integrate_rescan() -> None:
    print("\n== F14: integration rescan M21-M24 ==")
    sb = scratch("f14_")
    text = pp.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"])
    lines = text.splitlines()
    rescan = [l for l in lines if "frozen integration rescan set" in l
              or "M1-M17 + J1-J4" in l or "cover the" in l]
    check("F14 the rescan names M18-M24", any("M18-M24" in l for l in rescan), str(rescan)[:300])
    check("F14 the rescan names M21-M24 explicitly",
          any("M21-M24" in l for l in rescan), str(rescan)[:300])
    check("F14 the old M18-M20-only range is gone",
          "this stage's M18-M20" not in text)


# ---------------------------------------------------------------------------
# F16 -- a paged block's embedded ## headings must not end its section.
# ---------------------------------------------------------------------------
def test_f16_paging_headings() -> None:
    print("\n== F16: medium-profile paged section boundaries ==")
    sb = scratch("f16_")
    pp.revise_prompt(sb, "r1_a2_revise", 1, index=0, total=1, execution_profile="medium")
    text = (sb / "INSTRUCTIONS" / "PROFILE_RULES.md").read_text("utf-8")
    headings = [(i, l) for i, l in enumerate(text.splitlines(), 1) if l.startswith("## ")]
    titles = [l for _, l in headings]
    check("F16 no embedded Phase heading remains level 2",
          "## Phase 2" not in titles)
    check("F16 the phase contract is a level-3 heading", "### Phase 2" in text)
    start = next(i for i, l in headings if "ATTACHED REVISION BRIEF" in l)
    end = next((i for i, l in headings if i > start), len(text.splitlines()) + 1)
    section = "\n".join(text.splitlines()[start - 1:end - 1])
    check("F16 a heading-bounded read reaches the whole block",
          "Phase 2 — $paper-revise" in section and "LANGUAGE PASS" not in section,
          section[:200])


# ---------------------------------------------------------------------------
# F17 -- a zero-item readme-mode package owes no hand-off README.
# ---------------------------------------------------------------------------
def test_f17_zero_item_readme() -> None:
    print("\n== F17: zero-item readme-mode hand-off file ==")
    sb = scratch("f17_")
    (sb / "PROMPT.md").write_text(pp.placeholder_rule_text("readme"), encoding="utf-8")
    (sb / "integrated").mkdir()
    marker = {"status": "complete", "id": "r1_i1", "kind": "integrate", "round": 1,
              "summary": {"critical_remaining": 0, "writing_remaining": 0,
                          "manual_items": 0}}
    (sb / pp.MARKER_FILE).write_text(json.dumps(marker), encoding="utf-8")
    warns0 = [w for w in pp.sandbox_selfcheck(sb, "integrate", "r1_i1", 1)[2]
              if "README-AUTHOR" in w]
    check("F17 a zero-item package gets no missing-README warning", warns0 == [], str(warns0))
    marker["summary"]["manual_items"] = 2
    (sb / pp.MARKER_FILE).write_text(json.dumps(marker), encoding="utf-8")
    warns2 = [w for w in pp.sandbox_selfcheck(sb, "integrate", "r1_i1", 1)[2]
              if "README-AUTHOR" in w]
    check("F17 a package that owes items still gets the warning", bool(warns2), str(warns2))
    check("F17 the helper is used by both package postchecks",
          "_zero_item_handoff_package" in pp.__dict__
          and all("_zero_item_handoff_package" in inspect_source(fn)
                  for fn in (pp.postcheck_revise, pp.postcheck_rewrite)))


def inspect_source(fn) -> str:
    import inspect
    return inspect.getsource(fn)


# ---------------------------------------------------------------------------
# F20 -- the standalone revise prompt's manual-list deliverable is conditional.
# ---------------------------------------------------------------------------
def test_f20_standalone_prompt() -> None:
    print("\n== F20: standalone revise prompt manual-list deliverable ==")
    text = (WS / "paper-skills" / "prompts" / "adress_issues.prompt.md").read_text("utf-8")
    check("F20 the deliverable names the readme hand-off target",
          "or `REVISED/README-AUTHOR-TO-COMPLETE.md` under the readme hand-off mode" in text)
    check("F20 the unconditional old deliverable line is gone",
          "- `REVISED/MANUAL_STEPS.md` — for every manual-required finding" not in text)
    check("F20 E3b still documents both files",
          "`MANUAL_STEPS.md`, or `README-AUTHOR-TO-COMPLETE.md`" in text)


# ---------------------------------------------------------------------------
# F21 -- the token helper documents the any-depth work/ exclusion.
# ---------------------------------------------------------------------------
def test_f21_revision_token_help() -> None:
    print("\n== F21: revision_token.py work/ depth ==")
    path = WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py"
    text = path.read_text("utf-8")
    check("F21 help says any depth", "work/ at any depth" in text)
    check("F21 help no longer says top level", "work/ at the top level" not in text)
    mod = load("revision_token_1103", path)
    root = scratch("f21_")
    (root / "supp" / "work").mkdir(parents=True)
    p = root / "supp" / "work" / "render.png"
    p.write_text("x", encoding="utf-8")
    check("F21 nested work/ is not payload", mod.is_payload(p, root) is False)


# ---------------------------------------------------------------------------
# F25/F26 -- the README suite count and execution-profile table.
# ---------------------------------------------------------------------------
def test_f25_suite_count() -> None:
    print("\n== F25: README suite count ==")
    r = subprocess.run([sys.executable, str(WS / ".paper_test" / "run_all.py"), "--list"],
                       cwd=str(WS), capture_output=True, text=True, timeout=60)
    n = len([l for l in r.stdout.splitlines() if re.match(r"test_.*\.py$", l.strip())])
    readme = (WS / "README.md").read_text("utf-8")
    stated = re.search(r"parallel — (\d+) suites", readme)
    check("F25 the README states the enumerated suite count",
          stated is not None and int(stated.group(1)) == n,
          f"README {stated.group(1) if stated else None} != runner {n}")
    check("F25 the old 176 count is gone", "176 suites" not in readme)


def test_f26_profile_table() -> None:
    print("\n== F26: execution-profile size table ==")
    sys.path.insert(0, str(WS / ".paper_test"))
    render = load("render_stage_prompts_1103", WS / ".paper_test" / "render_stage_prompts.py")
    old_env = os.environ.get("PAPER_RENDER_SANDBOX")
    base = scratch("f26_")
    try:
        os.environ["PAPER_RENDER_SANDBOX"] = str(base / "sb" / "r1_guided_review")
        high = render.render(WS, "high")
        medium = render.render(WS, "medium")
    finally:
        if old_env is None:
            os.environ.pop("PAPER_RENDER_SANDBOX", None)
        else:
            os.environ["PAPER_RENDER_SANDBOX"] = old_env
    readme = (WS / "README.md").read_text("utf-8")
    rows = {
        "review": "review", "cold_start_review": "cold_start_review",
        "audit": "audit", "revise": "revise", "integrate": "integrate",
        "rewrite": "rewrite", "judge": "judge", "revision_audit": "revision_audit",
        "revision_repair": "revision_repair",
    }
    for name in rows:
        m = re.search(rf"^\| {re.escape(name)} \| (\d+) KB \| (\d+) KB \| (\d+)% \|$",
                      readme, re.M)
        check(f"F26 table has a row for {name}", m is not None)
        if not m:
            continue
        want_high = len(high[name]) // 1024
        want_medium = len(medium[name]) // 1024
        want_cut = round(100 * (1 - len(medium[name]) / len(high[name])))
        got = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        check(f"F26 {name} row matches the live render",
              got == (want_high, want_medium, want_cut),
              f"table {got} live {(want_high, want_medium, want_cut)}")


# ---------------------------------------------------------------------------
# F39 -- the M30 row-identity reference is pinned outside the sandbox.
# ---------------------------------------------------------------------------
def _m30_hrows():
    return [{"document": "paper.md", "kind": "body", "number": n, "unit": "cm",
             "sentence": f"the height is {n}",
             "candidate producer": "raw_data/plot.csv:height",
             "producer summary": "3 values", "seed check": "read the column"}
            for n in (1, 2, 3)]


def _m30_ledger(rows, dispositions):
    rs = [dict(r, disposition=d) for r, d in zip(rows, dispositions)]
    return ("# M30\n\n" + pp._evidence_artifact_table(
        rs, ["document", "kind", "number", "unit", "sentence", "candidate producer",
             "producer summary", "seed check"], "no rows") + "\n")


def test_f39_m30_pinned_seed() -> None:
    print("\n== F39: the M30 seed reference is pinned outside the sandbox ==")
    frozen = [{"id": "F-1", "check": "M30"}]
    rows = _m30_hrows()
    sb = scratch("f39_") / "r1_a2_revise"
    (sb / "work").mkdir(parents=True)
    (sb / "PROMPT.md").write_text("prompt\n", encoding="utf-8")
    # The agent truncates BOTH the live pack and the ledger.
    (sb / "work" / "CODE_SCANS.json").write_text(
        json.dumps({"hierarchy": {"rows": rows[:1], "count": 1}}), encoding="utf-8")
    pp.pin_m30_seed(sb, {"hierarchy": {"rows": rows, "count": len(rows)}})
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _m30_ledger(rows[:1], ["OK — read it"]), encoding="utf-8")
    errs, _w = pp.m30_hierarchy_problems(sb, frozen)
    check("F39 truncating the live pack and the ledger is still DROPPED",
          any("DROPPED" in e for e in errs), str(errs)[:220])
    # Deleting the pin must not silently fall back to the live pack.
    pp.m30_seed_pin_path(sb).unlink()
    errs2, _w2 = pp.m30_hierarchy_problems(sb, frozen)
    check("F39 a deleted pin in a real sandbox is reported, not skipped",
          any("identity check is not skipped" in e for e in errs2), str(errs2)[:220])
    # A fully disposed ledger under a valid pin passes.
    pp.pin_m30_seed(sb, {"hierarchy": {"rows": rows, "count": len(rows)}})
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _m30_ledger(rows, ["OK — read it"] * len(rows)), encoding="utf-8")
    errs3, _w3 = pp.m30_hierarchy_problems(sb, frozen)
    check("F39 a fully disposed ledger passes", not errs3, str(errs3)[:220])
    # A PROMPT-less unit fixture keeps the pre-pin fallback (old R04 suites).
    fix = scratch("f39_fixture_")
    (fix / "work").mkdir()
    (fix / "work" / "CODE_SCANS.json").write_text(
        json.dumps({"hierarchy": {"rows": rows, "count": len(rows)}}), encoding="utf-8")
    (fix / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _m30_ledger(rows[:1], ["OK — read it"]), encoding="utf-8")
    errs4, _w4 = pp.m30_hierarchy_problems(fix, frozen)
    check("F39 a PROMPT-less fixture still uses its live seed",
          any("DROPPED" in e for e in errs4), str(errs4)[:220])
    seed_src = inspect_source(pp.seed_evidence_pack)
    check("F39 the stage seeder writes the pin",
          'where == "stage"' in seed_src and "pin_m30_seed(sb, ev)" in seed_src)


# ---------------------------------------------------------------------------
# F41/F42/F43/F80 -- symlinked paths must not escape the sandbox.
# ---------------------------------------------------------------------------
def test_f41_append_parent_link() -> None:
    print("\n== F41: append_text_no_follow parent link ==")
    d = scratch("f41_")
    sb = d / "sb"
    sb.mkdir()
    outside = d / "outside"
    outside.mkdir()
    os.symlink(outside, sb / "work")
    try:
        pp.append_text_no_follow(sb / "work" / "_agent.log", "ESCAPED")
        refused = False
    except OSError:
        refused = True
    check("F41 the append is refused", refused)
    check("F41 nothing was written outside", not (outside / "_agent.log").exists())


def test_f42_read_parent_link() -> None:
    print("\n== F42: bounded readers parent link ==")
    d = scratch("f42_")
    sb = d / "sb"
    sb.mkdir()
    out = d / "out"
    out.mkdir()
    (out / "secret.txt").write_text("SECRET", encoding="utf-8")
    (out / "x.json").write_text('{"secret": true}', encoding="utf-8")
    os.symlink(out, sb / "work")
    check("F42 read_text_bounded refuses", pp.read_text_bounded(sb / "work" / "secret.txt") is None)
    check("F42 read_json refuses", pp.read_json(sb / "work" / "x.json") is None)
    try:
        pp.sha256_file(sb / "work" / "secret.txt")
        refused = False
    except OSError:
        refused = True
    check("F42 sha256_file refuses", refused)


def test_f43_copy_destination_link() -> None:
    print("\n== F43: copy_into symlinked destination ==")
    d = scratch("f43_")
    src = d / "src"
    src.mkdir()
    (src / "a.txt").write_text("A", encoding="utf-8")
    out = d / "out"
    out.mkdir()
    dst = d / "dst"
    os.symlink(out, dst)
    try:
        pp.copy_into(src, dst)
        refused = False
    except OSError:
        refused = True
    check("F43 the copy is refused", refused)
    check("F43 no file reached the outside directory", list(out.iterdir()) == [])


def test_f80_hash_root_link() -> None:
    print("\n== F80: hash_manifest/dir_matches symlinked ROOT ==")
    d = scratch("f80_")
    out = d / "out"
    out.mkdir()
    (out / "x.txt").write_text("X", encoding="utf-8")
    link = d / "link"
    os.symlink(out, link)
    digest = pp.sha256_file(out / "x.txt")
    check("F80 hash_manifest refuses an arbitrary root link",
          pp.hash_manifest(link, follow_dir_links=True).get("files") == {})
    check("F80 dir_matches refuses an arbitrary root link",
          pp.dir_matches(link, {"x.txt": digest}) is False)
    # The canonical evidence-area link (and reads through it) still works.
    root = d / "root"
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "non_revised" / "raw_data" / "t.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "state.json").write_text("{}", encoding="utf-8")
    sand = root / "runs" / "r1_w1"
    (sand / "non_revised").mkdir(parents=True)
    os.symlink(root / "non_revised" / "raw_data", sand / "non_revised" / "raw_data")
    got = pp.hash_manifest(sand / "non_revised" / "raw_data", follow_dir_links=True)
    check("F80 the canonical evidence root is still hashed",
          got.get("files", {}).get("t.csv") == pp.sha256_file(out.parent / "root" / "non_revised" / "raw_data" / "t.csv"))
    check("F80 readers still read through the canonical evidence link",
          pp.read_text_bounded(sand / "non_revised" / "raw_data" / "t.csv") == "a,b\n1,2\n")


# ---------------------------------------------------------------------------
# F44 -- a moved inline table must land at its revised position.
# ---------------------------------------------------------------------------
def _build_docx(path: Path, items) -> None:
    from docx import Document
    doc = Document()
    for item in items:
        if item == "table":
            t = doc.add_table(rows=1, cols=2)
            t.cell(0, 0).text = "A"
            t.cell(0, 1).text = "B"
        else:
            doc.add_paragraph(item)
    doc.save(str(path))


def _body_tags(path: Path) -> list:
    from docx import Document
    return [("p" if c.tag.endswith("}p") else "tbl") for c in Document(str(path)).element.body]


def test_f44_redline_moved_table() -> None:
    print("\n== F44: redline non-paragraph anchor ==")
    d = scratch("f44_")
    b, r, o = d / "b.docx", d / "r.docx", d / "o.docx"
    _build_docx(b, ["First paragraph here.", "table"])
    _build_docx(r, ["table", "First paragraph here."])
    info = pp.builtin_tracked_changes(b, r, o)
    tags = _body_tags(o)
    check("F44 the table lands at its revised position", tags[:3] == ["tbl", "p", "tbl"], str(tags))
    check("F44 the relocation is reported",
          info.get("non_paragraph_changed") is True and "MOVED" in str(info.get("warning")))
    # D-052: a table after an INSERTED paragraph stays after it.
    _build_docx(b, ["First", "table", "Third"])
    _build_docx(r, ["First", "Inserted", "table", "Third"])
    pp.builtin_tracked_changes(b, r, o)
    check("F44 D-052 table after an inserted paragraph is unchanged",
          _body_tags(o)[:4] == ["p", "p", "tbl", "p"], str(_body_tags(o)))
    # R01: a table after a DELETED paragraph keeps the base order.
    _build_docx(b, ["First", "Second", "table"])
    _build_docx(r, ["First", "table"])
    pp.builtin_tracked_changes(b, r, o)
    check("F44 R01 deleted-paragraph base order is unchanged",
          _body_tags(o)[:3] == ["p", "p", "tbl"], str(_body_tags(o)))


# ---------------------------------------------------------------------------
# R02 -- a moved AND internally changed table must keep the unmarked-content
# limitation in its warning; the MOVED branch must not hide it.
# ---------------------------------------------------------------------------
def test_r02_moved_changed_table_warning() -> None:
    print("\n== R02: moved+changed non-paragraph warning ==")
    from docx import Document

    d = scratch("r02_")
    b, r, o = d / "b.docx", d / "r.docx", d / "o.docx"

    def build(path: Path, items, cell: str) -> None:
        doc = Document()
        for item in items:
            if item == "table":
                t = doc.add_table(rows=1, cols=2)
                t.cell(0, 0).text = cell
                t.cell(0, 1).text = "B"
            else:
                doc.add_paragraph(item)
        doc.save(str(path))

    build(b, ["First paragraph here.", "table"], "A")
    build(r, ["table", "First paragraph here."], "CHANGED")
    info = pp.builtin_tracked_changes(b, r, o)
    warning = str(info.get("warning") or "")
    check("R02 moved+changed still reports MOVED", "MOVED" in warning, warning)
    check("R02 moved+changed reports the table change flag",
          info.get("non_paragraph_changed") is True, str(info))
    check("R02 moved+changed retains the unmarked-content limitation",
          "does NOT mark changes inside" in warning, warning)
    # A pure move keeps the MOVED warning; the content limitation is not implied.
    build(b, ["First paragraph here.", "table"], "A")
    build(r, ["table", "First paragraph here."], "A")
    only = pp.builtin_tracked_changes(b, r, o)
    check("R02 moved-only still reports MOVED", "MOVED" in str(only.get("warning")))


def main() -> int:
    for fn in (test_f01_unknown_prefer_string, test_f02_insertions_only_policy,
               test_r01_policy_direction_wording,
               test_f03_cli_usage, test_f09_audit_no_au_rows,
               test_f14_integrate_rescan, test_f16_paging_headings,
               test_f17_zero_item_readme, test_f20_standalone_prompt,
               test_f21_revision_token_help, test_f25_suite_count,
               test_f26_profile_table, test_f39_m30_pinned_seed,
               test_f41_append_parent_link, test_f42_read_parent_link,
               test_f43_copy_destination_link, test_f80_hash_root_link,
               test_f44_redline_moved_table,
               test_r02_moved_changed_table_warning):
        fn()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s): {FAILS}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
