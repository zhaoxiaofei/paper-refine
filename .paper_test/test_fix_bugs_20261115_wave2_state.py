#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2, group `state`.

Each check names the verified finding it guards and calls the function under
test on a tiny hermetic root built under tempfile.mkdtemp():

  F133  a failed save_state() must not leave state.json hard-linked to .prev
  F134  a symlinked version-corpus source ROOT is refused by the digest and
        judge-view walkers exactly as build_corpus_dir()/copy_into() refuses it
  F135  RTF identity fields are blanked in the judge view and a legacy .doc is a
        NAMED anonymity gap instead of a silent copy
  F136  OOXML HyperlinkBase / TitlesOfParts / cp:lastPrinted / w15:presenceInfo
        are neutralized in the judge view
  F137  a done reviser is stale when its recorded audit/ copy drifted
  F138  an integration run's frozen_discovery seed is freshness-checked and the
        review/cold-start/audit resets reach the integration runs
  F139  an integration run whose self_id is a reset pool member is reset too
  F140  judge_view_digest() survives an unreadable/symlinked view entry
  F142  an unreadable LIVE cold-start findings file falls back to the archive
  F145  the live prior-review layout's round2/findings_extra.json reaches
        prior_round/ (flat name) for the next review

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_state.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115wave2_state_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(p)
    return p


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rec(rid: str, kind: str, rnd: int = 1, **extra) -> dict:
    d = {"id": rid, "kind": kind, "round": rnd, "sandbox": f"runs/{rid}",
         "status": "done"}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# F133 -- failed save must leave a loadable, single-linked registry
# ---------------------------------------------------------------------------
def test_f133() -> None:
    print("\n== F133 crashed save leaves a loadable registry ==")
    root = scratch("w2state-f133-") / "root"
    root.mkdir()
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1}
    ctx.state = {"runs": {}}
    ctx.save_state()
    ctx.save_state()                       # the second save creates .prev
    state_path = root / "state.json"
    prev = root / "state.json.prev"
    check("fixture: first save writes state.json + .prev",
          state_path.is_file() and prev.is_file())

    real_write = pp.write_json_atomic

    def boom(path, obj, **kwargs):
        if Path(path).name == "state.json":
            raise OSError("simulated ENOSPC/crash before the atomic replace")
        return real_write(path, obj, **kwargs)

    raised = False
    pp.write_json_atomic = boom
    try:
        ctx.save_state()
    except OSError:
        raised = True
    finally:
        pp.write_json_atomic = real_write
    check("F133 the failed save propagates its error", raised)
    check("F133 the failed save leaves state.json single-linked",
          state_path.stat().st_nlink == 1,
          f"nlink={state_path.stat().st_nlink}")
    check("F133 .prev is a separate copy, not the live inode",
          prev.is_file() and prev.stat().st_ino != state_path.stat().st_ino)
    st, prob = pp.load_state_file(state_path)
    check("F133 the valid registry still loads after the failed save",
          st is not None and isinstance(st.get("runs"), dict), prob)

    # The process could also DIE between the link and the replace: the live
    # file then really is linked only to its canonical .prev backup.
    prev.unlink()
    os.link(state_path, prev)
    check("F133 state.json linked to its canonical .prev loads",
          pp.load_state_file(state_path)[0] is not None,
          f"nlink={state_path.stat().st_nlink}")
    # The narrower window: killed between the link and the rename onto .prev
    # leaves the companion at save_state()'s unique temporary name.
    prev.unlink()
    tmp_prev = root / f".{prev.name}.1234.abcdef.tmp"
    os.link(state_path, tmp_prev)
    check("F133 state.json linked to save_state's own temp loads",
          pp.load_state_file(state_path)[0] is not None,
          f"nlink={state_path.stat().st_nlink}")
    tmp_prev.unlink()
    # Any OTHER second link is still refused.
    foreign = root / "foreign"
    os.link(state_path, foreign)
    st2, prob2 = pp.load_state_file(state_path)
    check("F133 an unrelated hard link is still refused",
          st2 is None and "hard-linked" in str(prob2), str(prob2)[:120])


