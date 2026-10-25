#!/usr/bin/env python3
"""M4 also enumerates lower/upper ranges printed in descending order.

An interval is not only a CI: a unit-bearing physical range such as an
elevation, depth, time or concentration range is ordered the same way. The
review sweep previously left integer unit ranges to attention and caught only
decimal CIs, so a reversed physical range could survive. The M4 artifact now
carries a triage row for every same-unit pair whose first value is greater than
its second; the reviewer disposes each row (a directional sequence can be
legitimate, so this is not an automatic finding).

Run:  python3 .paper_test/test_number_range_2026_1025.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SCRIPT = WS / "paper-skills" / "paper-review" / "scripts" / "extract_numbers.py"
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="paper_range_"))
    try:
        corpus = tmp / "work" / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "ms.md.txt").write_text(
            "## Results\n"
            "Elevation from 900 m to 120 m and light from 9.8 to 24.6 mol.\n"
            "An ordered range from 120 m to 900 m is fine.\n"
            "A directional sequence from 2020 to 2019 has no unit.\n",
            encoding="utf-8")
        proc = subprocess.run([sys.executable, str(SCRIPT), "--work", str(tmp / "work")],
                              capture_output=True, text=True)
        check("the numbers sweep runs", proc.returncode == 0, proc.stderr[-300:])
        art = tmp / "artifacts" / "M4_numbers.json"
        payload = json.loads(art.read_text(encoding="utf-8")) if art.is_file() else {}
        rows = payload.get("descending_ranges") or []
        check("the descending unit range is enumerated",
              any(r.get("low") == "900" and r.get("high") == "120"
                  and r.get("unit") == "m" for r in rows), str(rows)[:500])
        check("the ordered range is not reported",
              not any(r.get("low") == "120" and r.get("high") == "900" for r in rows),
              str(rows)[:500])
        check("a unitless directional sequence is not misread as a range",
              not any("2020" in str(r.get("low")) for r in rows), str(rows)[:500])
        md = (tmp / "artifacts" / "M4_numbers.md").read_text(encoding="utf-8")
        check("the artifact gives the reviewer the triage section",
              "Descending numeric ranges" in md and "900" in md, md[-500:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("M4 RANGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
