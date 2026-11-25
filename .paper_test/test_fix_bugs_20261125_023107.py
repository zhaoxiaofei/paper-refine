#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 02:31 fix-bugs wave (agent's own fixes).

Each check pins one candidate confirmed against this tree by re-reading the
cited code and reproducing it.  Hermetic: temp dirs only, no network, no
Word/Office.

Run:  python3 .paper_test/test_fix_bugs_20261125_023107.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    import shutil
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def check_f001() -> None:
    print("\n== F001: an undecodable venue pack summary is a broken pack, not a crash ==")
    np = load("fixbugs1125_np", "paper_pipeline.py")
    tmp = scratch("fixbugs1125_f001_")
    pack = tmp / "venue_profiles" / "broken.templates"
    pack.mkdir(parents=True)
    (pack / "venue_architecture.md").write_bytes(b"\xff\xfe\x00bad")
    try:
        np.venue_norm_block("broken", root=tmp)
    except np.VenueProfileError as e:
        msg = str(e)
        check("F001 undecodable pack summary raises VenueProfileError",
              "not valid UTF-8" in msg and "venue_architecture.md" in msg, msg[:160])
    except Exception as e:  # noqa: BLE001 - the regression under test is a traceback
        check("F001 undecodable pack summary raises VenueProfileError", False,
              f"{type(e).__name__}: {e}")
    else:
        check("F001 undecodable pack summary raises VenueProfileError", False,
              "no exception raised")
    check("F001 a venue without a pack still contributes no block",
          np.venue_norm_block("nosuchvenue", root=tmp) == "")


def check_f064() -> None:
    print("\n== F064: the shipped-profile worked example matches the shipped profile ==")
    import json as _json
    readme = (WS / "venue_profiles" / "README.md").read_text(encoding="utf-8")
    profile = _json.loads((WS / "venue_profiles" / "nature-biotechnology.json")
                          .read_text(encoding="utf-8"))
    brief = next(t for t in profile["article_types"] if t["id"] == "brief-communication")
    lim = brief["length_limits"]
    check("F064 the shipped profile really carries 70/1500 for Brief Communication",
          lim["abstract"]["base"] == 70 and lim["main_text"]["base"] == 1500)
    check("F064 the worked-example snippet carries the same 70/1500 numbers",
          '"abstract": {"base": 70' in readme
          and '"main_text": {"base": 1500' in readme)
    check("F064 the README no longer claims Brief Communication yields no caps",
          "Selecting `brief-communication` on such a profile yields" not in readme)


def check_f065() -> None:
    print("\n== F065: the harness docs state the defect audit's real precedence ==")
    docs = (WS / "docs" / "agent-harnesses.md").read_text(encoding="utf-8")
    flat = " ".join(docs.split())
    check("F065 docs name the recorded-backend precedence instead of a flat codex-lite default",
          "then the agent backend a previous round recorded" in flat
          and "lightweight `codex-lite` default" in flat)


def check_f066() -> None:
    print("\n== F066: the test README counts all five docx_format parts ==")
    readme = (WS / ".paper_test" / "README.md").read_text(encoding="utf-8")
    parts = sorted(p.name for p in (WS / ".paper_test").glob("test_docx_format_[0-9]_*.py"))
    check("F066 there are five docx_format parts on disk", len(parts) == 5, str(parts))
    check("F066 the README says five and lists _5_caption_blocks",
          "Split into 5 parts" in readme and "`_5_caption_blocks`" in readme)


def check_f115_f116() -> None:
    print("\n== F115/F116: audit prompt wrapper + TP-reason gate ==")
    np = sys.modules.get("fixbugs1125_np") or load("fixbugs1125_np", "paper_pipeline.py")
    prompt = np._defect_audit_prompt(1, 2)
    check("F115 the prompt describes the defects.json wrapper object",
          "`defects` array" in prompt)
    check("F116 'a b c' / 'a a b' are not a basis",
          not np._defect_audit_reason_ok("a b c")
          and not np._defect_audit_reason_ok("a a b"))
    check("F116 'see the file' is not a basis",
          not np._defect_audit_reason_ok("see the file"))
    check("F116 a concrete file:line basis is accepted",
          np._defect_audit_reason_ok("checked main.md:4"))
    check("F116 existing real bases still pass",
          np._defect_audit_reason_ok("stub reason")
          and np._defect_audit_reason_ok("checked the quoted text")
          and np._defect_audit_reason_ok("text present at line 42")
          and np._defect_audit_reason_ok("base/main.md:12 quotes the sentence"))