# ---------------------------------------------------------------------------
# F134 -- symlinked source root: digest/view/pin agree
# ---------------------------------------------------------------------------
def test_f134() -> None:
    print("\n== F134 symlinked corpus source root refused consistently ==")
    root = scratch("w2state-f134-") / "root"
    root.mkdir()
    outside = scratch("w2state-f134-out-")
    write(outside / "secret.py", "SECRET = 1\n")
    write(outside / "data.csv", "a,b\n")
    ctx = pp.Ctx(root)
    ctx.state = {"judge_salt": "s" * 32, "runs": {}}
    sb = root / "runs" / "r1_w1"
    write(sb / "rewritten" / "ms.tex", "main\n")
    os.symlink(outside, sb / "code")
    ctx.state["runs"]["r1_w1"] = rec("r1_w1", "rewrite", produces="w1")

    man = pp.corpus_manifest(ctx, 1, "w1")
    check("F134 the digest never descends through a symlinked source root",
          not [k for k in man["files"] if k.startswith("code/")], str(man["files"]))
    check("F134 the judge-view file list never descends through it",
          not [k for k, _p in pp.corpus_files_for_view(ctx, 1, "w1")
               if k.startswith("code/")])
    dst = scratch("w2state-f134-pin-")
    pp.build_corpus_dir(ctx, 1, "w1", dst)
    pin_files = sorted(p.relative_to(dst).as_posix()
                       for p in dst.rglob("*") if p.is_file())
    check("F134 the pin materializes exactly the recorded corpus",
          pin_files == ["ms.tex"], str(pin_files))
    check("F134 the pin digest equals the recorded corpus digest",
          pp.manifest_digest(pp.corpus_dir_manifest(dst)) == pp.manifest_digest(man))

    # A canonical `<root>/non_revised/<area>` evidence link is still followed:
    # the fix must not drop the legitimate link.
    root2 = scratch("w2state-f134-ev-") / "root"
    root2.mkdir()
    write(root2 / "non_revised" / "raw_data" / "d.csv", "a,b\n")
    ctx2 = pp.Ctx(root2)
    write(root2 / "runs" / "r1_w1" / "rewritten" / "ms.tex", "m\n")
    os.symlink(root2 / "non_revised" / "raw_data",
               root2 / "runs" / "r1_w1" / "rewritten" / "raw_data")
    ctx2.state = {"runs": {"r1_w1": rec("r1_w1", "rewrite", produces="w1")}}
    man2 = pp.corpus_manifest(ctx2, 1, "w1")
    check("F134 the canonical evidence-area link is still followed",
          "raw_data/d.csv" in man2["files"], str(sorted(man2["files"])))


# ---------------------------------------------------------------------------
# F135 -- RTF metadata blanked; legacy .doc named as a gap
# ---------------------------------------------------------------------------
def test_f135() -> None:
    print("\n== F135 RTF sanitized, legacy .doc recorded as a gap ==")
    rtf = (b"{\\rtf1{\\info{\\author Alice Example}{\\company Secret Corp}"
           b"{\\title My Draft}}hi}")
    out, notes = pp._sanitize_rtf_bytes(rtf)
    check("F135 RTF author is blanked", b"Alice Example" not in out)
    check("F135 RTF company is blanked", b"Secret Corp" not in out)
    check("F135 RTF title is blanked", b"My Draft" not in out)
    check("F135 RTF body is preserved", out.endswith(b"hi}"))
    check("F135 the sanitized RTF stays the same length", len(out) == len(rtf))
    check("F135 a clean RTF produces no gap note", notes == [], str(notes))

    root = scratch("w2state-f135-") / "root"
    root.mkdir()
    ctx = pp.Ctx(root)
    ctx.state = {"judge_salt": "s" * 32, "runs": {}}
    sb = root / "runs" / "r1_w1"
    write(sb / "rewritten" / "ms.rtf", rtf.decode("latin-1"))
    (sb / "rewritten" / "ms.doc").write_bytes(
        b"\xd0\xcf\x11\xe0Author: Alice Example; Company: Secret Corp")
    ctx.state["runs"]["r1_w1"] = rec("r1_w1", "rewrite", produces="w1")
    view = scratch("w2state-f135-view-")
    pp.build_judge_view(ctx, 1, "w1", view, 1234.0, "seed|target")
    files = {p.suffix.lower(): p for p in view.rglob("*") if p.is_file()}
    rtf_bytes = files[".rtf"].read_bytes()
    check("F135 the judge view's RTF carries no author/company/title",
          b"Alice Example" not in rtf_bytes and b"Secret Corp" not in rtf_bytes
          and b"My Draft" not in rtf_bytes)
    gaps = [g for v in (ctx.state.get("view_transform_warnings") or {}).values()
            for g in v]
    check("F135 the legacy .doc is recorded as a named anonymity gap",
          any(".doc" in g and "byte-for-byte" in g for g in gaps), str(gaps))
    check("F135 the RTF is NOT recorded as a gap",
          not any(".rtf" in g for g in gaps), str(gaps))


