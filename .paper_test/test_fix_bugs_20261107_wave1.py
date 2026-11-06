#!/usr/bin/env python3
"""Regression checks for the 2026-11-07 fix-bugs wave 1 (F-* candidates).

Each check pins one candidate this wave re-validated on the tree and repaired.
Hermetic: every fixture lives under tempfile.mkdtemp(); the shell checks use a
private HOME/MCP_TOOLS_DIR and stub binaries.

Run:  python3 .paper_test/test_fix_bugs_20261107_wave1.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1107wave1_pp", "paper_pipeline.py")
fmt = load("fb1107wave1_fmt", "paper_docx_format.py")
pw = load("fb1107wave1_pw", "pairwise_scores.py")
cw = load("fb1107wave1_cw", "paper-skills/paper-review/scripts/count_words.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# F008/F009/F084/F085 -- the two M19 word counters agree and count prose only
# ---------------------------------------------------------------------------
def test_word_counters() -> None:
    print("\n== F008/F009/F084/F085: the LaTeX prose readers ==")
    corpus = [
        (r"a \nocite{x} b", 2, "F008 biblatex-prefixed citation (\\nocite)"),
        (r"a \autocite{x} b", 2, "F008 biblatex-prefixed citation (\\autocite)"),
        (r"a \parencite{x} b", 2, "F008 biblatex-prefixed citation (\\parencite)"),
        (r"a \textcite{x} b", 2, "F008 biblatex-prefixed citation (\\textcite)"),
        (r"a \footcite{x} b", 2, "F008 biblatex-prefixed citation (\\footcite)"),
        (r"a \Cite{x} b", 2, "F009 capitalized natbib (\\Cite)"),
        (r"a \Citet{x} b", 2, "F009 capitalized natbib (\\Citet)"),
        (r"a \Citep{x} b", 2, "F009 capitalized natbib (\\Citep)"),
        (r"a \verb|x y| b", 2, "F084 inline \\verb body is code, not prose"),
        (r"a \verb!x y! b", 2, "F084 inline \\verb with a ! delimiter"),
        (r"a \lstinline{x y} b", 2, "F084 inline \\lstinline body is code"),
        (r"a \lstinline[language=TeX]{x y} b", 2, "F084 \\lstinline with options"),
        (r"a \textcolor{red}{word} b", 3, "F085 a colour name is not a word"),
        (r"a \colorbox{red}{word} b", 3, "F085 a colourbox colour is not a word"),
        (r"a \includegraphics[width=3cm]{fig1} b", 2,
         "F085 a graphics file name is not a word"),
    ]
    for text, want, label in corpus:
        pipe = pp.count_words(pp._strip_latex(text))
        skill = cw.count_words(cw._strip_latex(text))
        check(f"{label}: pipeline counts {want}", pipe == want,
              f"{pipe} <- {pp._strip_latex(text)!r}")
        check(f"{label}: the skill counts {want}", skill == want,
              f"{skill} <- {cw._strip_latex(text)!r}")
    # The two implementations must stay in step: a manuscript the orchestrator
    # measures and one the agent measures can never be one word apart.
    for text, _want, _label in corpus:
        check("F008 the pipeline and the skill strip identically",
              pp._strip_latex(text) == cw._strip_latex(text),
              f"{pp._strip_latex(text)!r} vs {cw._strip_latex(text)!r}")
    # Prose and the visible text argument survive.
    visible = pp._strip_latex(r"a \textcolor{red}{word} b")
    check("F085 the visible \\textcolor argument survives", "word" in visible, repr(visible))
    # The escaped percent is not a comment (a regression in this area would
    # silently truncate every line carrying a percentage).
    check("F084 a 50\\% literal stays prose",
          pp.count_words(pp._strip_latex(r"a 50\% rise b")) == 4,
          repr(pp._strip_latex(r"a 50\% rise b")))


# ---------------------------------------------------------------------------
# F082/F083/F093 -- the PKG-12 p/CI scan reads the cells and the live caption
# ---------------------------------------------------------------------------
def _mcb_package(tmp: Path, caption: str, row: str) -> Path:
    pkg = tmp / "pkg"
    write(pkg / "mcb_table.tex",
          "\\documentclass{article}\n\\begin{document}\n"
          "\\begin{table}\n" + caption + "\n\\begin{tabular}{lllll}\n"
          + row + " \\\\\n\\end{tabular}\n\\end{table}\n\\end{document}\n")
    return pkg


def test_pkg12_cells() -> None:
    print("\n== F082/F083/F093: the PKG-12 p-value / CI scan ==")
    check("F082 a qualifier after the p value is not a parse failure",
          pp._parse_p("0.03 (two-sided)") == 0.03, repr(pp._parse_p("0.03 (two-sided)")))
    check("F082 a LaTeX superscript after the p value is not a parse failure",
          pp._parse_p(r"0.03\textsuperscript{*}") == 0.03,
          repr(pp._parse_p(r"0.03\textsuperscript{*}")))
    check("F082 a cell with no number at all is still unparsed",
          pp._parse_p("NS") is None, repr(pp._parse_p("NS")))
    for cell, want in (("(0.1, 0.5)", (0.1, 0.5)),
                       ("[1e-3, 0.5]", (0.001, 0.5)),
                       ("0.1-0.5", (0.1, 0.5)),
                       ("[0.1, 0.5)", (0.1, 0.5))):
        check(f"F083 the CI cell {cell!r} parses", pp._parse_ci(cell) == want,
              repr(pp._parse_ci(cell)))
    caption = ("\\caption{Small p and an interval entirely below 0 mark a "
               "significant difference.}")
    # The p cell carries a footnote/qualifier: it must still be compared.
    tmp = scratch("fb1107_pkg12_p_")
    pkg = _mcb_package(tmp, caption, "G1 & 10 & 0.03 (two-sided) & 1 & [-0.2, 0.5]")
    rows = [r for r in pp.scan_mcb_rule_conflicts(pkg) if r.get("rule") == "PKG-12"]
    check("F082 a qualified p cell still yields the p/CI contradiction row",
          len(rows) == 1, json.dumps(rows)[:300])
    # The CI uses parentheses: it must still be compared.
    tmp = scratch("fb1107_pkg12_ci_")
    pkg = _mcb_package(tmp, caption, "G1 & 10 & 0.9 & 1 & (0.1, 0.5)")
    rows = [r for r in pp.scan_mcb_rule_conflicts(pkg) if r.get("rule") == "PKG-12"]
    check("F083 a parenthesised CI still yields the p/CI contradiction row",
          len(rows) == 1, json.dumps(rows)[:300])
    # A commented-out old caption must not turn a clean table into a checked one.
    tmp = scratch("fb1107_pkg12_comment_")
    pkg = _mcb_package(
        tmp,
        "% \\caption{small p and an interval entirely below 0}\n"
        "\\caption{Unrelated table of annotations.}",
        "G1 & 10 & 0.03 & 1 & [-0.2, 0.5]")
    rows = [r for r in pp.scan_mcb_rule_conflicts(pkg) if r.get("rule") == "PKG-12"]
    check("F093 a commented-out caption does not activate the scan", rows == [],
          json.dumps(rows)[:300])
    check("F093 the commented caption body is not returned",
          pp._latex_command_bodies("% \\caption{old}", "caption") == [],
          repr(pp._latex_command_bodies("% \\caption{old}", "caption")))
    check("F093 a live caption beside a comment is still returned",
          pp._latex_command_bodies("\\caption{live} % \\caption{old}", "caption")
          == ["live"],
          repr(pp._latex_command_bodies("\\caption{live} % \\caption{old}", "caption")))


# ---------------------------------------------------------------------------
# F095/F096 -- TOML args: strings only, and legal multi-line strings parse
# ---------------------------------------------------------------------------
def test_toml_args() -> None:
    print("\n== F095/F096: the MCP config TOML args reader ==")
    check("F095 a TOML boolean is not turned into an argv string",
          pp._toml_array_values('[true, "x"]') is None,
          repr(pp._toml_array_values('[true, "x"]')))
    check("F095 a TOML number is not turned into an argv string",
          pp._toml_array_values('[1, 2]') is None,
          repr(pp._toml_array_values('[1, 2]')))
    check("F095 a string array with a trailing comma still parses",
          pp._toml_array_values('["a", "b",]') == ["a", "b"],
          repr(pp._toml_array_values('["a", "b",]')))
    check("F096 a triple-quoted basic string parses",
          pp._toml_array_values('[ """node""", "x"]') == ["node", "x"],
          repr(pp._toml_array_values('[ """node""", "x"]')))
    check("F096 a triple-quoted literal string parses",
          pp._toml_array_values("[ '''node''', 'x']") == ["node", "x"],
          repr(pp._toml_array_values("[ '''node''', 'x']")))
    check("F096 a multi-line basic string keeps its interior newline",
          pp._toml_array_values('["""node\nserver.js"""]') == ["node\nserver.js"],
          repr(pp._toml_array_values('["""node\nserver.js"""]')))
    # R04: the production reader delimits the array with _toml_array_at()
    # BEFORE _toml_string_at(); a one-character quote flag there never finds a
    # triple-quoted element that carries an embedded quote, so mcp_server_spec()
    # silently launched the server with args=[].
    check("R04 the array delimiter finds a triple-quoted element with an embedded quote",
          pp._toml_array_at(' ["""a"b"""]', 1) is not None,
          repr(pp._toml_array_at(' ["""a"b"""]', 1)))
    check("R04 the triple-quoted embedded-quote array parses",
          pp._toml_array_values('[ """a"b""" ]') == ['a"b'],
          repr(pp._toml_array_values('[ """a"b""" ]')))
    codex_home = scratch("fb1107_codex_")
    write(codex_home / "config.toml",
          '[mcp_servers.demo]\ncommand = "node"\nargs = ["""a"b"""]\n')
    _old_home = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(codex_home)
    try:
        spec = pp.mcp_server_spec("demo")
    finally:
        if _old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = _old_home
    check("R04 mcp_server_spec keeps the triple-quoted argument",
          spec == {"command": "node", "args": ['a"b']}, repr(spec))