def check_f006() -> None:
    print("\n== F006: a planted others/ symlink cannot redirect the donor materialization ==")
    np = sys.modules.get("fixbugs1125_np") or load("fixbugs1125_np", "paper_pipeline.py")
    from types import SimpleNamespace
    tmp = scratch("fixbugs1125_f006_")
    runs = tmp / "runs"
    sb = runs / "r1_i1"
    sb.mkdir(parents=True)
    outside = tmp / "outside"
    outside.mkdir()
    (sb / "others").symlink_to(outside, target_is_directory=True)
    ctx = SimpleNamespace(runs_dir=runs, run=lambda rid: None)
    saved = {}

    def stub(name, value):
        saved[name] = getattr(np, name)
        setattr(np, name, value)

    def noop(*a, **k):
        return None

    try:
        stub("round_counts", lambda ctx, r: (2, 1))
        stub("rid_for_fresh", lambda r, v: f"r{r}_{v}")
        stub("_require_done", noop)
        stub("ensure_corpus_dir",
             lambda ctx, r, v, dst: (Path(dst).mkdir(parents=True, exist_ok=True), False)[1])
        for name in ("ensure_pristine_input", "stage_venue_template", "seed_template_visuals",
                     "seed_evidence_pack", "seed_discovery_findings", "prior_failure_block",
                     "content_edit_policy_for_sandbox", "prefer_rewrite_for_sandbox",
                     "soft_deletions_for_sandbox", "_copy_session_tools", "write_text_atomic",
                     "integrate_prompt", "materialize_tools", "seed_round_helpers"):
            if hasattr(np, name):
                stub(name, noop)
        import contextlib as _ctx
        import io as _io
        err_buf = _io.StringIO()
        try:
            with _ctx.redirect_stderr(err_buf):
                np.materialize_integrate(ctx, 1, 1)
            raised = "no exception"
        except SystemExit as e:
            raised = f"SystemExit code={getattr(e, 'code', None)} {err_buf.getvalue()}"
        except Exception as e:  # noqa: BLE001 - the pre-fix path may die later
            raised = f"{type(e).__name__}: {e} {err_buf.getvalue()}"
    finally:
        for name, value in saved.items():
            setattr(np, name, value)
    check("F006 a planted others/ symlink is refused before a donor is written outside",
          not (outside / "w1").exists()
          and "refusing to create output directory" in raised,
          f"raised={raised!r} outside={sorted(p.name for p in outside.iterdir())}")


def check_f042() -> None:
    print("\n== F042: the MCP server gets SIGTERM before the driver's group kill ==")
    np = sys.modules.get("fixbugs1125_np") or load("fixbugs1125_np", "paper_pipeline.py")
    tmp = scratch("fixbugs1125_f042_")
    sig = tmp / "sigterm.txt"
    server = tmp / "fake_server.py"
    server.write_text(
        "import pathlib, signal, sys, time\n"
        "marker = pathlib.Path(sys.argv[1])\n"
        "def _term(signum, frame):\n"
        "    marker.write_text('sigterm')\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, _term)\n"
        "while True:\n"
        "    time.sleep(0.05)\n", encoding="utf-8")
    res = np.mcp_stdio_tool_call({"command": sys.executable,
                                  "args": [str(server), str(sig)]},
                                 "no_such_tool", {}, timeout=1)
    check("F042 a timed-out server receives SIGTERM before the killpg backstop",
          sig.is_file(), f"res={res}")
    check("F042 the timed-out call is still reported as a failure",
          res.get("ok") is False, str(res)[:200])


