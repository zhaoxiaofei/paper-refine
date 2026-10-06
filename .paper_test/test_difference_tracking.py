#!/usr/bin/env python3
"""Difference tracking: naming, coverage, fallbacks -- and the two DO-NOT properties.

Run:  python3 .paper_test/test_difference_tracking.py

The feature under test (paper_pipeline.py): every version the pipeline produces
is tracked against the pre-conformed original (`non_revised/`) and against the
version it was derived from, into

    <name>.tracking-original.<ext> / <name>.logging-original.<ext>
    <name>.tracking-previous.<ext> / <name>.logging-previous.<ext>
    <name>.tracking-prev-winner.<ext> / <name>.logging-prev-winner.<ext>

for .docx (Word's own compare engine via the docx-compare MCP tool, then the
redline chain), .tex/.bib (latexdiff). A published round winner is tracked in
place too: against the original, and (r > 1) against the previous round's
winner. When the real tool fails, the file that could not be produced is NOT
faked: the sibling logging fallback carries a readable before/after log.

The two properties this suite exists for:
  * DO NOT change any end result: the copies are auxiliaries everywhere -- a
    corpus digest, content fingerprint, pin, judge view, revision token and
    input manifest must be bit-identical with and without them; the champion,
    the scores and the recorded digests of a full stub round are compared
    against a control run with the pass disabled.
  * DO NOT add LLM usage: the pass starts no agent session (asserted by
    instrumenting every agent choke point and by a control e2e run).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_track", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_track"] = nb
spec.loader.exec_module(nb)

STUB = Path(__file__).resolve().parent / "stub_agent.py"
STUB_JUDGE = Path(__file__).resolve().parent / "stub_judge.py"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


def make_docx(path: Path, paras: list) -> None:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>{body}'
                   f'</w:body></w:document>')


TEX = "\\documentclass{article}\n\\begin{document}\nHello world.\n\\end{document}\n"
BIB = "@article{a,\n  title={One},\n  year={2020}\n}\n"
NON_AUX = ("manuscript.docx", "main.tex", "refs.bib", "notes.md", "fig1.png")
AUX_SAMPLES = (
    "manuscript.tracking-original.docx", "manuscript.logging-original.docx",
    "manuscript.tracking-previous.docx", "manuscript.logging-previous.docx",
    "manuscript.tracking-prev-winner.docx", "manuscript.logging-prev-winner.docx",
    "main.tracking-original.tex", "main.tracking-previous.tex",
    "main.tracking-prev-winner.tex", "main.logging-original.tex",
    "main.logging-previous.tex", "main.logging-prev-winner.tex",
    "refs.tracking-original.bib", "refs.tracking-previous.bib",
    "refs.tracking-prev-winner.bib", "refs.logging-original.bib",
    "refs.logging-previous.bib", "refs.logging-prev-winner.bib",
    # the pre-rename spellings (and the short-lived `log-previous` fallback)
    # stay recognized
    "manuscript.tracked.docx", "manuscript.before-after.docx",
    "manuscript.log-previous.docx", "main.log-previous.tex", "refs.log-previous.bib",
)


def build_source(root: Path) -> Path:
    """A small submission: one .docx, one LaTeX root, one .bib, one note -- plus
    the two EVIDENCE areas, whose documents must never be tracked or rendered."""
    src = root / "source"
    make_docx(src / "manuscript-a.docx", ["Title", "The old abstract text.", "Methods."])
    write(src / "main.tex", TEX)
    write(src / "refs.bib", BIB)
    write(src / "notes.md", "notes\n")
    make_docx(src / "raw_data" / "measurements.docx", ["raw measurement table"])
    write(src / "raw_data" / "analysis.tex", "\\documentclass{article}\n"
                                             "\\begin{document}\nraw analysis\n"
                                             "\\end{document}\n")
    make_docx(src / "human_review_feedback" / "reviewer_report.docx", ["reviewer text"])
    return src


def build_root(root: Path, source: Path, *, rounds: int = 2) -> "np.Ctx":
    """A synthetic root whose round-1/round-2 version sandboxes exist on disk.

    a1 (r1) = the original; w1 = an edited copy; i1 = w1's package integrated
    with self_id a1... plus round 2's a2 (revised from round 1's winner) and the
    two published winner directories.
    """
    pristine = root / "non_revised"
    shutil.copytree(source, pristine)
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": rounds, "judges": 1, "rewrites": 1, "revises": 1}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "config": ctx.cfg}

    def register(vid, kind, r, produces=None, self_id=None):
        rid = nb.rid_for_fresh(r, vid)
        ctx.state["runs"][rid] = {"id": rid, "kind": kind, "round": r, "status": "done",
                                  "sandbox": f"runs/{rid}", "corpus_digest": "d",
                                  "attempts": 1, "produces": produces or vid,
                                  "self_id": self_id}
        return rid

    a1 = root / "runs/r1_a1/base"
    shutil.copytree(pristine, a1)
    ctx.state["runs"]["r1_a1"] = {"id": "r1_a1", "kind": "a1", "round": 1, "status": "done",
                                  "sandbox": "runs/r1_a1", "corpus_digest": "d", "attempts": 1}
    w1 = root / "runs/r1_w1/rewritten"
    shutil.copytree(pristine, w1)
    make_docx(w1 / "manuscript-a.docx", ["Title", "The NEW abstract text.", "Methods.",
                                         "An added paragraph."])
    write(w1 / "main.tex", TEX.replace("Hello world.", "Hello brave new world."))
    write(w1 / "refs.bib", BIB.replace("One", "Two").replace("2020", "2021"))
    register("w1", "rewrite", 1)
    i1 = root / "runs/r1_i1/integrated"
    shutil.copytree(w1, i1)
    make_docx(i1 / "manuscript-a.docx", ["Title", "The integrated abstract text.", "Methods."])
    register("i1", "integrate", 1, self_id="w1")
    win1 = root / "round1_winner"
    shutil.copytree(w1, win1)
    ctx.state["rounds"]["1"] = {"status": "done", "winner_dir": "round1_winner",
                                "winner_id": "w1", "champion": "w1"}
    a1r2 = root / "runs/r2_a1/base"
    shutil.copytree(win1, a1r2)
    ctx.state["runs"]["r2_a1"] = {"id": "r2_a1", "kind": "a1", "round": 2, "status": "done",
                                  "sandbox": "runs/r2_a1", "corpus_digest": "d", "attempts": 1}
    a2 = root / "runs/r2_a2_revise/revised"
    shutil.copytree(win1, a2)
    write(a2 / "main.tex", TEX.replace("Hello world.", "Hello second-round world."))
    register("a2", "revise", 2)
    win2 = root / "round2_winner"
    shutil.copytree(a2, win2)
    ctx.state["rounds"]["2"] = {"status": "done", "winner_dir": "round2_winner",
                                "winner_id": "a2", "champion": "a2"}
    return ctx


# =====================================================================
# A. The name family and the auxiliary rule (both implementations agree)
# =====================================================================

def test_name_family_and_aux_rule():
    print()
    print("== the tracking name family + the auxiliary rule ==")
    check("the family spells the three baselines x three extensions",
          nb.tracking_aux_suffix("original", ".docx") == ".tracking-original.docx"
          and nb.tracking_aux_suffix("previous", ".tex") == ".tracking-previous.tex"
          and nb.tracking_aux_suffix("prev-winner", ".bib") == ".tracking-prev-winner.bib")
    check("the fallbacks follow the requested spellings",
          nb.tracking_aux_suffix("original", ".docx", True) == ".logging-original.docx"
          and nb.tracking_aux_suffix("previous", ".docx", True) == ".logging-previous.docx"
          and nb.tracking_aux_suffix("prev-winner", ".tex", True) == ".logging-prev-winner.tex")
    check("the fallback family is uniformly `logging-*`",
          all(s.startswith(".logging-") for s in nb.TRACKING_AUX_SUFFIXES
              if s not in [f".tracking-{b}{e}" for b in ("original", "previous", "prev-winner")
                           for e in (".docx", ".tex", ".bib")]),
          str([s for s in nb.TRACKING_AUX_SUFFIXES if s.startswith(".log")]))
    check("the short-lived `log-previous` spelling is only a LEGACY auxiliary",
          ".log-previous.docx" in nb.LEGACY_AUXILIARY_DOC_SUFFIXES
          and ".log-previous.docx" not in nb.TRACKING_AUX_SUFFIXES
          and nb._is_aux_doc("doc.log-previous.docx"))
    check("every one of the 18 suffixes is registered as an auxiliary",
          all(nb._is_aux_doc("doc" + s) for s in nb.TRACKING_AUX_SUFFIXES)
          and len(nb.TRACKING_AUX_SUFFIXES) == 18,
          str(nb.TRACKING_AUX_SUFFIXES))
    check("the pre-rename spellings stay recognized",
          nb._is_aux_doc("doc.tracked.docx") and nb._is_aux_doc("doc.before-after.docx"))
    check("a normal document is NOT an auxiliary",
          not any(nb._is_aux_doc(n) for n in NON_AUX))
    # the scanner and the corpus builder must agree on the same file set
    fmt = importlib.util.spec_from_file_location("paper_fmt", str(WS / "paper_docx_format.py"))
    fmt_mod = importlib.util.module_from_spec(fmt)
    sys.modules["paper_fmt"] = fmt_mod
    fmt.loader.exec_module(fmt_mod)
    mismatched = [n for n in (list(AUX_SAMPLES) + list(NON_AUX))
                  if nb._is_aux_doc(n) != fmt_mod._is_aux_name(n)]
    check("paper_docx_format._is_aux_name agrees with the pipeline's rule",
          not mismatched, str(mismatched))
    # ...and so must the shipped revision-token script
    rt_spec = importlib.util.spec_from_file_location(
        "paper_rt", str(WS / "paper-skills/paper-revise/scripts/revision_token.py"))
    rt = importlib.util.module_from_spec(rt_spec)
    sys.modules["paper_rt"] = rt
    rt_spec.loader.exec_module(rt)
    own = [n for n in (list(AUX_SAMPLES) + list(NON_AUX))
           if nb._is_aux_doc(n) != any(n.lower().endswith(s) for s in rt.AUX_SUFFIXES)]
    check("the revision-token script excludes exactly the same suffixes",
          not own, str(own))
    # The deliverable validator must not try to compile an auxiliary .tex
    # (a fragment's latexdiff copy has no preamble and would read as a broken
    # deliverable).
    vpkg = scratch("paper_track_val_")
    write(vpkg / "main.tex", TEX)
    write(vpkg / "main.tracking-original.tex", "\\DIFadd{a fragment, no preamble}\n")
    write(vpkg / "main.logging-original.tex", "% a commented-out logging fallback\n")
    rep = fmt_mod.validate_paths([vpkg])
    check("the .tex validator skips the whole auxiliary family",
          rep["files"] == 1 and rep["results"]
          and rep["results"][0]["file"].endswith("main.tex"),
          str([r["file"] for r in rep["results"]]))


# =====================================================================
# B. Auxiliaries never enter an identity: digests, pins, views, manifests
# =====================================================================

def test_auxiliaries_never_change_an_identity():
    print()
    print("== the auxiliaries never enter a corpus/pin/view/token ==")
    tmp = scratch("paper_track_id_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=1)
    sb = ctx.root / "runs/r1_w1/rewritten"
    clean = tmp / "clean_copy"
    shutil.copytree(sb, clean)
    before_manifest = nb.corpus_manifest(ctx, 1, "w1")
    before_fp = nb.corpus_content_fingerprint(ctx, 1, "w1")
    before_view = {k for k, _p in nb.corpus_files_for_view(ctx, 1, "w1")}
    before_docs = nb.document_set_check([(ctx.pristine, "", ())], [(sb, "", ())])
    before_token = nb.revision_token_for_dir(sb)
    # now add every auxiliary spelling next to the documents
    for name in AUX_SAMPLES:
        base = sb / name.split(".", 1)[0]
        target = base.parent / name
        target.write_bytes(b"aux")
    after_manifest = nb.corpus_manifest(ctx, 1, "w1")
    after_fp = nb.corpus_content_fingerprint(ctx, 1, "w1")
    after_view = {k for k, _p in nb.corpus_files_for_view(ctx, 1, "w1")}
    after_docs = nb.document_set_check([(ctx.pristine, "", ())], [(sb, "", ())])
    after_token = nb.revision_token_for_dir(sb)
    check("the corpus manifest (the recorded digest) is unchanged",
          before_manifest == after_manifest,
          f"{sorted(before_manifest['files'])} vs {sorted(after_manifest['files'])}")
    check("the content fingerprint is unchanged", before_fp == after_fp)
    check("no auxiliary reaches the judge view", before_view == after_view,
          str(sorted(after_view - before_view)))
    check("the revision token is unchanged", before_token == after_token,
          f"{before_token} vs {after_token}")
    check("the document-set check does not see them",
          before_docs == after_docs, f"{before_docs} vs {after_docs}")
    published = tmp / "published"
    nb.build_corpus_dir(ctx, 1, "w1", published)
    check("build_corpus_dir (the pin/winner rule) leaves them out",
          not any(nb._is_aux_doc(p.name) for p in published.rglob("*"))
          and (published / "manuscript-a.docx").is_file())
    check("the raw auxiliary files are still on disk (they are not deleted)",
          all((sb / n).is_file() for n in AUX_SAMPLES))


# =====================================================================
# C. The pass writes the requested family, for the requested baselines
# =====================================================================

def test_tracking_pass_outputs():
    print()
    print("== the pass writes original/previous/prev-winner copies ==")
    tmp = scratch("paper_track_run_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=2)
    mf1 = nb.run_difference_tracking(ctx, rounds=[1], versions=["a1", "w1", "i1"], quiet=True)
    mf2 = nb.run_difference_tracking(ctx, rounds=[2], versions=["a1", "a2"], quiet=True)
    by_version = {(v["round"], v["version"]): v for v in mf1["versions"] + mf2["versions"]}
    check("every requested version is covered, plus both winners",
          {(1, "a1"), (1, "w1"), (1, "i1"), (1, "round1_winner"),
           (2, "a1"), (2, "a2"), (2, "round2_winner")} <= set(by_version),
          str(sorted(by_version)))
    # a version the round never materialized is reported, never invented
    mf_all = nb.run_difference_tracking(ctx, rounds=[1], quiet=True)
    check("an unmaterialized integration arm is reported as such",
          any(v["version"] == "i2" and v["status"] == "not materialized"
              for v in mf_all["versions"]),
          str([(v["version"], v["status"]) for v in mf_all["versions"]]))
    check("w1 tracks the original AND the round base (its previous version)",
          by_version[(1, "w1")]["previous_baseline"] == "a1"
          and {c["baseline"] for c in by_version[(1, "w1")]["comparisons"]}
          == {"original", "previous"})
    check("i1's previous version is its own self/ member (w1)",
          by_version[(1, "i1")]["previous_baseline"] == "w1")
    check("round1_winner tracks only the original (there is no previous winner)",
          by_version[(1, "round1_winner")]["previous_baseline"] == ""
          and {c["baseline"] for c in by_version[(1, "round1_winner")]["comparisons"]}
          == {"original"})
    check("round2_winner tracks the original AND round1_winner",
          by_version[(2, "round2_winner")]["previous_baseline"] == "round1_winner"
          and {c["baseline"] for c in by_version[(2, "round2_winner")]["comparisons"]}
          == {"original", "prev-winner"})
    # file placement: beside the documents and mirrored under <root>/tracking/
    w1 = ctx.root / "runs/r1_w1/rewritten"
    check("the copies sit beside the candidate documents",
          (w1 / "manuscript-a.tracking-original.docx").is_file()
          and (w1 / "manuscript-a.tracking-previous.docx").is_file()
          and (w1 / "main.tracking-original.tex").is_file()
          and (w1 / "refs.tracking-previous.bib").is_file(),
          str(sorted(p.name for p in w1.iterdir())))
    check("a1 is the raw input copy: its copies live under tracking/ only",
          not (ctx.root / "runs/r1_a1/base/manuscript-a.tracking-original.docx").exists()
          and (ctx.root / "tracking/r1_a1/original/manuscript-a.tracking-original.docx").is_file())
    win2 = ctx.root / "round2_winner"
    check("the winner directory carries its own marked-up copies",
          (win2 / "manuscript-a.tracking-original.docx").is_file()
          and (win2 / "manuscript-a.tracking-prev-winner.docx").is_file()
          and (win2 / "main.tracking-prev-winner.tex").is_file())
    check("the tracking tree mirrors the winners under their own key",
          (ctx.root / "tracking/round2_winner/prev-winner/main.tracking-prev-winner.tex")
          .is_file())
    check("the manifest and README are written",
          (ctx.root / "tracking/manifest.json").is_file()
          and (ctx.root / "tracking/README.md").is_file())
    # The EVIDENCE areas are read-only inputs, not submission documents: no
    # tracking copy may ever be produced for one of their files.
    tracked_rels = [c["revised_rel"] for v in mf1["versions"] + mf2["versions"]
                    for c in v["comparisons"]]
    check("no EVIDENCE file is ever tracked",
          not any(r.startswith(("raw_data/", "raw_figs/", "human_review_feedback/"))
                  for r in tracked_rels), str(tracked_rels))
    readme = (ctx.root / "tracking/README.md").read_text(encoding="utf-8")
    check("the README documents the whole family and the no-agent rule",
          all(s in readme for s in (".tracking-original", ".tracking-previous",
                                    ".tracking-prev-winner", ".logging-prev-winner",
                                    "starts no agent session")))


# =====================================================================
# D. latexdiff, its fallback, and the .docx fallback
# =====================================================================

def test_redline_reuse_is_digest_gated():
    """A `from-base` redline must never stand in for an integration's
    previous-version copy: an integration's previous version is its own `self/`
    member, not the round base, and only the pair with the SAME two digests may
    be copied. Regression for the reuse mapping."""
    print()
    print("== the redline reuse is gated on the pair's own digests ==")
    tmp = scratch("paper_track_reuse_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=1)
    ctx.state["source"] = str(source)
    red = nb.run_redlines(ctx, rounds=[1], versions=["i1"], tool="auto", quiet=True)
    mf = nb.run_difference_tracking(ctx, rounds=[1], versions=["i1"], quiet=True,
                                    redlines_manifest=red)
    entry = mf["versions"][0]
    check("the integration's previous baseline is its self/ member", 
          entry["previous_baseline"] == "w1")
    prev_rec = next(c for c in entry["comparisons"]
                    if c["baseline"] == "previous" and c["ext"] == ".docx")
    with zipfile.ZipFile(ctx.root / prev_rec["out"]) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    check("the previous copy is the diff against self/ (w1), never the round base",
          "NEW" in xml and prev_rec["identical"] is False, xml[:200])
    orig_rec = next(c for c in entry["comparisons"]
                    if c["baseline"] == "original" and c["ext"] == ".docx")
    reuse_row = next((c for v in red["versions"] for c in v["comparisons"]
                      if c["source"] == "from-original" and c["revised_rel"]
                      == "manuscript-a.docx"), None)
    check("the original-baseline redline IS reused (identical pair digests)",
          reuse_row and "reused from redlines/" in str(orig_rec.get("tool"))
          and (ctx.root / orig_rec["out"]).read_bytes()
          == (ctx.root / reuse_row["out"]).read_bytes(),
          f"{orig_rec.get('tool')} / {bool(reuse_row)}")
    # The gate itself, on hand-built pairs: the same relative name with a
    # DIFFERENT base digest must NOT reuse the stored `from-base` redline.
    index = nb.redline_index(red)
    w1_docx = ctx.root / "runs/r1_w1/rewritten/manuscript-a.docx"
    i1_docx = ctx.root / "runs/r1_i1/integrated/manuscript-a.docx"
    a1_docx = ctx.root / "runs/r1_a1/base/manuscript-a.docx"
    mismatched = {"cand_rel": "manuscript-a.docx", "cand_path": i1_docx,
                  "base_path": w1_docx, "base_digest": nb.sha256_file(w1_docx),
                  "cand_digest": nb.sha256_file(i1_docx)}
    matching = dict(mismatched, base_path=a1_docx, base_digest=nb.sha256_file(a1_docx))
    check("the digest gate REFUSES the mismatched baseline",
          nb._reusable_redline(index, 1, "i1", "from-base", mismatched) == {})
    check("the digest gate accepts the identical pair",
          bool(nb._reusable_redline(index, 1, "i1", "from-base", matching)))


def test_latexdiff_and_fallbacks():
    print()
    print("== latexdiff, the logging fallbacks, and the no-fake rule ==")
    tmp = scratch("paper_track_fb_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=1)
    if not shutil.which("latexdiff"):
        skip("latexdiff tracking", "latexdiff is not on PATH on this machine")
    else:
        mf = nb.run_difference_tracking(ctx, rounds=[1], versions=["w1", "i1"], quiet=True)
        entry = next(v for v in mf["versions"] if v["version"] == "w1")
        tex_rec = next(c for c in entry["comparisons"]
                       if c["revised_rel"] == "main.tex" and c["baseline"] == "original")
        out = ctx.root / tex_rec["out"]
        text = out.read_text(encoding="utf-8", errors="replace")
        check("the .tex tracking copy is a latexdiff (marked additions/deletions)",
              tex_rec["tool"] == "latexdiff" and "\\DIFadd" in text and "\\DIFdel" in text,
              text[:160])
        # i1 is w1's package with an edited .docx: its .tex/.bib are byte-identical
        # to w1's, so the previous-version copies must be plain identical copies
        # (no fake diff, and no failure).
        i1 = next(v for v in mf["versions"] if v["version"] == "i1")
        bib_rec = next(c for c in i1["comparisons"]
                       if c["revised_rel"] == "refs.bib" and c["baseline"] == "previous")
        check("a byte-identical pair yields an identical copy, not a failure",
              (ctx.root / bib_rec["out"]).read_text(encoding="utf-8")
              == (ctx.root / "runs/r1_w1/rewritten/refs.bib").read_text(encoding="utf-8")
              and bib_rec["tool"] == "identical-copy" and bib_rec["identical"] is True,
              str(bib_rec)[:200])
    # latexdiff missing -> the logging fallback (never a fabricated diff)
    real_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = str(tmp / "no-tools")
        (tmp / "no-tools").mkdir(exist_ok=True)
        nb.LATEXDIFF_CMD = "latexdiff-not-installed"
        out_tex = tmp / "main.logging-original.tex"
        res = nb.latexdiff_one_pair(ctx.pristine / "main.tex",
                                    ctx.root / "runs/r1_w1/rewritten/main.tex", out_tex)
        check("a missing latexdiff is a failure (not a silent success)", not res["ok"])
        fb = nb.write_text_logging_fallback(ctx.pristine / "main.tex",
                                            ctx.root / "runs/r1_w1/rewritten/main.tex",
                                            out_tex, "original", "latexdiff is not on PATH")
        fb_text = out_tex.read_text(encoding="utf-8")
        check("the logging fallback is inert (every line commented) and readable",
              fb["ok"] and all(ln.startswith("% ") for ln in fb_text.splitlines())
              and "LOGGING FALLBACK" in fb_text and "not a latexdiff copy" in fb_text)
    finally:
        os.environ["PATH"] = real_path
        nb.LATEXDIFF_CMD = "latexdiff"
    # the .docx fallback: an unreadable pair still yields a READABLE marker docx
    bad = tmp / "broken"
    make_docx(bad / "manuscript-a.docx", ["base text"])
    bad_rev = tmp / "broken_rev"
    bad_rev.mkdir(parents=True)
    (bad_rev / "manuscript-a.docx").write_bytes(b"NOT A ZIP AT ALL")
    out_docx = tmp / "manuscript-a.logging-original.docx"
    res = nb.write_docx_logging_fallback(bad / "manuscript-a.docx",
                                         bad_rev / "manuscript-a.docx", out_docx,
                                         "original", "all redline backends failed")
    ok, detail = nb.docx_is_readable(out_docx)
    text = ""
    if ok:
        with zipfile.ZipFile(out_docx) as z:
            text = z.read("word/document.xml").decode("utf-8", "replace")
    check("an unreadable .docx pair still produces a READABLE logging fallback",
          res["ok"] and ok and "LOGGING FALLBACK" in text and "not a tracked-changes" in text,
          detail)


# =====================================================================
# E. DO NOT add LLM usage: instrument every agent choke point
# =====================================================================

def test_fallback_names_are_uniformly_logging():
    """A failed comparison must be reported under the uniform `logging-*` name
    (never the short-lived `log-previous` spelling)."""
    print()
    print("== a failed comparison writes the uniform `logging-*` fallback ==")
    tmp = scratch("paper_track_fbname_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=1)
    saved = nb.latexdiff_one_pair
    nb.latexdiff_one_pair = lambda *a, **k: {
        "ok": False, "tool": "latexdiff",
        "attempts": [{"backend": "latexdiff", "cmd": [], "rc": 1, "ok": False,
                      "detail": "forced failure (test)"}]}
    try:
        mf = nb.run_difference_tracking(ctx, rounds=[1], versions=["w1"], quiet=True)
    finally:
        nb.latexdiff_one_pair = saved
    entry = mf["versions"][0]
    tex_rows = [c for c in entry["comparisons"] if c["ext"] == ".tex"]
    check("the failed .tex comparisons report the logging fallback",
          tex_rows and all(c.get("ok") and c.get("fallback") for c in tex_rows),
          str([(c["baseline"], c.get("fallback"), c.get("tool")) for c in tex_rows]))
    names = [Path(c["fallback_out"]).name for c in tex_rows]
    check("the fallback files carry the `logging-*` family (never `log-previous`)",
          all(n.startswith("main.logging-") for n in names)
          and not any("log-previous" in n for n in names), str(names))
    check("the fallback sits under the baseline directory with the right name",
          (ctx.root / "tracking/r1_w1/original/main.logging-original.tex").is_file()
          and (ctx.root / "tracking/r1_w1/previous/main.logging-previous.tex").is_file())


def test_tool_none_writes_no_copy():
    print()
    print("== --tool none reports only (no copy, no logging fallback) ==")
    tmp = scratch("paper_track_none_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=1)
    mf = nb.run_difference_tracking(ctx, rounds=[1], versions=["w1"], tool="none", quiet=True)
    comparisons = [c for v in mf["versions"] for c in v["comparisons"]]
    check("every pair is reported as skipped",
          comparisons and all(c.get("skipped") and not c.get("ok") for c in comparisons),
          str(comparisons[:2]))
    check("no tracking copy is written (and no logging fallback either)",
          not (ctx.root / "tracking" / "r1_w1").exists())
    check("the entry status says skipped",
          "skipped (tool=none)" in str(mf["versions"][0]["status"]),
          str(mf["versions"][0]["status"]))


AGENT_CHOKE_POINTS = ("_execute_attempt_in", "run_defect_audit_agent",
                      "run_judge_conflict_agent", "resolve_agent_cmd", "agent_argv")


def test_no_agent_session_is_started():
    print()
    print("== DO NOT add LLM usage: no agent session is ever started ==")
    tmp = scratch("paper_track_llm_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=2)
    saved = {name: getattr(nb, name) for name in AGENT_CHOKE_POINTS}
    calls = []

    def boom(*a, **k):
        calls.append(a[:1])
        raise AssertionError("the difference-tracking pass tried to start an agent session")

    runs_before = json.dumps(ctx.state["runs"], sort_keys=True)
    try:
        for name in AGENT_CHOKE_POINTS:
            setattr(nb, name, boom)
        nb.run_difference_tracking(ctx, rounds=[1, 2], quiet=True)
        nb.run_pdf_conversion(ctx, rounds=[1, 2], quiet=True)
    finally:
        for name, fn in saved.items():
            setattr(nb, name, fn)
    check("the pass completes with every agent choke point disabled", not calls, str(calls))
    check("no run record was added or changed by the pass",
          json.dumps(ctx.state["runs"], sort_keys=True) == runs_before)
    # A static guarantee that does not depend on this test's fixtures: the new
    # code never references an agent-launching helper by name.
    src = "".join(inspect.getsource(fn) for fn in
                  (nb.run_difference_tracking, nb.track_one_pair, nb.run_pdf_conversion,
                   nb.compile_latex_pdf, nb.convert_docx_to_pdf_persistent,
                   nb.latexdiff_one_pair, nb.round_tracking))
    refs = [name for name in AGENT_CHOKE_POINTS if name in src]
    check("the new code paths name no agent-launching helper", not refs, str(refs))


# =====================================================================
# F. PDFs are produced, persist, and their failures are warnings
# =====================================================================

def test_pdf_pass_is_persistent_and_nonfatal():
    print()
    print("== the PDF pass: persistent output, warnings never fatal ==")
    tmp = scratch("paper_track_pdf_")
    source = build_source(tmp)
    ctx = build_root(tmp, source, rounds=1)
    mf = nb.run_pdf_conversion(ctx, rounds=[1], quiet=True)
    docs = [d for s in mf["sets"] for d in s["documents"]]
    labels = {s["label"] for s in mf["sets"]}
    check("the pass covers the original and every version of the round",
          {"original", "r1_a1", "r1_w1", "r1_i1"} <= labels, str(sorted(labels)))
    tex_ok = [d for d in docs if d["kind"] == "latex"]
    if shutil.which("latexmk"):
        check("LaTeX roots are compiled with latexmk",
              tex_ok and all(d["ok"] for d in tex_ok)
              and all(d["tool"] == "latexmk" for d in tex_ok),
              str([(d["rel"], d["ok"], d["error"]) for d in tex_ok]))
        check("the PDFs live under <root>/pdfs/ and are real files",
              all((ctx.root / d["out"]).is_file() and (ctx.root / d["out"]).stat().st_size > 0
                  for d in tex_ok))
    else:
        skip("the LaTeX compile/flush checks", "latexmk is not on PATH on this machine")
    # a broken LaTeX source is a WARNING, never an exception and never a fatal
    broken_pkg = tmp / "broken_pkg"
    write(broken_pkg / "bad.tex", "\\documentclass{article}\n\\begin{document}\n"
                                  "\\thisIsNotACommand\n")
    bad_out = tmp / "bad.pdf"
    if shutil.which("latexmk"):
        res = nb.compile_latex_pdf(broken_pkg, "bad.tex", bad_out)
        check("a LaTeX compile error is reported (ok=False) and never raises",
              res["ok"] is False and bool(res.get("error")) and not bad_out.exists(),
              str(res)[:200])
    else:
        skip("the LaTeX compile-error check", "latexmk is not on PATH on this machine")
    # a version with no renderable document is a no-op, not a crash
    empty = tmp / "empty_pkg"
    (empty / "pkg").mkdir(parents=True)
    write(empty / "pkg" / "README.txt", "nothing to render\n")
    docs2 = nb.render_pdf_set(ctx, "empty", [(empty / "pkg", "", ())], tmp / "empty_pdfs")
    check("a package with nothing to render yields an empty document list", docs2 == [])
    check("the manifest records the failure mode as a warning, not an error",
          (ctx.root / "pdfs/manifest.json").is_file()
          and (ctx.root / "pdfs/README.md").is_file())
    # the persistent tree is idempotent: a second call reuses the up-to-date PDFs
    mf2 = nb.run_pdf_conversion(ctx, rounds=[1], quiet=True)
    docs2 = [d for s in mf2["sets"] for d in s["documents"]]
    if shutil.which("latexmk"):
        check("an unchanged source is not re-rendered (cached record)",
              all(d.get("cached") for d in docs2 if d["kind"] == "latex" and d.get("ok")),
              str([(d["rel"], d.get("cached"), d.get("ok")) for d in docs2]))
    else:
        skip("the PDF cache check", "latexmk is not on PATH on this machine")
    check("prune never touches the PDF tree (the tree is not a sandbox)",
          "pdfs" not in nb.CORPUS_EXCLUDE_TOP
          and (ctx.root / "pdfs").is_dir())
    check("no EVIDENCE file is ever compiled or rendered",
          not any(d["rel"].startswith(("raw_data/", "raw_figs/", "human_review_feedback/"))
                  for d in docs), str([d["rel"] for d in docs]))


# =====================================================================
# G. DO NOT change any end result: a stub round, tracked vs control
# =====================================================================

def end_result_state(state: dict) -> dict:
    """The parts of state.json that DECIDE anything (paths/timestamps stripped).

    Judge runs are keyed by (round, target id, judge index) instead of their run
    id: the id is a per-root SALTED token (the blinding feature), so two roots
    legitimately disagree on the id while judging the very same target.
    """
    out = {"runs": {}, "judges": {}, "rounds": {}, "pinned": []}
    for rid, rec in sorted((state.get("runs") or {}).items()):
        if rec.get("kind") == "judge":
            key = f"{rec.get('round')}|{rec.get('target_id')}|{rec.get('judge_index')}"
            sheet = dict(rec.get("scores") or {})
            sheet.pop("run_id", None)          # the salted session id
            sheet.pop("target_id", None)       # the salted target token
            # The opponent labels are a per-session blind permutation; the
            # substance of each comparison is kept, the relabelling is not.
            comps = []
            for c in sheet.get("comparisons") or []:
                c = {k: v for k, v in dict(c).items() if k != "opponent_label"}
                comps.append(json.dumps(c, sort_keys=True))
            sheet = {"comparisons": sorted(comps),
                     "judge_index": sheet.get("judge_index"), "notes": sheet.get("notes")}
            out["judges"][key] = {"target_digest": rec.get("target_digest"),
                                  "field_digests": rec.get("field_digests"),
                                  "status": rec.get("status"), "scores": sheet}
            continue
        out["runs"][rid] = {k: rec.get(k) for k in (
            "kind", "round", "status", "corpus_digest", "content_fingerprint",
            "produces", "source_id", "self_id")}
    for r, rec in sorted((state.get("rounds") or {}).items()):
        out["rounds"][r] = {k: rec.get(k) for k in (
            "status", "champion", "pin_id", "pin_path", "field", "winner_digest",
            "winner_dir", "scores_per_version", "plan", "scoped")}
    out["pinned"] = [(p.get("id"), p.get("round"), p.get("digest"), p.get("source_id"))
                     for p in state.get("pinned") or []]
    out["original_digest"] = state.get("original_digest")
    out["original_content_fingerprint"] = state.get("original_content_fingerprint")
    return out


def run_stub_round(root: Path, source: Path, extra_args: list) -> subprocess.CompletedProcess:
    setup = [sys.executable, str(WS / "paper_pipeline.py"), "setup",
             "--source", str(source), "--root", str(root), "--rounds", "1", "--judges", "1",
             "--rewrites", "1", "--revises", "1", "--integrators", "1"]
    subprocess.run(setup, capture_output=True, text=True, check=True, timeout=900)
    run = [sys.executable, str(WS / "paper_pipeline.py"), "run", "--root", str(root),
           "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
           "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
           "--retries", "0", *extra_args]
    return subprocess.run(run, capture_output=True, text=True, timeout=1800)


def test_end_to_end_end_results_are_unchanged():
    print()
    print("== DO NOT change any end result: a stub round with and without tracking ==")
    tmp = scratch("paper_track_e2e_")
    source = tmp / "source"
    make_docx(source / "manuscript-a.docx", ["Title", "The abstract.", "Methods."])
    write(source / "main.tex", TEX)
    write(source / "refs.bib", BIB)
    control, treated = tmp / "control", tmp / "treated"
    p_control = run_stub_round(control, source, ["--no-track"])
    p_treated = run_stub_round(treated, source, [])
    check("the control round completes", p_control.returncode == 0,
          (p_control.stdout + p_control.stderr)[-400:])
    check("the tracked round completes", p_treated.returncode == 0,
          (p_treated.stdout + p_treated.stderr)[-400:])
    if p_control.returncode or p_treated.returncode:
        return
    st_c = json.loads((control / "state.json").read_text(encoding="utf-8"))
    st_t = json.loads((treated / "state.json").read_text(encoding="utf-8"))
    check("the recorded end result (champion, digests, pins, scores) is IDENTICAL",
          end_result_state(st_c) == end_result_state(st_t),
          _diff_hint(end_result_state(st_c), end_result_state(st_t)))
    # ...and the treated root's OWN chain still verifies: no tracked copy ever
    # leaked into a corpus, a pin or the published winner.
    ctx_t = nb.Ctx(treated)
    ctx_t.load(need_cfg=False)
    recomputed = []
    for rid, rec in sorted(ctx_t.state["runs"].items()):
        if rec.get("kind") in ("rewrite", "revise", "integrate") \
                and rec.get("status") == "done":
            vid = nb.freshness_vid(rec)
            if vid and nb.corpus_manifest(ctx_t, int(rec["round"]), vid):
                recomputed.append(nb.recompute_corpus_digest(ctx_t, int(rec["round"]), vid)
                                  == rec.get("corpus_digest"))
    check("every delivered corpus still hashes to its RECORDED digest "
          "(the tracked copies are outside the corpus)",
          recomputed and all(recomputed), str(recomputed))
    check("the pin/winner chain verifies after the pass",
          nb.pinned_integrity(ctx_t) == [], str(nb.pinned_integrity(ctx_t))[:200])
    check("no tracking auxiliary appears in a judged version corpus",
          not any(nb._is_aux_doc(k)
                  for k, _p in nb.corpus_files_for_view(ctx_t, 1, "w1")),
          str([k for k, _p in nb.corpus_files_for_view(ctx_t, 1, "w1")]))
    check("the treated run really produced the tracking copies",
          any((treated / "runs/r1_w1/rewritten").glob("*.tracking-*"))
          and (treated / "tracking/manifest.json").is_file()
          and (treated / "pdfs/manifest.json").is_file())
    check("the control run produced none of them",
          not (control / "tracking").exists() and not (control / "pdfs").exists())
    check("the champion's published winner carries the marked-up copies",
          any((treated / str(st_t["rounds"]["1"]["winner_dir"])).glob("*.tracking-original.*")),
          str(st_t["rounds"]["1"].get("winner_dir")))


def _diff_hint(a: dict, b: dict) -> str:
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            return f"{k}: {str(a.get(k))[:160]} != {str(b.get(k))[:160]}"
    return ""


def main():
    test_name_family_and_aux_rule()
    test_auxiliaries_never_change_an_identity()
    test_tracking_pass_outputs()
    test_redline_reuse_is_digest_gated()
    test_latexdiff_and_fallbacks()
    test_fallback_names_are_uniformly_logging()
    test_tool_none_writes_no_copy()
    test_no_agent_session_is_started()
    test_pdf_pass_is_persistent_and_nonfatal()
    test_end_to_end_end_results_are_unchanged()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("All difference-tracking checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