# ---------------------------------------------------------------------------
# F001 -- the M30 table parser keeps a quoted-newline record one record
# ---------------------------------------------------------------------------
def test_m30_table_csv() -> None:
    print("\n== F001: the M30 simple-table parser ==")
    text = ('id,reason,score\n'
            'a,"line one\nline two",3\n'
            'b,ok,4\n')
    header, body = fmt._simple_table(text)
    check("F001 the header is read", header == ["id", "reason", "score"], repr(header))
    check("F001 the quoted newline stays inside one cell",
          body == [["a", "line one\nline two", "3"], ["b", "ok", "4"]], repr(body))
    stats = fmt.table_column_stats([("t.csv", text)])
    score = [s for s in stats if s["column"] == "score"]
    check("F001 the numeric 3 stays in the score column",
          score and score[0]["values"] == [3.0, 4.0], json.dumps(score)[:300])
    check("F001 the row count is not inflated",
          score and score[0]["n rows"] == 2, json.dumps(score)[:200])
    # A GFM pipe table is unchanged by the whole-text CSV parse.
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
    header, body = fmt._simple_table(md)
    check("F001 a pipe table still reads two columns",
          header == ["a", "b"] and body == [["1", "2"], ["3", "4"]],
          f"{header} {body}")


# ---------------------------------------------------------------------------
# F080 -- a head dump with a long preamble is still a head dump
# ---------------------------------------------------------------------------
def test_pairwise_head_dump() -> None:
    print("\n== F080: the pairwise head-dump detector ==")
    tmp = scratch("fb1107_head_")
    path = tmp / "head_dump.txt"
    preamble = "a long shell banner line\n" * 500          # ~12000 bytes
    write(path, preamble
          + "==> run/round1_raw_scores.csv <==\n"
          + "member_id,opponent_id,score,credited,direction\n"
          + "w1,orig,3,3,own\n")
    check("F080 a marker past the first 8000 bytes is still detected",
          pw.is_head_dump(path) is True, f"size {path.stat().st_size}")
    blocks = list(pw.iter_head_dump(path))
    check("F080 the block is readable", len(blocks) == 1, repr(blocks)[:200])


