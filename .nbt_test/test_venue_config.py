#!/usr/bin/env python3
"""Venue and journal configuration: `set-venue`, `set-journal`, and every
stage reading the configured values instead of a hard-coded Nature
Biotechnology.

Run:  python3 .nbt_test/test_venue_config.py

Asserts:
  * the shipped profiles (`venue_profiles/*.json`) load, agree with the
    built-in fallback inside nbt_pipeline.py, and carry the numbers they claim:
    nature-biotechnology = 150/3,000 -> 172/3,750, generic = no caps,
    example-journal = 250/5,000 -> 275/6,000 with a 250-word legend cap;
  * `setup --venue/--journal` records the selection in pipeline_config.json
    (plus the resolved profile snapshot) and mirrors it into state.json;
  * `set-venue` / `set-journal` persist the same way, `--list`, `--show`,
    `--json` and `--profile` work, and a profile whose id does not match the
    requested venue is refused;
  * precedence: the config (and its snapshot) wins over the profile FILES, the
    profile's `default_journal` fills a missing journal, and a root with no
    `venue` key keeps the pre-venue default (backward compatibility);
  * missing / invalid / inconsistent configurations are reported the way the
    documentation says: unknown venue ids are refused with the available list,
    an invalid profile lists every schema problem, a journal outside the
    profile's journals warns (and is fatal under --strict-venue), and a venue
    change on a root that already has runs needs --force;
  * all six prompt builders render the configured venue (no default-venue text
    and no unresolved @@TOKEN@@ for a non-default venue), the M19 caps move with
    the profile, and a limit-less profile produces counts with cap=None and no
    "over the cap".

`NBT_WS` retargets the suite at another copy of the tree.
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

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_venue", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_venue"] = nb
spec.loader.exec_module(nb)

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


def run_cli(*argv, cwd=None):
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *map(str, argv)],
                          capture_output=True, text=True, cwd=str(cwd or WS))


def setup_root(tmp: Path, *extra, name: str = "root") -> Path:
    """A real (tiny) pipeline root, created with `setup`."""
    src = tmp / "src"
    write(src / "ms.md",
          "Abstract\n\n" + ("word " * 20).strip() + "\n\nIntroduction\n\n"
          + ("text " * 50).strip() + "\n\nMethods\n\nx\n")
    root = tmp / name
    proc = run_cli("setup", "--source", src, "--root", root, "--rounds", "1", "--judges", "1",
                   "--rewrites", "1", "--revises", "0", "--format-fix", "off", "--zotero", "off",
                   *extra)
    check(f"setup succeeded ({name})", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-300:])
    return root


def cfg_of(root: Path) -> dict:
    return json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))


def state_of(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def all_prompts(venue=None) -> dict:
    sb = Path("/tmp/nbt_venue_prompt")
    return {
        "review": nb.review_prompt(sb, "r1_review", 1, venue=venue),
        "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1, venue=venue),
        "revise": nb.revise_prompt(sb, "r1_a2_revise", 1, venue=venue),
        "audit": nb.audit_prompt(sb, "r1_audit", 1, venue=venue),
        "integrate": nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"], venue=venue),
        "judge": nb.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"], venue=venue),
    }


# =====================================================================
# VC1 — the profiles themselves
# =====================================================================

def test_profiles():
    print()
    print("== VC1: the shipped profiles, the built-ins and their numbers ==")
    avail = nb.available_venue_profiles()
    for vid in ("nature-biotechnology", "generic", "example-journal"):
        check(f"VC1 {vid} is visible to `set-venue --list`", vid in avail,
              str(sorted(avail)))
    nbt = nb.load_venue_profile("nature-biotechnology")
    limits = nbt.length_limits()
    check("VC1 the default profile carries the pipeline's old Article numbers",
          limits["abstract"] == {"base": 150, "relaxation": 1.15, "cap": 172}
          and limits["main text"] == {"base": 3000, "relaxation": 1.25, "cap": 3750},
          str(limits))
    check("VC1 the default profile's journal is Nature Biotechnology",
          nbt.default_journal == "Nature Biotechnology" and nbt.journal_matches("NBT")
          and not nbt.journal_matches("Cell"), str(nbt.default_journal))
    generic = nb.load_venue_profile("generic")
    check("VC1 the generic profile declares no caps",
          generic.length_limits()["abstract"]["cap"] is None
          and generic.length_limits()["main text"]["cap"] is None
          and generic.journal_matches("Any Journal") and generic.default_journal == "",
          str(generic.length_limits()))
    example = nb.load_venue_profile("example-journal")
    check("VC1 the example profile exercises a published legend cap and no cover-letter rule",
          example.length_limits()["abstract"]["cap"] == 275
          and example.length_limits()["main text"]["cap"] == 6000
          and example.length_limits()["cover letter"]["min"] is None
          and example.caption_default == 250, str(example.length_limits()))
    # The JSON files and the built-in fallback must not drift apart: a stripped
    # single-file copy and a full checkout have to enforce the same rules.
    for vid in ("nature-biotechnology", "generic"):
        shipped = json.loads((WS / "venue_profiles" / f"{vid}.json").read_text(encoding="utf-8"))
        check(f"VC1 {vid}.json matches the built-in fallback",
              nb.normalize_venue_profile(shipped) == nb.normalize_venue_profile(
                  nb.BUILTIN_VENUE_PROFILES[vid]), vid)
    check("VC1 length_limits() without an argument is the default venue",
          nb.length_limits() == limits)
    check("VC1 the constants kept for compatibility still match the profile",
          nb.NBT_ARTICLE_ABSTRACT_WORDS == 150 and nb.NBT_ARTICLE_MAIN_TEXT_WORDS == 3000
          and nb.NBT_ARTICLE_ABSTRACT_CAP == 172 and nb.NBT_ARTICLE_MAIN_TEXT_CAP == 3750)


# =====================================================================
# VC2 — setup records the selection; set-venue / set-journal persist it
# =====================================================================

def test_configuration_and_persistence():
    print()
    print("== VC2: configuration storage, precedence and persistence ==")
    tmp = scratch("nbt_venue_cfg_")
    root = setup_root(tmp, "--venue", "nature-biotechnology", "--journal", "Nature Biotechnology")
    cfg = cfg_of(root)
    check("VC2 setup records the venue id", cfg.get("venue") == "nature-biotechnology",
          str(cfg.get("venue")))
    check("VC2 setup records the journal", cfg.get("journal") == "Nature Biotechnology")
    snap = cfg.get("venue_profile") or {}
    check("VC2 setup records the resolved profile snapshot",
          snap.get("id") == "nature-biotechnology"
          and snap.get("length_limits", {}).get("abstract", {}).get("base") == 150,
          str(snap)[:160])
    check("VC2 the state mirror carries the same venue",
          (state_of(root).get("config") or {}).get("venue") == "nature-biotechnology")
    check("VC2 setup copies the profile directory into the root",
          (root / "venue_profiles" / "generic.json").is_file())

    proc = run_cli("set-venue", "--root", root, "generic")
    check("VC2 set-venue succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    cfg = cfg_of(root)
    check("VC2 set-venue persists the new venue", cfg.get("venue") == "generic")
    check("VC2 set-venue re-records the snapshot", (cfg.get("venue_profile") or {}).get("id")
          == "generic", str(cfg.get("venue_profile"))[:120])
    check("VC2 set-venue keeps an explicitly set journal that the old profile described",
          cfg.get("journal") == "Nature Biotechnology", str(cfg.get("journal")))
    check("VC2 the state mirror follows the config",
          (state_of(root).get("config") or {}).get("venue") == "generic")

    proc = run_cli("set-journal", "--root", root, "Another Journal")
    check("VC2 set-journal succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    check("VC2 set-journal persists the journal",
          cfg_of(root).get("journal") == "Another Journal"
          and (state_of(root).get("config") or {}).get("journal") == "Another Journal")
    check("VC2 set-journal leaves the venue alone", cfg_of(root).get("venue") == "generic")
    proc = run_cli("set-venue", "--root", root, "--journal", "Third Journal")
    check("VC2 `set-venue --journal` without a venue id changes only the journal",
          proc.returncode == 0 and cfg_of(root).get("journal") == "Third Journal"
          and cfg_of(root).get("venue") == "generic", (proc.stdout + proc.stderr)[-200:])

    # `set-venue` adopts the NEW profile's default journal when the current one
    # only came from the OLD profile's default; a journal the operator typed is
    # kept instead.
    root2 = setup_root(tmp, "--venue", "nature-biotechnology", name="root2")
    check("VC2 setup's journal comes from the profile default",
          cfg_of(root2).get("journal") == "Nature Biotechnology"
          and cfg_of(root2).get("journal_source") == "profile-default",
          str(cfg_of(root2).get("journal_source")))
    run_cli("set-venue", "--root", root2, "generic")
    check("VC2 a profile-default journal moves with the venue",
          cfg_of(root2).get("journal") == "" and cfg_of(root2).get("journal_source") == "unset",
          str({k: cfg_of(root2).get(k) for k in ("journal", "journal_source")}))
    run_cli("set-journal", "--root", root2, "Cell")
    run_cli("set-venue", "--root", root2, "nature-biotechnology")
    check("VC2 an operator-set journal is kept across a venue change",
          cfg_of(root2).get("journal") == "Cell"
          and cfg_of(root2).get("venue") == "nature-biotechnology")

    show = run_cli("set-venue", "--root", root, "--show", "--json")
    try:
        data = json.loads(show.stdout)
    except ValueError:
        data = {}
    check("VC2 `set-venue --show --json` reports the resolved values",
          data.get("venue") == cfg_of(root).get("venue")
          and data.get("journal") == cfg_of(root).get("journal")
          and (data.get("length_limits") or {}).get("abstract", {}).get("cap") is None,
          str(data)[:200])
    listed = run_cli("set-venue", "--list", "--json")
    try:
        venues = {v["id"] for v in json.loads(listed.stdout)["venues"]}
    except (ValueError, KeyError, TypeError):
        venues = set()
    check("VC2 `set-venue --list --json` lists the venues",
          {"generic", "nature-biotechnology"} <= venues, str(sorted(venues)))
    status = run_cli("status", "--root", root)
    check("VC2 status prints the venue, the journal and the limits",
          status.returncode == 0 and "venue:" in status.stdout
          and "generic" in status.stdout
          and "Third Journal" in status.stdout, status.stdout[:240])


# =====================================================================
# VC3 — a custom profile: install, id mismatch, invalid schema
# =====================================================================

def custom_profile(vid="custom-clin-journal", **over):
    data = {
        "id": vid,
        "label": "Custom Clinical Journal",
        "short": "CCJ",
        "article_type": "Original Research",
        "journals": ["Custom Clinical Journal"],
        "default_journal": "Custom Clinical Journal",
        "length_limits": {
            "source": "Custom Clinical Journal author instructions (fixture)",
            "abstract": {"base": 250, "relaxation": 1.1},
            "main_text": {"base": 4000, "relaxation": 1.1},
            "cover_letter": {"min": None, "max": None, "source": "no cover-letter limit"},
        },
        "captions": {"published_limit": 200, "default_cap": 200,
                     "source": "the journal limits each legend to 200 words"},
        "submission": {"pdf_accepted": True, "formats": ["PDF"], "pdf_note": "PDF accepted"},
        "prompt": {"subject": "a Custom Clinical Journal original-research submission",
                   "editor": "a Custom Clinical Journal editor or reviewer",
                   "requirements": "the Custom Clinical Journal author instructions",
                   "requirement_authority": "the Custom Clinical Journal instructions",
                   "guidelines_source": "the Custom Clinical Journal author instructions"},
    }
    data.update(over)
    return data


def test_custom_profile():
    print()
    print("== VC3: installing a profile of your own ==")
    tmp = scratch("nbt_venue_custom_")
    root = setup_root(tmp, "--venue", "generic", "--journal", "Custom Clinical Journal")
    prof_file = tmp / "custom-clin-journal.json"
    write(prof_file, json.dumps(custom_profile(), indent=2))
    proc = run_cli("set-venue", "--root", root, "--profile", prof_file, "custom-clin-journal")
    check("VC3 set-venue --profile installs and selects the profile", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-300:])
    installed = root / "venue_profiles" / "custom-clin-journal.json"
    check("VC3 the profile is written into the root (root-local, travels with it)",
          installed.is_file(), str(installed))
    cfg = cfg_of(root)
    check("VC3 the config records the custom venue and its snapshot",
          cfg.get("venue") == "custom-clin-journal"
          and (cfg.get("venue_profile") or {}).get("length_limits", {})
          .get("abstract", {}).get("base") == 250, str(cfg.get("venue_profile"))[:120])
    ctx = nb.Ctx(root)
    ctx.load()
    prof = nb.venue_profile_of(ctx)
    prompts = all_prompts(prof)
    check("VC3 the prompts carry the custom profile's own numbers",
          all("275" in t and "4400" in t for k, t in prompts.items() if k != "audit"),
          {k: ("275" in t, "4400" in t) for k, t in prompts.items()})
    check("VC3 the prompts no longer read as a Nature Biotechnology submission",
          all("Nature Biotechnology" not in t for t in prompts.values())
          and all("Custom Clinical Journal" in t for t in prompts.values()))
    check("VC3 the M19 rule quotes the custom source",
          "Custom Clinical Journal author instructions (fixture)" in prompts["review"])
    check("VC3 a published legend cap becomes the default caption limit",
          nb.caption_limit_of(ctx) == 200)
    check("VC3 the no-cover-letter profile drops the preference rule",
          "NO COVER-LETTER PREFERENCE IS CONFIGURED" in prompts["review"])
    # The journal now matches the profile: no inconsistency is reported.
    check("VC3 the matching journal produces no venue problem", not ctx.venue_problems,
          str(ctx.venue_problems))

    bad_id = tmp / "wrong-name.json"
    write(bad_id, json.dumps(custom_profile("some-other-id")))
    proc = run_cli("set-venue", "--root", root, "--profile", bad_id, "custom-clin-journal")
    check("VC3 a profile whose id does not match the requested venue is refused",
          proc.returncode != 0 and "declares id" in (proc.stdout + proc.stderr),
          (proc.stdout + proc.stderr)[-200:])
    bad = tmp / "bad.json"
    write(bad, json.dumps({"id": "bad-profile",
                           "length_limits": {"abstract": {"base": 0, "relaxation": 0.9},
                                             "main_text": {"base": 100}},
                           "journal_patterns": ["("]}))
    proc = run_cli("set-venue", "--root", root, "--profile", bad, "bad-profile")
    listed = proc.stdout + proc.stderr
    check("VC3 an invalid profile is refused with every schema problem",
          proc.returncode != 0 and "must be >= 1" in listed and "together" in listed
          and "regular expression" in listed, listed[-400:])
    check("VC3 ... and nothing was written for it",
          not (root / "venue_profiles" / "bad-profile.json").exists()
          and cfg_of(root).get("venue") == "custom-clin-journal")


# =====================================================================
# VC4 — missing, invalid and inconsistent configuration
# =====================================================================

def test_missing_invalid_inconsistent():
    print()
    print("== VC4: missing / invalid / inconsistent configuration ==")
    tmp = scratch("nbt_venue_missing_")
    # A root whose pipeline_config.json has no venue/journal at all: the
    # pre-venue behaviour, which is exactly the default venue.
    root = tmp / "legacy"
    root.mkdir(parents=True)
    write(root / "pipeline_config.json", json.dumps({"rounds": 1, "source": "/tmp/x"}))
    write(root / "state.json", json.dumps({"version": nb.STATE_VERSION, "runs": {},
                                           "rounds": {}, "pinned": [], "log": []}))
    ctx = nb.Ctx(root)
    ctx.load()
    check("VC4 a config without `venue` keeps the pre-venue default",
          nb.venue_id_of(ctx) == nb.DEFAULT_VENUE
          and nb.journal_of(ctx) == "Nature Biotechnology", nb.venue_summary(ctx))
    check("VC4 ... and says so", any("no venue recorded" in n for n in ctx.venue_notes),
          str(ctx.venue_notes))
    prompts = all_prompts(nb.venue_profile_of(ctx))
    check("VC4 ... and its prompts are the old Nature Biotechnology ones",
          "Nature Biotechnology" in prompts["review"] and "172" in prompts["review"])
    status = run_cli("status", "--root", root)
    check("VC4 status still works on a legacy root", status.returncode == 0, status.stdout[-200:])

    # An unknown venue id: listed by status, fatal for a command that renders
    # prompts, and fixable with set-venue.
    write(root / "pipeline_config.json",
          json.dumps({"rounds": 1, "venue": "no-such-venue"}))
    ctx = nb.Ctx(root)
    ctx.load()
    check("VC4 an unknown venue is reported", any("unknown venue" in p for p in ctx.venue_problems),
          str(ctx.venue_problems))
    check("VC4 the message lists the available venues",
          any("generic" in p and "nature-biotechnology" in p for p in ctx.venue_problems))
    strict = run_cli("status", "--root", root, "--strict-venue")
    check("VC4 --strict-venue refuses to run on it", strict.returncode != 0)
    bad_set = run_cli("set-venue", "--root", root, "no-such-venue")
    check("VC4 set-venue refuses an unknown id and lists what exists",
          bad_set.returncode != 0 and "unknown venue" in (bad_set.stdout + bad_set.stderr)
          and "generic" in (bad_set.stdout + bad_set.stderr),
          (bad_set.stdout + bad_set.stderr)[-200:])
    check("VC4 set-venue on a directory without pipeline_config.json is a usage error",
          run_cli("set-venue", "--root", tmp / "not-a-root", "generic").returncode == 2)

    # Missing journal + a journal outside the profile: both documented.
    run_cli("set-venue", "--root", root, "generic", "--force")
    ctx = nb.Ctx(root)
    ctx.load()
    check("VC4 a profile with no default journal reports the missing journal",
          any("no journal configured" in p for p in ctx.venue_problems), str(ctx.venue_problems))
    check("VC4 the prompts then say 'the target journal'",
          "the target journal" in all_prompts(nb.venue_profile_of(ctx))["review"])
    proc = run_cli("set-venue", "--root", root, "nature-biotechnology", "--force",
                   "--journal", "Cell")
    check("VC4 a journal outside the profile's journals warns but applies",
          proc.returncode == 0 and "is not one of the journals" in proc.stdout,
          proc.stdout[-200:])
    ctx = nb.Ctx(root)
    ctx.load()
    check("VC4 ... and is a problem the strict mode refuses",
          any("not one of the journals" in p for p in ctx.venue_problems))
    strict = run_cli("status", "--root", root, "--strict-venue")
    check("VC4 --strict-venue exits non-zero on the mismatch", strict.returncode != 0,
          strict.stdout[-160:])
    strict_j = run_cli("set-journal", "--root", root, "--strict-venue", "Cell")
    check("VC4 set-journal --strict-venue refuses the same mismatch", strict_j.returncode != 0,
          (strict_j.stdout + strict_j.stderr)[-160:])

    # The config file wins over the recorded snapshot, and over state.json.
    cfg = cfg_of(root)
    cfg["venue"] = "generic"
    write(root / "pipeline_config.json", json.dumps(cfg))
    ctx = nb.Ctx(root)
    ctx.load()
    check("VC4 a config/snapshot disagreement is reported",
          any("recorded profile snapshot names venue" in p for p in ctx.venue_problems),
          str(ctx.venue_problems))
    check("VC4 ... and the config file wins", nb.venue_id_of(ctx) == "generic")

    # A profile file that IS there but cannot be used is reported as a profile
    # problem (with the fix), not as an unknown venue.
    broken = setup_root(tmp, "--venue", "generic", name="broken")
    write(broken / "venue_profiles" / "brokenven.json", "{ not json")
    cfg = cfg_of(broken)
    cfg["venue"] = "brokenven"
    write(broken / "pipeline_config.json", json.dumps(cfg))
    ctx = nb.Ctx(broken)
    ctx.load()
    check("VC4 a present but unreadable profile is reported with its parse error",
          any("cannot be used" in p and "not readable JSON" in p for p in ctx.venue_problems),
          str(ctx.venue_problems))
    check("VC4 ... and the command that must render a prompt refuses to run",
          run_cli("run", "--root", broken).returncode != 0)


# =====================================================================
# VC5 — changing the venue of a root that already ran; profiles win/lose
# =====================================================================

def test_force_and_snapshot_precedence():
    print()
    print("== VC5: mid-flight changes, --force and the snapshot ==")
    tmp = scratch("nbt_venue_force_")
    root = setup_root(tmp, "--venue", "nature-biotechnology")
    st = state_of(root)
    st.setdefault("runs", {})["r1_w1"] = {"id": "r1_w1", "kind": "rewrite", "round": 1,
                                          "status": "done", "sandbox": "runs/r1_w1"}
    write(root / "state.json", json.dumps(st))
    proc = run_cli("set-venue", "--root", root, "generic")
    check("VC5 a venue change on a root with runs needs --force",
          proc.returncode != 0 and "--force" in (proc.stdout + proc.stderr)
          and cfg_of(root).get("venue") == "nature-biotechnology",
          (proc.stdout + proc.stderr)[-200:])
    proc = run_cli("set-venue", "--root", root, "generic", "--force")
    check("VC5 --force applies it", proc.returncode == 0 and cfg_of(root).get("venue") == "generic")
    proc = run_cli("set-journal", "--root", root, "Cell")
    check("VC5 a journal change on such a root needs --force too", proc.returncode != 0)
    check("VC5 ... and --force applies it",
          run_cli("set-journal", "--root", root, "Cell", "--force").returncode == 0
          and cfg_of(root).get("journal") == "Cell")

    # Editing the profile FILE must not change an existing root: the snapshot wins.
    installed = root / "venue_profiles" / "generic.json"
    data = json.loads(installed.read_text(encoding="utf-8"))
    data["length_limits"]["main_text"] = {"base": 1234, "relaxation": 2.0}
    data["label"] = "Edited Generic"
    write(installed, json.dumps(data))
    ctx = nb.Ctx(root)
    ctx.load()
    prof = nb.venue_profile_of(ctx)
    check("VC5 the recorded snapshot wins over an edited profile file",
          prof.label == "generic venue (no venue-specific rules)"
          and "1234 words" not in nb.length_rule_text(prof), nb.venue_summary(ctx))
    check("VC5 re-running set-venue re-records it",
          run_cli("set-venue", "--root", root, "generic", "--force").returncode == 0)
    ctx2 = nb.Ctx(root)
    ctx2.load()
    check("VC5 ... and then the edit is in force",
          nb.venue_profile_of(ctx2).label == "Edited Generic",
          nb.venue_summary(ctx2))
    # An unparseable / invalid file in the root is reported by --list instead of
    # being silently skipped.
    write(root / "venue_profiles" / "broken.json", "{not json")
    listed = run_cli("set-venue", "--root", root, "--list")
    check("VC5 an unparseable profile file is listed as INVALID",
          "broken" in listed.stdout and "INVALID" in listed.stdout, listed.stdout[-200:])


# =====================================================================
# VC6 — the scans and the prompts follow the profile
# =====================================================================

def test_scans_and_prompts():
    print()
    print("== VC6: stages read the configured values ==")
    tmp = scratch("nbt_venue_scan_")
    write(tmp / "ms.md",
          "Abstract\n\n" + ("word " * 200).strip() + "\n\nKeywords: a, b.\n\nIntroduction\n\n"
          + ("text " * 4000).strip() + "\n\nMethods\n\nx\n")
    default_info = nb.scan_lengths_in_sources([(tmp, "", ())])
    abstract = [r for r in default_info["rows"] if r["section"] == "abstract"][0]
    check("VC6 the default scan flags the 200-word abstract against 172",
          abstract["cap"] == 172 and abstract["over_limit"] is True, str(abstract))
    generic = nb.load_venue_profile("generic")
    generic_info = nb.scan_lengths_in_sources([(tmp, "", ())], profile=generic)
    abstract_g = [r for r in generic_info["rows"] if r["section"] == "abstract"][0]
    check("VC6 a limit-less profile counts the same words with no cap",
          abstract_g["cap"] is None and abstract_g["over_limit"] is False
          and abstract_g["words"] == 200, str(abstract_g))
    check("VC6 the scan records which venue produced it",
          generic_info["venue"] == "generic" and "no number" in generic_info["source"])
    note = nb.length_note(generic_info)
    check("VC6 the note says there is no cap instead of inventing one",
          "no venue cap configured" in note and "OVER" not in note, note)
    example = nb.load_venue_profile("example-journal")
    example_info = nb.scan_lengths_in_sources([(tmp, "", ())], profile=example)
    abstract_e = [r for r in example_info["rows"] if r["section"] == "abstract"][0]
    check("VC6 the example profile's 275-word cap applies instead",
          abstract_e["cap"] == 275 and abstract_e["over_limit"] is False, str(abstract_e))
    check("VC6 the cover-letter rule follows the profile",
          example_info["limits"]["cover letter"]["min"] is None
          and example_info["limits"]["cover letter"]["max"] is None
          and "no cover-letter word limit" in nb.length_rule_text(example)
          and nb.length_rule_text(example).count("NO COVER-LETTER PREFERENCE") == 1)

    prompts = all_prompts(generic)
    check("VC6 no prompt of a non-default venue names Nature Biotechnology",
          all("Nature Biotechnology" not in t for t in prompts.values()))
    for name, text in prompts.items():
        unresolved = sorted(set(re.findall(r"@@[A-Z_0-9]+@@", text)))
        check(f"VC6 the {name} prompt has no unresolved @@TOKEN@@", not unresolved,
              str(unresolved[:4]))
    check("VC6 the M19 mandates state that no cap is configured",
          "this venue profile sets no abstract or main-text cap" in prompts["review"]
          and "do NOT compress" in prompts["revise"]
          and "no cap" in prompts["integrate"])
    check("VC6 the caption rule of a profile without a legend number says so",
          "GENERIC" not in prompts["review"] and "figure-legend length rule" in prompts["review"])
    check("VC6 the default venue keeps its numbers and its branding",
          "172" in all_prompts()["review"] and "Nature Biotechnology" in all_prompts()["review"])


# =====================================================================
# VC7 — the bundled skill script reads the same profile
# =====================================================================

def test_skill_script():
    print()
    print("== VC7: the bundled count_words.py follows the profile ==")
    tmp = scratch("nbt_venue_words_")
    write(tmp / "ms.md",
          "Abstract\n\n" + ("word " * 200).strip() + "\n\nIntroduction\n\n"
          + ("text " * 4000).strip() + "\n\nMethods\n\nx\n")
    script = WS / "nbt-skills" / "nbt-review" / "scripts" / "count_words.py"
    if not script.is_file():
        check("VC7 count_words.py is present", False, str(script))
        return
    proc = subprocess.run([sys.executable, str(script), str(tmp / "ms.md"), "--json"],
                          capture_output=True, text=True)
    default = json.loads(proc.stdout)
    check("VC7 without a profile it uses the default Article caps",
          default["caps"] == {"abstract": 172, "main text": 3750}, str(default["caps"]))
    proc = subprocess.run([sys.executable, str(script), str(tmp / "ms.md"), "--json",
                           "--venue-profile", str(WS / "venue_profiles" / "generic.json")],
                          capture_output=True, text=True)
    generic = json.loads(proc.stdout)
    check("VC7 with the generic profile it reports no caps and no over-cap row",
          generic["caps"] == {"abstract": None, "main text": None}
          and all(not row["over_limit"] for row in generic["rows"]), str(generic)[:200])
    proc = subprocess.run([sys.executable, str(script), str(tmp / "ms.md"), "--json",
                           "--venue-profile",
                           str(WS / "venue_profiles" / "example-journal.json")],
                          capture_output=True, text=True)
    example = json.loads(proc.stdout)
    check("VC7 with the example profile it uses that profile's caps",
          example["caps"] == {"abstract": 275, "main text": 6000}, str(example["caps"]))


def main() -> int:
    try:
        test_profiles()
        test_configuration_and_persistence()
        test_custom_profile()
        test_missing_invalid_inconsistent()
        test_force_and_snapshot_precedence()
        test_scans_and_prompts()
        test_skill_script()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL VENUE-CONFIGURATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
