#!/usr/bin/env python3
"""Rule 6's pure ranking core, and the exec-in-globals name-space guard.

`select_champion` used to interleave the ranking decision with `Ctx` lookups,
live-config reads and report formatting. The decision itself is now
`derive_ranking`, a function of recorded inputs only:

    (panel stats, fresh-arm ids, base representative, issue census, floor)

and `select_champion` is an adapter that resolves the round's structural inputs
and attaches the REPORTED-only tiebreak values.

This suite pins the properties that make that split worth having:

  * the input contract -- no `ctx`, no file or config read inside the core, so a
    later config edit cannot change a past round's champion (F18/F19);
  * the ranking semantics the tier/severity scale and Rule 6 require: the
    adaptive defect prefix leads, per-cell counts keep a fatal defect worse than
    a minor one, an exact (median, mean, IQR) tie retains the incumbent, the
    digest is the name-free final rung, a partial panel is ineligible, no
    eligible row falls back to the base, and floor 0 disables the prefix;
  * that the core does not mutate its inputs; and
  * that a later part cannot silently shadow a top-level name an earlier part
    defined (the loader's one structural hazard).

Run:  python3 .paper_test/test_ranking_core.py
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import os
import sys
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


spec = importlib.util.spec_from_file_location("paperp_rank", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp_rank"] = np
spec.loader.exec_module(np)

SEVERITIES = ("fatal", "critical", "major", "minor")
BASE_REP = "r1_a2"
CANDIDATES = ["w1", "a2"]


def stat(median=0.0, mean=None, iqr=0.0, digest="0" * 40, complete=True,
         anti=True, vs_orig=0.0, placeholders=0):
    """One version's panel statistics, shaped as `aggregate_round` emits them."""
    return {"n": 3, "expected_n": 3, "complete": bool(complete),
            "vs_original_complete": True, "vs_original_n": 1, "vs_original_expected": 1,
            "anti_regression_ok": bool(anti), "median": median,
            "mean": median if mean is None else mean, "iqr": iqr,
            "digest": digest, "vs_original": vs_orig, "vs_base": 0.0,
            "caption_note": "", "author_placeholders": placeholders}


def census_row(counts=None, source="own"):
    """The per-version census row `{tiers: {tier: {severities: {severity: {..}}}}}`."""
    row = {"tiers": {tier: {"severities": {sev: {"own": 0, "peer": 0}
                                           for sev in SEVERITIES}}
                     for tier in np.BASIS_TIERS}}
    for (sev, tier), n in (counts or {}).items():
        row["tiers"][tier]["severities"][sev][source] = int(n)
    return row


def run_rank(stats, candidates=None, base_rep=BASE_REP, census=None, floor=10):
    return np.derive_ranking(stats, CANDIDATES if candidates is None else candidates,
                             base_rep, census or {}, floor, 2)