# ---------------------------------------------------------------------------
# F136 -- extra OOXML provenance fields are neutralized
# ---------------------------------------------------------------------------
def test_f136() -> None:
    print("\n== F136 OOXML HyperlinkBase/TitlesOfParts/lastPrinted/presence ==")
    core = ("<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/"
            "2006/metadata/core-properties\" xmlns:dc=\"http://purl.org/dc/elements/"
            "1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\">"
            "<dc:creator>Alice</dc:creator>"
            "<cp:lastPrinted>2019-05-06T07:08:00Z</cp:lastPrinted>"
            "<dc:title>Draft</dc:title></cp:coreProperties>")
    app = ("<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/"
           "extended-properties\" xmlns:vt=\"http://schemas.openxmlformats.org/"
           "officeDocument/2006/docPropsVTypes\"><Application>Word</Application>"
           "<HyperlinkBase>C:\\Users\\alice\\papers\\draft.docx</HyperlinkBase>"
           "<TitlesOfParts><vt:vector size=\"1\"><vt:lpstr>My Secret Draft Title"
           "</vt:lpstr></vt:vector></TitlesOfParts></Properties>")
    people = ("<w15:people xmlns:w15=\"http://schemas.microsoft.com/office/word/2012/"
              "wordml\"><w15:person w15:author=\"Alice\"><w15:presenceInfo "
              "w15:providerId=\"AD\" w15:userId=\"alice@example.com\"/>"
              "</w15:person></w15:people>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   "<w:document xmlns:w=\"http://schemas.openxmlformats.org/"
                   "wordprocessingml/2006/main\"><w:body/></w:document>")
        z.writestr("word/people.xml", people)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
    out, notes = pp._sanitize_ooxml_bytes(buf.getvalue())
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        app_out = z.read("docProps/app.xml")
        core_out = z.read("docProps/core.xml")
        people_out = z.read("word/people.xml")
    check("F136 HyperlinkBase is blanked", b"C:\\Users\\alice" not in app_out)
    check("F136 TitlesOfParts is blanked", b"My Secret Draft Title" not in app_out)
    check("F136 cp:lastPrinted is blanked", b"2019-05-06" not in core_out)
    check("F136 w15:presenceInfo userId/providerId are gone",
          b"alice@example.com" not in people_out and b"providerId" not in people_out)
    check("F136 the sanitized package is still a readable zip", bool(out))