# ---------------------------------------------------------------------------
# F061 -- nested work/ is not corpus content
# ---------------------------------------------------------------------------
def test_nested_work_exclusion() -> None:
    print("\n== F061: nested work/ scratch is excluded at every depth ==")
    tmp = scratch("fb1107_work_")
    src = tmp / "src"
    write(src / "main.md", "main\n")
    write(src / "supp" / "work" / "scratch.md", "scratch\n")
    dst = tmp / "dst"
    pp.copy_into(src, dst, exclude_top=("work",))
    files = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    check("F061 copy_into drops a nested work/ file", files == ["main.md"], repr(files))
    man = pp.corpus_dir_manifest(src, exclude_top=("work",))
    check("F061 corpus_dir_manifest drops the same nested file",
          sorted(man["files"]) == ["main.md"], repr(sorted(man["files"])))
    view = sorted(rel for rel, _p in pp.corpus_dir_view_files(src))
    check("F061 corpus_dir_view_files drops the same nested file",
          view == ["main.md"], repr(view))
    # R01: the RECORDED identity (manifest_for_sources, which feeds
    # recompute_corpus_digest) and the fingerprint must use the same rule as
    # the materialized corpus, or pin_champion dies on its own inconsistency
    # check and ensure_corpus_dir rebuilds forever.
    sources = [(src, "", tuple(pp.CORPUS_EXCLUDE_TOP))]
    recorded = pp.manifest_for_sources(sources)
    check("R01 the recorded corpus identity drops the nested work/ file",
          sorted(recorded["files"]) == ["main.md"], repr(sorted(recorded["files"])))
    check("R01 the recorded digest equals the materialized pin's digest",
          pp.manifest_digest(recorded) == pp.manifest_digest(pp.corpus_dir_manifest(dst)),
          f"{pp.manifest_digest(recorded)[:12]} != "
          f"{pp.manifest_digest(pp.corpus_dir_manifest(dst))[:12]}")
    check("R01 the content fingerprint describes the same file set",
          pp.corpus_content_set_fingerprint(sources)
          == pp.corpus_content_set_fingerprint([(dst, "", ())]))
    check("R01 the corpus copy matches the recorded manifest",
          pp.dir_matches(dst, recorded["files"]))
    dst2 = tmp / "dst2"
    seq = [pp.ensure_copy(src, dst2, exclude_top=("work",)) for _ in range(3)]
    check("R01 ensure_copy converges with a nested work/ exclusion",
          seq == [True, False, False], repr(seq))


