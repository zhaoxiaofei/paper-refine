#!/usr/bin/env python3
"""The `zot` CLI (pyzotero-cli) must be wired into every prompt, safely.

Run:  python3 .paper_test/test_zotero_integration.py

Asserts:
  * `setup --zotero {off,read,edit,apply}` parses, defaults to `edit`, persists
    the policy in pipeline_config.json, and documents itself in --help and the
    usage examples;
  * every prompt (review, rewrite, revise, integration, judge) carries the
    Zotero block, with the availability line filled in and no unresolved
    @@TOKEN@@ left behind;
  * the policy is propagated into the prompt: `off` never names the CLI, `read`
    resolves references without allowing a field edit, `edit` (the default)
    adds the citation-edit clause, and only `apply` reaches the
    propose-then-verify library-update protocol;
  * the WRITE path is unreachable from review, rewrite and judge sessions even
    when the run is configured with `--zotero apply`;
  * an unknown/hand-edited policy value falls back to the default, never to a
    more permissive mode;
  * the citation-edit clause preserves the live-field safety net (the
    $zotero-use DOCX reference + validator, snapshot-then-prove, no invented
    keys, no automatic Zotero Refresh) and the apply clause keeps its hard
    limits (one field, one item, no create/delete, no bulk edit,
    --last-modified auto);
  * one real stub-agent round with `--zotero apply` writes the protocol into
    the sandboxes' PROMPT.md files on disk.

`PAPER_WS` retargets the suite at another copy of the tree.
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
spec = importlib.util.spec_from_file_location("paper_zot", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_zot"] = nb
spec.loader.exec_module(nb)

STUB = Path(__file__).resolve().parent / "stub_agent.py"
STUB_JUDGE = Path(__file__).resolve().parent / "stub_judge.py"
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


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def prompts(mode: str = None) -> dict:
    """Build all five prompts, optionally with one explicit Zotero policy."""
    sb = Path("/tmp/paper_zot_prompt")
    kw = {} if mode is None else {"zotero": mode}
    return {
        "review": nb.review_prompt(sb, "r1_review", 1, **kw),
        "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1, **kw),
        "revise": nb.revise_prompt(sb, "r1_a2_revise", 1, **kw),
        "integrate": nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"], **kw),
        "judge": nb.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"], **kw),
    }


# =====================================================================
# ZT1 - the policy knob
# =====================================================================

def test_policy_knob():
    print()
    print("== ZT1: setup --zotero {off,read,edit,apply}, default edit ==")
    check("ZT1 the four modes are declared in order",
          tuple(nb.ZOTERO_MODES) == ("off", "read", "edit", "apply"),
          str(nb.ZOTERO_MODES))
    check("ZT1 the default policy is `edit`",
          nb.DEFAULT_ZOTERO_MODE == "edit" and nb.DEFAULTS["zotero"] == "edit",
          f"{nb.DEFAULT_ZOTERO_MODE} {nb.DEFAULTS['zotero']}")
    parser = nb.build_parser()
    setup_default = parser.parse_args(["setup", "--source", "/tmp/nonexistent-source"])
    check("ZT1 `setup` defaults to the edit policy",
          setup_default.zotero == "edit", str(setup_default.zotero))
    check("ZT1 `setup --zotero apply` parses",
          parser.parse_args(["setup", "--source", "/tmp/x", "--zotero", "apply"]).zotero
          == "apply")
    bad = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                          "--source", "/tmp/x", "--zotero", "banana"],
                         capture_output=True, text=True)
    check("ZT1 an unknown policy is rejected by argparse",
          bad.returncode != 0 and "invalid choice" in (bad.stderr + bad.stdout),
          (bad.stderr + bad.stdout)[-120:])
    choices = parser._subparsers._group_actions[0].choices
    subs = {a.dest: a for a in choices["setup"]._actions}
    help_text = subs["zotero"].help or ""
    check("ZT1 setup help documents every mode and the remote-write warning",
          all(m in help_text for m in ("off", "read", "edit", "apply"))
          and "remote Zotero account" in help_text)
    check("ZT1 usage examples document --zotero",
          "--zotero off|read|edit|apply" in nb.USAGE_EXAMPLES)


def test_policy_persistence():
    print()
    print("== ZT1b: the policy is persisted by setup and read back by run ==")
    for want in ("edit", "apply"):
        tmp = scratch(f"paper_zot_setup_{want}_")
        source = tmp / "source"
        write(source / "manuscript-b.md", "title\n")
        root = tmp / "root"
        argv = [sys.executable, str(WS / "paper_pipeline.py"), "setup",
                "--source", str(source), "--root", str(root), "--judges", "1"]
        if want != "edit":
            argv += ["--zotero", want]
        proc = subprocess.run(argv, capture_output=True, text=True)
        check(f"ZT1b setup with --zotero {want} succeeds", proc.returncode == 0,
              (proc.stdout + proc.stderr)[-200:])
        cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
        check(f"ZT1b pipeline_config.json records zotero={want}", cfg.get("zotero") == want,
              str(cfg.get("zotero")))
        ctx = nb.Ctx(root)
        ctx.load(need_cfg=True)
        check(f"ZT1b zotero_mode_of() reads {want} back", nb.zotero_mode_of(ctx) == want,
              nb.zotero_mode_of(ctx))
    check("ZT1b an unknown stored value falls back to the default (never to apply)",
          nb.zotero_mode_of(type("C", (), {"cfg": {"zotero": "apply-everything"}})()) == "edit")


# =====================================================================
# ZT2 - the block is in every prompt
# =====================================================================

def test_prompt_coverage():
    print()
    print("== ZT2: every prompt carries the Zotero block ==")
    texts = prompts()
    for name, text in texts.items():
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
        check(f"ZT2 {name} prompt has no unresolved @@TOKEN@@", not unresolved, str(unresolved))
        check(f"ZT2 {name} prompt carries the Zotero tooling block",
              "ZOTERO REFERENCE TOOLING" in text)
        check(f"ZT2 {name} prompt names the read routes",
              "zot items get" in text and "zot fulltext get" in text)
        check(f"ZT2 {name} prompt states the availability honestly",
              "available -- the `zot` command" in text
              or "NOT available -- the `zot` command" in text)
    check("ZT2 revise prompt names its ledger path",
          "revised/work/ZOTERO_LIBRARY.md" in texts["revise"])
    check("ZT2 integration prompt names its ledger path",
          "integrated/work/ZOTERO_LIBRARY.md" in texts["integrate"])
    check("ZT2 review prompt is identification-only",
          "YOUR STAGE IDENTIFIES, IT NEVER EDITS" in texts["review"]
          and "report each\n    problem as a finding" in texts["review"])
    check("ZT2 rewrite prompt keeps citations unchanged",
          "YOUR STAGE REWRITES FORM, NOT CONTENT" in texts["rewrite"])
    check("ZT2 judge prompt is read-only",
          "JUDGE SESSIONS ARE READ-ONLY" in texts["judge"])


# =====================================================================
# ZT3 - the policy reaches the prompt, and never widens the read-only roles
# =====================================================================

def test_policy_propagation():
    print()
    print("== ZT3: off/read/edit/apply change exactly what they should ==")
    off = prompts("off")
    for name, text in off.items():
        check(f"ZT3 off-mode {name} prompt disables the CLI",
              "SWITCHED OFF" in text and "ZOTERO REFERENCE TOOLING" not in text
              and "zot items get" not in text)
        check(f"ZT3 off-mode {name} prompt overrides the read-exception sentence",
              "overrides any earlier sentence in this prompt" in text)
    read = prompts("read")["revise"]
    check("ZT3 read-mode keeps references resolvable",
          "ZOTERO REFERENCE TOOLING" in read and "zot items get" in read)
    check("ZT3 read-mode forbids citation-field edits",
          "does NOT allow citation-field edits" in read
          and "CITATION EDITS IN YOUR REVISED COPY" not in read)
    check("ZT3 read-mode forbids the library update command",
          "--last-modified auto" not in read and "zot items update" not in read)
    edit = prompts("edit")["revise"]
    check("ZT3 edit-mode allows citation edits",
          "CITATION EDITS IN YOUR REVISED COPY" in edit
          and "insert a citation to a resolved library item" in edit)
    check("ZT3 edit-mode keeps the library read-only",
          "the library is READ-ONLY for this run" in edit
          and "zot items update" not in edit and "--last-modified auto" not in edit)
    check("ZT3 edit-mode turns a suspected metadata error into a proposal",
          "becomes a proposal row in the\n    ledger" in edit
          and "plus a matching manual step" in edit)
    apply_text = prompts("apply")["revise"]
    check("ZT3 apply-mode enables the two-pass write protocol",
          "P1 PROPOSE" in apply_text and "P2 THINK TWICE, THEN VERIFY" in apply_text)
    check("ZT3 apply-mode names the guarded update command",
          '`zot items update <KEY> --field <FIELD> "<VALUE>" --last-modified auto`'
          in apply_text)
    check("ZT3 apply-mode re-reads and logs the outcome",
          "RE-READ the item" in apply_text and "append the\n      outcome" in apply_text)
    for name, text in prompts("apply").items():
        if name == "revise" or name == "integrate":
            continue
        check(f"ZT3 apply-mode cannot reach the write path from {name}",
              "--last-modified auto" not in text and "P2 THINK TWICE" not in text
              and "zot items update" not in text)
    unknown = prompts("banana")
    check("ZT3 an unknown mode falls back to the default, not to apply",
          "CITATION EDITS IN YOUR REVISED COPY" in unknown["revise"]
          and "--last-modified auto" not in unknown["revise"])


# =====================================================================
# ZT4 - the safety content of the clauses
# =====================================================================

def test_safety_clauses():
    print()
    print("== ZT4: the live-field and library-write guardrails ==")
    revise = prompts("edit")["revise"]
    check("ZT4 the DOCX citation reference is required reading",
          "references/word-docx-citations.md" in revise)
    check("ZT4 the bundled validator is named",
          "scripts/validate_zotero_docx.py" in revise)
    check("ZT4 parent item keys, unique citationIDs, preserved baseline",
          "PARENT bibliographic item keys" in revise
          and "unique\n    citationID" in revise
          and "preserve every existing citation\n    ID, item ID, URI and embedded itemData"
          in revise)
    check("ZT4 no synthesized cached citation text",
          "never synthesize `formattedCitation`/`plainCitation`" in revise)
    check("ZT4 the agents must not trigger Zotero Refresh",
          "never trigger Zotero" in revise and "Refresh yourself" in revise)
    check("ZT4 snapshot-then-prove, restore on failure",
          "SNAPSHOT FIRST, PROVE THE EDIT" in revise
          and "restore the snapshot and write a manual step" in revise)
    check("ZT4 the evidence chain forbids claim changes",
          "EVIDENCE CHAIN" in revise
          and "scientific judgement call -- record it for the author" in revise)
    check("ZT4 an unreachable library degrades to the manual route",
          "ConnectError" in revise and "do not retry in a loop" in revise)
    check("ZT4 an unreadable live field is never rewritten",
          "stays untouched and goes to the manual-verification list" in revise)
    apply_text = prompts("apply")["revise"]
    check("ZT4 apply-mode hard limits are present",
          "never create or delete library items" in apply_text
          and "never bulk-edit" in apply_text
          and "ONE field on ONE item" in apply_text)
    check("ZT4 apply-mode demands the propose row before any write",
          "before any write, put the proposal row in the ledger" in apply_text)
    check("ZT4 apply-mode verifies identity before writing",
          "compare key,\n         item type, title, creators, year and DOI" in apply_text)
    judge = prompts()["judge"]
    check("ZT4 judge sessions keep no Zotero ledger",
          "do not create a separate Zotero ledger" in judge)
    check("ZT4 the mode override is explicit (skill default superseded)",
          "EXPLICIT override\n    of the skill's default prohibition" in revise
          and "explicit override of the skill's read-only-Zotero default" in apply_text)


# =====================================================================
# ZT5 - a real stub round writes the policy into the on-disk prompts
# =====================================================================

def test_end_to_end_prompt():
    print()
    print("== ZT5: a stub round with --zotero apply writes it into PROMPT.md ==")
    tmp = scratch("paper_zot_e2e_")
    source = tmp / "source"
    write(source / "manuscript-b.md", "title\n")
    root = tmp / "root"
    setup = [sys.executable, str(WS / "paper_pipeline.py"), "setup",
             "--source", str(source), "--root", str(root), "--judges", "1",
             "--rounds", "1", "--rewrites", "0", "--revises", "1",
             "--zotero", "apply"]
    proc = subprocess.run(setup, capture_output=True, text=True)
    check("ZT5 setup succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    check("ZT5 setup prints the apply policy and its warning",
          "zotero policy" in proc.stdout and "WRITES TO" in proc.stdout, proc.stdout[-300:])
    run = [sys.executable, str(WS / "paper_pipeline.py"), "run", "--root", str(root),
           "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
           "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
           "--retries", "0"]
    proc = subprocess.run(run, capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    check("ZT5 the stub round completes", proc.returncode == 0, out[-400:])
    check("ZT5 the run log announces the apply mode",
          "zotero reference tooling:  apply" in out, out[-300:])
    review_prompt = root / "runs" / "r1_review" / "PROMPT.md"
    revise_prompt = root / "runs" / "r1_a2_revise" / "PROMPT.md"
    check("ZT5 the on-disk review prompt is read-only for the library",
          review_prompt.is_file() and "YOUR STAGE IDENTIFIES, IT NEVER EDITS" in
          review_prompt.read_text(encoding="utf-8")
          and "zot items update" not in review_prompt.read_text(encoding="utf-8"))
    revise_text = revise_prompt.read_text(encoding="utf-8") if revise_prompt.is_file() else ""
    check("ZT5 the on-disk revise prompt carries the apply protocol",
          revise_text and "P2 THINK TWICE, THEN VERIFY" in revise_text
          and "revised/work/ZOTERO_LIBRARY.md" in revise_text)


def main() -> int:
    sections = (("policy", test_policy_knob),
                ("policy", test_policy_persistence),
                ("prompts", test_prompt_coverage),
                ("prompts", test_policy_propagation),
                ("safety", test_safety_clauses),
                ("e2e", test_end_to_end_prompt))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL ZOTERO-INTEGRATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