# ---------------------------------------------------------------------------
# F137 -- a done reviser is stale when the audit/ copy drifted
# ---------------------------------------------------------------------------
def build_round1_root(tmp: Path, *, audit: str = "on"):
    """Round-1 root: a1 base, a done guided_review, an audit and one reviser."""
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    write(root / "non_revised" / "n.txt", "n\n")
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "audit": audit, "guided_review": "on",
               "review_split": "off", "cold_start_review": "off"}
    ctx.state = {"judge_salt": "s" * 32, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": pp.hash_manifest(root / "non_revised")}
    write(root / "runs" / "r1_a1" / "base" / "ms.tex", "x\n")
    ctx.state["runs"]["r1_a1"] = rec("r1_a1", "a1")
    write(root / "runs" / "r1_guided_review" / "guided_review" / "findings.json",
          '{"findings": []}')
    write(root / "runs" / "r1_guided_review" / "guided_review" / "round2"
          / "findings_extra.json", '{"findings": []}')
    ctx.state["runs"]["r1_guided_review"] = rec("r1_guided_review", "guided_review")
    write(root / "runs" / "r1_audit" / "audit" / "audit.json",
          '{"dispositions": [{"id": "F-1", "verdict": "drop"}]}')
    ctx.state["runs"]["r1_audit"] = rec("r1_audit", "audit")
    rev = root / "runs" / "r1_a2_revise"
    write(rev / "base" / "ms.tex", "x\n")
    shutil.copytree(root / "non_revised", rev / "non_revised")
    write(rev / "guided_review" / "findings.json", '{"findings": []}')
    write(rev / "guided_review" / "round2" / "findings_extra.json",
          '{"findings": []}')
    write(rev / "audit" / "audit.json", '{"dispositions": []}')
    ctx.state["runs"]["r1_a2_revise"] = rec(
        "r1_a2_revise", "revise", produces="a2",
        inputs_manifest={"audit": {"files": {"audit.json": "old"}}})
    return ctx


def test_f137() -> None:
    print("\n== F137 a stale audit/ copy makes the reviser stale ==")
    ctx = build_round1_root(scratch("w2state-f137-"))
    revise = ctx.state["runs"]["r1_a2_revise"]
    probs = pp._input_freshness_problems(ctx, revise)
    check("F137 the drifted audit/ copy is reported",
          any("audit/" in p for p in probs), str(probs))
    # Resynchronize the copy: the reviser is fresh again.
    shutil.copy2(ctx.sandbox_of(ctx.state["runs"]["r1_audit"]) / "audit" / "audit.json",
                 ctx.sandbox_of(revise) / "audit" / "audit.json")
    probs2 = pp._input_freshness_problems(ctx, revise)
    check("F137 a matching audit/ copy is clean",
          not [p for p in probs2 if "audit/" in p], str(probs2))


# ---------------------------------------------------------------------------
# F138 -- integration seed freshness + review resets reach integrations
# ---------------------------------------------------------------------------
def build_integration_fixture(tmp: Path, *, with_review: bool = True):
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    write(root / "non_revised" / "n.txt", "n\n")
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [1], "revises": [1],
               "integrators": 0xFFFFFFFF, "guided_review": "on",
               "cold_start_review": "off", "audit": "off", "review_split": "off"}
    ctx.state = {"judge_salt": "s" * 32, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": pp.hash_manifest(root / "non_revised")}
    write(root / "runs" / "r1_a1" / "base" / "ms.tex", "X\n")
    ctx.state["runs"]["r1_a1"] = rec("r1_a1", "a1")
    write(root / "runs" / "r1_w1" / "rewritten" / "ms.tex", "w1\n")
    ctx.state["runs"]["r1_w1"] = rec("r1_w1", "rewrite", produces="w1")
    a2_rid = pp.rid_for_fresh(1, "a2")
    write(root / "runs" / a2_rid / "revised" / "ms.tex", "a2\n")
    ctx.state["runs"][a2_rid] = rec(a2_rid, "revise", produces="a2")
    if with_review:
        write(root / "runs" / "r1_guided_review" / "guided_review" / "findings.json",
              '{"findings": []}')
        write(root / "runs" / "r1_guided_review" / "guided_review" / "round2"
              / "findings_extra.json",
              '{"findings": [{"id": "X-901", "location": "l", "explanation": "e"}]}')
        ctx.state["runs"]["r1_guided_review"] = rec("r1_guided_review", "guided_review")
    isb = root / "runs" / "r1_i2"
    write(isb / "self" / "ms.tex", "w1\n")
    write(isb / "others" / "a1" / "ms.tex", "X\n")
    write(isb / "others" / "a2" / "ms.tex", "a2\n")
    shutil.copytree(root / "non_revised", isb / "non_revised")
    if with_review:
        write(isb / "frozen_discovery" / "findings_extra.json", '{"findings": []}')
    extra = ({"inputs_manifest": {"frozen_discovery":
                                  {"files": {"findings_extra.json": "OLD"}}}}
             if with_review else {})
    ctx.state["runs"]["r1_i2"] = rec(
        "r1_i2", "integrate", self_id="w1", other_ids=["a1", "a2"],
        produces="i2", **extra)
    return ctx


def test_f138() -> None:
    print("\n== F138 frozen_discovery is freshness-checked ==")
    ctx = build_integration_fixture(scratch("w2state-f138-"))
    i2 = ctx.state["runs"]["r1_i2"]
    probs = pp._input_freshness_problems(ctx, i2)
    check("F138 a stale frozen_discovery seed is reported",
          any(pp.DISCOVERY_SEED_DIR in p for p in probs), str(probs))

    # The integration runs are dependents of the review producer: resetting the
    # review must reset the done integrator that consumed its X-* rows.
    ctx2 = build_integration_fixture(scratch("w2state-f138-dep-"))
    i2b = ctx2.state["runs"]["r1_i2"]
    # Refresh the seed the way materialize_integrate() would, so the ONLY drift
    # in this fixture is the review base we break below.
    pp.seed_discovery_findings(ctx2, 1, ctx2.sandbox_of(i2b))
    write(ctx2.sandbox_of(ctx2.state["runs"]["r1_guided_review"]) / "base" / "ms.tex",
          "DIFFERENT\n")
    check("fixture: the integrator itself is fresh before the reset",
          pp._input_freshness_problems(ctx2, i2b) == [],
          str(pp._input_freshness_problems(ctx2, i2b)))
    reset = pp.revalidate_round_inputs(ctx2, 1)
    check("F138 resetting the review also resets the integration run",
          "r1_i2" in reset, str(reset))


# ---------------------------------------------------------------------------
# F139 -- an integration's SELF edge is a dependency
# ---------------------------------------------------------------------------
def test_f139() -> None:
    print("\n== F139 the self integration is a dependent of its pool member ==")
    ctx = build_integration_fixture(scratch("w2state-f139-"), with_review=False)
    # Give the round's rewrite its base, then break it so w1 is stale.
    write(ctx.root / "runs" / "r1_w1" / "base" / "ms.tex", "X\n")
    i2 = ctx.state["runs"]["r1_i2"]
    pre = pp._input_freshness_problems(ctx, i2)
    check("fixture: the integrator is fresh before the reset", pre == [], str(pre))
    write(ctx.sandbox_of(ctx.state["runs"]["r1_w1"]) / "base" / "ms.tex", "CHANGED\n")
    reset = pp.revalidate_round_inputs(ctx, 1)
    check("F139 the integration whose self is the reset member is reset",
          "r1_i2" in reset and "r1_w1" in reset, str(reset))


# ---------------------------------------------------------------------------
# F140 -- a damaged derived view is stale, not a traceback
# ---------------------------------------------------------------------------
def test_f140() -> None:
    print("\n== F140 judge_view_digest survives a damaged view ==")
    view = scratch("w2state-f140-")
    write(view / "f0001.tex", "x\n")
    os.chmod(view / "f0001.tex", 0)
    try:
        got = pp.judge_view_digest(view)
        raised = None
    except Exception as exc:                                       # noqa: BLE001
        got, raised = None, exc
    finally:
        os.chmod(view / "f0001.tex", 0o644)
    check("F140 an unreadable file does not raise",
          raised is None, f"{type(raised).__name__}: {raised}" if raised else "")
    check("F140 the unreadable file is a non-matching sentinel",
          got == [("f0001.tex", "<unreadable>")], str(got))

    view2 = scratch("w2state-f140-link-")
    write(view2 / "a.tex", "x\n")
    os.symlink("/etc/hostname", view2 / "b.tex")
    raised2 = None
    try:
        got2 = pp.judge_view_digest(view2)
    except Exception as exc:                                       # noqa: BLE001
        got2, raised2 = None, exc
    check("F140 a planted file symlink does not raise",
          raised2 is None, f"{type(raised2).__name__}: {raised2}" if raised2 else "")
    # The current contract (F162 of the 2026-11-15 08:17 run) is the opposite:
    # a planted symlink must make the derived view compare UNEQUAL so it is
    # rebuilt, and it is named by a sentinel rather than followed.
    check("F162 the planted symlink is a non-matching sentinel",
          got2 == [("a.tex", pp.sha256_file(view2 / "a.tex")),
                   ("b.tex", "<symlink>")], str(got2))


# ---------------------------------------------------------------------------
# F142 -- unreadable live probe file falls back to the archive
# ---------------------------------------------------------------------------
def test_f142() -> None:
    print("\n== F142 unreadable live cold-start findings fall back ==")
    root = scratch("w2state-f142-") / "root"
    root.mkdir()
    ctx = pp.Ctx(root)
    ctx.state = {"runs": {}, "rounds": {}, "pinned": [], "log": []}
    sb = root / "runs" / "r1_cold_start_review"
    live = sb / "cold_start_review" / "findings_cold_start_review.json"
    write(live, '{"findings": [{"id": "X-901", "location": "l", "explanation": "e"}]}')
    write(ctx.reports_dir / "round1_review" / "findings_cold_start_review.json",
          '{"findings": [{"id": "X-902", "location": "l", "explanation": "e"}]}')
    ctx.state["runs"]["r1_cold_start_review"] = rec(
        "r1_cold_start_review", "cold_start_review")
    check("fixture: the readable live file wins",
          [r.get("id") for r in pp.cold_start_findings_rows(ctx, 1)] == ["X-901"])
    os.chmod(live, 0)
    try:
        ids = [r.get("id") for r in pp.cold_start_findings_rows(ctx, 1)]
    finally:
        os.chmod(live, 0o644)
    check("F142 an unreadable LIVE file falls back to the archived list",
          ids == ["X-902"], str(ids))
    write(live, "{ not json")
    ids2 = [r.get("id") for r in pp.cold_start_findings_rows(ctx, 1)]
    check("F142 a corrupt LIVE file falls back to the archived list",
          ids2 == ["X-902"], str(ids2))
    write(live, '{"findings": []}')
    ids3 = [r.get("id") for r in pp.cold_start_findings_rows(ctx, 1)]
    check("F142 a genuinely empty live list still wins over the archive",
          ids3 == [], str(ids3))


# ---------------------------------------------------------------------------
# F145 -- the live prior-review layout reaches prior_round/ under flat names
# ---------------------------------------------------------------------------
def build_round2_root(tmp: Path):
    source = tmp / "source"
    write(source / "ms.md", "title\n")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(source, root / "non_revised")
    pristine = root / "non_revised"
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 2, "judges": 1, "rewrites": [1], "revises": [1],
               "audit": "off", "review_split": "off", "placeholder_lookup": "off",
               "caption_limit": 0, "format_policy": {}, "zotero": "off",
               "vs_original_rule": "median", "cold_start_review": "off",
               "guided_review": "on"}
    ctx.state = {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": pp.hash_manifest(pristine),
                 "original_digest": pp.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     pp.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "jsalt", "config": ctx.cfg, "source": str(source)}
    for rnd in (1, 2):
        rid = pp.rid_a1(rnd)
        shutil.copytree(pristine, root / "runs" / rid / "base")
        ctx.state["runs"][rid] = rec(rid, "a1", rnd)
    # Round 1's review survives only as the LIVE sandbox (no archive), and the
    # discovery deliverable lives under guided_review/round2/.
    r1_review = ctx.register(pp.rid_guided_review(1), "guided_review", 1,
                             f"runs/{pp.rid_guided_review(1)}")
    r1_review["status"] = "done"
    rs = ctx.sandbox_of(r1_review)
    write(rs / pp.GUIDED_REVIEW_DIR / "findings.json", '{"findings": []}')
    write(rs / pp.GUIDED_REVIEW_DIR / "findings.md", "prior findings\n")
    write(rs / pp.GUIDED_REVIEW_DIR / "round2" / "findings_extra.json",
          '{"findings": [{"id": "X-901"}]}')
    pp.write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.save_state()
    return ctx