def check_f057() -> None:
    print("\n== F057: the pipeline normalizes a wrapped Markdown keyword line too ==")
    import json as _json
    import subprocess as _sub
    np = sys.modules.get("fixbugs1125_np") or load("fixbugs1125_np", "paper_pipeline.py")
    tmp = scratch("fixbugs1125_f057_")
    md = tmp / "k.md"
    md.write_text("# Title\n\n## Abstract\nThis abstract has four words here.\n\n"
                  "**Keywords:** alpha, beta\n**primary cancer, immunity**\n\n"
                  "## Introduction\nMain body prose goes here now.\n", encoding="utf-8")
    scan = np.scan_lengths_in_sources([(tmp, "", ())])
    pipe = {r.get("section"): r.get("words") for r in scan.get("rows") or []}
    proc = _sub.run([sys.executable, str(WS / "paper-skills/paper-review/scripts/"
                                              "count_words.py"), str(md), "--json"],
                    capture_output=True, text=True, timeout=120)
    try:
        script = {r["section"]: r["words"] for r in _json.loads(proc.stdout)["rows"]}
    except (ValueError, KeyError, TypeError):
        script = {}
    check("F057 the wrapped keyword continuation is excluded by both counters",
          pipe.get("main text") == script.get("main text") == 6,
          f"pipeline={pipe} script={script}")


def check_f043() -> None:
    print("\n== F043: the server's Word timer fires before the Python caller's deadline ==")
    import re as _re
    conv = (WS / "mcp-docx-converter" / "index.js").read_text(encoding="utf-8")
    comp = (WS / "mcp-docx-compare" / "index.js").read_text(encoding="utf-8")
    m_conv = _re.search(r"runFile\(CONVERTER.*?timeout:\s*(\d+)", conv, _re.S)
    m_comp = _re.search(r"runFile\(COMPARER.*?timeout:\s*(\d+)", comp, _re.S)
    # p06's documented caller budgets: 300 s template render, 900 s redline.
    check("F043 the converter timer is below the 300 s caller deadline",
          bool(m_conv) and int(m_conv.group(1)) < 300_000,
          m_conv.group(1) if m_conv else "not found")
    check("F043 the comparer timer is below the 900 s caller deadline",
          bool(m_comp) and int(m_comp.group(1)) < 900_000,
          m_comp.group(1) if m_comp else "not found")


def check_f055() -> None:
    print("\n== F055: the M19 scan and count_words.py read one Markdown text ==")
    import json as _json
    import subprocess as _sub
    np = sys.modules.get("fixbugs1125_np") or load("fixbugs1125_np", "paper_pipeline.py")
    tmp = scratch("fixbugs1125_f055_")
    md = tmp / "ms.md"
    md.write_text("# Title\n\n## Abstract\n"
                  "This abstract has exactly eight words in total here.\n\n"
                  "## Introduction\nMain body prose follows here.\n\n"
                  "```\ncode line one\ncode line two\n```\n\n"
                  "More prose after the code.\n", encoding="utf-8")
    scan = np.scan_lengths_in_sources([(tmp, "", ())])
    pipe = {r.get("section"): r.get("words") for r in scan.get("rows") or []}
    proc = _sub.run([sys.executable, str(WS / "paper-skills/paper-review/scripts/"
                                              "count_words.py"), str(md), "--json"],
                    capture_output=True, text=True, timeout=120)
    try:
        script = {r["section"]: r["words"] for r in _json.loads(proc.stdout)["rows"]}
    except (ValueError, KeyError, TypeError):
        script = {}
    check("F055 the fenced code is not main-text prose in the M19 scan",
          pipe.get("main text") == 10,
          f"pipeline={pipe}")
    check("F055 the pipeline and the artifact report the same counts",
          pipe.get("abstract") == script.get("abstract")
          and pipe.get("main text") == script.get("main text"),
          f"pipeline={pipe} script={script}")


def check_f056() -> None:
    print("\n== F056: whitespace before a LaTeX environment brace is legal ==")
    import json as _json
    import subprocess as _sub
    cw = load("fixbugs1125_cw",
              "paper-skills/paper-review/scripts/count_words.py")
    check("F056 a whitespace-opened equation is blanked",
          "x = 1" not in cw.blank_math_environments(
              "before\n\\begin {equation}x = 1\\end {equation}\nafter"),
          repr(cw.blank_math_environments(
              "before\n\\begin {equation}x = 1\\end {equation}\nafter")))
    tmp = scratch("fixbugs1125_f056_")
    tex = tmp / "sp.tex"
    tex.write_text("\\documentclass{article}\n\\begin {abstract}\n"
                   "This abstract has exactly nine words in it.\n"
                   "\\end {abstract}\n\\section{Introduction}\n"
                   "Main body prose follows here.\n", encoding="utf-8")
    proc = _sub.run([sys.executable, str(WS / "paper-skills/paper-review/scripts/"
                                              "count_words.py"), str(tex), "--json"],
                    capture_output=True, text=True, timeout=120)
    rows = {}
    try:
        rows = {r["section"]: r["words"] for r in _json.loads(proc.stdout)["rows"]}
    except (ValueError, KeyError, TypeError):
        pass
    check("F056 the abstract row and its words survive `\\begin {abstract}`",
          rows.get("abstract") == 8 and rows.get("main text") == 5,
          f"rows={rows} rc={proc.returncode} {proc.stderr[-200:]}")


