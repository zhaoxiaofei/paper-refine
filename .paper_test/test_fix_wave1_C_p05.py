#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 1 batch C_p05 (F10, F20, F47, F76, F78, F84).

Every check fails on the unpatched tree: each pins a legal metadata spelling
that the sanitizer used to copy into the blinded judge view (or a dangling OPC
pointer it used to leave there).
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp        # noqa: E402

W = b"http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FAILS: list[str] = []


def check(label: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def docx(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, payload in parts.items():
            z.writestr(name, payload)
    return buf.getvalue()


def pdf_info(value: bytes) -> bytes:
    return (b"%PDF-1.4\n2 0 obj\n<< /Author " + value + b" >>\nendobj\n"
            b"trailer\n<< /Info 2 0 R /ID [<AA> <BB>] >>\n%%EOF\n")


def main() -> None:
    print("== F10/F78: PDF /Info values ==")
    raw = (b"%PDF-1.4\n2 0 obj\n<< /Author 3 0 R /Title (T) >>\nendobj\n"
           b"3 0 obj\n(Alice Author)\nendobj\n"
           b"trailer\n<< /Info 2 0 R /ID [<AA> <BB>] >>\n%%EOF\n")
    out, notes = pp._sanitize_pdf_bytes(raw)
    check("F10 an indirect /Author reference is resolved and blanked",
          b"Alice Author" not in out, notes)
    out2, _ = pp._sanitize_pdf_bytes(out)
    check("F10 the PDF view is idempotent", out2 == out)
    dangling = pdf_info(b"9 0 R")
    out3, notes3 = pp._sanitize_pdf_bytes(dangling)
    check("F10 an unresolvable indirect /Author records a named gap",
          bool(notes3) and b"9 0 R" in out3, notes3)
    out4, _ = pp._sanitize_pdf_bytes(pdf_info(b"(Jane (J.) Author)"))
    check("F78 a nested balanced literal is blanked", b"Jane" not in out4, out4)
    out5, _ = pp._sanitize_pdf_bytes(pdf_info(b"(Jane \\) Author)"))
    check("F78 an escaped close paren is blanked", b"Jane" not in out5, out5)

    print("\n== F20: Word namespace aliasing ==")
    second = (b'<w:document xmlns:w="' + W + b'" xmlns:wp="' + W + b'"><w:body>'
              b'<w:p><wp:del w:author="Jane Author"><wp:r><wp:delText>'
              b'SECRET-DELETED</wp:delText></wp:r></wp:del>'
              b'<wp:ins w:author="X"><wp:r><wp:t>ADDED</wp:t></wp:r></wp:ins>'
              b'</w:p></w:body></w:document>')
    default = (b'<document xmlns="' + W + b'" xmlns:m="urn:math"><body><p>'
               b'<del w:author="Jane Author"><r><delText>SECRET-DELETED'
               b'</delText></r></del><m:oMath xmlns="urn:math"><m:r/></m:oMath>'
               b'<ins author="X">ADDED</ins></p></body></document>')
    for label, body in (("second prefix", second), ("default namespace", default)):
        data = docx({"word/document.xml": body,
                     "docProps/core.xml": b'<cp:coreProperties xmlns:cp="http://s'
                     b'chemas.openxmlformats.org/package/2006/metadata/core-properties">'
                     b"</cp:coreProperties>"})
        view, _notes = pp._sanitize_ooxml_bytes(data)
        with zipfile.ZipFile(io.BytesIO(view)) as z:
            doc = z.read("word/document.xml")
        check(f"F20 {label}: rejected text and author are gone",
              b"SECRET-DELETED" not in doc and b"Jane Author" not in doc
              and b'author="X"' not in doc, doc)
        check(f"F20 {label}: inserted text stays (accepted document)",
              b"ADDED" in doc)
    out = pp._sanitize_ooxml_bytes(docx({"word/document.xml": default}))[0]
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        doc = z.read("word/document.xml")
    check("F20 a nested default namespace is not corrupted",
          b"<m:oMath" in doc and b"<w:oMath" not in doc, doc)

    print("\n== F47: dangling OPC pointers ==")
    for paired in (False, True):
        ct = (b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              b'<Override PartName="/docProps/thumbnail.jpeg" ContentType="image/jpeg"'
              + (b"></Override>" if paired else b"/>") + b"</Types>")
        rels = (b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                b'<Relationship Id="rId1" Type="t" Target="docProps/thumbnail.jpeg"'
                + (b"></Relationship>" if paired else b"/>") + b"</Relationships>")
        out, notes = pp._sanitize_ooxml_bytes(docx({
            "[Content_Types].xml": ct, "_rels/.rels": rels,
            "word/document.xml": b'<w:document xmlns:w="' + W + b'"><w:body/>'
                                 b"</w:document>",
            "docProps/thumbnail.jpeg": b"\xff\xd8\xff"}))
        with zipfile.ZipFile(io.BytesIO(out)) as z:
            check(f"F47 paired-tag override/relationship pruned (paired={paired})",
                  b"thumbnail" not in z.read("[Content_Types].xml")
                  and b"thumbnail" not in z.read("_rels/.rels") and notes, notes)

    print("\n== F76/F84: namespace-bound metadata elements ==")
    core = (b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/'
            b'2006/metadata/core-properties" xmlns:d="http://purl.org/dc/elements/1.1/">'
            b"<d:creator>Jane Author</d:creator></cp:coreProperties>")
    check("F76 an alternate-prefix dc:creator is blanked",
          b"Jane Author" not in pp._blank_xml_elements(
              core, (b"dc:creator", b"cp:lastModifiedBy"), b"author"))
    app = (b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
           b'extended-properties" xmlns:p="http://schemas.openxmlformats.org/'
           b'officeDocument/2006/extended-properties"><p:Company>Acme Labs</p:Company>'
           b"</Properties>")
    check("F76 a prefixed extended-properties element is blanked",
          b"Acme Labs" not in pp._blank_xml_elements(app, (b"Company",), b""))
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" '
           b'xmlns:d="http://purl.org/dc/elements/1.1/">'
           b"<d:creator>Alice Author</d:creator></svg>")
    svg_out, svg_notes = pp._sanitize_svg_bytes(svg)
    check("F84 a non-dc Dublin Core binding is stripped",
          b"Alice Author" not in svg_out and not svg_notes, svg_out)
    svg_attr = (b'<svg xmlns="http://www.w3.org/2000/svg" '
                b'xmlns:d="http://purl.org/dc/elements/1.1/" '
                b'd:creator="Alice Author"><rect/></svg>')
    check("F84 a non-dc metadata attribute is stripped",
          b"Alice Author" not in pp._sanitize_svg_bytes(svg_attr)[0])

    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED: " + ", ".join(FAILS))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