# =====================================================================
# A. the input contract
# =====================================================================
def test_contract():
    params = list(inspect.signature(np.derive_ranking).parameters)
    check("A1 derive_ranking's inputs are exactly the recorded data",
          params == ["stats", "candidates", "base_rep", "census", "floor", "round_no"],
          str(params))
    check("A1 derive_ranking does not take a Ctx",
          "ctx" not in params, str(params))

    tree = ast.parse(inspect.getsource(np.derive_ranking))
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"ctx", "Ctx"}:
            forbidden.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in {
                "cfg", "state", "round_get", "sandbox_of", "save_state", "load"}:
            forbidden.append(f"attribute .{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "open", "read_json", "read_text", "write_json_atomic", "write_text_atomic"}:
            forbidden.append(f"call {node.func.id}()")
    check("A1 the core reads no context, config, state or file",
          not forbidden, str(forbidden))

    sig = inspect.signature(np.select_champion)
    check("A2 select_champion keeps its public signature",
          list(sig.parameters) == ["ctx", "r", "agg", "floor"]
          and sig.parameters["floor"].default is None, str(sig))
    check("A2 the module exposes the pure core", callable(np.derive_ranking))


# =====================================================================
# B. ranking semantics
# =====================================================================
def test_semantics():
    stats = {"w1": stat(2.0), "a2": stat(1.0), BASE_REP: stat(0.0)}
    sel = run_rank(stats)
    check("B1 a complete panel ranks the higher median first",
          sel["champion"] == "w1" and sel["eligible"] == ["w1", "a2", "a1"],
          f"champion={sel['champion']} eligible={sel['eligible']}")

    # The defect prefix leads: w1 has the better panel median but one more
    # major/correctness defect, so a2 must win.
    stats = {"w1": stat(2.0), "a2": stat(1.0), BASE_REP: stat(0.0)}
    cen = {"w1": census_row({("major", "correctness"): 1}), "a2": census_row(),
           BASE_REP: census_row()}
    sel = run_rank(stats, census=cen, floor=1)
    check("B2 the adaptive defect prefix leads the panel median",
          sel["champion"] == "a2",
          f"champion={sel['champion']} ranking={[r['id'] for r in sel['ranking']]}")

    # A fatal defect is worse than a minor one even when the minor count is
    # larger: the per-cell census preserves the rung, it never collapses to a
    # total.
    stats = {"w1": stat(1.0), "a2": stat(1.0), BASE_REP: stat(0.0)}
    cen = {"w1": census_row({("fatal", "correctness"): 1}),
           "a2": census_row({("minor", "formatting"): 3}), BASE_REP: census_row()}
    # No base row here: a clean base would win the census outright and hide the
    # w1/a2 comparison this check is about.
    sel = run_rank(stats, base_rep=None, census=cen, floor=1)
    check("B3 one fatal defect loses to three minor ones",
          sel["champion"] == "a2",
          f"champion={sel['champion']} ranking={[r['id'] for r in sel['ranking']]}")

    # An exact panel-statistic tie is not improvement: the incumbent is kept even
    # when the challenger carries a better census.
    stats = {"w1": stat(1.0, mean=1.0, iqr=0.0), "a2": stat(1.0, mean=1.0, iqr=0.0),
             BASE_REP: stat(1.0, mean=1.0, iqr=0.0)}
    cen = {"w1": census_row(), "a2": census_row(),
           BASE_REP: census_row({("major", "correctness"): 1})}
    sel = run_rank(stats, census=cen, floor=1)
    check("B4 an exact (median, mean, IQR) tie retains the incumbent base",
          sel["champion"] == "a1" and sel["champion_rep"] == BASE_REP,
          f"champion={sel['champion']} rep={sel['champion_rep']}")
    check("B4 the retention is explained in the trace",
          any("incumbent base is retained" in ln for ln in sel["trace"]), str(sel["trace"]))

    # A perfect statistical tie is decided by the content digest, never the id.
    stats = {"w1": stat(1.0, digest="b" * 40), "a2": stat(1.0, digest="a" * 40),
             BASE_REP: stat(0.0)}
    sel = run_rank(stats)
    check("B5 the content digest is the final, name-free rung",
          sel["champion"] == "a2",
          f"champion={sel['champion']} (id order would pick w1)")
    check("B5 the ranking key names the provenance-free tie-break",
          any("NAME never decides" in ln for ln in sel["trace"]), str(sel["trace"])[:200])

    # Eligibility: a partial panel can never win; with no eligible row the base
    # is the answer.
    stats = {"w1": stat(3.0, complete=False), "a2": stat(1.0), BASE_REP: stat(0.0)}
    sel = run_rank(stats)
    check("B6 an incomplete panel is ineligible",
          "w1" not in sel["eligible"] and sel["champion"] == "a2",
          f"eligible={sel['eligible']} champion={sel['champion']}")
    stats = {"w1": stat(3.0, complete=False), "a2": stat(1.0, complete=False),
             BASE_REP: stat(0.0, complete=False)}
    sel = run_rank(stats)
    check("B7 no eligible row falls back to the round's base",
          sel["champion"] == "a1" and sel["ranking"] == [] and "tiebreak" not in sel,
          str(sel.get("champion")))
    check("B7 the fallback is explained", any("no eligible rows" in ln for ln in sel["trace"]))

    # A fresh arm below the pristine original is ineligible; the base is exempt
    # from that gate (it is the status quo, and the fallback must be able to
    # crown it).
    stats = {"w1": stat(3.0, anti=False, vs_orig=-1.0), "a2": stat(1.0),
             BASE_REP: stat(0.0, anti=False, vs_orig=-2.0)}
    sel = run_rank(stats)
    check("B8 a fresh arm that regresses the original is ineligible",
          "w1" not in sel["eligible"] and sel["champion"] == "a2",
          f"eligible={sel['eligible']}")
    check("B8 the base is exempt from the anti-regression gate",
          sel["eligible"] == ["a2", "a1"], str(sel["eligible"]))

    # floor 0 disables the prefix: the panel statistics decide even when the
    # leader carries more defects.
    stats = {"w1": stat(2.0), "a2": stat(1.0), BASE_REP: stat(0.0)}
    cen = {"w1": census_row({("major", "correctness"): 5}), "a2": census_row(),
           BASE_REP: census_row()}
    sel = run_rank(stats, census=cen, floor=0)
    check("B9 floor 0 disables the defect prefix (the panel statistics decide)",
          sel["champion"] == "w1" and sel["tiebreak"]["cells_used"] == 0,
          f"champion={sel['champion']} cells={sel['tiebreak']['cells_used']}")

    # The core must not mutate the recorded inputs it ranks.
    stats = {"w1": stat(2.0), "a2": stat(1.0), BASE_REP: stat(0.0)}
    cen = {"w1": census_row({("major", "correctness"): 1}), "a2": census_row(),
           BASE_REP: census_row()}
    before = (copy.deepcopy(stats), copy.deepcopy(cen))
    run_rank(stats, census=cen, floor=1)
    check("B10 the core does not mutate its inputs", (stats, cen) == before)


def test_adapter():
    """`select_champion` resolves the structural inputs and delegates the order."""
    stats = {"w1": stat(2.0), "a2": stat(1.0), BASE_REP: stat(0.0)}
    agg = {"stats": stats, "base_rep": BASE_REP, "issue_census": {}}
    calls = {}
    originals = (np.round_candidate_ids_run, np.tiebreak_defect_floor_of,
                 np.candidate_tiebreak_inputs, np.derive_ranking)
    real_core = np.derive_ranking

    def spy(core_stats, candidates, base_rep, census, floor, round_no):
        calls.update(stats=core_stats, candidates=candidates, base_rep=base_rep,
                     census=census, floor=floor, round_no=round_no)
        return real_core(core_stats, candidates, base_rep, census, floor, round_no)

    try:
        np.round_candidate_ids_run = lambda ctx, r: ["w1", "a2"]
        np.tiebreak_defect_floor_of = lambda ctx: 10
        np.candidate_tiebreak_inputs = lambda ctx, r, cid: (4, 5, 6)
        np.derive_ranking = spy
        sel = np.select_champion(object(), 2, agg)
    finally:
        (np.round_candidate_ids_run, np.tiebreak_defect_floor_of,
         np.candidate_tiebreak_inputs, np.derive_ranking) = originals
    check("C1 the adapter passes the recorded inputs to the core",
          calls.get("candidates") == ["w1", "a2"] and calls.get("base_rep") == BASE_REP
          and calls.get("floor") == 10 and calls.get("round_no") == 2,
          str({k: calls.get(k) for k in ("candidates", "base_rep", "floor", "round_no")}))
    check("C1 the adapter does not decide the order itself",
          sel["champion"] == "w1", sel["champion"])
    row = next((r for r in sel["ranking"] if r["id"] == "w1"), {})
    check("C2 the adapter attaches the REPORTED-only tiebreak inputs",
          (row.get("critical_remaining"), row.get("writing_remaining"),
           row.get("manual_steps")) == (4, 5, 6), str(row))
    check("C2 those values are reported in the trace, not ranked",
          any("critical_remaining=4" in ln for ln in sel["trace"]), str(sel["trace"])[:160])


# =====================================================================
# D. the loader's name-space guard
# =====================================================================
def test_no_shadowing():
    def target_names(target):
        """Every Name bound by one assignment target (`a = b = 1`, `a, b = ...`)."""
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            return [n for elt in target.elts for n in target_names(elt)]
        if isinstance(target, ast.Starred):
            return target_names(target.value)
        return []

    dups = []
    # The two loaders are separate namespaces: a name may exist in both, but not
    # twice in ONE ordered bundle (a later part would silently shadow it).
    for dirname in ("paper_pipeline_parts", "paper_docx_format_parts"):
        seen = {}
        for part in sorted((WS / dirname).glob("p[0-9][0-9]_*.py")):
            for node in ast.parse(part.read_text(encoding="utf-8")).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names = [node.name]
                elif isinstance(node, ast.Assign):
                    names = [name for t in node.targets for name in target_names(t)]
                elif isinstance(node, ast.AnnAssign):
                    names = target_names(node.target)
                else:
                    continue
                for name in names:
                    if name in seen:
                        dups.append(f"{dirname}: {name} ({seen[name]} + {part.name})")
                    else:
                        seen[name] = part.name
    check("D1 no top-level name is defined twice in one ordered bundle",
          not dups, "; ".join(dups[:8]))


def main() -> int:
    test_contract()
    test_semantics()
    test_adapter()
    test_no_shadowing()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL RANKING-CORE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