def test_nested_evidence_name_copy() -> None:
    print("\n== R02: an evidence-area name is excluded only at the top level ==")
    tmp = scratch("fb1107_evname_")
    src = tmp / "src"
    write(src / "main.md", "main\n")
    write(src / "raw_data" / "obs.csv", "x\n")
    write(src / "supp" / "raw_data" / "table.csv", "a,b\n")
    dst = tmp / "dst"
    pp.copy_into(src, dst, exclude_top_only=("raw_data",))
    files = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    check("R02 a nested raw_data/ file is ordinary submission content",
          files == ["main.md", "supp/raw_data/table.csv"], repr(files))
    check("R02 the top-level raw_data/ area is still excluded",
          "raw_data/obs.csv" not in files, repr(files))
    h_src = pp.hash_manifest(src, exclude_top_only=("raw_data",))["files"]
    h_dst = pp.hash_manifest(dst, follow_dir_links=True,
                             exclude_top_only=("raw_data",))["files"]
    check("R02 the copy and its expected manifest agree", h_src == h_dst,
          f"{sorted(h_src)} vs {sorted(h_dst)}")
    dst2 = tmp / "dst2"
    seq = [pp.ensure_copy(src, dst2, exclude_top_only=("raw_data",)) for _ in range(3)]
    check("R02 the sandbox copy converges instead of rebuilding every entry",
          seq == [True, False, False], repr(seq))


