#!/usr/bin/env python3
"""The 7-character content-hash version token of a revision package.

    python3 revision_token.py DIR [--json] [--verify TOKEN]

The token is the first 7 lowercase hex characters of SHA-256 over the SORTED
content digests of every PAYLOAD file in DIR. Payload = every file except:

  * the pipeline's/your own reports: CHANGELOG.md, MANUAL_STEPS.md,
    REVISION_REPORT.md, revision_report.json, DIFF_LEDGER.md, REWRITE_REPORT.md,
    VISUAL_CHECK.md;
  * the tracked-changes auxiliaries: *.tracked.docx, *.before-after.docx;
  * the process scratch: work/ at the top level.

File NAMES do not enter the hash, and existing version tokens inside file
contents are normalized to "<VERSION>" before hashing. That makes the token
STABLE: it does not change when you apply it (rename "...-a.docx" to
"...-<token>.docx", "..._v2.tex" to "..._<token>.tex", and repoint the
references) -- so it is a package ID derived from the revision content, not a
hash of its own naming pass.

Applying the token (the naming rule of paper-revise, step R2): for every editable
manuscript document replace a trailing version token ("-a", "_v2", an existing
"-<7hex>") with "-<token>", or append "-<token>" before the extension when the
basename has none. All payload documents of one package carry the SAME token.
Legacy letter tokens remain readable by the pipeline, but new revisions do not
produce them.

Exit status: 0 (also when --verify matches); 1 on a verify mismatch or a
read error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPORTS = {"changelog.md", "manual_steps.md", "revision_report.md",
           "revision_report.json", "diff_ledger.md", "rewrite_report.md",
           "visual_check.md"}
AUX_SUFFIXES = (".tracked.docx", ".before-after.docx")

# "-a" / "_v2" / "_V2" / "-4f3a9c1" at the very end of a stem (the version slot).
TOKEN_RE = re.compile(r"^(?P<base>.*?)[-_](?P<tok>[0-9a-f]{7}|[A-Za-z]|[vV]\d+)$")
HEX7_RE = re.compile(r"[0-9a-f]{7}")


def is_payload(p: Path, root: Path) -> bool:
    rel = p.relative_to(root)
    if rel.parts and rel.parts[0] == "work":
        return False
    name = p.name.lower().strip()
    if name in REPORTS or name.endswith(AUX_SUFFIXES):
        return False
    return True


def payload_files(root: Path) -> list:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and is_payload(p, root))


def filename_token(name: str):
    """The version token a payload file name carries, or None."""
    stem = Path(name).stem
    m = TOKEN_RE.match(stem)
    return m.group("tok") if m else None


def content_token_free(data: bytes, tokens) -> bytes:
    """Bytes with version-token REFERENCES normalized (so the hash is stable).

    Only reference-like occurrences are touched -- never a bare "-x" in prose:
      1. any token (or 7-hex token) immediately followed by a file extension;
      2. any token inside a LaTeX reference command's argument.
    """
    alts = [re.escape(t.encode()) for t in sorted(set(tokens), key=len, reverse=True) if t]
    alts.append(rb"[0-9a-f]{7}")
    tok = rb"(?:" + b"|".join(alts) + rb")"
    data = re.sub(rb"([-_])" + tok + rb"(?=\.[A-Za-z][A-Za-z0-9]{0,9}\b)",
                  rb"\1<VERSION>", data)
    cmd = re.compile(
        rb"(\\(?:input|include|subfile|bibliography|bibliographystyle|addbibresource|"
        rb"includegraphics|lstinputlisting|inputminted|externaldocument|subimport|import)\b"
        rb"[^{}]*?\{)([^{}]*)(\})")

    def _arg(m):
        inner = re.sub(rb"([-_])" + tok + rb"(?![0-9A-Za-z_])", rb"\1<VERSION>", m.group(2))
        return m.group(1) + inner + m.group(3)

    return cmd.sub(_arg, data)


def revision_token(root: Path) -> dict:
    """{'token','files','tokens_seen','consistent','notes'} for one package."""
    if not root.is_dir():
        raise SystemExit(f"error: not a directory: {root}")
    files = payload_files(root)
    tokens = [t for t in (filename_token(p.name) for p in files) if t]
    digs = []
    skipped = []
    for p in files:
        try:
            data = p.read_bytes()
        except OSError as e:                                  # noqa: BLE001
            # The pipeline twin (revision_token_for_dir) skips an unreadable
            # payload file and hashes the readable remainder; aborting here
            # made the two implementations derive different tokens for the
            # same directory.
            skipped.append(f"{p.name}: {e}")
            continue
        digs.append(hashlib.sha256(content_token_free(data, tokens)).hexdigest())
    if not digs:
        return {"token": "", "files": 0, "tokens_seen": [],
                "consistent": False, "notes": ["no payload file found"]}
    token = hashlib.sha256("\n".join(sorted(digs)).encode("utf-8")).hexdigest()[:7]
    hex_tokens = sorted({t for t in tokens if HEX7_RE.fullmatch(t)})
    consistent = bool(hex_tokens) and all(t == token for t in hex_tokens)
    notes = []
    if skipped:
        notes.append("unreadable payload file(s) skipped: " + "; ".join(skipped[:3]))
    if not hex_tokens:
        notes.append("no 7-hex token in any payload filename (legacy letter tokens, or none "
                     "applied yet)")
    elif not consistent:
        notes.append(f"filename token(s) {hex_tokens} do not match the content-derived token "
                     f"{token}")
    return {"token": token, "files": len(files), "tokens_seen": sorted(set(tokens)),
            "hex_tokens": hex_tokens, "consistent": consistent, "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify", default=None, help="compare against this token; exit 1 on mismatch")
    args = ap.parse_args(argv)
    info = revision_token(Path(args.directory))
    if args.verify is not None:
        ok = info["token"] == args.verify
        print(f"{'OK' if ok else 'MISMATCH'}: content token {info['token']} vs --verify "
              f"{args.verify}")
        return 0 if ok else 1
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"version token: {info['token']}")
        print(f"payload files: {info['files']}")
        print(f"tokens in filenames: {info['tokens_seen'] or '(none)'}")
        for note in info["notes"]:
            print(f"note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
