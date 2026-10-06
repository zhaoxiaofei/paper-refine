#!/usr/bin/env python3
"""The 7-character content-hash version token (replaces letter increments).

Run:  python3 .paper_test/test_revision_token.py

Asserts:
  * the bundled tool `paper-revise/scripts/revision_token.py` and the pipeline's
    `revision_token_for_dir()` compute the SAME token for the same package;
  * the token is STABLE across applying it (rename "...-a.md" to
    "...-<token>.md", rename a .bib and repoint a LaTeX reference) and
    `--verify <token>` exits 0;
  * a content change makes the token change and `--verify` fail;
  * the payload definition excludes self-written reports, tracked-changes
    auxiliaries and `work/` scratch (changing them does not change the token);
  * the pipeline's document matching strips 7-hex tokens exactly like legacy
    letter/digit tokens;
  * a filename token that contradicts the content-derived token is recorded and
    warned about (never a hard error);
  * the revision/rewrite/integration prompts state the rule and no longer
    contain the letter-increment rule.

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
spec = importlib.util.spec_from_file_location("paper_rtok", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_rtok"] = nb
spec.loader.exec_module(nb)

SCRIPT = WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py"
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


def run_script(*args):
    return subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args],
                          capture_output=True, text=True)


def script_token(d: Path) -> str:
    out = run_script(d)
    m = re.search(r"version token:\s*([0-9a-f]{7})", out.stdout)
    if not m:
        raise AssertionError(f"no token in output: {out.stdout!r} {out.stderr!r}")
    return m.group(1)


def make_package(tmp: Path) -> Path:
    (tmp / "ms-a.md").write_text("text body of the revision\n", encoding="utf-8")
    (tmp / "supp-a.tex").write_text(
        "\\addbibresource{refs-a.bib}\n\\includegraphics{fig1.pdf}\n", encoding="utf-8")
    (tmp / "refs-a.bib").write_text("@article{x}\n", encoding="utf-8")
    (tmp / "fig1.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp / "CHANGELOG.md").write_text("a self-written report\n", encoding="utf-8")
    (tmp / "ms-a.tracking-a1.docx").write_bytes(b"auxiliary")
    (tmp / "ms-a.logging-winner1.docx").write_bytes(b"winner auxiliary")
    (tmp / "work").mkdir()
    (tmp / "work" / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    return tmp


def test_agreement_and_identity():
    print()
    print("== RT1: the tool and the pipeline agree; the token is 7 hex ==")
    tmp = make_package(scratch("paper_rtok_"))
    s_tok = script_token(tmp)
    p_tok = nb.revision_token_for_dir(tmp)["token"]
    check("RT1 both implementations print a 7-hex token", len(s_tok) == 7 == len(p_tok),
          f"{s_tok} {p_tok}")
    check("RT1 the tool and the pipeline agree", s_tok == p_tok, f"{s_tok} vs {p_tok}")
    check("RT1 the token counts only the payload files",
          nb.revision_token_for_dir(tmp)["files"] == 4,
          str(nb.revision_token_for_dir(tmp)))


def test_stability_and_verification():
    print()
    print("== RT2: applying the token does not change it; --verify proves it ==")
    tmp = make_package(scratch("paper_rtok_apply_"))
    tok = script_token(tmp)
    (tmp / "ms-a.md").rename(tmp / f"ms-{tok}.md")
    (tmp / "refs-a.bib").rename(tmp / f"refs-{tok}.bib")
    tex = tmp / "supp-a.tex"
    tex.write_text(tex.read_text(encoding="utf-8").replace("refs-a.bib", f"refs-{tok}.bib"),
                   encoding="utf-8")
    (tex).rename(tmp / f"supp-{tok}.tex")
    after = script_token(tmp)
    check("RT2 the token is unchanged after rename + repoint", after == tok, f"{tok} -> {after}")
    ver = run_script(tmp, "--verify", tok)
    check("RT2 --verify exits 0 and prints OK",
          ver.returncode == 0 and "OK" in ver.stdout, ver.stdout + ver.stderr)
    info = nb.revision_token_for_dir(tmp)
    check("RT2 the pipeline marks the applied token as consistent",
          info["token"] == tok and info["consistent"] is True
          and info["tokens_seen"] == [tok], str(info))
    (tmp / f"ms-{tok}.md").write_text("a DIFFERENT body\n", encoding="utf-8")
    check("RT2 a content change changes the token",
          nb.revision_token_for_dir(tmp)["token"] != tok)
    ver2 = run_script(tmp, "--verify", tok)
    check("RT2 --verify fails on a changed package", ver2.returncode == 1
          and "MISMATCH" in ver2.stdout, ver2.stdout)


def test_payload_exclusions():
    print()
    print("== RT3: reports/auxiliaries/scratch never enter the token ==")
    tmp = make_package(scratch("paper_rtok_payload_"))
    tok = script_token(tmp)
    (tmp / "CHANGELOG.md").write_text("a rewritten report with new text\n", encoding="utf-8")
    (tmp / "REVISION_REPORT.md").write_text("more self-written text\n", encoding="utf-8")
    (tmp / "work" / "scratch.txt").write_text("different scratch\n", encoding="utf-8")
    (tmp / "ms-a.logging-a2.docx").write_bytes(b"another auxiliary")
    (tmp / "ms-a.tracking-w1.docx").write_bytes(b"a third auxiliary")
    (tmp / "ms-a.logging-winner3.bib").write_bytes(b"winner auxiliary")
    check("RT3 the token survives report/aux/scratch edits",
          script_token(tmp) == tok and nb.revision_token_for_dir(tmp)["token"] == tok)
    # RT3b: the pipeline's own completion signals are bookkeeping too. A
    # misplaced `_pipeline_done.json`/`scores.json` inside a package must not
    # enter the token -- and the two implementations must agree either way,
    # or the orchestrator warns about a token the agents computed correctly.
    (tmp / "_pipeline_done.json").write_text('{"stage": "revise", "status": "complete"}\n',
                                             encoding="utf-8")
    (tmp / "scores.json").write_text('{"rows": []}\n', encoding="utf-8")
    check("RT3b a package carrying completion signals keeps its token",
          script_token(tmp) == tok and nb.revision_token_for_dir(tmp)["token"] == tok)
    check("RT3b both implementations still agree with a completion signal inside",
          script_token(tmp) == nb.revision_token_for_dir(tmp)["token"],
          f"{script_token(tmp)} vs {nb.revision_token_for_dir(tmp)['token']}")
    check("RT3b the signal is not counted as a payload file",
          nb.revision_token_for_dir(tmp)["files"] == 4,
          str(nb.revision_token_for_dir(tmp)))


def test_matching_and_recording():
    print()
    print("== RT4: 7-hex tokens are stripped in matching; mismatches warn ==")
    tok = "4f3a9c1"
    a = nb._doc_key(f"cnb01B-2-mainText-{tok}.docx")
    b = nb._doc_key("cnb01B-2-mainText-b.docx")
    check("RT4 _doc_key strips a 7-hex token like a legacy letter", a == b, f"{a!r} vs {b!r}")
    check("RT4 a numbered family member is not mistaken for a version token",
          nb._doc_key("SI-Table-1.csv") != nb._doc_key("SI-Table-2.csv"))
    tmp = make_package(scratch("paper_rtok_rec_"))
    rec, warns = {}, []
    nb._record_revision_token(rec, tmp, warns)
    check("RT4 the package token is recorded on the run record",
          rec.get("revision_token", {}).get("token") == script_token(tmp))
    bad = scratch("paper_rtok_bad_")
    (bad / "ms-deadbee.md").write_text("content that does not hash to deadbee\n", encoding="utf-8")
    rec2, warns2 = {}, []
    nb._record_revision_token(rec2, bad, warns2)
    check("RT4 a contradictory filename token is warned about, not fatal",
          warns2 and "token mismatch" in warns2[0], str(warns2))


def test_evidence_area_names_are_not_naming_evidence():
    print()
    print("== RT6: a 7-hex name inside a READ-ONLY evidence area is not naming evidence ==")
    tmp = make_package(scratch("paper_rtok_ev_"))
    (tmp / "raw_data").mkdir()
    (tmp / "raw_data" / "results-deadbee.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    script_info = json.loads(run_script(tmp, "--json").stdout)
    pipe_info = nb.revision_token_for_dir(tmp)
    check("RT6 both implementations compute the same token",
          script_info["token"] == pipe_info["token"],
          f"{script_info['token']} vs {pipe_info['token']}")
    check("RT6 both count the evidence file in the content hash",
          script_info["files"] == pipe_info["files"] == 5,
          f"{script_info['files']} vs {pipe_info['files']}")
    check("RT6 both treat the evidence-area name as NO naming evidence",
          script_info["hex_tokens"] == pipe_info["hex_tokens"] == []
          and script_info["tokens_seen"] == pipe_info["tokens_seen"] == ["a"]
          and "deadbee" not in pipe_info["tokens_seen"]
          and script_info["consistent"] == pipe_info["consistent"] is False,
          f"{script_info} vs {pipe_info}")
    # ...while a token in a WRITABLE path is still naming evidence, in both.
    (tmp / "ms-a.md").rename(tmp / "ms-deadbee.md")
    script_info = json.loads(run_script(tmp, "--json").stdout)
    pipe_info = nb.revision_token_for_dir(tmp)
    check("RT6 a 7-hex name OUTSIDE the evidence area is still naming evidence",
          script_info["hex_tokens"] == pipe_info["hex_tokens"] == ["deadbee"]
          and script_info["tokens_seen"] == pipe_info["tokens_seen"] == ["a", "deadbee"]
          and script_info["consistent"] is False and pipe_info["consistent"] is False,
          f"{script_info} vs {pipe_info}")
    # ...and the SAME evidence area carried as the RELATIVE SYMLINK every
    # sandbox package really has (see ensure_pristine_input): the pipeline's
    # payload walk follows it, so the shipped tool must follow it too, or the
    # token it prints for a real sandbox package diverges from the pipeline's.
    real = tmp.parent / (tmp.name + "_raw_data_real")     # outside the package
    (tmp / "raw_data").rename(real)
    os.symlink(os.path.relpath(real, tmp), tmp / "raw_data")
    linked_script = json.loads(run_script(tmp, "--json").stdout)
    linked_pipe = nb.revision_token_for_dir(tmp)
    check("RT6 a LINKED evidence area hashes like the real one, in both",
          linked_script["token"] == linked_pipe["token"] == script_info["token"]
          and linked_script["files"] == linked_pipe["files"] == 5
          and linked_script["hex_tokens"] == linked_pipe["hex_tokens"] == ["deadbee"],
          f"{linked_script} vs {linked_pipe}")


def test_prompts():
    print()
    print("== RT5: the prompts state the content-hash rule ==")
    sb = Path("/tmp/paper_rtok_prompt")
    texts = {"revise": nb.revise_prompt(sb, "r1_a2_revise", 1),
             "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1),
             "integrate": nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"]),
             "judge": nb.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"])}
    for name in ("revise", "rewrite", "integrate"):
        t = " ".join(texts[name].split())
        check(f"RT5 {name} prompt names revision_token.py",
              "revision_token.py" in t)
        check(f"RT5 {name} prompt withdraws the increment rule",
              "INCREMENT" in t.upper() and "withdrawn" in t.lower())
        check(f"RT5 {name} prompt requires --verify",
              "--verify" in t)
        check(f"RT5 {name} prompt has no live letter-increment instruction",
              "increment that letter" not in t and "increment its digits" not in t
              and "increment the digits" not in t and "ONE step" not in t)
    check("RT5 judge prompt treats a token/rename difference as a rename",
          "content-hash version token" in " ".join(texts["judge"].split()))


def main() -> int:
    for fn in (test_agreement_and_identity, test_stability_and_verification,
               test_payload_exclusions, test_matching_and_recording,
               test_evidence_area_names_are_not_naming_evidence, test_prompts):
        try:
            fn()
        except Exception as e:                                   # noqa: BLE001
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL REVISION-TOKEN CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