# ---------------------------------------------------------------------------
# F086 -- an added non-editable submission file is reported
# ---------------------------------------------------------------------------
def test_added_non_editable() -> None:
    print("\n== F086: the document-set check's added direction ==")
    tmp = scratch("fb1107_added_")
    base, cand = tmp / "base", tmp / "cand"
    write(base / "main.md", "Body\n")
    write(cand / "main.md", "Body, revised\n")
    (cand / "extra.pdf").write_bytes(b"%PDF-1.4 new file\n")
    got = pp.document_set_check([(base, "", ())], [(cand, "", ())])
    check("F086 an added PDF is reported in the added direction",
          got.get("added_non_editable") == ["extra.pdf"], json.dumps(got)[:300])
    same = tmp / "same"
    write(same / "main.md", "Body\n")
    (same / "extra.pdf").write_bytes(b"%PDF-1.4 new file\n")
    got2 = pp.document_set_check([(same, "", ())], [(same, "", ())])
    check("F086 the same PDF in the base is not added",
          got2.get("added_non_editable") == [], json.dumps(got2)[:300])
    check("F086 the editable added list is unchanged",
          got.get("added") == [], json.dumps(got)[:200])


# ---------------------------------------------------------------------------
# F014 -- a platform without os.killpg must still time out cleanly
# ---------------------------------------------------------------------------
def test_kill_process_group() -> None:
    print("\n== F014: the process-group kill on a platform without os.killpg ==")
    code = r'''
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("pp14", sys.argv[1])
pp = importlib.util.module_from_spec(spec)
sys.modules["pp14"] = pp
spec.loader.exec_module(pp)
class P:
    pid = 987654
    killed = False
    def kill(self):
        self.killed = True
del os.killpg                      # the Windows attribute set
p = P()
pp._kill_process_group(p)
print("KILLED" if p.killed else "NOT")
'''
    proc = subprocess.run([sys.executable, "-c", code, str(WS / "paper_pipeline.py")],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check("F014 a missing os.killpg falls back to proc.kill()",
          proc.returncode == 0 and "KILLED" in proc.stdout,
          (proc.stderr.strip().splitlines() or [""])[-1])


# ---------------------------------------------------------------------------
# F098 -- the evidence-area copy fallback must not follow nested symlinks
# ---------------------------------------------------------------------------
def test_evidence_copy_no_follow() -> None:
    print("\n== F098: the LaTeX evidence-link fallback ==")
    tmp = scratch("fb1107_symlink_")
    pkg = tmp / "pkg"
    write(pkg / "main.tex",
          "\\documentclass{article}\n\\begin{document}x\\end{document}\n")
    outside = tmp / "outside"
    write(outside / "secret.tex", "OUTSIDE-SECRET\n")
    (pkg / "raw_data").mkdir(parents=True)
    real_symlink = os.symlink
    os.symlink(outside / "secret.tex", pkg / "raw_data" / "linked.tex")
    # A stub latexmk proves what reached the build tree: it copies the linked
    # evidence file out (when it is there) and asks for no output.
    bin_dir = tmp / "bin"
    inner = ('#!/bin/sh\n'
             'cat raw_data/linked.tex > "$LEAK_OUT" 2>/dev/null || true\n'
             'exit 1\n')
    write(bin_dir / "latexmk", inner)
    (bin_dir / "latexmk").chmod(0o755)
    leak = tmp / "leak.txt"
    old_path, old_leak = os.environ.get("PATH", ""), os.environ.get("LEAK_OUT")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
    os.environ["LEAK_OUT"] = str(leak)

    def _no_symlinks(*_a, **_k):
        raise OSError("symlinks are unavailable")

    os.symlink = _no_symlinks
    try:
        res = pp.compile_latex_pdf(pkg, "main.tex", tmp / "out" / "main.pdf",
                                   timeout=30, link_evidence=True)
    finally:
        os.symlink = real_symlink
        os.environ["PATH"] = old_path
        if old_leak is None:
            os.environ.pop("LEAK_OUT", None)
        else:
            os.environ["LEAK_OUT"] = old_leak
    leaked = leak.read_text(encoding="utf-8") if leak.is_file() else ""
    check("F098 the fallback copy does not follow a nested evidence symlink",
          "OUTSIDE-SECRET" not in leaked, repr(leaked))
    check("F098 the skipped link is recorded on the result",
          "linked.tex" in json.dumps(res.get("skipped_links") or []),
          json.dumps(res.get("skipped_links"))[:200])


# ---------------------------------------------------------------------------
# F081 -- a failed switch-in restores the previous MCP tool
# ---------------------------------------------------------------------------
def test_installer_rollback() -> None:
    print("\n== F081: the installer's failed switch-in ==")
    tmp = scratch("fb1107_install_")
    home = tmp / "home"
    (home / ".codex" / "skills").mkdir(parents=True)
    tools = tmp / "tools"
    live = tools / "mcp-docx-converter"
    write(live / "KEEP.txt", "previous install\n")
    (tools / "mcp-docx-compare").mkdir(parents=True)
    bin_dir = tmp / "bin"
    write(bin_dir / "npm", "#!/bin/sh\nexit 0\n")
    (bin_dir / "npm").chmod(0o755)
    # A wrapper that fails exactly the staged-tree -> live-tool move.
    wrapper = (
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if len(args) == 3 and args[0] == '--':\n"
        "    src, dst = args[1], args[2]\n"
        "    if dst == os.environ.get('FAIL_DST') and '.stage.' in src:\n"
        "        print('injected mv failure', file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "os.execv('/bin/mv', ['/bin/mv'] + args)\n")
    write(bin_dir / "mv", wrapper)
    (bin_dir / "mv").chmod(0o755)
    env = dict(os.environ,
               HOME=str(home), MCP_TOOLS_DIR=str(tools), FAIL_DST=str(live),
               PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
               PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(["bash", "install_skill.sh"], cwd=str(WS), env=env,
                          capture_output=True, text=True, timeout=300)
    check("F081 the injected failure fails the install", proc.returncode != 0,
          f"rc={proc.returncode}")
    check("F081 the previous live tool is restored",
          live.is_dir() and (live / "KEEP.txt").is_file(),
          f"exists={live.exists()}")
    check("F081 no .old.<pid> tree is left behind",
          not any(p.name.startswith("mcp-docx-converter.old.") for p in tools.iterdir()),
          repr(sorted(p.name for p in tools.iterdir())))


# ---------------------------------------------------------------------------
# F088 -- create-test-env.sh detects a registered named conda environment
# ---------------------------------------------------------------------------
def test_create_test_env_registered() -> None:
    print("\n== F088: create-test-env.sh reads a named conda environment ==")
    tmp = scratch("fb1107_conda_")
    base = tmp / "miniconda3"
    (base / "envs").mkdir(parents=True)
    bin_dir = tmp / "bin"
    calls = tmp / "calls.txt"
    stub = f'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open({str(calls)!r}, "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")
if args[:2] == ["info", "--base"]:
    print({str(base)!r}); sys.exit(0)
if args[:2] == ["env", "list"]:
    print(json.dumps({{"envs": [{str(base)!r},
                                {str(base / "envs" / "paper-refine-test")!r}]}}))
    sys.exit(0)
if args[:1] == ["run"]:
    sys.exit(1)                       # the registered env has no working Python
sys.exit(0)
'''
    write(bin_dir / "conda", stub)
    (bin_dir / "conda").chmod(0o755)
    env = dict(os.environ,
               CONDA_EXE=str(bin_dir / "conda"),
               PAPER_REFINE_TEST_EXPORT_DIR=str(tmp / "no-export"),
               PAPER_REFINE_TEST_ENV="paper-refine-test",
               PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(["bash", "scripts/create-test-env.sh", "--recreate"],
                          cwd=str(WS), env=env, capture_output=True, text=True, timeout=120)
    recorded = calls.read_text(encoding="utf-8") if calls.is_file() else ""
    check("F088 the registered named env is recognised as a broken install",
          "removing existing-but-broken environment" in proc.stdout, proc.stdout[-400:])
    check("F088 --recreate issues the env remove for it",
          "env remove -y -n paper-refine-test" in recorded, repr(recorded[-300:]))


# ---------------------------------------------------------------------------
# F002 -- the sign rule refuses a judge count it can never reject at
# ---------------------------------------------------------------------------
def test_sign_rule_attainability() -> None:
    print("\n== F002: the sign anti-regression rule's attainability ==")
    check("F002 four directed losses are not significant at alpha 0.05",
          pp._binomial_tail_p(4, 4) == 0.0625, repr(pp._binomial_tail_p(4, 4)))
    tmp = scratch("fb1107_sign_")
    src = tmp / "src"
    write(src / "main.md", "# Title\n\n## Abstract\n\nWe show a thing.\n")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup",
         "--source", str(src), "--root", str(tmp / "root"),
         "--vs-original-rule", "sign"],
        cwd=str(WS), capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    out = (proc.stdout or "") + (proc.stderr or "")
    check("F002 setup refuses sign with the default 2 judges",
          proc.returncode == 2 and "3 judges" in out, f"rc={proc.returncode} {out[-300:]}")


# ---------------------------------------------------------------------------
# F003/F027/F033 -- the prose contracts the code/venue profile contradicts
# ---------------------------------------------------------------------------
def test_prose_contracts() -> None:
    print("\n== F003/F027/F033: prompt and sweep contracts ==")
    judge_prompt = pp.judge_prompt(Path("/tmp/x"), "judge_tok_j1", 1, "tok", 1, 1, ["v1"])
    flat_prompt = " ".join(judge_prompt.split())
    check("F003 the judge prompt no longer promises that the calibration "
          "directions never cancel",
          "never cancels the other" not in flat_prompt)
    _start = flat_prompt.find("CLAIM CALIBRATION")
    _para = flat_prompt[_start:_start + 1500] if _start >= 0 else ""
    check("F003 the judge prompt states that the two directions net within the tier",
          "cancel" in _para.lower() and "net" in _para.lower(), _para[:600])
    check("R03 the paragraph scopes the cancellation to the correctness tier "
          "rather than promising the comparison scores 0",
          "comparison scores 0" not in _para and "correctness net" in _para.lower(),
          _para[:800])
    sweeps = (WS / "paper-skills/paper-review/references/sweeps.md").read_text(
        encoding="utf-8")
    flat_sweeps = " ".join(sweeps.split())
    check("F027 M29 does not ask a text layer to prove visual encodings",
          "panel/encoding (n, error bars, colour scale, markers, axis meaning) "
          "with the artwork's own text" not in flat_sweeps)
    check("F027 M29 names the rendered-image check for a visual encoding",
          "rendered image" in flat_sweeps or "rendered-image" in flat_sweeps)
    skill = (WS / "paper-skills/paper-review/SKILL.md").read_text(encoding="utf-8")
    check("F033 the local author guide no longer outranks the recorded profile",
          "prefer a local copy of the author guidelines if present in the directory"
          not in skill)
    check("F033 the skill states when a local copy may be used",
          "names the same journal" in skill.lower(),
          skill[skill.find("Guidelines source"):][:400].lower())


# ---------------------------------------------------------------------------
# F074/F101 -- the journal concern ledger's source list and attribution
# ---------------------------------------------------------------------------
def _ledger_fixture(tmp: Path, row: dict):
    sb = tmp / "sb"
    (sb / "concerns").mkdir(parents=True)
    for d in ("feedback/files", "feedback/text",
              "feedback/llm/files", "feedback/llm/text"):
        (sb / d).mkdir(parents=True)
    write(sb / "feedback/files/editor_letter.txt", "x")
    write(sb / "feedback/text/editor_letter.txt.txt",
          "Reviewer 1: The sample size is too small for the claim.\n")
    write(sb / "feedback/files/reviewer_report.txt", "x")
    write(sb / "feedback/text/reviewer_report.txt.txt",
          "The sample size is too small for the claim.\n")
    write(sb / "feedback/CONCERN_SEED.json", json.dumps({
        "files": ["editor_letter.txt", "reviewer_report.txt"]}))
    write(sb / "concerns/JF_concerns.json", json.dumps({"concerns": [row]}))
    write(sb / "concerns/JF_concerns.md", "| id |\n|---|\n| R1-1 |\n")
    errs, warns = [], []
    pp.journal_ledger_problems(None, sb, errs, warns)
    return errs, warns


def test_journal_ledger() -> None:
    print("\n== F074/F101: the journal concern ledger ==")
    row = {"id": "R1-1", "source": "editor_letter.txt; reviewer_report.txt",
           "author": "Reviewer 1",
           "quote": "The sample size is too small for the claim.",
           "summary": "sample size", "action": "text", "disposition": "to-fix"}
    errs, _w = _ledger_fixture(scratch("fb1107_ledger_merged_"), row)
    check("F074 a merged row naming both staged files passes",
          not any("does not name any file" in e for e in errs), str(errs)[:400])
    row2 = dict(row, source="editor_letter.txt; not_a_feedback_file.txt")
    errs, _w = _ledger_fixture(scratch("fb1107_ledger_bad_"), row2)
    check("F074 a merged row naming an unstaged file is still rejected",
          any("does not name any file" in e for e in errs), str(errs)[:400])
    row3 = dict(row, source="editor_letter.txt", author="Professor Plum")
    errs, warns = _ledger_fixture(scratch("fb1107_ledger_author_"), row3)
    check("F101 an invented attribution is reported, not passed silently",
          errs == [] and any("Professor Plum" in w for w in warns), str(warns)[:300])
    row4 = dict(row, source="editor_letter.txt", author="Reviewer 1")
    errs, warns = _ledger_fixture(scratch("fb1107_ledger_author_ok_"), row4)
    check("F101 the review's own label is accepted without a warning",
          errs == [] and warns == [], f"{errs} {warns}")


def main() -> int:
    print("== 2026-11-07 fix-bugs wave 1 regression checks ==")
    test_word_counters()
    test_pkg12_cells()
    test_toml_args()
    test_m30_table_csv()
    test_pairwise_head_dump()
    test_nested_work_exclusion()
    test_nested_evidence_name_copy()
    test_added_non_editable()
    test_kill_process_group()
    test_evidence_copy_no_follow()
    test_installer_rollback()
    test_create_test_env_registered()
    test_sign_rule_attainability()
    test_prose_contracts()
    test_journal_ledger()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