def check_f106() -> None:
    print("\n== F106: .rtf/.html feedback produces quoting text ==")
    np = sys.modules.get("fixbugs1125_np") or load("fixbugs1125_np", "paper_pipeline.py")
    tmp = scratch("fixbugs1125_f106_")
    rtf = tmp / "letter.rtf"
    rtf.write_bytes(b"{\\rtf1\\ansi\\deff0 {\\fonttbl{\\f0 Times;}} "
                    b"\\f0 Reviewer 1: The sample size is not justified.\\par "
                    b"Please add power calculations.}")
    htm = tmp / "letter.html"
    htm.write_text("<html><head><title>x</title></head><body>"
                   "<p>Reviewer 2: The methods are unclear.</p><p>Please expand.</p>"
                   "</body></html>", encoding="utf-8")
    t_rtf, n_rtf = np.feedback_text_of(rtf)
    t_htm, n_htm = np.feedback_text_of(htm)
    check("F106 .rtf yields the reviewer's prose",
          "sample size is not justified" in t_rtf and "power calculations" in t_rtf
          and "fonttbl" not in t_rtf and n_rtf == "", f"{t_rtf!r} {n_rtf!r}")
    check("F106 .html yields the reviewer's prose",
          "methods are unclear" in t_htm and "Please expand." in t_htm
          and "<p>" not in t_htm and n_htm == "", f"{t_htm!r} {n_htm!r}")
    # `\*` is an RTF control SYMBOL (an ignorable destination), not a control
    # word. Word writes `{\*\generator ...}` into every file, and an unknown
    # destination must not be emitted as prose: the marker is skipped and its
    # group's text is not part of the reviewer's letter.
    rtf2 = tmp / "letter2.rtf"
    rtf2.write_bytes(b"{\\rtf1\\ansi{\\*\\generator Microsoft Word;}"
                     b"{\\*\\bkmkstart hiddenmark}"
                     b"Reviewer 3: The figures are illegible.\\par}")
    t_rtf2, n_rtf2 = np.feedback_text_of(rtf2)
    check("F106 an ignorable RTF destination is skipped, not emitted",
          "figures are illegible" in t_rtf2 and "hiddenmark" not in t_rtf2
          and "*" not in t_rtf2 and n_rtf2 == "", f"{t_rtf2!r} {n_rtf2!r}")


