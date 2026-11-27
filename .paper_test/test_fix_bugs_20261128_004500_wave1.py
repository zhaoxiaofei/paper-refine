#!/usr/bin/env python3
"""Regression checks for the 2026-11-28 004500 fix-bugs wave (wave 1).

One check block per confirmed candidate (F01-F05). Every fixture is a temp dir
under the system temp root; no network, no Word/Office, no repo writes. The F01
block runs the real CLI in a subprocess because the defect is in the shared
loader's side effects.

Run:  python3 .paper_test/test_fix_bugs_20261128_004500_wave1.py
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1128wave1_pp", "paper_pipeline.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# A real 1x1 white JPEG and a real 1x1 white TIFF, generated once with
# ImageMagick and embedded so the check needs no image library or external tool.
_REAL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsO"
    "CwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
    "AAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q==")
_REAL_TIFF = base64.b64decode(
    "SUkqAAoAAAD//w8AAAEDAAEAAAABAAAAAQEDAAEAAAABAAAAAgEDAAEAAAAQAAAAAwEDAAEAAAABAAAABgEDAAEA"
    "AAABAAAACgEDAAEAAAABAAAAEQEEAAEAAAAIAAAAEgEDAAEAAAABAAAAFQEDAAEAAAABAAAAFgEDAAEAAAABAAAA"
    "FwEEAAEAAAACAAAAHAEDAAEAAAABAAAAKQEDAAIAAAAAAAEAPgEFAAIAAAD0AAAAPwEFAAYAAADEAAAAAAAAAIXr"
    "UQAAAIAAw/WoAAAAAALNzEwAAAAAAc3MTAAAAIAAzcxMAAAAAAKPwvUAAAAAEDcaoAAAAAACK4cKAAAAIAA=")


def _root(tmp: Path) -> Path:
    root = tmp / "root"
    root.mkdir()
    (root / "pipeline_config.json").write_text(json.dumps({
        "rounds": 1, "judges": [1], "venue": "nature-biotechnology",
        "source": "/nonexistent"}), encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": [],
        "source": "/nonexistent", "config": {}, "judge_salt": "abcd1234"}),
        encoding="utf-8")
    return root


def _run_cli(*args):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *args],
                          cwd=str(WS), capture_output=True, text=True, timeout=180)


def test_f01_read_only_commands():
    print("\n== F01: read-only commands do not create runs/ or reports/ ==")
    tmp = Path(tempfile.mkdtemp())
    try:
        root = _root(tmp)

        def snapshot(r):
            # Directories are the point: the defect creates `runs/` and
            # `reports/`, so a file-only snapshot cannot observe it (R01).
            return {p.name: b"<dir>" if p.is_dir() else p.read_bytes()
                    for p in r.iterdir()}

        before = snapshot(root)
        r = _run_cli("status", "--root", str(root))
        after = snapshot(root)
        check("F01 status succeeds without creating files or directories",
              r.returncode == 0 and before == after, f"rc={r.returncode} {list(before)}->{list(after)}")
        r = _run_cli("agents", "--root", str(root))
        after2 = snapshot(root)
        check("F01 agents succeeds without creating files or directories",
              r.returncode == 0 and before == after2,
              f"rc={r.returncode} {list(before)}->{list(after2)} {r.stderr[-300:]}")
        # The 0555 check needs a root no earlier writable-root call has
        # touched: on the baseline the calls above already create `runs/` and
        # `reports/`, so re-chmodding this root would hide the PermissionError
        # the check exists to catch (R01).
        ro_tmp = tmp / "ro"
        ro_tmp.mkdir()
        ro_root = _root(ro_tmp)
        ro_before = snapshot(ro_root)
        ro_root.chmod(0o555)
        try:
            rs = _run_cli("status", "--root", str(ro_root))
            ra = _run_cli("agents", "--root", str(ro_root))
            ro_after = snapshot(ro_root)
        finally:
            ro_root.chmod(0o755)
        check("F01 status succeeds on a 0555 root without runs/reports",
              rs.returncode == 0 and ro_before == ro_after,
              f"rc={rs.returncode} {list(ro_before)}->{list(ro_after)} {rs.stderr[-300:]}")
        check("F01 agents succeeds on a 0555 root without runs/reports",
              ra.returncode == 0 and ro_before == ro_after,
              f"rc={ra.returncode} {list(ro_before)}->{list(ro_after)} {ra.stderr[-300:]}")
    finally:
        for p in tmp.rglob("*"):
            try:
                p.chmod(0o755)
            except OSError:
                pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _pooled_dirs(tmp: Path, units: str, pooled: str) -> Path:
    d = tmp / "pkg"
    d.mkdir()
    (d / "x_units.tsv").write_text(units, encoding="utf-8")
    (d / "x_mcb_pooled.tsv").write_text(pooled, encoding="utf-8")
    return d


def test_f02_malformed_units_excluded():
    print("\n== F02: a malformed units value excludes the whole method ==")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _pooled_dirs(tmp,
                         "method\tn_units\tmean\nA\t9\t5.0\nA\t9\tn/a\n",
                         "method\tn_units\tmean\nA\t9\t10.0\n")
        rows = pp.scan_pooled_table_mismatches(d)
        gaps = [r for r in rows if r.get("gap")]
        mismatches = [r for r in rows if not r.get("gap")]
        check("F02 the unreadable value is a named coverage gap",
              len(gaps) == 1 and "NOT compared" in str(gaps[0].get("detail")), str(rows))
        check("F02 no mismatch is computed from the partial mean",
              mismatches == [], str(mismatches))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_f03_malformed_pooled_rows():
    print("\n== F03: malformed pooled rows are named gaps, not a clean scan ==")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _pooled_dirs(tmp,
                         "method\tn_units\tmean\nA\t9\t5.0\n",
                         "method\tn_units\tmean\nA\tn/a\t5.0\n")
        rows = pp.scan_pooled_table_mismatches(d)
        check("F03 a non-numeric pooled n_units records a gap",
              len(rows) == 1 and rows[0].get("gap")
              and "NOT compared" in str(rows[0].get("detail")), str(rows))
        import shutil
        shutil.rmtree(d)
        d = _pooled_dirs(tmp,
                         "method\tn_units\tmean\nA\t9\t5.0\n",
                         "method\tn_units\tmean\nA\n")
        rows = pp.scan_pooled_table_mismatches(d)
        check("F03 a short pooled row records a gap",
              len(rows) == 1 and rows[0].get("gap")
              and "no method/n_units/mean cell" in str(rows[0].get("detail")), str(rows))
        shutil.rmtree(d)
        d = _pooled_dirs(tmp,
                         "method\tn_units\tmean\nA\t9\t5.0\n",
                         "method\tn_units\tmean\nA\t9\t5.0\n")
        rows = pp.scan_pooled_table_mismatches(d)
        check("F03 a readable matching table is still clean", rows == [], str(rows))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _png(width: int, height: int, raw: bytes, color_type: int = 0,
         bit_depth: int = 8) -> bytes:
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth,
                                           color_type, 0, 0, 0))
    return (b"\x89PNG\r\n\x1a\n" + ihdr
            + _png_chunk(b"IDAT", zlib.compress(raw)) + _png_chunk(b"IEND", b""))


def test_f04_visual_evidence_gate():
    print("\n== F04: the visual-evidence gate validates real image structure ==")
    tmp = Path(tempfile.mkdtemp())
    try:
        jpg = tmp / "stub.jpg"
        jpg.write_bytes(bytes.fromhex("ffd8ffda0000ffd9"))
        check("F04 an 8-byte marker-only JPEG is refused",
              not pp._render_evidence_is_real(jpg))
        tif = tmp / "stub.tif"
        tif.write_bytes(b"II*\x00" + (8).to_bytes(4, "little")
                        + (1).to_bytes(2, "little") + b"\x00" * 12 + b"\x00" * 4)
        check("F04 a 26-byte TIFF with one empty IFD entry is refused",
              not pp._render_evidence_is_real(tif))
        # 62-byte TIFF: ImageWidth=ImageLength=1, StripOffsets=8 (this IFD's own
        # offset), StripByteCounts=1, and no pixel bytes. The old range check
        # accepted it as a render (R02).
        tif62 = tmp / "stub62.tif"
        tif62.write_bytes(
            b"II*\x00" + (8).to_bytes(4, "little") + (4).to_bytes(2, "little")
            + struct.pack("<HHI", 256, 3, 1) + (1).to_bytes(4, "little")
            + struct.pack("<HHI", 257, 3, 1) + (1).to_bytes(4, "little")
            + struct.pack("<HHI", 273, 4, 1) + (8).to_bytes(4, "little")
            + struct.pack("<HHI", 279, 4, 1) + (1).to_bytes(4, "little")
            + (0).to_bytes(4, "little"))
        check("F04 a 62-byte TIFF whose strip points into its IFD is refused",
              not pp._render_evidence_is_real(tif62))
        bomb = tmp / "bomb.png"
        # 1x1 grayscale expects exactly 2 decoded bytes; the payload is ~1 MiB.
        bomb.write_bytes(_png(1, 1, b"\x00" + b"\x00" * (1024 * 1024)))
        check("F04 a PNG whose payload exceeds the header's shape is refused",
              not pp._render_evidence_is_real(bomb))
        bad_shape = tmp / "short.png"
        bad_shape.write_bytes(_png(2, 2, b"\x00\x00\x00"))
        check("F04 a PNG whose payload is shorter than the header's shape is refused",
              not pp._render_evidence_is_real(bad_shape))
        real_jpg = tmp / "real.jpg"
        real_jpg.write_bytes(_REAL_JPEG)
        check("F04 a structurally valid JPEG is still accepted",
              pp._render_evidence_is_real(real_jpg))
        real_tif = tmp / "real.tif"
        real_tif.write_bytes(_REAL_TIFF)
        check("F04 a structurally valid TIFF is still accepted",
              pp._render_evidence_is_real(real_tif))
        real_png = tmp / "real.png"
        real_png.write_bytes(_png(1, 1, b"\x00\xff"))
        check("F04 a structurally valid PNG is still accepted",
              pp._render_evidence_is_real(real_png))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_f05_missing_census_rows():
    print("\n== F05: a missing census row is not rendered as measured zeros ==")
    missing = {"field": ["a2"], "issue_census": {"a2": {}}}
    table = pp.issue_census_table(missing)
    head = list(pp.ISSUE_CENSUS_TABLE_HEAD)
    row = dict(zip(head, table[0]))
    check("F05 the long-form table renders a missing row as '-'",
          row["member"] == "a2" and row["correctness"] == "-"
          and row["major"] == "-" and row["own/peer"] == "-/-", str(row))
    from types import SimpleNamespace
    ctx = SimpleNamespace(root=Path("/tmp/x"))
    names, rows = pp.issue_matrix_rows(ctx, 1, missing)
    check("F05 the durable matrix renders a missing row as '-'",
          {rows[0][n] for n in names} == {"-"}, str(rows[0]))
    names, rows = pp.issue_cumulative_rows(ctx, 1, missing)
    check("F05 the cumulative matrix renders a missing row as '-'",
          {rows[0][n] for n in names} == {"-"}, str(rows[0]))
    measured_zero = {
        "tiers": {t: {"severities": {}} for t in pp.BASIS_TIERS},
        "severities": {}, "own": 0, "peer": 0,
        "own_sessions": 0, "peer_sessions": 0, "sessions_expected": 0}
    agg2 = {"field": ["a2"], "issue_census": {"a2": measured_zero}}
    row2 = dict(zip(head, pp.issue_census_table(agg2)[0]))
    check("F05 a MEASURED zero row is still rendered as 0",
          row2["correctness"] == "0" and row2["major"] == "0"
          and row2["own/peer"] == "0/0", str(row2))
    names2, rows2 = pp.issue_matrix_rows(ctx, 1, agg2)
    check("F05 a MEASURED zero row still carries numeric zeros",
          all(rows2[0][n] == 0 for n in names2), str(rows2[0]))


def main() -> int:
    test_f01_read_only_commands()
    test_f02_malformed_units_excluded()
    test_f03_malformed_pooled_rows()
    test_f04_visual_evidence_gate()
    test_f05_missing_census_rows()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("OK: all 2026-11-28 004500 wave-1 checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