def test_f145() -> None:
    print("\n== F145 live prior review's nested discovery file is carried ==")
    ctx = build_round2_root(scratch("w2state-f145-"))
    prior = pp.prior_review_dir(ctx, 2)
    check("fixture: prior_review_dir falls back to the live sandbox",
          prior is not None and prior.name == pp.GUIDED_REVIEW_DIR, str(prior))
    sources = pp.prior_round_file_sources(prior)
    check("F145 the nested discovery file is resolved to the flat name",
          sources.get("findings_extra.json") == prior / "round2" / "findings_extra.json",
          str(sources))
    # materialize_review also seeds evidence packs/templates; those are outside
    # this finding's surface, so stub the seeding helpers that would import the
    # formatter and keep this check focused on the carry-over.
    saved = {n: getattr(pp, n) for n in
             ("seed_evidence_pack", "stage_venue_template", "seed_template_visuals",
              "_copy_session_tools")}
    try:
        for name in saved:
            setattr(pp, name, lambda *a, **k: None)
        review = pp.materialize_review(ctx, 2)
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)
    got = ctx.sandbox_of(review) / "prior_round"
    check("F145 prior_round/findings_extra.json exists",
          (got / "findings_extra.json").is_file(),
          str(sorted(p.name for p in got.iterdir()) if got.is_dir() else "missing"))
    check("F145 its bytes are the prior discovery list",
          (got / "findings_extra.json").read_text(encoding="utf-8")
          == (prior / "round2" / "findings_extra.json").read_text(encoding="utf-8"))
    probs = pp._input_freshness_problems(ctx, review)
    check("F145 the materializer and the freshness check agree",
          not [p for p in probs if "prior_round" in p], str(probs))


# ---------------------------------------------------------------------------
def main() -> int:
    for fn in (test_f133, test_f134, test_f135, test_f136, test_f137,
               test_f138, test_f139, test_f140, test_f142, test_f145):
        try:
            fn()
        except Exception as exc:                                   # noqa: BLE001
            check(f"{fn.__name__} (unexpected {type(exc).__name__})", False,
                  str(exc)[:400])
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