def check_f067_f071() -> None:
    print("\n== F067/F069/F070/F071: adapter config errors, tool probes, argv escaping, body caps ==")
    import io as _io
    import os as _os
    import re as _re
    import sys as _sys
    sys.path.insert(0, str(WS))
    sys.path.insert(0, str(WS / "agent-common"))
    import json as _json
    import paper_dots_agent as _dots
    import paper_qwen_agent as _qwen
    import paper_model_agent as _model
    from agent_common import llm_retry as _llm

    # F067 -- the ConfigError must come back as (argv, env, error), not escape.
    _saved_env = dict(_os.environ)
    try:
        for mod, label, env in (
                (_dots, "dots", {"PAPER_DOTS_CONTEXT_WINDOW": "1000"}),
                (_qwen, "qwen", {"PAPER_QWEN_CONTEXT_WINDOW": "1000"}),
                (_model, "model", {"PAPER_AGENT_MODEL_ENDPOINT": "https://api.example/v1",
                                   "PAPER_AGENT_CONTEXT_WINDOW": "1000",
                                   "PAPER_AGENT_MAX_TOKENS": "32768"})):
            _os.environ.update(env)
            cfg = mod.config()
            try:
                argv, _env, err = mod.dsh_argv(cfg)
                got = (argv == [] and "max tokens" in err)
            except Exception as e:  # noqa: BLE001 - the regression is a traceback
                got = False
                err = f"{type(e).__name__}: {e}"
            finally:
                _os.environ.clear()
                _os.environ.update(_saved_env)
            check(f"F067 {label}.dsh_argv reports the ConfigError instead of raising",
                  got, str(err)[:120])
    finally:
        _os.environ.clear()
        _os.environ.update(_saved_env)

    # F069 -- CHECK_TOOLS is a probe-and-warn switch, not a hard failure.
    import contextlib as _ctx
    for mod, label, env_name in (
            (_dots, "dots", "PAPER_DOTS_CHECK_TOOLS"),
            (_qwen, "qwen", "PAPER_QWEN_CHECK_TOOLS")):
        _saved = {k: _os.environ.get(k) for k in (env_name, "PAPER_DOTS_REQUIRE_TOOLS",
                                                  "PAPER_QWEN_REQUIRE_TOOLS")}
        old_argv = mod.codex_argv
        old_run = mod.subprocess.run
        try:
            _os.environ[env_name] = "1"
            _os.environ.pop("PAPER_DOTS_REQUIRE_TOOLS", None)
            _os.environ.pop("PAPER_QWEN_REQUIRE_TOOLS", None)
            mod.probe_endpoint = lambda c, timeout=4.0: (True, [c["model"]], "")
            mod.check_tools = lambda c, timeout=30.0: (False, "HTTP 400")
            mod.codex_argv = lambda cfg, extra=None: ["/bin/true"]
            mod.subprocess.run = lambda *a, **k: type("P", (), {"returncode": 0})()
            old_stdin = _sys.stdin
            _sys.stdin = _io.StringIO("hello")
            stderr = _io.StringIO()
            with _ctx.redirect_stderr(stderr):
                rc = mod.main(["--harness", "codex", "--base-url", "http://127.0.0.1:9/v1"])
            _sys.stdin = old_stdin
            check(f"F069 {env_name} warns instead of exiting 2",
                  rc != 2 and "WARNING" in stderr.getvalue(),
                  f"rc={rc} {stderr.getvalue()[:160]}")
        finally:
            mod.codex_argv = old_argv
            mod.subprocess.run = old_run
            for k, v in _saved.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v

    # F070 -- a quote/newline in model/base URL cannot inject another TOML key.
    for mod, label in ((_dots, "dots"), (_qwen, "qwen")):
        cfg = mod.config()
        cfg["model"] = 'm"\nweb_search="enabled'
        cfg["base_url"] = 'https://x/v1"\nfoo="bar'
        args = mod.codex_argv(cfg)
        bad = [a for a in args if "\n" in a]
        check(f"F070 {label}.codex_argv never emits a multi-line -c value", not bad, str(bad)[:160])

    # F071 -- a provider body is capped before it is decoded.
    class _Big:
        def __init__(self, payload):
            self.payload = payload
            self.pos = 0

        def read(self, n=-1):
            if self.pos >= len(self.payload):
                return b""
            end = len(self.payload) if n is None or n < 0 else self.pos + n
            chunk = self.payload[self.pos:end]
            self.pos += len(chunk)
            return chunk
    for mod, label in ((_dots, "dots"), (_qwen, "qwen")):
        try:
            mod._read_capped(_Big(b"x" * 100), limit=10)
            capped = False
        except ValueError:
            capped = True
        check(f"F071 {label}._read_capped refuses an oversized body", capped)
        check(f"F071 {label}._request reads through the cap",
              "_read_capped(resp)" in Path(mod.__file__).read_text(encoding="utf-8"))

    # F068 -- the Dots compaction idle bound covers jittered sleeps + per-attempt time.
    schedule = _llm.RetrySchedule(_llm.load_policy())
    needed_ms = int((sum(schedule.delays()) * (1.0 + schedule.jitter_ratio)
                     + (schedule.max_retries + 1) * 600.0) * 1000)
    overlay = _llm.dots_dsh_overlay(model="m", base_url="https://api.example/v1",
                                    context_window=100000, max_tokens=1000)
    m = _re.search(r"streamIdleTimeoutMs:\s*(\d+)", overlay)
    check("F068 the stream-idle bound covers jittered retries and per-attempt time",
          bool(m) and int(m.group(1)) >= needed_ms,
          f"bound={m.group(1) if m else None} needed>={needed_ms}")


def main() -> int:
    try:
        check_f001()
        check_f064()
        check_f065()
        check_f066()
        check_f115_f116()
        check_f006()
        check_f106()
        check_f056()
        check_f055()
        check_f043()
        check_f057()
        check_f042()
        check_f067_f071()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
