#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adapter: produce a tracked-changes .docx with python-redlines[docxodus].

Used by paper_pipeline.py when the redline backend is `redlines` (or first in
the `auto` chain). It probes the installed package instead of assuming one API,
prints which interface it used on success, and exits with

    0  wrote OUT
    2  bad arguments (including an OUT that is one of the inputs)
    4  python-redlines is not importable
    5  installed, but no supported docx redline interface was found (the names it
       did find are printed, so you can wire --redline-cmd yourself)
    6  an input file is missing or unreadable, or a stale OUT could not be
       cleared (never a traceback)

Usage: paper_redlines_adapter.py BASE.docx REVISED.docx OUT.docx
"""

import os
import sys


def fail(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def wrote(out_path):
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def clear_out(out_path):
    """Delete a pre-existing OUT before any backend is tried.

    ``wrote`` only asks whether a non-empty file exists, so a leftover OUT (a
    previous run of this adapter, another backend, an earlier attempt) made a
    backend that wrote nothing look successful: exit 0 was reported for content
    the adapter had not produced, and the same run reported exit 5 once the
    stale file was removed by hand.
    """
    if not os.path.lexists(out_path):
        # `exists` is False for a broken symlink, so an OUT left as a dangling
        # link was neither refused nor cleared: the backend wrote THROUGH the
        # link and exit 0 was reported while OUT was still a symlink.
        return
    try:
        os.unlink(out_path)
    except OSError as exc:                                          # noqa: BLE001
        fail("cannot clear the stale output file %s: %s" % (out_path, exc), 6)


def main(argv):
    if len(argv) != 3:
        fail(__doc__.strip(), 2)
    base, revised, out = argv
    for path in (base, revised):
        if not os.path.isfile(path):
            fail("input file not found: %s" % path, 6)
    for path in (base, revised):
        # OUT is the file this adapter writes (and clears first): an input path
        # must be refused rather than destroyed when no backend can produce a
        # redline, and a working backend would overwrite it anyway.
        if os.path.exists(out) and os.path.samefile(out, path):
            fail("refusing to use an input file as OUT: %s" % path, 2)
    clear_out(out)
    try:
        import redlines
    except ImportError as exc:
        fail("python-redlines is not importable: %s\nInstall it with "
             "`pip install \"python-redlines[docxodus]\"`." % exc, 4)

    _cache = {}

    def read_bytes(path):
        """Read lazily, with the handle closed again.

        The bytes form is only needed when a class rejects the path form; a
        missing/unreadable input produces our documented exit code 6 instead of
        an uncaught traceback (the old code read both files eagerly while only
        BUILDING the argument tuple).
        """
        if path in _cache:
            return _cache[path]
        try:
            with open(path, "rb") as fh:
                _cache[path] = fh.read()
        except OSError as exc:
            fail("cannot read input %s: %s" % (path, exc), 6)
        return _cache[path]

    # 1) docx-aware class API with an output method (names vary by version).
    for cls_name in ("DocxRedlines", "DocxRedline", "Redline", "Redlines"):
        cls = getattr(redlines, cls_name, None)
        if cls is None:
            continue
        obj = None
        try:
            try:
                obj = cls(base, revised)
            except Exception:                                  # noqa: BLE001
                obj = None
            if obj is None:
                try:
                    obj = cls(read_bytes(base), read_bytes(revised))
                except Exception:                              # noqa: BLE001
                    obj = None
        except SystemExit:
            raise                                              # unreadable input -> exit 6
        if obj is None:
            continue
        for meth in ("output_docx", "to_docx", "save_docx", "write_docx",
                     "render_docx", "output"):
            try:
                fn = getattr(obj, meth, None)
            except Exception:                                  # noqa: BLE001
                fn = None                                      # a property getter may compute/fail
            if not callable(fn):
                continue
            try:
                fn(out)
            except Exception as exc:                           # noqa: BLE001
                print("redlines.%s.%s failed: %s" % (cls_name, meth, exc), file=sys.stderr)
                continue
            if wrote(out):
                print("python-redlines:%s.%s" % (cls_name, meth))
                return 0

    # 2) module-level docx helpers.
    for fn_name in ("compare_docx", "redline_docx", "diff_docx", "docx_redline",
                    "compare_docx_files", "make_redline"):
        fn = getattr(redlines, fn_name, None)
        if not callable(fn):
            continue
        for args in ((base, revised, out), (base, revised)):
            try:
                res = fn(*args)
            except Exception:                                  # noqa: BLE001
                continue
            if isinstance(res, (bytes, bytearray)):
                with open(out, "wb") as fh:
                    fh.write(res)
            if wrote(out):
                print("python-redlines:%s" % fn_name)
                return 0

    # 3) a CLI entry point inside the module.
    entry = getattr(redlines, "main", None)
    if callable(entry):
        try:
            entry(["redlines", base, revised, out])   # argv[0] for argparse-shaped mains
        except SystemExit:
            pass
        except Exception as exc:                               # noqa: BLE001
            print("redlines.main failed: %s" % exc, file=sys.stderr)
        if wrote(out):
            print("python-redlines:main")
            return 0

    names = ", ".join(sorted(n for n in dir(redlines) if not n.startswith("_")))
    fail("python-redlines is installed but no supported docx redline interface was found.\n"
         "Available names: %s\n"
         "Use `redline --redline-cmd '<json argv with {base} {revised} {out}>'` to wire your "
         "own invocation." % names, 5)
    return 5


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
