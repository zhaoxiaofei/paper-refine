# -*- coding: utf-8 -*-
# Part 03/03 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

def analyse_document(xml: str, styles: dict, policy: dict, doc: str,
                     sizes: dict = None, rels: dict = None) -> dict:
    rows = []
    paras = paragraphs(xml)
    franges = field_ranges(xml)

    def row(rule, severity, location, evidence, detail, protected=False, fix=None):
        # A finding inside a Zotero field is reported, never silently edited --
        # the fix kind has to say so, or the fixer's "all mechanical findings
        # resolved" verification would fail on a row it is not allowed to touch.
        # `fix` overrides the rule's default: a caption block the merge must
        # refuse (a field or an image inside it) is an editorial row even though
        # the rule is mechanical for the blocks the fixer can merge.
        fix = fix or _fix_kind(rule, policy)
        if protected and fix == "mechanical":
            fix = "style-field"
        rows.append({"rule": rule, "severity": severity, "document": doc, "location": location,
                     "evidence": evidence, "detail": detail,
                     "fix": fix, "protected": protected, "tier": tier_of(rule)})

    title_block_end = None
    for idx, (_, _, para) in enumerate(paras):
        if re.match(r"^\s*(abstract|summary)\s*:?\s*$", text_of(para), re.I):
            title_block_end = idx
            break

    # ---- structural -----------------------------------------------------------
    # The fixer refuses an in-table paragraph by design (deleting a cell's only
    # paragraph makes Word report a corrupt file). The scanner must not file a
    # mechanical FMT-S1 row it knows the fixer will refuse: one in-table page
    # break otherwise made the whole document's fix verify as failed and threw
    # away every other repair.
    in_table = _table_paragraph_indices(xml, paras)
    for idx, (p0, p1, para) in enumerate(paras):
        text = text_of(para)
        # A field run is CONTENT, never an empty paragraph: the fixer refuses to
        # touch one (moving its page break would unbalance the field), so a row
        # the scan still filed `mechanical` could never be repaired and made the
        # whole fix verify as failed. The two sides read the same definition.
        empty = not text.strip() and not has_drawing(para) and not has_field(para)
        if PAGEBREAK_RE.search(para) and empty:
            # In a table cell the fixer cannot move/delete the paragraph (that
            # would leave an empty `<w:tc>`); report the defect as manual rather
            # than filing a mechanical row the fixer refuses by design.
            row("FMT-S1", "high", f"p{idx}", "empty paragraph holding a page break",
                "break-only paragraphs render as a blank page (or a stray empty line); delete it "
                "and put w:pageBreakBefore on the paragraph that should start the page",
                fix=("manual" if idx in in_table else None))
        ppr = ppr_of(para)
        style = elem_val(ppr, "pStyle")
        if style and style.startswith("Heading"):
            if policy["heading_keep_with_next"] and not (ppr and "<w:keepNext" in ppr):
                row("FMT-T3a", "medium", f"p{idx}", f"heading {text[:40]!r} has no keepNext",
                    "headings can be orphaned at the bottom of a page; add keepNext + keepLines")
            direct = {elem_val(rpr_of(r[2]), "sz") for r in runs(para)
                      if text_of(r[2]).strip() and elem_val(rpr_of(r[2]), "sz")}
            want = style_sz(styles, style)
            if want and direct and any(s != want for s in direct):
                row("FMT-T3b", "medium", f"p{idx}",
                    f"heading runs sz={sorted(direct)} vs style {style} sz={want}",
                    "direct run sizes contradict the heading style definition")

    # Stray empty paragraphs: template-prescribed blanks (the front-matter spacer
    # above the title, a slot the journal's own template carries) are exempt; a
    # blank attached to a heading is FMT-S8, a run beyond the cap is FMT-S6.
    rows.extend(stray_empty_paragraph_rows(paras, policy, doc, xml))

    # ---- legends / captions ---------------------------------------------------
    # The unit is the caption BLOCK: a label ("Fig. 2 | ...", "Figure S1. ...",
    # "Table 3 ...") plus the paragraphs that continue it. A caption is ONE
    # paragraph (FMT-T2c) and every paragraph of one caption carries the
    # caption's spacing (FMT-T2a/T2b): a continuation left without direct
    # spacing inherits the document default and renders 1.5-spaced beside a
    # single-spaced caption -- the 2026-10-14 packages' Fig. 3 defect. Blocks
    # are read inside the venue's own display areas (see
    # `caption_block_ranges`); a figure label outside one still gets its own
    # spacing rows, exactly as before.
    areas = display_area_kinds(paras)
    blocks = caption_block_ranges(paras, areas, container_spans(xml), xml=xml)
    legend_rows = []
    for b in blocks:
        members = [b["label"]] + (b["continuations"] if b["in_area"] else [])
        for m in members:
            legend_rows.append((m, b))
    in_blocks = {m for m, _ in legend_rows}
    for i, (_, _, p) in enumerate(paras):
        if LEGEND_RE.match(text_of(p)) and i not in in_blocks:
            legend_rows.append((i, None))
    legend_idx = sorted({m for m, _ in legend_rows})
    for i, b in sorted(legend_rows):
        para = paras[i][2]
        if b is not None and i != b["label"]:
            what = (f"continuation paragraph of the {b['kind']} caption "
                    f"{text_of(paras[b['label']][2]).strip()[:40]!r} (p{b['label']})")
        elif b is not None:
            what = f"{b['kind']} caption {text_of(para).strip()[:40]!r}"
        else:
            what = f"legend {text_of(para).strip()[:40]!r}"
        sp = elem(ppr_of(para), "spacing")
        line, before, after = attr(sp, "line"), attr(sp, "before"), attr(sp, "after")
        if line != str(policy["caption_line"]):
            row("FMT-T2a", "medium", f"p{i}",
                f"{what} line spacing {line or 'inherit'} != {policy['caption_line']} "
                f"(single)",
                "a caption is single-spaced: a continuation left at the body's own "
                "spacing renders one caption at two line spacings")
        if before != str(policy["caption_space"]) or after != str(policy["caption_space"]):
            row("FMT-T2b", "low", f"p{i}",
                f"{what} spacing before={before} after={after} != "
                f"{policy['caption_space']}",
                "legend paragraph spacing differs between captions")
    for b in blocks:
        if not (b["in_area"] and b["continuations"]):
            continue
        conts = ", ".join(f"p{c}" for c in b["continuations"][:4])
        if len(b["continuations"]) > 4:
            conts += f", +{len(b['continuations']) - 4} more"
        row("FMT-T2c", "medium", f"p{b['label']}",
            f"the {b['kind']} caption {text_of(paras[b['label']][2]).strip()[:50]!r} "
            f"continues in {len(b['continuations'])} more paragraph(s) ({conts})",
            "a caption is one paragraph: merge the continuation paragraph(s) into the "
            "caption so the legend renders (and is read) as one block",
            fix=None if b.get("mergeable") else "editorial")
    # One caption family, one paragraph style: a caption that carries a
    # different style from the majority of its siblings in the same area (a
    # front-matter 'Author List' style on the first supplementary legend, say)
    # renders differently from every other caption. A tie reports nothing --
    # there is no majority to follow.
    for area_kind in ("figure", "table"):
        members = [b["label"] for b in blocks if b["in_area"] and b["kind"] == area_kind]
        if len(members) < 2:
            continue
        seen = Counter(_para_style(paras[i][2]) for i in members)
        if len(seen) < 2:
            continue
        majority, count = seen.most_common(1)[0]
        if count * 2 <= len(members):
            continue
        for i in members:
            style = _para_style(paras[i][2])
            if style == majority:
                continue
            row("FMT-T2d", "low", f"p{i}",
                f"the {area_kind} caption {text_of(paras[i][2]).strip()[:50]!r} carries "
                f"paragraph style {style or '(body)'!r} while {count} of "
                f"{len(members)} captions in this area use "
                f"{majority or '(body)'!r}",
                "one caption family, one paragraph style: align the minority with its "
                "siblings")

    # ---- italics / journal emphasis -------------------------------------------
    # What is italic is decided by the FULL style precedence (direct rPr >
    # character style > paragraph style > document defaults). Reading only the
    # run's own `<w:i/>` misses an italic that lives in a character style such as
    # Word's "Emphasis" -- on a real cover letter that made "Nature
    # Biotechnology" italic in one sentence, roman in the next, and looked clean
    # to this scanner.
    policy_j = policy["journal_italics"]
    journal_regions = defaultdict(lambda: defaultdict(lambda: {True: [], False: []}))
    for idx, (p0, p1, para) in enumerate(paras):
        text = text_of(para)
        style = elem_val(ppr_of(para), "pStyle")
        analysis = journal_emphasis_runs(styles, style, para)
        region = "refs" if style == "Bibliography" else "prose"
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if not rtext.strip() or not run_is_italic(styles, style, run):
                continue
            field = in_field(franges, p0 + r0)
            protect = bool(field)
            if title_block_end is not None and idx < title_block_end \
                    and re.search(r"@|Correspondence|ORCID", text, re.I):
                row("FMT-T6a", "medium", f"p{idx}",
                    f"italic run in the title/correspondence block: {rtext[:50]!r}",
                    "the correspondence and affiliation blocks must be roman"
                    + (f" (Zotero field: {field})" if field else ""), protected=protect)
            if style == "Bibliography" and re.search(r"\bet\s+al\.", rtext):
                row("FMT-T6b", "medium", f"p{idx}", f"italic 'et al.' in a reference: {rtext[:40]!r}",
                    "only the journal title is italic in a reference"
                    + (f" (Zotero field: {field})" if field else ""), protected=protect)
        for r0, _r1, run, names in analysis["italic"]:
            field_here = in_field(franges, p0 + r0)
            journal_regions[region][names[0].lower()][True].append((idx, field_here))
            if region == "prose" and policy_j in ("refs-only", "off"):
                row("FMT-T6c", "low", f"p{idx}",
                    f"italic journal name outside the reference list: {', '.join(names)!r}",
                    "policy: journal titles are italic only in the reference list"
                    + (f" (Zotero field: {field_here})" if field_here else ""),
                    protected=bool(field_here))
        for r0, _r1, run, names in analysis["roman"]:
            field_here = in_field(franges, p0 + r0)
            journal_regions[region][names[0].lower()][False].append((idx, field_here))
            # Only a run that IS the journal title is auto-fixable: italicising a
            # run that also carries the volume and page numbers would rewrite more
            # than the title (the mixed-treatment row T6e still reports it).
            if (((region == "refs" and policy_j in ("refs-only", "everywhere"))
                 or (region == "prose" and policy_j == "everywhere"))
                    and all(_title_only(text_of(run), n) for n in names)):
                row("FMT-T6g", "low", f"p{idx}",
                    f"roman journal title where the policy asks for italics: "
                    f"{', '.join(names)!r}",
                    "policy: journal titles are italic in the reference list"
                    + (" and in the body text" if region == "prose" else "")
                    + (f" (Zotero field: {field_here})" if field_here else ""),
                    protected=bool(field_here))
        for r0, _r1, _run, extra, name in analysis["continuation"]:
            field_here = in_field(franges, p0 + r0)
            # Prose only: a reference list legitimately emphasises a title that
            # contains several capitalised words (see _has_lowercase_word).
            if region != "prose":
                continue
            row("FMT-T6f", "medium", f"p{idx}",
                f"emphasis continues past the journal title ({name!r}): {extra[:40]!r}",
                "only the journal title itself may be emphasised; the surrounding "
                "words are ordinary prose"
                + (f" (Zotero field: {field_here})" if field_here else ""),
                protected=bool(field_here))
    for region, by_name in journal_regions.items():
        for name, seen in by_name.items():
            if seen[True] and seen[False]:
                paras_i = ", ".join(str(i) for i, _f in seen[True][:4])
                paras_r = ", ".join(str(i) for i, _f in seen[False][:4])
                any_field = any(f for _i, f in seen[True] + seen[False])
                row("FMT-T6e", "medium", f"{region}: {name}",
                    f"'{name}' is formatted italic in {len(seen[True])} place(s) "
                    f"(para {paras_i}) and roman in {len(seen[False])} place(s) "
                    f"(para {paras_r})",
                    "the same journal name must carry ONE treatment throughout a region "
                    "(the reference list italicises journal titles; body text does not)"
                    + (" (partly inside a Zotero field)" if any_field else ""),
                    protected=any_field)

    for i, (p0, p1, p) in enumerate(paras):
        if elem_val(ppr_of(p), "pStyle") != "Bibliography":
            continue
        text = text_of(p)
        ital = [text_of(r[2]) for r in runs(p)
                if text_of(r[2]).strip() and run_is_italic(styles, "Bibliography", r[2])]
        field = in_field(franges, p0)
        if re.search(r"\(\d{4}[a-z]?\)", text) and not ital:
            row("FMT-T6d", "medium", f"p{i}", f"reference with no italic journal title: {text[:60]!r}",
                "an article reference must italicize the journal title"
                + (f" (Zotero field: {field})" if field else ""), protected=bool(field))

    # ---- URLs / emails --------------------------------------------------------
    treatments = defaultdict(set)
    for idx, (_, _, para) in enumerate(paras):
        # A hyperlink is a run CONTAINER: `"<w:hyperlink" in para` classified
        # every URL run in a mixed paragraph as a link, so a plain URL beside a
        # hyperlinked one never produced the FMT-T7a mixed-treatment row.
        link_spans = [(m.start(), m.end()) for m in
                      re.finditer(r"<w:hyperlink\b[^>]*>.*?</w:hyperlink>", para, re.S)]
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if not URL_RE.search(rtext):
                continue
            in_link = any(a <= r0 < b for a, b in link_spans)
            rpr = rpr_of(run)
            t = ("link" if in_link else "plain",
                 elem_val(rpr, "rStyle") or "-",
                 elem_val(rpr, "color") or "-",
                 # `w:u w:val="none"` is an EXPLICIT "not underlined": it renders
                 # exactly like no `w:u` at all, so counting it as underlined made
                 # a document that mixes both spellings report mixed treatments.
                 "u" if is_on(rpr, "u") else "-",
                 "i" if is_on(rpr, "i") else "-")
            for m in URL_RE.finditer(rtext):
                treatments[m.group(0)].add(t)
    for u, ts in list(treatments.items()):
        if len(ts) > 1:
            row("FMT-T7a", "medium", "document", f"URL {u[:60]!r} rendered {len(ts)} different ways",
                "the same URL is hyperlinked in one place and plain text in another")
    shapes = {(t[0], t[1] != "-", t[2] != "-", t[3] != "-", t[4] != "-")
              for ts in treatments.values() for t in ts}
    if len(shapes) > 1:
        detail = "; ".join(sorted(f"{t}" for t in
                                  {t for ts in treatments.values() for t in ts}))
        row("FMT-T7b", "medium", "document", f"mixed URL/email treatments: {detail}",
            "pick one treatment (plain black, or one link colour/underline) everywhere")

    # ---- text hygiene ---------------------------------------------------------
    full = "\n".join(text_of(p[2]) for p in paras)
    n_straight, n_curly = len(STRAIGHT_RE.findall(full)), len(CURLY_RE.findall(full))
    if n_straight and n_curly:
        row("FMT-T1", "medium", "document",
            f"mixed quotation marks: {n_straight} straight vs {n_curly} curly",
            "use one apostrophe/quote style throughout", )
    words = max(1, len(re.findall(r"\S+", full)))
    em = full.count(EM)
    density = em * 1000.0 / words
    if density > policy["max_em_dashes_per_1000"]:
        ctx = [full[max(0, m.start() - 35):m.start() + 20] for m in list(re.finditer(EM, full))[:3]]
        row("FMT-P1", "medium", "document",
            f"{em} em-dashes = {density:.1f} per 1000 words (cap {policy['max_em_dashes_per_1000']})",
            "over-used em-dashes: rewrite parenthetical dashes as commas/parentheses. e.g. "
            + " | ".join(ctx))
    spaced = len(re.findall(r"\s-\s", full))
    if spaced:
        row("FMT-P2", "low", "document", f"{spaced} spaced hyphen(s) used as a dash",
            "use a comma or a spaced en-dash instead of ' - '")
    # Per-instance text hygiene: FMT-P4 (a space at a line edge) and FMT-G1 (a
    # doubled article/preposition) are mechanical and the fixer applies them;
    # FMT-P3 (doubled spaces, bracket spacing, zero-width marks), FMT-G2
    # (possible lowercase sentence start) and FMT-G3 (missing space after
    # punctuation) are reported for the editing arms.
    is_ref_para = [elem_val(ppr_of(p[2]), "pStyle") == "Bibliography" for p in paras]
    doc_field_results = _field_result_spans(xml)
    field_result_text = [field_result_text_ranges(p[2], doc_field_results, p[0])
                         for p in paras]
    rows.extend(hygiene_rows(paras, is_ref_para, doc, protected=field_result_text))
    rows.extend(capitalization_rows(paras, is_ref_para, doc))
    # Fonts, paragraph formatting and heading levels: the copy-editor classes
    # the editing arms align (FMT-T10a..e; report-only, like the text rules).
    rows.extend(style_convention_rows(paras, styles, doc))
    # Embedded-image geometry: a figure rescaled without its own aspect ratio.
    if sizes is not None:
        geo_rows, _geo_fixes = drawing_geometry_rows(xml, rels or {}, sizes, doc, policy)
        rows.extend(geo_rows)

    # ---- header / title page / tracked changes --------------------------------
    first_sect = first_section_props(xml)
    if first_sect and re.search(r"<w:headerReference", first_sect) \
            and "<w:titlePg" not in first_sect \
            and policy["title_page_header"] == "suppress":
        row("FMT-S3", "low", "document", "the running head is printed on the title page",
            "add w:titlePg to the section properties so page 1 carries no header")
    n_ins = len(re.findall(r"<w:ins(?=[\s/>])", xml))
    n_del = len(re.findall(r"<w:del(?=[\s/>])", xml))
    n_other_rev = len(OTHER_REVISION_MARK_RE.findall(xml))
    if n_ins or n_del or n_other_rev:
        other = f" / {n_other_rev} other revision mark(s)" if n_other_rev else ""
        row("FMT-S4", "high", "document",
            f"tracked changes present: {n_ins} ins / {n_del} del{other}",
            "a final package must not carry revision marks; accept or reject them first")
    n_proof = len(PROOFERR_RE.findall(xml))
    if n_proof:
        row("FMT-S5", "low", "document", f"{n_proof} proofing marker(s) (w:proofErr)",
            "the file was last saved with unaccepted spelling/grammar marks")
    # A literal tab is a run-level `<w:tab/>` or a TAB character in the text.
    # `<w:tab w:val=".." w:pos=".."/>` inside `<w:pPr><w:tabs>` DEFINES a tab
    # stop -- counting it reported "1 literal tab character" on paragraphs that
    # carry no tab at all (the `<w:tab[^>]*/>` regex cannot tell them apart).
    n_tabs, _tab_depth = 0, 0
    for _tok in re.finditer(r"<w:tabs(?=[\s/>])[^>]*>|</w:tabs>|<w:tab(?=[\s/>])[^>]*/>",
                            xml):
        _raw = _tok.group(0)
        if _raw.startswith("</"):
            _tab_depth = max(0, _tab_depth - 1)
        elif _raw.startswith("<w:tabs"):
            _tab_depth += 0 if _raw.endswith("/>") else 1
        elif not _tab_depth:
            n_tabs += 1
    n_tabs += full.count("\t")
    if n_tabs:
        row("FMT-S7", "low", "document", f"{n_tabs} literal tab character(s)",
            "tabs used for layout; prefer paragraph indentation/spacing")

    # ---- text-level style & consistency (FMT-T8a..FMT-T8e) --------------------
    # Citation formats, nested parentheses, redundant repetition and term variants
    # are document-TEXT problems: they are read from the paragraph text so the same
    # rules can also run over the LaTeX/markdown sources (paper_pipeline scans those).
    para_texts = [text_of(p[2]) for p in paras]
    para_is_ref = [elem_val(ppr_of(p[2]), "pStyle") == "Bibliography" for p in paras]
    # The reference-SHAPE rules must survive a venue template that remaps style
    # ids by NAME (apply_word_template rewrites them): a package restyled that
    # way carries its reference list under another style id and every FMT-R
    # rule switched off silently. When no paragraph uses the literal id but the
    # document HAS an explicit bibliography heading, fall back to the numbered
    # entries under it (the same structural primitive FMT-Z2 uses).
    para_is_ref_rows = para_is_ref
    if not any(para_is_ref):
        bib_start = _bibliography_entry_start(para_texts)
        if bib_start > 0:
            para_is_ref_rows = [bool(para_is_ref[i])
                                or (i >= bib_start
                                    and bool(re.match(r"^\s*\d+\s*[\.\)]\s*\S",
                                                      str(para_texts[i] or ""))))
                                for i in range(len(para_is_ref))]
    para_is_head = [bool((elem_val(ppr_of(p[2]), "pStyle") or "").startswith("Heading"))
                    for p in paras]
    # A caption/legend paragraph is not a display-item CALL-OUT: the ordering
    # rule below (FMT-O1) reads the prose, so the caption blocks are excluded the
    # same way the length scan excludes them from the main text.
    para_is_caption = [bool(TABLE_CAPTION_RE.match(t) or FIGURE_CAPTION_RE.match(t)
                            or TABLE_CAPTION_BARE_RE.match(t)
                            or FIGURE_CAPTION_BARE_RE.match(t))
                       for t in para_texts]
    # Table-cell and text-box paragraphs are not narrative paragraphs: the
    # one-sentence rule (FMT-T9k) reads prose, and a cell holding a description
    # is a table's cell however many words it carries.
    _containers = container_spans(xml)
    para_in_container = [any(a <= paras[i][0] < b for a, b in _containers)
                         for i in range(len(paras))]
    para_in_area = [bool(x) for x in display_area_kinds(paras)]
    # Reference-entry shape (FMT-R1..R5), glued front matter (FMT-X2),
    # publisher leftovers (FMT-L1) and the availability statements (FMT-AV1/A2)
    # are RETRIEVABILITY/HYGIENE classes: they hold wherever the text appears
    # (a supplementary file carries its own reference list and availability
    # note, a cover letter can carry another publisher's boilerplate), so they
    # run on every document the package scan opens.
    for r in reference_entry_rows(para_texts, para_is_ref_rows, policy):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": bool(r.get("protected")),
                     "tier": tier_of(r["rule"])})
    for r in correspondence_glue_rows(para_texts, para_is_ref):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False, "tier": tier_of(r["rule"])})
    for r in leftover_phrase_rows(para_texts, policy.get("leftover_phrases"),
                                  para_is_ref):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False, "tier": tier_of(r["rule"])})
    for r in availability_rows(para_texts, para_is_ref):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False, "tier": tier_of(r["rule"])})
    # The live Zotero field state (FMT-Z1..Z4): a document whose citation
    # markers/bibliography disagree with its own citation order is rewritten by
    # the next Word/Zotero refresh, so it must never be treated as clean. Every
    # row is a field-held fact, hence `protected` (the fixer never edits a
    # field result) and `fix=manual` (only Zotero can re-render it). FMT-Z5
    # (the conflicting style stores) is added by `analyse_package`, which has
    # the other package parts.
    for r in zotero_parity_rows(xml, para_texts):
        if r["rule"] == "FMT-Z5":
            continue
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": "manual",
                     "protected": True, "tier": tier_of(r["rule"])})
    # Display-item ORDER (FMT-O1) is a MANUSCRIPT-BODY convention: a
    # supplementary file references the main figures and arranges its own
    # (the first call-out test would compare mentions of another document's
    # items), and a cover letter has no numbered display items of its own.
    if display_rules_apply(doc):
        for r in display_order_rows(para_texts, para_is_ref, para_is_caption,
                                    para_is_head,
                                    order_policy=str(policy.get("numbering") or "") == "citation"):
            rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                         "location": r["location"], "evidence": r["evidence"],
                         "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                         "protected": False, "tier": tier_of(r["rule"])})
    for r in text_style_rows(para_texts, para_is_ref, para_is_head,
                             in_container=para_in_container,
                             in_area=para_in_area,
                             field_spans=field_result_text):
        fix = _fix_kind(r["rule"], policy)
        if r.get("protected") and fix == "mechanical":
            fix = "style-field"
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": "document", "evidence": r["evidence"],
                     "detail": r["detail"], "fix": fix,
                     "protected": bool(r.get("protected")),
                     "tier": r.get("tier") or tier_of(r["rule"])})
    emphasis_rows, _emphasis_fixes = emphasis_consistency(styles, paras)
    for r in emphasis_rows:
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": "document", "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False})

    # ---- layout consistency and the front-page budget (FMT-T8f/T8g) ----------
    rows.extend(layout_consistency_rows(xml, paras, title_block_end, doc))
    _fm_row = front_matter_page_break_row(xml, paras, doc)
    if _fm_row:
        rows.append(_fm_row)

    # ---- the venue's DISPLAY rules (FMT-TB1..3 tables, FMT-FG1..3 figures) ---
    # The venue's rules come from `policy["tables"]`/`policy["figures"]` (the
    # profile's own blocks): a kind with no block contributes no rows, and one
    # with a block names the exact item so the review and the producing arms do
    # not have to guess. Neither runs on a supplementary/cover/response document
    # (`display_rules_apply`): the rule is about the manuscript body.
    table_rows, table_inventory = table_conformance_rows(xml, policy, doc)
    figure_rows, figure_inventory = figure_conformance_rows(xml, policy, doc)
    rows.extend(table_rows)
    rows.extend(figure_rows)

    # ---- layout integrity and rendered-bibliography emphasis -----------------
    # These are independent of the venue's display rules: a malformed table grid
    # or a bold year in a reference is wrong under any venue.
    rows.extend(table_layout_rows(xml, styles, doc, policy))
    rows.extend(reference_bold_rows(xml, styles, doc))
    rows.extend(availability_claim_rows(para_texts, doc))

    return {"rows": rows, "paras": len(paras), "words": words, "legend_idx": legend_idx,
            "fields": [f[2][:60] for f in franges],
            "style_survey": style_survey(xml, styles),
            "treatments": {k: sorted(v) for k, v in treatments.items()},
            "title_block_end": title_block_end,
            "tables": table_inventory,
            "figures": figure_inventory}


def analyse_package(path: Path, policy: dict) -> dict:
    app_pages = None
    sizes, doc_rels, aux_parts, aux_xml, part_targets = {}, {}, [], {}, {}
    try:
        with zipfile.ZipFile(path) as pkg:
            styles = parse_styles(pkg)
            xml = pkg.read("word/document.xml").decode("utf-8")
            # Embedded-image geometry: the image parts' own pixels, resolved
            # through each part's relationship file (document + header/footer,
            # where the logo lives).
            sizes = media_pixel_sizes(pkg)
            doc_rels = part_rels(pkg, "word/document.xml")
            # Header/footer parts can carry a VENUE name (`footer_venue_default.xml`)
            # as well as a numbered one; the old `\d*` regex read only the numbered
            # parts, so the part actually printed was never scanned and an orphan
            # numbered part produced the row instead.
            rels_name = "word/_rels/document.xml.rels"
            if rels_name in pkg.namelist():
                rels_xml = pkg.read(rels_name).decode("utf-8", "replace")
                for m in re.finditer(r"<Relationship(?=[\s/>])[^>]*/>", rels_xml):
                    attrs = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', m.group(0)))
                    typ = attrs.get("Type", "")
                    if attrs.get("Id") and (typ.endswith("/header") or typ.endswith("/footer")):
                        target = attrs.get("Target", "").lstrip("/").replace("\\", "/")
                        part_targets[attrs["Id"]] = (target if target.startswith("word/")
                                                     else "word/" + target)
            for name in sorted(pkg.namelist()):
                if re.match(r"word/(?:header|footer)[A-Za-z0-9_\-]*\.xml$", name):
                    aux_parts.append((name, part_rels(pkg, name)))
                    aux_xml[name] = pkg.read(name).decode("utf-8", "replace")
            if "docProps/app.xml" in pkg.namelist():
                m = re.search(r"<Pages>(\d+)</Pages>",
                              pkg.read("docProps/app.xml").decode("utf-8", "replace"))
                if m:
                    app_pages = int(m.group(1))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError, OSError,
            RuntimeError, NotImplementedError) as e:
        # RuntimeError is what `zipfile` raises for an ENCRYPTED entry (and
        # NotImplementedError for an unsupported compression method): a
        # password-protected .docx is unreadable like any other, not a crash.
        row = {"rule": "FMT-X1", "severity": "high", "document": path.name, "location": "-",
               "evidence": f"{type(e).__name__}: {e}", "detail": "unreadable DOCX package",
               "fix": "manual", "protected": False}
        return {"file": str(path), "rows": [row], "by_rule": {"FMT-X1": 1},
                "high": 1, "medium": 0, "low": 0, "documents": {}}
    res = analyse_document(xml, styles, policy, path.name, sizes=sizes, rels=doc_rels)
    # FMT-Z5: the document's Zotero citation STYLE is recorded in more than one
    # place (`word/settings.xml` docVars and, in newer versions, the
    # `docProps/custom.xml` property). They can disagree after an upgrade or a
    # partial re-save, and the next refresh then re-renders every bibliography
    # entry in the other CSL style -- a whole-package formatting change with no
    # other warning. Only this package-level pass can see both stores.
    try:
        with zipfile.ZipFile(path) as pkg:
            zotero_parts = {}
            for cand in ("word/settings.xml", "docProps/custom.xml"):
                if cand in pkg.namelist():
                    zotero_parts[cand] = pkg.read(cand).decode("utf-8", "replace")
            for cand in pkg.namelist():
                if re.match(r"customXml/item\d*\.xml$", cand):
                    zotero_parts[cand] = pkg.read(cand).decode("utf-8", "replace")
            styles_found = zotero_style_ids(zotero_parts)
            if len(set(styles_found.values())) > 1:
                res["rows"].append({
                    "rule": "FMT-Z5", "severity": "medium", "document": path.name,
                    "location": "document preferences",
                    "evidence": "; ".join(f"{p} -> {s}" for p, s in sorted(styles_found.items())),
                    "detail": "the document carries more than one Zotero citation-style "
                              "identifier; a Word/Zotero refresh re-renders every "
                              "bibliography entry in whichever store it honours, so the "
                              "reference FORMAT can change (and no longer match the target "
                              "journal's style) without any other warning",
                    "fix": "manual", "protected": True, "tier": tier_of("FMT-Z5")})
    except (zipfile.BadZipFile, KeyError, OSError):
        pass
    # Only a REFERENCED header/footer part is printed: the template packages
    # carry orphan numbered parts (footer2.xml) that Word never uses, and a row
    # against one of those is a false positive.
    ref_ids = set(re.findall(
        r"<w:(?:header|footer)Reference[^>]*r:id=\"([^\"]+)\"", xml))
    referenced = {part_targets[rid] for rid in ref_ids if rid in part_targets}
    res["rows"].extend(page_field_rows(
        [(name, aux_xml[name]) for name in sorted(referenced) if name in aux_xml],
        path.name))
    for name, rels in aux_parts:
        if name not in referenced:
            # The SAME rule as FMT-S10 above: an orphan part is not printed, and
            # the fixer now neither repairs nor verifies it. Scanning its image
            # geometry would file a mechanical FMT-IM1 row that `fix` reports as
            # resolved but never repairs (scan: 2 rows, fix: ok, scan again: 1).
            continue
        aux_rows, _aux_fixes = drawing_geometry_rows(
            aux_xml.get(name, ""), rels, sizes, path.name, policy,
            location_prefix=f"{posixpath.basename(name)} p")
        res["rows"].extend(aux_rows)
    # The cover letter's two-page budget: a rendered PDF beside the .docx is
    # authoritative; without one, the cached Pages value is reported (and the
    # row says which source it came from -- the cache can be stale).
    if re.search(r"cover[\s_-]?letter", path.name, re.I):
        pages, src = None, ""
        pdf = path.with_suffix(".pdf")
        if pdf.is_file() and shutil.which("pdftotext"):
            try:
                txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                                     capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=60).stdout
                pages, src = (blank_pages_in_text(txt)["pages"],
                              "the rendered PDF beside it")
            except (OSError, subprocess.SubprocessError) as e:
                # A wedged or erroring pdftotext must degrade to the cached value,
                # never abort the whole corpus scan (the sibling helpers catch
                # exactly this tuple). `pages` stays None so the fallback runs.
                print(f"warning: pdftotext failed on {pdf.name} ({type(e).__name__}); "
                      f"using the cached page count", file=sys.stderr)
        if pages is None and app_pages is not None:
            pages, src = app_pages, "the cached docProps/app.xml value -- render to confirm"
        if pages and pages > 2:
            res["rows"].append(cover_letter_page_row(path, pages, src))
    # The cover letter formatted in the MANUSCRIPT template (FMT-CL1): the venue
    # policy carries the manuscript template's own front-matter style ids and
    # header/footer part hashes, so a stamped letter is a deterministic row --
    # never only an agent's visual impression.
    res["rows"].extend(cover_letter_stamp_rows(path, policy))
    # FMT-IM6: the placed raster's own type size (FMT-IM4 only checks dpi;
    # a 300-dpi image drawn at half width still halves the printed type).
    # `figure_ocr=false` turns off OCR; FMT-IM6 cannot be measured without it,
    # so it becomes a recorded gap instead of an unconditional tesseract call.
    if _policy_flag(policy, "figure_ocr", True):
        res["rows"].extend(figure_text_size_rows(path, policy))
    elif sizes and float(policy.get("min_figure_text_pt")
                         or (policy.get("figure_text") or {}).get("min_pt") or 0) > 0:
        res["rows"].append({
            "rule": "FMT-IM6", "severity": "low", "document": path.name,
            "location": "figures", "evidence": "figure_ocr is off",
            "detail": ("the embedded figure-text-size class (FMT-IM6) was NOT examined: "
                       "measure the artwork's type at the printed width or re-run with "
                       "figure_ocr on"),
            "fix": "manual", "protected": False, "tier": "advisory"})
    counts = Counter(r["rule"] for r in res["rows"])
    return {"file": str(path), "rows": res["rows"], "by_rule": dict(counts),
            "high": sum(1 for r in res["rows"] if r["severity"] == "high"),
            "medium": sum(1 for r in res["rows"] if r["severity"] == "medium"),
            "low": sum(1 for r in res["rows"] if r["severity"] == "low"),
            "documents": {path.name: res}}


def docx_files_under(dirp: Path) -> list:
    """Every .docx under a directory, EITHER extension case.

    `rglob("*.docx")` is case-SENSITIVE on Linux, so a Word-authored
    `REPORT.DOCX` was invisible to the scan and validate paths (the corpus
    itself copies any file, so the document was in the package but never
    checked). The set dedupes on case-insensitive filesystems.
    """
    return sorted(set(dirp.rglob("*.docx")) | set(dirp.rglob("*.DOCX")))


def scan_paths(paths: list, policy: dict) -> dict:
    """Scan the corpus documents under `paths`.

    Difference-tracking auxiliaries (`*.tracking-<token>.<ext>` and their
    `*.logging-<token>.<ext>` fallbacks -- see `_is_aux_name()`) and the stage
    scratch under any `work/` directory are NOT corpus content (the pipeline
    strips both from every judged/pinned corpus), so they are skipped: scanning
    them inflated one real sandbox report to 971 findings and hid the signal.
    There is deliberately no switch back: they are never corpus content.
    """
    docs = []
    for p in paths:
        if not p.exists():
            continue
        files = docx_files_under(p) if p.is_dir() else [p]
        for f in files:
            if f.name.startswith("~$") or _is_aux_name(f.name):
                continue
            if any(part == "work" for part in f.parts[:-1]):
                continue
            if any(part in EVIDENCE_DIRNAMES for part in f.parts[:-1]):
                # The EVIDENCE areas are not submission content: a reviewer's
                # .docx report or a data-source document is never a submission
                # formatting finding.
                continue
            docs.append(analyse_package(f, policy))
    rows = [r for d in docs for r in d["rows"]]
    if _policy_flag(policy, "figure_ocr", True):
        texts = []
        for d in docs:
            try:
                with zipfile.ZipFile(d["file"]) as z:
                    dxml = z.read("word/document.xml").decode("utf-8", "replace")
                texts.append("\n".join(text_of(pp[2]) for pp in paragraphs(dxml)))
            except (OSError, zipfile.BadZipFile, KeyError, RuntimeError,
                    NotImplementedError):
                continue
        images = []
        for p in paths:
            if not p.is_dir():
                continue
            for q in sorted(p.rglob("*")):
                if not q.is_file() or q.suffix.lower() not in (".png", ".jpg", ".jpeg",
                                                              ".tif", ".tiff"):
                    continue
                if any(part == "work" or part in EVIDENCE_DIRNAMES
                       for part in q.parts[:-1]):
                    continue
                images.append(q)
        if images:
            rows.extend(figure_label_rows(images, vocabulary_terms(texts)))
    return {"files": [d["file"] for d in docs], "documents": docs, "rows": rows,
            "by_rule": dict(Counter(r["rule"] for r in rows)),
            "high": sum(1 for r in rows if r["severity"] == "high"),
            "medium": sum(1 for r in rows if r["severity"] == "medium"),
            "low": sum(1 for r in rows if r["severity"] == "low")}


def format_note(info) -> str:
    """One-line summary for the pipeline's setup/decide output."""
    if not info:
        return "not verified (no formatting scan recorded)"
    rows = info.get("rows") or []
    if not rows:
        return "OOXML formatting: clean (no structural/typographic findings)"
    top = ", ".join(f"{k} x{v}" for k, v in sorted((info.get("by_rule") or {}).items())[:5])
    return (f"OOXML formatting: {len(rows)} finding(s) [{info.get('high', 0)} high, "
            f"{info.get('medium', 0)} medium, {info.get('low', 0)} low]: {top}")


# --------------------------------------------------------------------------
# fixing (byte-level splices, applied back-to-front, self-verified)
# --------------------------------------------------------------------------

def apply_edits(xml: str, edits: list) -> str:
    for start, end, new in sorted(edits, key=lambda e: -e[0]):
        xml = xml[:start] + new + xml[end:]
    return xml


# CT_PPrBase's children that PRECEDE `w:spacing`, in schema order: a child spliced
# into a `w:pPr` must land after every one of them or the emitter produces a
# schema-invalid property bag that only a real OOXML validator notices.
PPR_SPACING_AFTER = ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
                     "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
                     "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
                     "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
                     "snapToGrid")


def insert_into_ppr(para: str, element: str, after=("pStyle", "keepNext", "keepLines")) -> str:
    ppr = ppr_of(para)
    if ppr is None:
        tag_end = para.find(">") + 1
        head, tail = para[:tag_end], para[tag_end:]
        if head.rstrip().endswith("/>"):
            # A self-closing paragraph (`<w:p w:rsidR="..."/>`, what python-docx
            # emits for an empty paragraph) has no `>` that closes an open tag:
            # inserting after it would orphan the properties OUTSIDE the
            # paragraph and produce schema-invalid XML. Expand the tag first.
            head = head.rstrip()[:-2].rstrip() + ">"
            tail = "</w:p>" + tail
        return head + "<w:pPr>" + element + "</w:pPr>" + tail
    pos = 0
    for tag in after:
        m = re.search(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>", ppr, re.S)
        if m:
            pos = max(pos, m.end())
    if pos == 0:
        # Anchor at the END of the `w:pPr` open tag, not at a fixed offset: Word
        # writes attributes on it (`<w:pPr w:rsidR="...">`), and splicing a child
        # in after a fixed `len("<w:pPr>")` corrupts the tag. A self-closing
        # `w:pPr` has to be expanded before the child can go inside it.
        m = re.match(r"<w:pPr(?=[\s/>])[^>]*>", ppr)
        if m and m.group(0).rstrip().endswith("/>"):
            head = m.group(0).rstrip()[:-2].rstrip() + ">"
            return para.replace(ppr, head + element + "</w:pPr>", 1)
        pos = m.end() if m else len("<w:pPr>")
    return para.replace(ppr, ppr[:pos] + element + ppr[pos:], 1)


def _unlink_fields(xml: str) -> tuple:
    """Drop fldChar/instrText runs; keep field RESULT runs (Zotero unlinking)."""
    # A `w:fldSimple` is a live field too, but it carries no fldChar/instrText
    # runs: the old loop left the element (and therefore the field) in place.
    # Removing only its tags keeps the RESULT runs as plain text.
    simple_opens = re.findall(r"<w:fldSimple\b[^>]*>", xml)
    if simple_opens:
        xml = re.sub(r"<w:fldSimple\b[^>]*/>|<w:fldSimple\b[^>]*>|</w:fldSimple>", "", xml)
    edits, depth, removed = [], 0, len(simple_opens)
    for m in RUN_RE.finditer(xml):
        run = m.group(0)
        fld = FIELD_CHAR_RE.search(run)
        is_instr = bool(INSTR_RE.search(run))
        if fld:
            kind = fld.group(1)
            if kind == "begin":
                depth += 1
            elif kind == "end":
                depth = max(0, depth - 1)
            edits.append((m.start(), m.end(), ""))
            removed += 1
        elif is_instr and depth > 0:
            edits.append((m.start(), m.end(), ""))
            removed += 1
    return apply_edits(xml, edits), removed


def fix_document(xml: str, styles: dict, policy: dict,
                 sizes: dict = None, rels: dict = None) -> tuple:
    """(new_xml, changes, meta) — byte-level edits; rules run in dependency order."""
    changes = []

    # 1. unlink fields first, so run-level fixes stick ---------------------------
    if policy["unlink_zotero_fields"]:
        xml, removed = _unlink_fields(xml)
        if removed:
            changes.append(f"unlinked {removed} field run(s): Zotero citations/bibliography "
                           f"are now plain text (refreshable in the Zotero copy only)")

    # 2. break-only empty paragraph -> pageBreakBefore on the next paragraph ----
    # A paragraph inside a table cell is NEVER the target and never the
    # paragraph the break moves onto: splicing a cell's only (empty) paragraph
    # out leaves `<w:tc></w:tc>`, which Word reports as a corrupt file (the same
    # hazard `_table_paragraph_indices` documents for step 2b), and a
    # `w:pageBreakBefore` written into a cell is not the document-level break
    # the rule means. The next BODY paragraph still receives the break.
    for _ in range(50):
        plist = paragraphs(xml)
        in_table = _table_paragraph_indices(xml, plist)
        target = None
        for idx, (p0, p1, para) in enumerate(plist):
            if idx in in_table:
                continue
            if PAGEBREAK_RE.search(para) and not text_of(para).strip() \
                    and not has_drawing(para) and not has_field(para):
                target = (idx, p0, p1, para)
                break
        if target is None:
            break
        idx, p0, p1, para = target
        edits = [(p0, p1, "")]
        nxt = next((j for j in range(idx + 1, len(plist)) if j not in in_table), None)
        if nxt is not None:
            np0, np1, npara = plist[nxt]
            edits.append((np0, np1, insert_into_ppr(npara, "<w:pageBreakBefore/>")))
            changes.append(f"moved the page break onto the following paragraph (was the empty p{idx})")
        else:
            changes.append(f"removed the trailing break-only paragraph p{idx}")
        xml = apply_edits(xml, edits)

    # 2b. stray empty paragraphs (template-aware) --------------------------------
    # A blank line attached to a heading, or a run beyond the cap, that the
    # venue's own template does NOT prescribe. Deleting an empty paragraph does
    # not change the document text (the fixer's verification compares non-empty
    # paragraph texts), and the prescribed blanks -- the front-matter spacer
    # above the title, the template's own placeholder slots -- are never in the
    # group.
    groups, _prescribed = stray_empty_paragraph_groups(paragraphs(xml), policy, xml)
    drop = sorted({i for indices, _kind in groups for i in indices})
    if drop:
        plist = paragraphs(xml)
        edits = [(plist[i][0], plist[i][1], "") for i in drop if i < len(plist)]
        xml = apply_edits(xml, edits)
        changes.append(f"deleted {len(edits)} stray empty paragraph(s): a blank line "
                       f"next to a heading or beyond the max_empty_paragraph_run cap "
                       f"(template-prescribed blanks kept)")

    # 3. caption/legend blocks ---------------------------------------------------
    # One caption, one paragraph, one spacing, one style (see
    # `caption_block_ranges`): the merge (FMT-T2c) first, so the spacing below
    # runs on the paragraphs the file will actually ship.
    # 3a. the caption's own paragraph style (FMT-T2d) ---------------------------
    plist = paragraphs(xml)
    areas = display_area_kinds(plist)
    blocks = caption_block_ranges(plist, areas, container_spans(xml), xml=xml)
    edits, n = [], 0
    for area_kind in ("figure", "table"):
        members = [x["label"] for x in blocks
                   if x["in_area"] and x["kind"] == area_kind]
        if len(members) < 2:
            continue
        seen = Counter(_para_style(plist[i][2]) for i in members)
        majority, count = seen.most_common(1)[0]
        if len(seen) < 2 or count * 2 <= len(members):
            continue
        for i in members:
            para = plist[i][2]
            if _para_style(para) == majority:
                continue
            pstyle = elem(ppr_of(para), "pStyle")
            if pstyle is None:
                # The scanner reports an unstyled minority caption as
                # mechanical, so the fixer must give it a style (or drop the
                # row to editorial); skipping it left the row unfixed and the
                # whole file's repairs were then rejected.
                if majority:
                    edits.append((plist[i][0], plist[i][1],
                                  _set_para_style(para, majority)))
                    n += 1
                continue
            at = plist[i][0] + para.find(pstyle)
            replacement = f'<w:pStyle w:val="{majority}"/>' if majority else ""
            edits.append((at, at + len(pstyle), replacement))
            n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"aligned {n} caption paragraph(s) with the paragraph style "
                       f"their sibling captions in the same area use")

    # 3b. merge multi-paragraph captions (FMT-T2c) ------------------------------
    plist = paragraphs(xml)
    areas = display_area_kinds(plist)
    blocks = caption_block_ranges(plist, areas, container_spans(xml), xml=xml)
    edits, joins, refused = [], [], 0
    for b in blocks:
        if not (b["in_area"] and b["continuations"]):
            continue
        parts = [plist[i] for i in [b["label"]] + b["continuations"]]
        merged = merged_caption_paragraph(parts, styles)
        if merged is None or not b.get("mergeable"):
            refused += 1
            continue
        edits.append((parts[0][0], parts[-1][1], merged))
        joins.append({"label": b["label"], "continuations": b["continuations"],
                      "caption": text_of(parts[0][2]).strip()[:60]})
    joined_baseline = None
    if edits:
        # The verifier compares the flattened document text; the merge turns two
        # paragraphs into one, so it gets the joined baseline of THIS list.
        joined_baseline = _flatten_with_joins([text_of(p[2]) for p in plist], joins)
        xml = apply_edits(xml, edits)
        changes.append(f"merged {len(edits)} multi-paragraph caption(s) into one "
                       f"paragraph" + (f" ({refused} left for the revision arms: a "
                                       f"field/image inside)" if refused else ""))

    # 3c. the caption's line spacing (FMT-T2a/T2b) ------------------------------
    want_sp = (f'<w:spacing w:before="{policy["caption_space"]}" '
               f'w:after="{policy["caption_space"]}" w:line="{policy["caption_line"]}" '
               f'w:lineRule="auto"/>')
    plist = paragraphs(xml)
    areas = display_area_kinds(plist)
    blocks = caption_block_ranges(plist, areas, container_spans(xml), xml=xml)
    targets = set()
    for b in blocks:
        targets.add(b["label"])
        if b["in_area"]:
            targets.update(b["continuations"])
    for i, (_, _, para) in enumerate(plist):
        if LEGEND_RE.match(text_of(para)):
            targets.add(i)
    edits, n = [], 0
    for i in sorted(targets):
        p0, p1, para = plist[i]
        ppr = ppr_of(para)
        if ppr and elem(ppr, "spacing"):
            old = elem(ppr, "spacing")
            already = (attr(old, "line") == str(policy["caption_line"])
                       and attr(old, "before") == str(policy["caption_space"])
                       and attr(old, "after") == str(policy["caption_space"]))
            if not already:
                at = p0 + para.find(old)
                edits.append((at, at + len(old), want_sp))
                n += 1
        else:
            # `w:spacing` is late in CT_PPrBase's child sequence: anchoring it
            # after pStyle/keepNext/keepLines alone put it BEFORE an existing
            # numPr/pBdr/shd/tabs, which the schema orders ahead of it (the
            # well-formedness fence cannot see the difference, and the optional
            # `docx validate` may not be installed).
            edits.append((p0, p1, insert_into_ppr(para, want_sp, after=PPR_SPACING_AFTER)))
            n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"unified figure-legend spacing on {n} caption paragraph(s) "
                       f"(line={policy['caption_line']}, before/after={policy['caption_space']})")

    # 4. heading keepNext (+ optional size alignment) ---------------------------
    edits, kept, aligned = [], 0, 0
    for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
        ppr = ppr_of(para)
        style = elem_val(ppr, "pStyle")
        if not style or not style.startswith("Heading"):
            continue
        new_para = para
        if policy["heading_keep_with_next"] and not (ppr and "<w:keepNext" in ppr):
            new_para = insert_into_ppr(new_para, "<w:keepNext/><w:keepLines/>")
            kept += 1
        if policy["align_heading_sizes"]:
            want = style_sz(styles, style)
            if want:
                for _, _, run in runs(new_para):
                    rpr = rpr_of(run)
                    if elem_val(rpr, "sz") and elem_val(rpr, "sz") != want:
                        new_run = run.replace(
                            rpr, re.sub(r"<w:sz(?=[\s/>])[^>]*/>", "", rpr), 1)
                        new_para = new_para.replace(run, new_run, 1)
                        aligned += 1
        if new_para != para:
            edits.append((p0, p1, new_para))
    if edits:
        xml = apply_edits(xml, edits)
        if kept:
            changes.append(f"added keepNext/keepLines to {kept} heading(s)")
        if aligned:
            changes.append(f"aligned {aligned} heading run size(s) with their heading style")

    # 5. title-page header ------------------------------------------------------
    if policy["title_page_header"] == "suppress":
        # SECT_READ_RE is the reader that also matches a legal self-closing
        # `<w:sectPr .../>`; the old non-greedy pattern ran past it to the NEXT
        # section's closing tag, so a self-closing first section never got its
        # w:titlePg added.
        s = next(SECT_READ_RE.finditer(xml), None)
        if s is not None and "<w:headerReference" in s.group(0) \
                and "<w:titlePg" not in s.group(0):
            body = s.group(0)
            if body.rstrip().endswith("/>"):
                # A legal self-closing (empty) section has no closing tag to
                # insert before: expand it, or the splice lands OUTSIDE the
                # element and the scanner keeps reporting FMT-S3 while the fixer
                # believes it repaired it.
                head = body.rstrip()[:-2].rstrip() + ">"
                xml = apply_edits(xml, [(s.start(), s.end(), head + "<w:titlePg/></w:sectPr>")])
            else:
                at = s.start() + body.find("</w:sectPr>")
                for tag in ("docGrid", "printerSettings"):
                    t = body.find(f"<w:{tag}")
                    if t != -1:
                        at = min(at, s.start() + t)
                xml = apply_edits(xml, [(at, at, "<w:titlePg/>")])
            changes.append("added w:titlePg: the running head no longer prints on page 1")

    # 6. unintended italics (title block, italic 'et al.' outside fields) -------
    plist = paragraphs(xml)
    franges = field_ranges(xml)
    title_end = None
    for i, (_, _, p) in enumerate(plist):
        if re.match(r"^\s*(abstract|summary)\s*:?\s*$", text_of(p), re.I):
            title_end = i
            break
    edits, n = [], 0
    for idx, (p0, p1, para) in enumerate(plist):
        text = text_of(para)
        style = elem_val(ppr_of(para), "pStyle")
        block = (title_end is not None and idx < title_end
                 and re.search(r"@|Correspondence|ORCID", text, re.I))
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if not rtext.strip():
                continue
            rpr = rpr_of(run)
            if not (is_on(rpr, "i") or is_on(rpr, "iCs")):
                continue
            in_field_run = bool(in_field(franges, p0 + r0))
            if in_field_run and not policy["unlink_zotero_fields"]:
                continue                      # reported as style-field, never silently "fixed"
            if block or (style == "Bibliography" and re.search(r"\bet\s+al\.", rtext)):
                if rpr:
                    edits.append((p0 + r0, p0 + r1, run.replace(
                        rpr, re.sub(r"<w:i(?:Cs)?(?=[\s/>])[^>]*/>", "", rpr), 1)))
                    n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"removed {n} unintended italic run(s) (title/correspondence block, "
                       f"italic 'et al.')")

    # 6b. journal emphasis: one treatment for a journal title in each region ----
    # This is the fix for the class the direct-rPr check could not see: an italic
    # that comes from a character style (Word's "Emphasis"), a journal emphasised
    # in some sentences and not others, and an emphasis span that runs on over
    # ordinary words ("Nature Methods and other leading journals").
    policy_j = policy["journal_italics"]
    if policy_j in ("refs-only", "everywhere", "off"):
        edits, flipped = [], 0
        franges = field_ranges(xml)
        for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
            style = elem_val(ppr_of(para), "pStyle")
            region = "refs" if style == "Bibliography" else "prose"
            want_italic = (region == "refs" and policy_j in ("refs-only", "everywhere")) \
                or (region == "prose" and policy_j == "everywhere")
            analysis = journal_emphasis_runs(styles, style, para)
            targets = []                      # (r0, r1, run, desired italic)
            if want_italic:
                targets += [(r0, r1, run, True)
                            for r0, r1, run, names in analysis["roman"]
                            if all(_title_only(text_of(run), n) for n in names)]
                targets += [(r0, r1, run, False)
                            for r0, r1, run, _extra, _name in analysis["continuation"]]
            else:
                targets += [(r0, r1, run, False)
                            for r0, r1, run, _names in analysis["italic"]]
                targets += [(r0, r1, run, False)
                            for r0, r1, run, _extra, _name in analysis["continuation"]]
            for r0, r1, run, want in targets:
                if run_is_italic(styles, style, run) == want:
                    continue
                if in_field(franges, p0 + r0):
                    continue                  # field-protected: reported, never silently edited
                new_run = run
                rpr = rpr_of(run)
                new_rpr, changed = _rpr_set_emphasis(rpr, want)
                if rpr is None:
                    open_tag = re.match(r"<w:r(?=[\s/>])[^>]*>", new_run)
                    if open_tag is None:
                        continue
                    new_run = new_run[:open_tag.end()] + new_rpr + new_run[open_tag.end():]
                elif changed:
                    new_run = new_run.replace(rpr, new_rpr, 1)
                if new_run != run:
                    edits.append((p0 + r0, p0 + r1, new_run))
                    flipped += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"normalized journal emphasis on {flipped} run(s) "
                           f"(policy: journal_italics={policy_j})")

    # 6c. mixed emphasis for the SAME phrase (label italic once, roman once) ----
    # A parenthetical label is not emphasis: the majority treatment wins and a
    # tie resolves to roman. Non-label phrases are reported by the scanner, never
    # silently restyled (a name may legitimately be italic, e.g. a gene).
    _t9a_rows, t9a_fixes = emphasis_consistency(styles, paragraphs(xml))
    if t9a_fixes:
        plist = paragraphs(xml)
        edits, flipped = [], 0
        for idx, r0, r1, want in t9a_fixes:
            p0 = plist[idx][0]
            run = plist[idx][2][r0:r1]
            if run_is_italic(styles, elem_val(ppr_of(plist[idx][2]), "pStyle"), run) == want:
                continue
            rpr = rpr_of(run)
            new_rpr, changed = _rpr_set_emphasis(rpr, want)
            new_run = run
            if rpr is None:
                open_tag = re.match(r"<w:r(?=[\s/>])[^>]*>", new_run)
                if open_tag is None:
                    continue
                new_run = new_run[:open_tag.end()] + new_rpr + new_run[open_tag.end():]
            elif changed:
                new_run = new_run.replace(rpr, new_rpr, 1)
            if new_run != run:
                edits.append((p0 + r0, p0 + r1, new_run))
                flipped += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"unified {flipped} mixed-emphasis label run(s)")

    # 7. URL/email treatment ----------------------------------------------------
    if policy["url_style"] == "plain":
        edits, n = [], 0
        for m in re.finditer(r"<w:hyperlink(?=[\s>]).*?</w:hyperlink>", xml, re.S):
            block = m.group(0)
            inner = block[block.find(">") + 1:block.rfind("</w:hyperlink>")]
            inner = re.sub(r"<w:rStyle[^>]*/>", "", inner)
            inner = re.sub(r"<w:color[^>]*/>", "", inner)
            inner = re.sub(r"<w:u[^>]*/>", "", inner)
            edits.append((m.start(), m.end(), inner))
            n += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"unwrapped {n} hyperlink(s) into plain black text (url_style=plain)")
        # plain runs that carry a URL/email must match: no link style, no colour,
        # no underline, no italic (the correspondence block used dark-grey italic)
        edits, n2 = [], 0
        for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
            for r0, r1, run in runs(para):
                if not URL_RE.search(text_of(run)):
                    continue
                rpr = rpr_of(run)
                if not rpr:
                    continue
                stripped = rpr
                for tag in ("rStyle", "color", "u", "i", "iCs"):
                    stripped = re.sub(rf"<w:{tag}(?=[\s/>])[^>]*/>", "", stripped)
                    stripped = re.sub(rf"<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>", "", stripped)
                if stripped != rpr:
                    edits.append((p0 + r0, p0 + r1, run.replace(rpr, stripped, 1)))
                    n2 += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"removed leftover link/colour/italic styling from {n2} URL/email run(s)")

    # 8. quotes / proofing markers ---------------------------------------------
    if policy["quote_style"] in ("straight", "curly"):
        # Characters after which a straight quote OPENS. Anything else closes
        # (letters/digits/.,:;!?)]} and the closing curly quotes). The openers
        # are whitespace, brackets, dashes and the opening curly quotes -- a
        # `("quoted")` must not become `(”quoted”)`, and a nested `"'...'"`
        # must open both.
        quote_openers = frozenset(" \t\n\r\f\v([{<\u2012\u2013\u2014\u2015\u2018\u201c-")

        # A quotation can span several `<w:t>` runs -- Word splits them freely
        # (a spell-check boundary, a language change, a deleted revision) -- so
        # the open/close decision needs the last visible character BEFORE this
        # run, not a flag that restarts at run 1. Restarting per run turned the
        # closing quote of a two-run `"hello` + ` there"` into an opening one,
        # and keying `'` off the `"` state flipped a quoted phrase inside-out
        # (`'quoted'` -> '\u2018quoted\u2018'); the text-identity verifier strips
        # quotes before comparing, so that corruption shipped silently.
        def conv(mm, prev_open):
            raw = mm.group(0)
            open_tag = raw[:raw.find(">") + 1]
            close_tag = raw[raw.rfind("<"):]
            text = unesc(raw[raw.find(">") + 1:raw.rfind("<")])
            if policy["quote_style"] == "curly":
                # An apostrophe inside a word is always a right single quote.
                text = re.sub(r"(?<=\w)'(?=\w)", "\u2019", text)
                out = []
                for ch in text:
                    if ch in "\"'":
                        opening = prev_open
                        out.append(("\u201c" if ch == '"' else "\u2018") if opening
                                   else ("\u201d" if ch == '"' else "\u2019"))
                        # An OPENING quote leaves the next quote free to open
                        # again (nested quotes); a closing one does not.
                        prev_open = opening
                    else:
                        out.append(ch)
                        prev_open = ch in quote_openers
                text = "".join(out)
            else:
                text = (text.replace("\u2019", "'").replace("\u2018", "'")
                        .replace("\u201c", '"').replace("\u201d", '"'))
                if text:
                    prev_open = text[-1] in quote_openers
            return open_tag + esc(text) + close_tag, prev_open

        def _paragraph(xml_frag: str) -> str:
            """Normalize one paragraph's text runs with state across runs."""
            prev_open = True
            pieces, pos = [], 0
            for mm in TEXT_RE.finditer(xml_frag):
                gap = xml_frag[pos:mm.start()]
                # A tab or a line break starts a new visual line: the next
                # quote opens. (Both live OUTSIDE `<w:t>`, so the text scan
                # alone would keep the previous character's state.)
                if re.search(r"<w:(?:tab|br|cr)(?=[\s/>])", gap):
                    prev_open = True
                pieces.append(gap)
                new_frag, prev_open = conv(mm, prev_open)
                pieces.append(new_frag)
                pos = mm.end()
            pieces.append(xml_frag[pos:])
            return "".join(pieces)

        pieces, pos = [], 0
        for pm in re.finditer(r"<w:p(?=[\s/>])[\s\S]*?</w:p>", xml):
            pieces.append(_paragraph(xml[pos:pm.end()]))
            pos = pm.end()
        pieces.append(_paragraph(xml[pos:]))
        new = "".join(pieces)
        if new != xml:
            xml = new
            changes.append(f"normalized quotation marks (policy: {policy['quote_style']})")
    if policy["strip_proofing_markers"] and PROOFERR_RE.search(xml):
        n = len(PROOFERR_RE.findall(xml))
        xml = PROOFERR_RE.sub("", xml)
        changes.append(f"removed {n} proofing marker(s) (w:proofErr)")

    # 9. text-level consistency: citations / spelling / hyphenation ------------
    # These DO change document text, so each edit is recorded and the fixer's
    # verification proves that nothing beyond the recorded edits moved (the
    # reference list is never rewritten: its titles are quotations).
    # The edits below are enumerated and offset against THIS XML (after the
    # structural fixes and the quote normalisation), so the verification must
    # reconstruct its expectation from the same stage -- reconstructing from the
    # original XML applied them to the wrong paragraphs once a break-only
    # paragraph had been deleted above (and mismatched quotes whenever
    # quote_style also fired).
    text_stage_xml = xml
    text_edits, cit_n, spell_n, hy_n, hyg_n = [], 0, 0, 0, 0
    want_cit = policy["citation_journal_names"] == "drop"
    want_spell = policy["term_spelling"] == "dominant"
    want_hy = policy["term_hyphenation"] == "dominant"
    # This block ALWAYS runs: text hygiene is mechanical and unconditional, and
    # the three consistency rules below are policy-gated (`keep` pre-judge).
    doc_field_results = _field_result_spans(xml)
    bodies = []
    step9_paras = paragraphs(xml)
    step9_texts = [text_of(p[2]) for p in step9_paras]
    step9_is_ref = [elem_val(ppr_of(p[2]), "pStyle") == "Bibliography"
                    for p in step9_paras]
    if not any(step9_is_ref):
        # A template-restyled package carries its reference list under another
        # style id. The scanner's FMT-R rules already fall back to the numbered
        # entries under an explicit bibliography heading; step 9 must use the
        # same definition, or it rewrites reference TITLES ("Colour" -> "Color")
        # even though the module promises the reference list is never rewritten
        # (its titles are quotations).
        bib_start = _bibliography_entry_start(step9_texts)
        if bib_start > 0:
            step9_is_ref = [
                step9_is_ref[i]
                or (i >= bib_start
                    and bool(re.match(r"^\s*\d+\s*[\.\)]\s*\S", step9_texts[i])))
                for i in range(len(step9_is_ref))]
    for idx, (p0, p1, para) in enumerate(step9_paras):
        if step9_is_ref[idx]:
            continue
        bodies.append((idx, p0, p1, para, step9_texts[idx]))
    blob = "\n".join(b[4] for b in bodies)
    spell_target = (spelling_minority_targets([b[4] for b in bodies])
                    if want_spell else {})
    hy_target = set()
    # Only an attributive use takes the hyphen. A following function word
    # ("the copy number of a locus") starts the noun use, which the rule
    # documents as correct without one. The scanner applies the same exclusion;
    # arming on a noun use made the fixer edit text no FMT-T8e row reported.
    hy_noun_follow = "|".join(re.escape(w) for w in HYPHEN_NOUN_FOLLOWERS)
    if want_hy:
        for hy, split in HYPHEN_COMPOUNDS:
            if re.search(rf"\b{re.escape(hy)}(?=\s+(?!(?:{hy_noun_follow})\b)[A-Za-z])",
                         blob):
                hy_target.add((hy, split))
    edits = []
    for idx, p0, p1, para, text in bodies:
        spans = []
        # A live field's RESULT text is regenerated by Word, so a text edit
        # inside it would be lost on refresh: the scanner reports those rows as
        # field-protected (`fix=style-field`) and the fixer must not apply them
        # (the unlink policy is the one explicit opt-out).
        protected = ([] if policy["unlink_zotero_fields"]
                     else field_result_text_ranges(para, doc_field_results, p0))
        # Text hygiene: a space at a line edge (FMT-P4) and a doubled
        # article/preposition (FMT-G1) are mechanical. Both are recorded
        # below like every other text edit, so the fixer's verification can
        # prove that nothing beyond them moved.
        hygiene = [(sp["start"], sp["end"], sp["repl"])
                   for sp in hygiene_spans(para) if sp["fix"] == "mechanical"]
        if protected:
            hygiene = [h for h in hygiene if not in_field_result(protected, h[0], h[1])]
        spans.extend(hygiene)
        if want_cit:
            for m in CIT_YEAR_JOURNAL.finditer(text):
                if not in_field_result(protected, m.end(2), m.end(3)):
                    spans.append((m.end(2), m.end(3), ""))
            for m in CIT_JOURNAL_YEAR.finditer(text):
                if not in_field_result(protected, m.end(1), m.end(2)):
                    spans.append((m.end(1), m.end(2), ""))
        if want_spell:
            for minority, majority in spell_target.items():
                for m in re.finditer(rf"\b{re.escape(minority)}\b", text, re.I):
                    if in_field_result(protected, m.start(), m.end()):
                        continue
                    rep = (majority.capitalize()
                           if m.group(0)[:1].isupper() else majority)
                    spans.append((m.start(), m.end(), rep))
        if want_hy:
            for hy, split in hy_target:
                for m in re.finditer(
                        rf"\b{re.escape(split)}(?=\s+(?!(?:{hy_noun_follow})\b)[A-Za-z])",
                        text):
                    if in_field_result(protected, m.start(), m.end()):
                        continue
                    spans.append((m.start(), m.end(), hy))
        if not spans:
            continue
        new_para, applied = rewrite_text_spans(para, spans)
        if new_para == para:
            continue
        edits.append((p0, p1, new_para))
        hygiene_set = set(hygiene)
        for s, e, removed, repl in applied:
            text_edits.append((idx, s, e, repl))
            if (s, e, repl) in hygiene_set:
                hyg_n += 1
            elif repl == "":
                cit_n += 1
            elif repl in {h for h, _s in hy_target}:
                hy_n += 1
            else:
                spell_n += 1
    if edits:
        xml = apply_edits(xml, edits)
        bits = []
        if cit_n:
            bits.append(f"dropped the redundant journal name from {cit_n} citation(s)")
        if spell_n:
            bits.append(f"normalized {spell_n} spelling variant(s)")
        if hy_n:
            bits.append(f"hyphenated {hy_n} attributive compound(s)")
        if hyg_n:
            bits.append(f"cleaned {hyg_n} stray-space/doubled-word hygiene instance(s)")
        if bits:
            changes.append("text consistency: " + "; ".join(bits))

    # 10. embedded-image aspect ratio ------------------------------------------
    # The fix runs LAST (it is computed against the final XML); only the
    # drawing's geometry attributes change, never its text.
    if sizes is not None:
        _geo_rows, geo_fixes = drawing_geometry_rows(xml, rels or {}, sizes,
                                                     "stage", policy)
        if geo_fixes:
            xml = apply_edits(xml, geo_fixes)
            changes.append(f"restored the aspect ratio of {len(geo_fixes)} embedded "
                           f"image extent(s) from the image's own pixels")

    # 10b. table geometry (FMT-TB4/TB5) ----------------------------------------
    # The same width repair `repair-layout` performs, applied in the normal fix
    # path. Without it `fix` reported FMT-TB5 as a remaining mechanical rule and
    # rejected its own output (the round-2 neohet Table 3 is the case). The
    # repair changes only w:tblGrid/w:tcW, never text.
    _layout_rows = table_layout_rows(xml, styles, "stage", policy)
    _layout_edits = table_layout_fixes(xml, _layout_rows)
    if _layout_edits:
        xml = apply_edits(xml, _layout_edits)
        changes.append(f"repaired the geometry of {len(_layout_edits)} table(s) "
                       f"(grid/cells and identifier-column widths)")

    return xml, changes, {"text_edits": text_edits, "text_stage_xml": text_stage_xml,
                          "caption_joins": joins, "text_baseline": joined_baseline}


def fix_package(src: Path, out: Path, policy: dict) -> dict:
    # The scanner reports an unreadable package as a FMT-X1 row and never
    # raises; the fixer must fail the same way (a clean `ok: false` report the
    # CLI turns into exit 1) instead of leaking a zip/KeyError traceback.
    try:
        with zipfile.ZipFile(src) as probe:
            probe_names = set(probe.namelist())
    except (zipfile.BadZipFile, OSError) as e:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": f"unreadable DOCX package: {type(e).__name__}: {e}", "ok": False}
    if "word/document.xml" not in probe_names:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": "unreadable DOCX package: no word/document.xml", "ok": False}
    # The same contract covers the READ phase: an encrypted entry (RuntimeError),
    # an unsupported compression method, a malformed styles.xml (ParseError) or
    # a non-UTF-8 document.xml must come back as `ok: false`, not a traceback.
    sizes, doc_rels, aux = {}, {}, {}
    try:
        with zipfile.ZipFile(src) as pkg:
            parts = {i.filename: pkg.read(i.filename) for i in pkg.infolist()}
            styles = parse_styles(pkg)
            sizes = media_pixel_sizes(pkg)
            doc_rels = part_rels(pkg, "word/document.xml")
            for name in sorted(pkg.namelist()):
                if re.match(r"word/(?:header|footer)[A-Za-z0-9_\-]*\.xml$", name):
                    aux[name] = (pkg.read(name).decode("utf-8", "replace"),
                                 part_rels(pkg, name))
        xml_before = parts["word/document.xml"].decode("utf-8")
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError, OSError,
            RuntimeError, NotImplementedError) as e:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": f"unreadable DOCX package: {type(e).__name__}: {e}", "ok": False}
    referenced_aux = referenced_header_footer_parts(parts, xml_before)

    # 0. THE LOCAL ZOTERO REFRESH (and the style-store reconcile), so every
    # later rule -- and the delivered file -- sees the numbering a Word/Zotero
    # refresh would produce. A refusal (an unresolvable field, a bibliography
    # the rebuild cannot own) leaves the document untouched and is reported:
    # the flatten guard below then still refuses to freeze a stale numbering.
    zotero_refresh = {"changed": False, "skip": "disabled by policy"}
    if _policy_flag(policy, "refresh_zotero_fields", True):
        _zr = refresh_zotero_parts(parts, policy)
        zotero_refresh = {k: v for k, v in _zr.items() if k != "parts"}
        if _zr.get("changed"):
            parts = _zr["parts"]
            xml_before = parts["word/document.xml"].decode("utf-8")
    # 0b. REFERENCE-ENTRY REPAIRS: the facts a sibling .bib supplies repair the
    # FMT-R1/R2/R3 shapes in the bibliography text; the Zotero library itself is
    # not written (a later refresh would restore the library's own values, and
    # the rules would report that again -- never a silent drift).
    reference_repair = {"changed": False, "repairs": [], "skipped": []}
    if _policy_flag(policy, "repair_reference_entries", True):
        bibs = sorted(p for p in Path(src).parent.glob("*.bib") if p.is_file())
        if bibs:
            _rr = repair_reference_entries(xml_before, load_bib_facts(bibs))
            reference_repair = {k: v for k, v in _rr.items() if k != "xml"}
            if _rr.get("changed"):
                xml_before = _rr["xml"]
    xml_after, changes, meta = fix_document(xml_before, styles, policy,
                                            sizes=sizes, rels=doc_rels)
    if zotero_refresh.get("changed"):
        changes = list(zotero_refresh.get("changes") or []) + list(changes)
    if reference_repair.get("changed"):
        changes = [f"reference-entry repair: {len(reference_repair['repairs'])} entr(y/ies) "
                   f"repaired from the package's own bibliography ("
                   + ", ".join(sorted({r['rule'] for r in reference_repair['repairs']})) + ")"
                   ] + list(changes)
    try:
        ET.fromstring(xml_after)
        xml_wellformed, xml_detail = True, ""
    except ET.ParseError as e:
        # The byte-level splices must never unbalance the document. `docx
        # validate` is optional, so the parse check is the always-on fence: a
        # malformed output must fail the fixer's own verification, not ship.
        xml_wellformed, xml_detail = False, str(e)
    # LIVE-FIELD FENCE: a mechanical fix must carry every Zotero field over
    # unchanged. The stray-empty-paragraph rule once deleted the no-text
    # paragraph holding a Zotero bibliography's closing fldChar end, leaving
    # the field unterminated; the gate below turns any such change into a
    # failed self-verification, so the caller keeps the original file.
    fields_before = zotero_field_report(xml_before)
    fields_after = zotero_field_report(xml_after)
    field_problems = zotero_field_continuity_problems(fields_before, fields_after)
    field_signature_kept = (zotero_field_signature(fields_before)
                            == zotero_field_signature(fields_after))
    if policy.get("unlink_zotero_fields"):
        # Explicit submission-copy policy: the fields are MEANT to become plain
        # text, so the continuity gate stands down for this one caller. It does
        # NOT stand down for a STALE document: the documented workflow is
        # "refresh, re-run zotero-check, and only then flatten", and flattening
        # a stale document freezes the wrong numbers in the submission copy (no
        # later refresh can repair a field that is no longer a field).
        field_parts = [(name, parts[name].decode("utf-8", "replace"))
                       for name in sorted(parts)
                       if name in ZOTERO_FIELD_PARTS
                       or ZOTERO_FIELD_AUX_PARTS_RE.search(name)]
        stale = [r for r in zotero_parity_rows_for_parts(field_parts)
                 if r.get("rule") in ("FMT-Z1", "FMT-Z2", "FMT-Z4")]
        if stale:
            return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                    "error": (f"refusing to flatten a stale document: "
                              f"{len(stale)} stale-citation fault(s) (FMT-Z1/Z2/Z4) must be "
                              f"repaired in Word/Zotero and `zotero-check` re-run before "
                              f"`unlink_zotero_fields` unlinks the fields -- flattening now "
                              f"freezes the wrong numbering in the submission copy"),
                    "ok": False}
        field_errors = []
    else:
        field_errors = list(field_problems["errors"])
        if not field_signature_kept:
            field_errors.append("a mechanical fix changed which live fields exist (one was "
                                "added, removed or left unterminated); the formatter must carry "
                                "every field over unchanged")
    parts_new = dict(parts)
    parts_new["word/document.xml"] = xml_after.encode("utf-8")
    for name, (axml, arels) in aux.items():
        if name not in referenced_aux:
            # An orphan part is not printed and the scanner ignores it by design;
            # repairing it changed bytes the scan never judged.
            continue
        # The two repairs are applied in sequence against the SAME evolving
        # string. Each fix set's offsets are computed on the string it is
        # applied to; applying both to the original overwrote the first result
        # (a header needing both a geometry and a PAGE-field repair kept the
        # distorted image while the report claimed both were fixed).
        _arows, afixes = drawing_geometry_rows(axml, arels, sizes, src.name, policy)
        axml_fixed = apply_edits(axml, afixes) if afixes else axml
        # FMT-S10: a referenced footer/header part with two PAGE fields. The
        # normal `fix` path must repair it too, or the fixer's own verification
        # finds a remaining mechanical rule and rejects the output.
        _pf = page_field_fixes(axml_fixed)
        if _pf:
            axml_fixed = apply_edits(axml_fixed, _pf)
        if afixes or _pf:
            parts_new[name] = axml_fixed.encode("utf-8")
        if afixes:
            changes.append(f"restored the aspect ratio of {len(afixes)} embedded "
                           f"image extent(s) in {posixpath.basename(name)}")
        if _pf:
            changes.append(f"removed {len(_pf)} duplicate PAGE field paragraph(s) from "
                           f"{posixpath.basename(name)}")
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts_new.items():
                z.writestr(name, data)
    except (OSError, RuntimeError, NotImplementedError) as e:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": f"could not write the fixed DOCX: {type(e).__name__}: {e}",
                "ok": False}

    # Text identity is about the DOCUMENT TEXT, not about paragraph count: a
    # fix may delete an empty paragraph or split a run, which changes the
    # newline count but not a single character of text. A caption the fixer
    # MERGED is the one structural change that joins two paragraph texts into
    # one; `fix_document` records the joined baseline, and the comparison uses
    # it so the merge is verified against the same text it started from.
    text_before = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml_before)) if t.strip())
    text_after = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml_after)) if t.strip())
    text_baseline = meta.get("text_baseline") or text_before
    quote_free = lambda s: re.sub(r"[\"'\u2018\u2019\u201c\u201d]", "", s)
    # The recorded text edits (citation journals, spelling, hyphenation) are the
    # only allowed text differences; rebuild the expected text by applying them to
    # the STAGE the edits were recorded against (descending offsets, so they stay
    # valid). `text_stage` differs from the input only by the structural fixes --
    # which delete empty paragraphs, never text -- and the quote normalisation.
    stage_xml = meta.get("text_stage_xml") or xml_before
    stage_paras = [text_of(p[2]) for p in paragraphs(stage_xml)]
    text_stage = "\n".join(t for t in stage_paras if t.strip())
    expected_paras = list(stage_paras)
    by_para = {}
    for idx, s, e, repl in meta.get("text_edits") or []:
        by_para.setdefault(idx, []).append((s, e, repl))
    for idx, spans in by_para.items():
        t = expected_paras[idx]
        for s, e, repl in sorted(spans, key=lambda x: -x[0]):
            t = t[:s] + repl + t[e:]
        expected_paras[idx] = t
    text_expected = "\n".join(t for t in expected_paras if t.strip())
    with zipfile.ZipFile(out) as pkg:
        same_parts = all(pkg.read(n) == d for n, d in parts_new.items())
        styles_after = parse_styles(pkg)
    before_rows = analyse_document(xml_before, styles, policy, src.name,
                                   sizes=sizes, rels=doc_rels)["rows"]
    after_rows = analyse_document(xml_after, styles_after, policy, src.name,
                                  sizes=sizes, rels=doc_rels)["rows"]
    mech_before = {r["rule"] for r in before_rows if r["rule"] in MECHANICAL_RULES and r["fix"] == "mechanical"}
    mech_after = {r["rule"] for r in after_rows if r["fix"] == "mechanical"}
    remaining = sorted(mech_before & mech_after)
    # The body-only analyse_document() call above cannot see a header/footer
    # part. Re-read every REFERENCED aux part the fixer touched (orphan parts are
    # ignored by the scanner and must not fail the fence here).
    aux_remaining = []
    for name, (_axml, arels) in aux.items():
        if name not in referenced_aux:
            continue
        fixed = parts_new.get(name, _axml.encode("utf-8")).decode("utf-8", "replace")
        _aux_rows, _aux_fixes = drawing_geometry_rows(fixed, arels, sizes, src.name,
                                                      policy)
        aux_remaining += [r["rule"] for r in _aux_rows
                          if r["rule"] in MECHANICAL_RULES
                          and r.get("fix") == "mechanical"]
        aux_remaining += [r["rule"] for r in page_field_rows([(name, fixed)], src.name)
                          if r.get("fix") == "mechanical"]
    remaining = sorted(set(remaining) | set(aux_remaining))
    schema = validate_package(out)
    verified = {
        "zip_readable": True,
        "parts_intact": same_parts,
        "text_identical": text_baseline == text_after,
        "text_diff_only_quotes": quote_free(text_baseline) == quote_free(text_after),
        "text_stage_diff_only_quotes": quote_free(text_baseline) == quote_free(text_stage),
        "text_diff_only_recorded_edits": text_after == text_expected,
        "text_edits": len(meta.get("text_edits") or []),
        "caption_joins": len(meta.get("caption_joins") or []),
        "mechanical_findings_before": len([r for r in before_rows if r["fix"] == "mechanical"]),
        "mechanical_findings_after": len([r for r in after_rows if r["fix"] == "mechanical"]),
        "remaining_mechanical_rules": remaining,
        "schema_ok": schema[0], "schema_detail": schema[1],
        "xml_wellformed": xml_wellformed, "xml_detail": xml_detail,
        "zotero_fields_before": dict(fields_before["counts"]),
        "zotero_fields_after": dict(fields_after["counts"]),
        "zotero_field_signature_kept": field_signature_kept,
        "zotero_field_problems": field_problems["errors"],
        "zotero_field_warnings": field_problems["warnings"],
        "zotero_field_deleted": field_problems["deleted"],
        "zotero_field_plain_text": field_problems["plain_text"],
    }
    ok = bool(same_parts
              and (verified["text_identical"] or verified["text_diff_only_quotes"]
                   or (verified["text_stage_diff_only_quotes"]
                       and verified["text_diff_only_recorded_edits"]))
              and not remaining
              and xml_wellformed
              and schema[0] is not False
              and not field_errors)
    return {"source": str(src), "output": str(out), "changes": changes, "verified": verified,
            "zotero_refresh": zotero_refresh, "reference_repair": reference_repair, "ok": ok}


def validate_package(path: Path):
    """(ok, detail) with the optional `docx` CLI; (None, reason) when unavailable."""
    exe = shutil.which("docx")
    if not exe:
        return None, "docx CLI not on PATH: schema check skipped"
    try:
        proc = subprocess.run([exe, "validate", str(path)], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"docx validate could not run: {e}"
    lines = [ln for ln in (proc.stdout or proc.stderr).strip().splitlines() if ln.strip()]
    return proc.returncode == 0, (lines[-1] if lines else f"rc={proc.returncode}")


def blank_pages_in_text(text: str) -> dict:
    """Pages whose body is empty once running head/footer/page numbers are ignored."""
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    stripped = [[ln.strip() for ln in p.splitlines() if ln.strip()] for p in pages]
    n = len(stripped)
    freq = Counter(ln for page in stripped for ln in page)
    furniture = {ln for ln, c in freq.items() if n and c >= max(2, int(0.6 * n))}
    blank = [i for i, page in enumerate(stripped, 1)
             if not [ln for ln in page if ln not in furniture and not re.fullmatch(r"\d+", ln)]]
    return {"pages": n, "blank_pages": blank, "furniture": sorted(furniture)}


# ---- deliverable validation (DOCX XML + LaTeX) ----------------------------
# What the editing stages must run after every edit: a DOCX whose parts do not
# parse (or that fails the `docx` schema check) and a .tex that does not compile
# are broken deliverables, no matter how good the prose is.

LATEX_ENGINES = (("latexmk", ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error"]),
                 ("xelatex", ["xelatex", "-interaction=nonstopmode", "-halt-on-error"]),
                 ("pdflatex", ["pdflatex", "-interaction=nonstopmode", "-halt-on-error"]),
                 ("lualatex", ["lualatex", "-interaction=nonstopmode", "-halt-on-error"]))


def latex_engine() -> tuple | None:
    """(name, argv) of the first available TeX engine, or None."""
    for name, argv in LATEX_ENGINES:
        exe = shutil.which(argv[0])
        if exe:
            return name, [exe] + argv[1:]
    return None


def validate_docx_parts(path: Path) -> dict:
    """Validate one DOCX: zip readable, every XML/rels part parses, optional schema."""
    errs = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                errs.append("word/document.xml is missing from the package")
            for name in names:
                if not (name.endswith(".xml") or name.endswith(".rels")):
                    continue
                try:
                    ET.fromstring(z.read(name))
                except ET.ParseError as e:
                    errs.append(f"{name}: malformed XML ({e})")
                except (OSError, RuntimeError, NotImplementedError) as e:  # noqa: PERF203
                    errs.append(f"{name}: unreadable ({e})")
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
        errs.append(f"not a readable .docx zip ({type(e).__name__}: {e})")
    schema_ok, schema_detail = validate_package(path)
    if schema_ok is False:
        errs.append(f"schema check failed: {schema_detail}")
    return {"file": str(path), "kind": "docx", "ok": not errs, "errors": errs,
            "schema_ok": schema_ok, "detail": schema_detail if schema_ok is None else "valid"}


# --------------------------------------------------------------------------
# Official venue templates: restyle a package into the journal's own DOCX
# --------------------------------------------------------------------------

_STYLE_REF_RE = re.compile(r'<w:(pStyle|rStyle)\b[^>]*?w:val="([^"]+)"')
# Direct properties the template's styles are supposed to own. Semantic run
# formatting (b/i/u/color/vertAlign/...) is deliberately NOT stripped.
_DIRECT_FORMAT_PATTERNS = (
    r"<w:spacing(?=[\s/>])[^>]*/>",
    r"<w:ind(?=[\s/>])[^>]*/>",
    r"<w:jc(?=[\s/>])[^>]*/>",
    r"<w:rFonts(?=[\s/>])[^>]*/>",
    r"<w:sz(?=[\s/>])[^>]*/>",
    r"<w:szCs(?=[\s/>])[^>]*/>",
)
_SECT_RE = re.compile(r"<w:sectPr(?=[\s>])[\s\S]*?</w:sectPr>")
_RELS_TAG_RE = re.compile(r"<Relationship\b[^>]*>")


def _rels_entries(xml: str) -> list:
    """[{id, type, target}] from a `.rels` part, in any attribute order.

    OOXML attributes are unordered; a `Target`-before-`Type` template must
    yield the same header/footer role map as the canonical order.
    """
    out = []
    for m in _RELS_TAG_RE.finditer(xml or ""):
        tag = m.group(0)
        rid, typ, target = attr_of(tag, "Id"), attr_of(tag, "Type"), attr_of(tag, "Target")
        if rid is None or target is None:
            continue
        out.append({"id": rid, "type": (typ or "").rsplit("/", 1)[-1].lower(),
                    "target": target})
    return out

# Another publisher's block headings ("Lead contact", "Key resources", ...) are
# VENUE DATA, never pipeline knowledge: the calling venue profile passes its own
# `foreign_container_headings` list and this default is empty, so the formatter
# carries no journal's vocabulary and stays venue-agnostic.
_FOREIGN_CONTAINERS_DEFAULT = ()
_SIMPLE_PAGE_FOOTER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
    '<w:fldSimple w:instr=" PAGE \\* Arabic "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
    '</w:p></w:ftr>')


def _set_para_style(para: str, style: str) -> str:
    """Force `w:pStyle` on a paragraph fragment (insert or replace)."""
    m = re.search(r"<w:pPr(?=[\s/>])[^>]*/>|<w:pPr(?=[\s>])[^>]*>[\s\S]*?</w:pPr>", para)
    if m:
        block = m.group(0)
        if block.rstrip().endswith("/>"):
            new = (block[:block.rfind("/>")].rstrip() + ">"
                   + f'<w:pStyle w:val="{style}"/>' + "</w:pPr>")
        elif "<w:pStyle" in block:
            new = re.sub(r"<w:pStyle(?=[\s>])[^>]*/>", f'<w:pStyle w:val="{style}"/>',
                         block, count=1)
        else:
            om = re.match(r"<w:pPr(?=[\s>])[^>]*>", block)
            new = block[:om.end()] + f'<w:pStyle w:val="{style}"/>' + block[om.end():]
        return para.replace(block, new, 1)
    om = re.match(r"<w:p(?=[\s>])[^>]*>", para)
    return para[:om.end()] + f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' + para[om.end():]


def _style_index(styles_xml: str) -> tuple:
    """({styleId: (type, normalized-name)}, {(type, name): styleId})."""
    try:
        root = ET.fromstring(styles_xml)
    except ET.ParseError:
        return {}, {}
    by_id, by_name = {}, {}
    for st in root.iter(W + "style"):
        sid = str(st.get(W + "styleId") or "")
        if not sid:
            continue
        typ = str(st.get(W + "type") or "paragraph")
        name_el = st.find(W + "name")
        name = (str(name_el.get(W + "val")) if name_el is not None
                and name_el.get(W + "val") else sid)
        key = re.sub(r"[^a-z0-9]+", "", name.lower())
        by_id[sid] = (typ, key)
        by_name.setdefault((typ, key), sid)
    return by_id, by_name


def _strip_direct_format(para: str) -> tuple:
    """(fragment, removed_count): drop direct props that defeat a template style."""
    removed = 0
    for pat in _DIRECT_FORMAT_PATTERNS:
        para, n = re.subn(pat, "", para)
        removed += n
    return para, removed


def _remap_style_refs(xml: str, mapping: dict) -> tuple:
    """(xml, count): rewrite pStyle/rStyle ids through the manuscript->template map."""
    count = [0]

    def sub(m):
        new = mapping.get(m.group(2))
        if not new or new == m.group(2):
            return m.group(0)
        count[0] += 1
        return m.group(0).replace(f'w:val="{m.group(2)}"', f'w:val="{new}"')

    return _STYLE_REF_RE.sub(sub, xml), count[0]


def _adopt_page_geometry(doc_xml: str, template_doc_xml: str) -> tuple:
    """(xml, applied): give EVERY manuscript section the template's geometry.

    The template's own (single) sectPr is the SOURCE. Page 1 is governed by the
    FIRST `w:sectPr` in document order (see `first_section_props`) and a
    title-page break splits the body into sections, so writing only the LAST one
    left page 1 -- and every middle section -- in the author's geometry: the
    delivered package was not the journal's layout, while the conformance
    report, which read the same last section, showed no gap.
    """
    t_sects = list(_SECT_RE.finditer(template_doc_xml or ""))
    # The MANUSCRIPT side reads the same way `first_section_props` reads it: a
    # legal self-closing `<w:sectPr .../>` is an empty section and must not be
    # skipped, or page 1 silently keeps the author's geometry while the report
    # (which reads the first section correctly) shows the template's.
    m_sects = list(SECT_READ_RE.finditer(doc_xml))
    if not t_sects or not m_sects:
        return doc_xml, False
    # CT_SectPr's child order; a replacement must keep the sequence valid even
    # when the manuscript carries elements between the geometry children
    # (lnNumType/pgNumType/...), which re-serializing from scratch would move.
    order = ("headerReference", "footerReference", "footnotePr", "endnotePr", "type",
             "pgSz", "pgMar", "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols",
             "formProt", "vAlign", "noEndnote", "titlePg", "textDirection", "bidi",
             "rtlGutter", "docGrid", "printerSettings", "sectPrChange")
    tpl_sect = t_sects[-1].group(0)
    geo = {tag: elem(tpl_sect, tag) for tag in ("pgSz", "pgMar", "cols", "docGrid")}
    geo = {k: v for k, v in geo.items() if v}
    if not geo:
        return doc_xml, False

    def adopt(body: str) -> str:
        if body.rstrip().endswith("/>"):
            # Expand the empty section first: the geometry children belong
            # INSIDE it, and a splice before the tag's `/>` would orphan them.
            body = body[:body.rfind("/>")].rstrip() + ">" + "</w:sectPr>"
        for tag in ("pgSz", "pgMar", "cols", "docGrid"):
            el = elem(body, tag)
            new_el = geo.get(tag)
            if el and new_el:
                body = body.replace(el, new_el, 1)
            elif new_el:
                pos = body.rfind("</w:sectPr>")
                idx = order.index(tag)
                for m in re.finditer(r"<w:([A-Za-z]+)(?=[\s/>])", body):
                    name = m.group(1)
                    if name in order and order.index(name) > idx:
                        pos = min(pos, m.start())
                        break
                body = body[:pos] + new_el + body[pos:]
        return body

    for m in reversed(m_sects):                     # backwards: offsets stay valid
        doc_xml = doc_xml[:m.start()] + adopt(m.group(0)) + doc_xml[m.end():]
    return doc_xml, True


def _template_front_parts(tpkg: zipfile.ZipFile, parts: dict, tnames: set) -> dict:
    """Copy the template's whole header/footer role map into the package.

    Every role the template defines -- first, default (odd) and EVEN -- is
    carried, together with the `w:evenAndOddHeaders` parity setting the
    template relies on: a template whose furniture alternates by page parity
    (Frontiers: the page number on odd pages and its typeset-provisional note on
    even ones; a running head defined for even pages only) loses half of its
    furniture when only first+default are copied.

    The FIRST-page footer is always a plain synthetic PAGE field, and an EVEN
    footer that is not plain pagination -- a VML/DrawingML text box, or a part
    carrying the template's own typesetting prose ("This is a provisional
    file...") -- is replaced by the same plain footer. Word refuses a template
    text-box footer re-roled to first/even ("the file appears to be corrupted"
    on open), and the pipeline takes STRUCTURE from a template, never its
    prose. Every substitution is reported in `footer_replaced`.
    """
    try:
        tdoc = tpkg.read("word/document.xml").decode("utf-8", "replace")
        trels = (tpkg.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
                 if "word/_rels/document.xml.rels" in tnames else "")
        tset = (tpkg.read("word/settings.xml").decode("utf-8", "replace")
                if "word/settings.xml" in tnames else "")
    except (KeyError, OSError, RuntimeError, NotImplementedError):
        return {}
    rel_map = {e["id"]: (e["type"], e["target"]) for e in _rels_entries(trels)}
    refs = {"header": {}, "footer": {}}
    sect = _SECT_RE.findall(tdoc)
    ref_re = r'<w:(header|footer)Reference w:type="(\w+)" r:id="([^"]+)"'

    def harvest(xml: str, roles: tuple) -> None:
        for m in re.finditer(ref_re, xml):
            if m.group(2) in roles and m.group(2) not in refs[m.group(1)]:
                refs[m.group(1)][m.group(2)] = m.group(3)

    # Page 1 is governed by the FIRST section (`_apply_front_refs` writes the
    # "first" role there), while the running head/footer belong to the
    # template's body section. Reading every role from sect[-1] copied the
    # running head into the first-page role -- the logo header of a template
    # that splits its title page off was left behind while the change log
    # still claimed it had been copied.
    for role, order in (("first", sect),
                        ("default", list(reversed(sect))),
                        ("even", list(reversed(sect)))):
        for one in order:
            harvest(one, (role,))
    if not (refs["header"] or refs["footer"]):
        return {}
    copied, issued = [], {}

    def copy_part(src_name: str, dest_name: str) -> bool:
        full = f"word/{src_name}"
        if full not in tnames:
            return False
        parts[f"word/{dest_name}"] = tpkg.read(full)
        copied.append(dest_name)
        rels_name = f"word/_rels/{src_name}.rels"
        if rels_name in tnames:
            rxml = tpkg.read(rels_name).decode("utf-8", "replace")
            for rm in _rels_entries(rxml):
                if rm["type"] != "image":
                    continue
                # The relationship target is RELATIVE TO THE HEADER/FOOTER PART
                # (`word/`), so the rewritten target must keep the media
                # directory: `media/logo.png` -> `media/venue_logo.png`, never a
                # bare `venue_logo.png` (which resolves to word/venue_logo.png,
                # a missing part -- the logo then renders as an empty frame).
                media = rm["target"]
                src_media = posixpath.normpath(posixpath.join("word", media))
                if not src_media.startswith("word/") or ".." in Path(src_media).parts:
                    continue
                dest_media = posixpath.join(posixpath.dirname(src_media),
                                            f"venue_{posixpath.basename(media)}")
                if dest_media not in parts and src_media in tnames:
                    parts[dest_media] = tpkg.read(src_media)
                rel_target = posixpath.relpath(dest_media, "word")
                rxml = rxml.replace(f'Target="{media}"', f'Target="{rel_target}"')
            parts[f"word/_rels/{dest_name}.rels"] = rxml.encode("utf-8")
        hdr = tpkg.read(full).decode("utf-8", "replace")
        issued[dest_name] = bool(re.search(r"<w:drawing|<w:pict|<v:imagedata|<a:blip", hdr))
        return True

    def target_of(kind: str, role: str) -> str:
        rid = refs[kind].get(role)
        k, target = rel_map.get(rid, ("", "")) if rid else ("", "")
        return target if k == kind and target and f"word/{target}" in tnames else ""

    by_target = {}

    def carry(kind: str, role: str, dest: str) -> str:
        """Copy the template part for one role (deduped by source part)."""
        target = target_of(kind, role)
        if not target:
            return ""
        if target in by_target:
            return by_target[target]
        if copy_part(target, dest):
            by_target[target] = dest
            return dest
        return ""

    def synthesize(dest: str) -> str:
        parts[f"word/{dest}"] = _SIMPLE_PAGE_FOOTER.encode("utf-8")
        copied.append(dest)
        issued[dest] = False
        return dest

    def footer_part_is_plain_pagination(role: str) -> bool:
        """Pagination only: a PAGE field, no text box and no visible prose.

        Word accepts the template's AlternateContent (VML/DrawingML text-box)
        footer as the DEFAULT footer, but refuses the very same part in the
        first/even roles ("the file appears to be corrupted" on open), and a
        role-tagged part is what the schema asks for -- so only plain
        pagination parts are re-roled.
        """
        target = target_of("footer", role)
        if not target:
            return False
        xml = tpkg.read(f"word/{target}").decode("utf-8", "replace")
        if not re.search(r'<w:instrText[^>]*>[^<]*\bPAGE\b'
                         r'|<w:fldSimple[^>]*w:instr="[^"]*\bPAGE\b', xml, re.I):
            return False
        if re.search(r"<w:txbxContent|<wps:wsp|<w:pict\b", xml):
            return False
        visible = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
        return not re.search(r"[A-Za-z]", visible)

    out = {"footer_replaced": []}
    for role, dest in (("first", "header_venue_first.xml"),
                       ("default", "header_venue_default.xml"),
                       ("even", "header_venue_even.xml")):
        # A template with a single header uses it on every page, first included.
        part = carry("header", role, dest) if role != "first" \
            else (carry("header", "first", dest) or carry("header", "default", dest))
        if part:
            out[f"header_{role}"] = part
    for role, dest in (("first", "footer_venue_first.xml"),
                       ("default", "footer_venue_default.xml"),
                       ("even", "footer_venue_even.xml")):
        target = target_of("footer", role)
        # first: always the plain synthetic page number (a re-roled template
        # text box corrupts the file); even: only plain pagination (the
        # template's typeset-provisional prose must not reach the manuscript);
        # default: the template's own part, as before.
        if not target or role == "first":
            keep = False
        elif role == "even":
            keep = footer_part_is_plain_pagination(role)
        else:
            keep = True
        part = carry("footer", role, dest) if keep else ""
        if not keep and target:
            out["footer_replaced"].append(role)
        if not part and (role == "first" or target):
            # pagination the manuscript must have; first page included
            part = synthesize(dest)
        if part:
            out[f"footer_{role}"] = part
    out["even_odd"] = ("evenAndOddHeaders" in tset
                       or any(k.startswith(("header_even", "footer_even")) for k in out))
    out["logo"] = bool(issued.get(out.get("header_first", ""), False))
    out["copied"] = copied
    # content-type overrides for the new parts + media defaults
    ct = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    for name in copied:
        kind = "header" if name.startswith("header") else "footer"
        if f'PartName="/word/{name}"' not in ct:
            ct = ct.replace("</Types>",
                            f'<Override PartName="/word/{name}" ContentType="application/vnd.'
                            f'openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>'
                            f'</Types>')
    for media in [n for n in parts if n.startswith("word/media/venue_")]:
        ext = Path(media).suffix.lstrip(".").lower()
        ctype = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png",
                 "gif": "image/gif", "emf": "image/x-emf", "wmf": "image/x-wmf"}.get(ext)
        if ctype and f'Extension="{ext}"' not in ct:
            ct = ct.replace("</Types>", f'<Default Extension="{ext}" ContentType="{ctype}"/>'
                                       f'</Types>')
    parts["[Content_Types].xml"] = ct.encode("utf-8")
    # document relationships (fresh ids)
    rels = parts.get("word/_rels/document.xml.rels", b"").decode("utf-8", "replace")
    used = set(re.findall(r'Id="([^"]+)"', rels))
    n = 2001
    for key, dest in (("header_default", out.get("header_default")),
                      ("header_first", out.get("header_first")),
                      ("header_even", out.get("header_even")),
                      ("footer_default", out.get("footer_default")),
                      ("footer_first", out.get("footer_first")),
                      ("footer_even", out.get("footer_even"))):
        if not dest:
            continue
        while f"rId{n}" in used:
            n += 1
        rid = f"rId{n}"
        used.add(rid)
        n += 1
        kind = "header" if key.startswith("header") else "footer"
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
                            f'officeDocument/2006/relationships/{kind}" Target="{dest}"/>'
                            f'</Relationships>')
        out[key + "_rid"] = rid
    parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    return out


def template_style_roles(template: Path) -> dict:
    """The style ids a TEMPLATE uses for its front matter and heading levels.

    Venue-agnostic: the roles are read from the template's own styles.xml
    (`title`, `author list`/`authors`, the styles whose aliases cover both
    keywords and abstract, `heading 1..5`, `caption`), and the deepest heading
    level the template's own document actually uses at least twice becomes the
    level cap -- a template that never nests sub-sub-sections does not get them
    imposed on the manuscript.
    """
    try:
        with zipfile.ZipFile(template) as tpkg:
            styles = tpkg.read("word/styles.xml").decode("utf-8", "replace")
            doc = tpkg.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return {}
    roles = {"headings": {}}
    try:
        root = ET.fromstring(styles)
    except ET.ParseError:
        return {}
    for st in root.iter(W + "style"):
        sid = str(st.get(W + "styleId") or "")
        if not sid:
            continue
        name_el = st.find(W + "name")
        name = str(name_el.get(W + "val")) if name_el is not None else sid
        keys = {re.sub(r"[^a-z0-9]+", "", name.lower())}
        aliases_el = st.find(W + "aliases")
        if aliases_el is not None and aliases_el.get(W + "val"):
            keys |= {re.sub(r"[^a-z0-9]+", "", a.lower())
                     for a in str(aliases_el.get(W + "val")).split(",")}
        if "title" in keys and "title" not in roles:
            roles["title"] = sid
        if keys & {"authorlist", "authors", "author"} and "author" not in roles:
            roles["author"] = sid
        if "keywords" in keys and "abstract" in keys and "author" not in roles:
            roles["author"] = sid          # the front-matter style by its aliases
        for level in range(1, 6):
            if f"heading{level}" in keys:
                roles["headings"].setdefault(level, sid)
        if "caption" in keys and "caption" not in roles:
            roles["caption"] = sid
    used = {}
    for m in re.finditer(r'<w:pStyle w:val="([^"]+)"', doc):
        used[m.group(1)] = used.get(m.group(1), 0) + 1
    depth = 0
    for level, sid in roles["headings"].items():
        if used.get(sid, 0) >= 2:
            depth = max(depth, level)
    roles["max_heading_level"] = depth or 2
    return roles


_HEADING_MAX_CHARS = 90
_HEADING_MAX_WORDS = 12
_HEADING_SKIP_PREFIXES = ("figure ", "fig. ", "fig ", "table ", "supplementary figure",
                          "supplementary table", "extended data ", "box ")


def _body_run_size(doc_xml: str):
    """The document's dominant run size (its body-text size), or None.

    Weighted by TEXT, over the long paragraphs that actually carry the prose: a
    short document's figure legends, tables and captions can outnumber its body
    runs, and their small sizes must not become the body baseline (that would
    turn every bold line above them into a "heading").
    """
    weights = Counter()
    for _p0, _p1, frag in paragraphs(doc_xml):
        if len(text_of(frag).split()) < 25:
            continue
        for run in re.findall(r"<w:r\b[\s\S]*?</w:r>", frag):
            t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
            for s in re.findall(r'<w:sz w:val="(\d+)"', run):
                weights[int(s)] += len(t)
    if weights:
        return weights.most_common(1)[0][0]
    sizes = Counter(re.findall(r'<w:sz w:val="(\d+)"', doc_xml))
    if not sizes:
        return None
    return int(sizes.most_common(1)[0][0])


def heading_like_paragraphs(doc_xml: str, containers=()) -> list:
    """[(paragraph index, text, size)] of DIRECTLY-formatted section headings.

    A manuscript written in Word often carries its section headings as direct
    formatting -- a short bold line one or two points larger than the body text,
    with NO paragraph style at all. The template's Heading 1..N styles cannot
    apply to such a paragraph until it is tagged, and the normalizer's own
    direct-format strip (which exists so the template's typography shows) would
    otherwise flatten the heading into body text. Pure detection: the retag pass
    and the conformance report read the same rows.

    Deliberately conservative: only unstyled/Normal paragraphs whose every
    non-empty run is bold, whose size is at least 1 pt above the document's
    dominant run size, whose text is a short single line without a terminal
    period/comma/semicolon, and that are not captions, lists, table cells, front
    matter or a known foreign-publisher container heading.
    """
    body = _body_run_size(doc_xml)
    if body is None:
        return []
    paras = list(paragraphs(doc_xml))
    # `_table_spans` balances nested tables; the lazy regex this used to run
    # stopped at the inner `</w:tbl>`, so a paragraph of the OUTER table after a
    # nested one was read as body text and `_retag_headings` could stamp a
    # Heading style onto a short bold line inside a table cell.
    tables = _table_spans(doc_xml)
    entries = [i for i, p in enumerate(paras) if text_of(p[2]).strip()]
    skip = set(entries[:1])                       # the article title
    for i in entries[1:4]:                        # the author line
        t = text_of(paras[i][2]).strip()
        if len(t) < 400 and "@" not in t and ("," in t or " and " in t):
            skip.add(i)
            break
    for i in entries:                             # abstract / keywords front matter
        low = text_of(paras[i][2]).strip().lower()
        if low == "abstract" or low.startswith("keywords"):
            skip.add(i)
    out = []
    for i, (p0, p1, frag) in enumerate(paras):
        if i in skip or any(a <= p0 < b for a, b in tables):
            continue
        text = text_of(frag).strip()
        if not text or len(text) > _HEADING_MAX_CHARS \
                or len(text.split()) > _HEADING_MAX_WORDS:
            continue
        if not text[0].isalpha() or text[-1] in ".,;":
            continue
        low = text.lower()
        if low.startswith(_HEADING_SKIP_PREFIXES) \
                or low in {c.lower() for c in (containers or _FOREIGN_CONTAINERS_DEFAULT)}:
            continue
        pstyle = elem_val(ppr_of(frag), "pStyle")
        if pstyle and pstyle != "Normal":
            continue
        if "<w:numPr" in frag:
            continue
        sizes, all_bold, has_text = [], True, False
        for run in re.findall(r"<w:r\b[\s\S]*?</w:r>", frag):
            if not "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run)).strip():
                continue
            has_text = True
            if not re.search(r"<w:b/>|<w:b w:val=\"(?:1|true|on)\"", run):
                all_bold = False
                break
            sizes += [int(s) for s in re.findall(r'<w:sz w:val="(\d+)"', run)]
        if not (has_text and all_bold and sizes) or max(sizes) < body + 2:
            continue
        out.append((i, text, max(sizes)))
    return out


def _retag_headings(doc_xml: str, roles: dict, containers=()) -> tuple:
    """(xml, retagged): tag directly-formatted headings with the template's styles.

    The paragraph STYLE IS the only thing changed -- the text stays byte-identical,
    and the normalizer's direct-format strip that follows removes the local
    font/size/spacing so the template's Heading 1..N own the typography (and its
    automatic numbering comes along). The largest heading size becomes level 1,
    the next level 2, and so on, capped at the depth the template's own document
    uses. Every retag is reported so a review session can correct a mis-tag.
    """
    headings = dict(roles.get("headings") or {})
    if not headings:
        return doc_xml, []
    cands = heading_like_paragraphs(doc_xml, containers)
    if not cands:
        return doc_xml, []
    depth = max(1, int(roles.get("max_heading_level") or 2))
    level_of = {size: min(i + 1, depth)
                for i, size in enumerate(sorted({s for _i, _t, s in cands}, reverse=True))}
    paras = list(paragraphs(doc_xml))
    edits, done = [], []
    for i, text, size in cands:
        style = headings.get(level_of[size]) or headings.get(depth)
        if not style:
            continue
        p0, p1, frag = paras[i]
        edits.append((p0, p1, _set_para_style(frag, style)))
        done.append({"text": text[:80], "level": level_of[size], "style": style})
    return (apply_edits(doc_xml, edits) if edits else doc_xml), done


_CORRESP_RE = re.compile(r"^\s*\*\s*Correspondence\s*:", re.I)


def _ppr_extra(ppr_xml: str) -> str:
    """A template paragraph's NON-style pPr children (spacing/ind/jc/rPr)."""
    if not ppr_xml:
        return ""
    keep = []
    for tag in ("spacing", "ind", "jc", "keepNext", "keepLines", "rPr"):
        keep += re.findall(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s>])[^>]*>[\s\S]*?</w:{tag}>",
                           ppr_xml)
    return "".join(keep)


def _template_front_layout(tpl_doc: str) -> dict:
    """The TEMPLATE's own paragraph properties for the first-page block.

    The title/author/keywords/abstract roles come from style ids, but a Word
    template formats its affiliation lines and its correspondence block with
    DIRECT `w:spacing` (before=240/after=0) and a Times New Roman cs font. The
    normalizer strips direct paragraph properties, so unless those values are
    copied from the template the block ends up under Normal's spacing -- which is
    exactly the "line spacing between the affiliation/correspondence lines is
    wrong" deviation. Returns {role: pPr-snippet} for affiliation (first and
    rest), correspondence, keywords, abstract_head and abstract_body.
    """
    out = {}
    paras = list(paragraphs(tpl_doc))
    affil = 0
    abstract_seen = False
    for _p0, _p1, frag in paras:
        text = text_of(frag).strip()
        ppr = ppr_of(frag)
        extra = _ppr_extra(ppr)
        if not text:
            continue
        style = elem_val(ppr, "pStyle")
        if _CORRESP_RE.match(text):
            out.setdefault("correspondence", extra)
        elif style == "AuthorList" and text.lower().startswith("keywords"):
            out.setdefault("keywords", extra)
        elif style == "AuthorList" and text.lower() == "abstract":
            out.setdefault("abstract_head", extra)
            abstract_seen = True
        elif abstract_seen and "abstract_body" not in out and style not in ("Heading1", "Heading2"):
            out["abstract_body"] = extra
        elif re.match(r"^\d+[A-Z]", text) and "correspondence" not in text.lower():
            affil += 1
            out.setdefault("affiliation_first" if affil == 1 else "affiliation_rest", extra)
    return out


def _correspondence_lead(para_xml: str) -> int:
    """Leading spaces/tabs of the FIRST text-bearing correspondence run.

    `_CORRESP_RE` is matched against the paragraph's STRIPPED text, while the run
    walk starts at the unstripped paragraph: leading spaces therefore consumed
    the start of the label window ("  * Correspondence: Zhen Xie" bolded
    "  * Correspondenc" and left "e: ..." roman). Only the first text-bearing
    run's own leading whitespace extends that window -- a whitespace-only run
    before it is skipped by the walk itself, so counting its characters here
    would shift the bold span into the name.
    """
    for rm in re.finditer(r"<w:r\b[\s\S]*?</w:r>", para_xml):
        tm = re.search(r"<w:t[^>]*>([\s\S]*?)</w:t>", rm.group(0))
        if not tm:
            continue
        text = unesc(tm.group(1))
        if text.strip():
            return len(text) - len(text.lstrip(" \t"))
    return 0


def _bold_label_runs(para_xml: str) -> str:
    """Make the leading `* Correspondence:` label BOLD (template's own look).

    The label is often one run that also carries the name/email; the run is split
    at the colon so only the label is bold -- the concatenated w:t text stays
    byte-identical.
    """
    RPR_RE = re.compile(r"<w:rPr(?=[\s/>])(?:[^>]*/>|[^>]*>[\s\S]*?</w:rPr>)")

    raw_text = text_of(para_xml)
    m = _CORRESP_RE.match(raw_text.strip())
    if not m:
        return para_xml
    left = len(m.group(0)) + _correspondence_lead(para_xml)
    out = para_xml
    for rm in list(re.finditer(r"<w:r\b[\s\S]*?</w:r>", out)):
        run = rm.group(0)
        tm = re.search(r"(<w:t[^>]*>)([\s\S]*?)(</w:t>)", run)
        if not tm:
            continue
        # `unesc`, not `xml.sax.saxutils.unescape`: the sax decoder only knows
        # `&amp;`/`&lt;`/`&gt;`, so a run carrying a numeric reference
        # (`&#8211;`, Word's own serialization for a dash) was under-decoded and
        # then re-escaped by with_text into `&amp;#8211;` -- visible junk in the
        # correspondence line. The text-identity check could not see it either
        # (both sides decode back to the same character through unesc), and the
        # bold/roman split point drifted because `left` counts decoded
        # characters while the under-decoded text is longer.
        text = unesc(tm.group(2))
        if not text.strip():
            continue
        take = min(left, len(text))
        head, tail = text[:take], text[take:]
        left -= take
        rpr = RPR_RE.search(run)
        props = rpr.group(0) if rpr else ""
        if "<w:b/>" in props or re.search(r'<w:b w:val="(?:1|true|on)"', props):
            bold = props
        elif not props:
            bold = "<w:rPr><w:b/></w:rPr>"
        elif props.endswith("/>"):
            bold = props[:-2].rstrip() + "><w:b/></w:rPr>"
        else:
            # Merge the bold INTO the existing property bag. Word writes the
            # routine w:rsidRPr attribute on run properties, and CT_R allows
            # exactly ONE w:rPr child, so the old insert-a-second-<w:rPr>
            # splice produced a schema-invalid run (Word: "unreadable
            # content") for any rsid-carrying run.
            open_tag = re.match(r"<w:rPr(?=[\s/>])[^>]*>", props).group(0)
            bold = props.replace(open_tag, open_tag + "<w:b/>", 1)

        def with_text(txt: str, want: str) -> str:
            frag = run[:tm.start(2)] + xml_escape(txt) + run[tm.end(2):]
            fm = RPR_RE.search(frag)
            if fm:
                return frag[:fm.start()] + want + frag[fm.end():]
            om = re.match(r"<w:r\b[^>]*>", frag)
            return frag[:om.end()] + want + frag[om.end():]

        new_runs = with_text(head, bold)
        if tail:
            new_runs += with_text(tail, props)
        out = out.replace(run, new_runs, 1)
        if left <= 0:
            break
    return out


def _label_is_bold(para_xml: str) -> bool:
    """Is the `* Correspondence: ` label (up to the colon) actually bold?"""
    raw_text = text_of(para_xml)
    m = _CORRESP_RE.match(raw_text.strip())
    if not m:
        return False
    left = len(m.group(0)) + _correspondence_lead(para_xml)
    for run in re.findall(r"<w:r\b[\s\S]*?</w:r>", para_xml):
        text = "".join(unesc(t) for t in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
        if not text.strip():
            continue
        take = min(left, len(text))
        if take > 0 and not re.search(r"<w:b/>|<w:b w:val=\"(?:1|true|on)\"", run):
            return False
        left -= take
        if left <= 0:
            return True
    return False


def _insert_ppr_extra(ppr_xml: str, extra: str) -> str:
    """Add template pPr children (spacing/ind/jc/rPr) in schema-safe positions."""
    if not extra:
        return ppr_xml
    # `w:pPrChange` (a recorded formatting change) is the LAST child of a pPr
    # and carries a nested `w:pPr` of its own: the `<w:rPr>` inside it is
    # revision RECORD, not this paragraph's property bag, so every edit below
    # stays in the part before it -- and a target with no direct rPr lands its
    # children there too, never after the change (CT_PPr's child order forbids
    # that).
    ci = ppr_xml.find("<w:pPrChange")
    head, change = (ppr_xml[:ci], ppr_xml[ci:]) if ci >= 0 else (ppr_xml, "")
    open_tag = re.match(r"<w:pPr(?=[\s/>])[^>]*>", head)
    if open_tag and open_tag.group(0).endswith("/>"):
        # `<w:pPr/>`: an empty property bag with no closing tag. Open it so the
        # template's children have a home; the old fallback appended a SECOND
        # pPr to the paragraph (CT_P allows one). The test is on the pPr's OWN
        # open tag -- a head that merely ENDS with a self-closing child
        # (`<w:pPr><w:jc w:val="center"/>`) is not an empty bag.
        return (open_tag.group(0)[:-2].rstrip() + ">" + extra + "</w:pPr>" + change)
    if re.search(r"<w:rPr(?=[\s>])", extra):
        # CT_PPr carries at most ONE w:rPr child, and it must sit after every
        # other pPr child except sectPr/pPrChange. The template's own rPr
        # REPLACES the paragraph's direct one -- the same way `_apply_ppr_extra`
        # drops the direct spacing/ind/jc before inserting -- so the existing
        # rPr is removed first. Splicing the template's rPr BESIDE the existing
        # one emitted two rPr children, schema-invalid OOXML that Word reports
        # as unreadable content (the shipped NeoHeteroclitic main text carries
        # exactly that on its affiliation and correspondence lines, and its
        # `docx validate` fails on it).
        head = re.sub(r"<w:rPr(?=[\s/>])[^>]*/>|<w:rPr(?=[\s>])[^>]*>[\s\S]*?</w:rPr>",
                      "", head, count=1)
    rm = re.search(r"<w:rPr(?=[\s>])", head)
    if rm:
        head = head[:rm.start()] + extra + head[rm.start():]
    elif change:
        head = head + extra
    else:
        head = head.replace("</w:pPr>", extra + "</w:pPr>", 1)
    return head + change


def _apply_ppr_extra(frag: str, extra: str) -> str:
    """Give a paragraph the TEMPLATE's own pPr children (its direct spacing)."""
    if not extra:
        return frag
    om = re.match(r"<w:p\b[^>]*>", frag)
    if not om:
        return frag
    # The paragraph's OWN pPr: a balanced span, so a nested `w:pPrChange`
    # (which carries a `</w:pPr>` of its own) is not mistaken for its end --
    # the lazy regex that stopped at the first `</w:pPr>` truncated the block
    # inside the recorded change and spliced the template's children into the
    # revision record.
    pm = re.compile(r"<w:pPr(?=[\s/>])").search(frag, om.end())
    if not pm:
        return frag[:om.end()] + f"<w:pPr>{extra}</w:pPr>" + frag[om.end():]
    s, e = element_span(frag, pm.start(), "pPr")
    block = frag[s:e]
    # The direct spacing/ind/jc the template replaces: confined to the part
    # BEFORE a recorded `w:pPrChange`, whose nested pPr is revision record
    # (stripping inside it edited the author's tracked formatting history).
    ci = block.find("<w:pPrChange")
    head, change = (block[:ci], block[ci:]) if ci >= 0 else (block, "")
    head = re.sub(r"<w:(?:spacing|ind|jc)(?=[\s/>])[^>]*/>", "", head)
    return frag[:s] + _insert_ppr_extra(head + change, extra) + frag[e:]


def _front_matter_styles(doc_xml: str, roles: dict, tpl_doc: str = "") -> tuple:
    """(xml, info): template front matter + the template's heading depth.

    Title on the first paragraph, AuthorList on the author line (bold),
    Abstract/Keywords as unnumbered front matter, headings deeper than the
    template's own depth demoted one level, and direct indents/spacing/
    alignment removed from all styled paragraphs so the template's styles own
    the typography. All ids come from the template.
    """
    title_id = roles.get("title") or ""
    author_id = roles.get("author") or ""
    headings = dict(roles.get("headings") or {})
    depth = int(roles.get("max_heading_level") or 2)
    layout = _template_front_layout(tpl_doc) if tpl_doc else {}
    info = {"title": False, "authors": False, "abstract": False, "keywords": False,
            "correspondence": False, "deep_headings_demoted": 0}
    if not (title_id or author_id or headings):
        return doc_xml, info
    paras = paragraphs(doc_xml)
    entries = [(i, p) for i, p in enumerate(paras) if text_of(p[2]).strip()]
    if not entries:
        return doc_xml, info
    edits = []

    def style_para(idx, style, role=None):
        p0, p1, frag = paras[idx]
        new = _strip_direct_props(_set_para_style(frag, style), strip_num=True)
        if role and layout.get(role):
            new = _apply_ppr_extra(new, layout[role])
        edits.append((p0, p1, new))

    if title_id:
        style_para(entries[0][0], title_id)
        info["title"] = True
    if author_id:
        for idx, p in entries[1:4]:
            t = text_of(p[2]).strip()
            if len(t) < 400 and "@" not in t and ("," in t or " and " in t):
                style_para(idx, author_id)
                info["authors"] = True
                break
    kw_heading = None
    kw_pending = False
    for idx, p in entries:
        t = text_of(p[2]).strip()
        low = t.lower()
        if low == "abstract":
            style_para(idx, author_id or "AuthorList", "abstract_head")
            info["abstract"] = True
        elif low == "keywords":
            kw_heading = idx
            style_para(idx, author_id or "AuthorList")
            kw_pending = True
        elif low.startswith("keywords:") or low.startswith("keywords :"):
            style_para(idx, author_id or "AuthorList")
            info["keywords"] = True
        elif kw_pending:
            # The template uses ONE "Keywords: ..." line; styling the heading and
            # the list keeps the TEXT byte-identical (the merge itself is a
            # content edit the review/rewrite sessions are told to make).
            style_para(idx, author_id or "AuthorList")
            info["keywords"] = True
            kw_pending = False
    # The FIRST page's block order and its direct spacing come from the template:
    # the affiliation lines (before=240/after=0) and the correspondence block
    # (* Correspondence: in BOLD, then the name and the email on their own lines).
    affil = 0
    after_front = len(paras)
    for idx, p in entries:
        t = text_of(p[2]).strip()
        if _CORRESP_RE.match(t) or t.lower() == "abstract" or t.lower().startswith("keywords"):
            after_front = min(after_front, idx)
    for idx, p in entries:
        t = text_of(p[2]).strip()
        if _CORRESP_RE.match(t):
            p0, p1, frag = p
            new = _strip_direct_props(frag, strip_num=True)
            if layout.get("correspondence"):
                new = _apply_ppr_extra(new, layout["correspondence"])
            new = _bold_label_runs(new)
            if new != frag:
                edits.append((p0, p1, new))
            info["correspondence"] = True
        elif idx < after_front and re.match(r"^\d+[A-Z]", t):
            affil += 1
            role = "affiliation_first" if affil == 1 else "affiliation_rest"
            if layout.get(role):
                p0, p1, frag = p
                new = _strip_direct_props(frag, strip_num=True)
                new = _apply_ppr_extra(new, layout[role])
                if new != frag:
                    edits.append((p0, p1, new))
    deep = {sid: level for level, sid in headings.items() if level > depth}
    for idx, p in enumerate(paras):
        pstyle = elem_val(ppr_of(p[2]), "pStyle")
        if pstyle in deep:
            level = deep[pstyle]
            target = headings.get(level - 1) or headings.get(depth)
            if target:
                p0, p1, frag = p
                edits.append((p0, p1, _strip_direct_props(
                    _set_para_style(frag, target), strip_num=False)))
                info["deep_headings_demoted"] += 1
    styled = {sid for sid in (title_id, author_id, roles.get("caption"),
                              *headings.values()) if sid}
    for idx, p in enumerate(paras):
        if elem_val(ppr_of(p[2]), "pStyle") in styled:
            p0, p1, frag = p
            new = _strip_direct_props(frag, strip_num=(elem_val(ppr_of(frag), "pStyle") ==
                                                       "AuthorList"))
            if new != frag:
                edits.append((p0, p1, new))
    if edits:
        # `apply_edits` is only correct for DISJOINT spans. Two passes here (the
        # front-matter roles, then the styled-paragraph strip) can append an edit
        # for the SAME paragraph twice -- e.g. an Abstract heading already styled
        # AuthorList, or a demoted deep heading -- and the second replacement is
        # computed from the unedited fragment, so splicing it at the original
        # offsets removes the text the first replacement inserted. Keep the FIRST
        # (richer: style + template layout) edit per span.
        seen_spans, deduped = set(), []
        for e in edits:
            if (e[0], e[1]) in seen_spans:
                continue
            seen_spans.add((e[0], e[1]))
            deduped.append(e)
        doc_xml = apply_edits(doc_xml, deduped)
    return doc_xml, info


def _strip_direct_props(frag: str, strip_num: bool = False) -> str:
    for pat in (r"<w:ind(?=[\s/>])[^>]*/>", r"<w:spacing(?=[\s/>])[^>]*/>",
                r"<w:jc(?=[\s/>])[^>]*/>"):
        frag = re.sub(pat, "", frag)
    if strip_num:
        frag = re.sub(r"<w:numPr>[\s\S]*?</w:numPr>", "", frag, count=1)
    return frag


def _apply_front_refs(doc_xml: str, front: dict) -> tuple:
    """(xml, applied): point the document's sections at the venue headers/footers.

    Page 1 is governed by the FIRST `w:sectPr` (see `first_section_props`), so
    the template's first-page furniture -- `w:titlePg`, the "first" role and the
    default/even fallbacks -- lands THERE. Every later section gets the
    template's default/even roles but NOT `w:titlePg`: its pages continue the
    run with the venue's running head / page-number footer instead of repeating
    the title page's logo header. Writing only the LAST section (the old
    behaviour) left page 1 in the author's own furniture.
    """
    # A self-closing `<w:sectPr .../>` IS the page-1 section (see
    # `first_section_props`): skipping it put the venue's logo/title-page
    # furniture on the BODY section while page 1 kept the author's own.
    sects = list(SECT_READ_RE.finditer(doc_xml))
    if not sects:
        return doc_xml, False
    refs_all, refs_body = "", ""
    for key, tag, typ in (("header_default_rid", "headerReference", "default"),
                          ("header_first_rid", "headerReference", "first"),
                          ("header_even_rid", "headerReference", "even"),
                          ("footer_default_rid", "footerReference", "default"),
                          ("footer_first_rid", "footerReference", "first"),
                          ("footer_even_rid", "footerReference", "even")):
        if front.get(key):
            ref = f'<w:{tag} w:type="{typ}" r:id="{front[key]}"/>'
            refs_all += ref
            if typ != "first":
                refs_body += ref
    out = doc_xml
    for idx in range(len(sects) - 1, -1, -1):       # backwards: offsets stay valid
        m = sects[idx]
        body = re.sub(r"<w:(?:header|footer)Reference[^>]*/>", "", m.group(0))
        body = re.sub(r"<w:titlePg[^>]*/>", "", body)
        # The OPENING tag only: `[^>]*` greedily consumed the `/` of a legal
        # `<w:sectPr att="x"/>`, so the references were inserted AFTER the
        # self-closing element -- as siblings of `w:sectPr`, which is
        # schema-invalid OOXML -- instead of inside it.
        om = re.match(r"<w:sectPr(?=[\s>])(?:[^>/]|/(?!>))*>", body)
        if om:
            body = body[:om.end()] + (refs_all if idx == 0 else refs_body) + body[om.end():]
        else:
            # A self-closing empty section: expand it so the references land
            # INSIDE the element instead of after its `/>`.
            body = (body[:body.rfind("/>")].rstrip() + ">"
                    + (refs_all if idx == 0 else refs_body) + "</w:sectPr>")
        if idx == 0 and "<w:titlePg" not in body:
            body = (body.replace("<w:docGrid", "<w:titlePg/><w:docGrid", 1)
                    if "<w:docGrid" in body else
                    body.replace("</w:sectPr>", "<w:titlePg/></w:sectPr>", 1))
        out = out[:m.start()] + body + out[m.end():]
    if refs_all:
        root = re.search(r"<w:document\b[^>]*>", out)
        if root and "xmlns:r=" not in root.group(0):
            out = out.replace(
                root.group(0), root.group(0)[:-1] + ' xmlns:r="http://schemas.'
                'openxmlformats.org/officeDocument/2006/relationships">', 1)
    return out, True


def _with_even_odd_headers(parts: dict) -> bool:
    """Make `word/settings.xml` carry `w:evenAndOddHeaders` (the parity switch).

    A template that defines even-page headers/footers only renders them when the
    document turns this setting on. The element is inserted where the schema --
    and the templates themselves -- put it: immediately before
    `w:characterSpacingControl`, or before the first later element present.
    Returns True when the setting was added (the package is modified in place).
    """
    ct = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    settings = parts.get("word/settings.xml")
    if settings is None:
        parts["word/settings.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
            '2006/main"><w:evenAndOddHeaders/></w:settings>').encode("utf-8")
        if 'PartName="/word/settings.xml"' not in ct:
            ct = ct.replace(
                "</Types>", '<Override PartName="/word/settings.xml" ContentType='
                            '"application/vnd.openxmlformats-officedocument.wordprocessingml.'
                            'settings+xml"/></Types>')
            parts["[Content_Types].xml"] = ct.encode("utf-8")
        rels = parts.get("word/_rels/document.xml.rels", b"").decode("utf-8", "replace")
        if "relationships/settings" not in rels:
            used = set(re.findall(r'Id="([^"]+)"', rels))
            n = 3001
            while f"rId{n}" in used:
                n += 1
            rels = rels.replace(
                "</Relationships>",
                f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/settings" Target="settings.xml"/>'
                f"</Relationships>")
            parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        return True
    text = settings.decode("utf-8", "replace")
    if "evenAndOddHeaders" in text:
        return False
    element = "<w:evenAndOddHeaders/>"
    anchors = [i for i in (text.find("<w:characterSpacingControl"),
                           text.find("<w:footnotePr"),
                           text.find("<w:endnotePr"),
                           text.find("<w:compat"),
                           text.find("<w:rsids"))
               if i != -1]
    if anchors:
        i = min(anchors)
        text = text[:i] + element + text[i:]
    else:
        i = text.find("<w:defaultTabStop")
        j = text.find("/>", i) if i != -1 else -1
        if j != -1:
            text = text[:j + 2] + element + text[j + 2:]
        else:
            text = text.replace("</w:settings>", element + "</w:settings>", 1)
    parts["word/settings.xml"] = text.encode("utf-8")
    return True


_NUMBERING_GROUP_RE = re.compile(
    r"<w:(numPicBullet|abstractNum|num|numIdMacAtCleanup)(?=[\s/>])")


def _reorder_numbering_groups(xml: str, pics: str, abstracts: str, nums: str) -> str:
    """Rebuild `word/numbering.xml` with the carried blocks in schema order.

    CT_Numbering is a strict sequence (`numPicBullet*`, `abstractNum*`,
    `num*`, `numIdMacAtCleanup?`); splicing the carried definitions before
    `</w:numbering>` leaves an `abstractNum` after the template's own `num`
    whenever the template already defined one, and Word/`docx validate` refuses
    the part. Each existing top-level block keeps its bytes; only the group
    order changes, and the three carried groups join their own group.
    """
    close_at = xml.rfind("</w:numbering>")
    open_m = re.search(r"<w:numbering(?=[\s/>])[^>]*>", xml)
    if close_at == -1 or not open_m:
        return xml
    inner = xml[open_m.end():close_at]
    entries, other = [], []
    pos = 0
    for m in _NUMBERING_GROUP_RE.finditer(inner):
        if m.start() > pos:
            other.append(inner[pos:m.start()])
        open_end = (m.end() if inner[m.end() - 1:m.end()] == ">"
                    else inner.find(">", m.end()) + 1)
        if inner[open_end - 2:open_end] == "/>":
            end = open_end
        else:
            close = inner.find(f"</w:{m.group(1)}>", open_end)
            end = close + len(f"</w:{m.group(1)}>") if close != -1 else open_end
        entries.append((m.group(1), inner[m.start():end]))
        pos = end
    if pos < len(inner):
        other.append(inner[pos:])
    groups = {k: [] for k in ("numPicBullet", "abstractNum", "num", "numIdMacAtCleanup")}
    for tag, block in entries:
        groups[tag].append(block)
    # Anything that is not a numbering group (comments, whitespace) is kept,
    # appended at the end: XML comments are legal between the sequence
    # children, and silently dropping them would be a data loss of its own.
    return (xml[:open_m.end()]
            + "".join(groups["numPicBullet"]) + pics
            + "".join(groups["abstractNum"]) + abstracts
            + "".join(groups["num"]) + nums
            + "".join(groups["numIdMacAtCleanup"])
            + "".join(other)
            + xml[close_at:])


def _merge_source_lists(parts: dict, src_numbering: str, doc_part_re) -> dict:
    """Keep the source's list definitions that the template does not define.

    `apply_word_template` swaps the template's `word/numbering.xml` in; a
    paragraph whose DIRECT `w:numPr` names a source numId the template does not
    define then points at nothing and Word silently drops its bullet/number.
    Copy those definitions into the template's part under fresh ids (fresh
    abstractNum/num/picture-bullet ids, so nothing can collide) and rewrite the
    document's references. Returns {old numId: new numId} for what it carried;
    a numId the template DOES define keeps the template's definition.
    """
    tpl_numbering = parts.get("word/numbering.xml", b"").decode("utf-8", "replace")
    if not tpl_numbering or "</w:numbering>" not in tpl_numbering:
        return {}
    doc_names = [n for n in sorted(parts) if doc_part_re.fullmatch(n)]
    referenced = set()
    for name in doc_names:
        referenced |= set(re.findall(r'<w:numId(?=[\s/>])[^>]*w:val="(\d+)"',
                                     parts[name].decode("utf-8", "replace")))
    defined = set(re.findall(r'<w:num(?=[\s/>])[^>]*w:numId="(\d+)"', tpl_numbering))
    missing = sorted(referenced - defined, key=lambda s: (len(s), s))
    if not missing:
        return {}
    both = tpl_numbering + src_numbering
    next_abs = max((int(x) for x in re.findall(r'w:abstractNumId="(\d+)"', both)), default=0) + 1
    next_num = max((int(x) for x in re.findall(r'<w:num(?=[\s/>])[^>]*w:numId="(\d+)"', both)),
                   default=0) + 1
    next_pic = max((int(x) for x in re.findall(r'w:numPicBulletId="(\d+)"', both)), default=0) + 1
    abs_map, abs_blocks, num_blocks, pic_blocks = {}, [], [], []
    num_map = {}
    for old_num in missing:
        num_block = re.search(
            rf'<w:num(?=[\s/>])[^>]*w:numId="{re.escape(old_num)}"[\s\S]*?</w:num>', src_numbering)
        if not num_block:
            continue
        abs_ref = re.search(r'<w:abstractNumId(?=[\s/>])[^>]*w:val="(\d+)"', num_block.group(0))
        if not abs_ref:
            continue
        old_abs = abs_ref.group(1)
        if old_abs not in abs_map:
            abs_block = re.search(
                rf'<w:abstractNum(?=[\s/>])[^>]*w:abstractNumId="{re.escape(old_abs)}"'
                r'[\s\S]*?</w:abstractNum>', src_numbering)
            if not abs_block:
                continue
            new_abs = str(next_abs)
            next_abs += 1
            block = re.sub(rf'w:abstractNumId="{re.escape(old_abs)}"',
                           f'w:abstractNumId="{new_abs}"', abs_block.group(0), count=1)
            # a picture-bullet level references a numPicBullet element that must
            # travel with the copied list (schema order: numPicBullet, abstractNum, num)
            pic_map = {}
            for pid in sorted(set(re.findall(
                    r'<w:lvlPicBulletId(?=[\s/>])[^>]*w:val="(\d+)"', block))):
                pic = re.search(
                    rf'<w:numPicBullet(?=[\s/>])[^>]*w:numPicBulletId="{re.escape(pid)}"'
                    r'[\s\S]*?</w:numPicBullet>', src_numbering)
                if not pic:
                    continue
                new_pid = str(next_pic)
                next_pic += 1
                pic_map[pid] = new_pid
                pic_blocks.append(re.sub(rf'w:numPicBulletId="{re.escape(pid)}"',
                                         f'w:numPicBulletId="{new_pid}"', pic.group(0), count=1))
            for pid, new_pid in pic_map.items():
                block = re.sub(rf'(<w:lvlPicBulletId(?=[\s/>])[^>]*w:val="){re.escape(pid)}(")',
                               rf'\g<1>{new_pid}\g<2>', block)
            abs_map[old_abs] = new_abs
            abs_blocks.append(block)
        new_num = str(next_num)
        next_num += 1
        carried = re.sub(r'(<w:abstractNumId(?=[\s/>])[^>]*w:val=")[^"]*(")',
                         rf'\g<1>{abs_map[old_abs]}\g<2>', num_block.group(0), count=1)
        carried = re.sub(r'(<w:num(?=[\s/>])[^>]*w:numId=")[^"]*(")',
                         rf'\g<1>{new_num}\g<2>', carried, count=1)
        num_blocks.append(carried)
        num_map[old_num] = new_num
    if not num_map:
        return {}
    # ECMA-376 requires the numbering part's children in schema order:
    # numPicBullet*, abstractNum*, num*, numIdMacAtCleanup?. Appending the three
    # groups at the end is only correct when the template has no w:num yet --
    # a template that already defines one made the merged part run
    # `abstractNum, num, abstractNum, num`, and `docx validate` rejected it
    # ("abstractNum: This element is not expected. Expected is num").
    parts["word/numbering.xml"] = _reorder_numbering_groups(
        parts["word/numbering.xml"].decode("utf-8", "replace"),
        "".join(pic_blocks), "".join(abs_blocks), "".join(num_blocks)).encode("utf-8")
    for name in doc_names:
        xml = parts[name].decode("utf-8", "replace")
        new_xml = re.sub(
            r'(<w:numId(?=[\s/>])[^>]*w:val=")(\d+)(")',
            lambda m: m.group(1) + num_map.get(m.group(2), m.group(2)) + m.group(3), xml)
        if new_xml != xml:
            parts[name] = new_xml.encode("utf-8")
    return num_map


def apply_word_template(src: Path, out: Path, template: Path, containers=()) -> dict:
    """Restyle one DOCX into the venue's official Word template.

    The template's styles/theme/font table/numbering REPLACE the manuscript's
    (the names are mapped by style NAME, so a manuscript that uses its own ids
    still lands on the template's Heading 1/2, Title, Caption, ...), the
    template's page geometry is adopted, and the direct fonts/sizes/spacing/
    indentation that would otherwise override the styles are dropped on
    styled paragraphs. A heading the source only DIRECT-formatted (a short bold
    line above the body size, no paragraph style) is first retagged onto the
    template's Heading 1..N (`headings_retagged`), so the strip below cannot
    flatten it into body text and the template's heading styles -- and their
    numbering -- actually apply. Content, media, fields, headers/footers and
    relationships are preserved; the document TEXT must be byte-identical
    (reported as `text_unchanged`, and the caller keeps the original when it is
    not).
    """
    try:
        with zipfile.ZipFile(src) as spkg, zipfile.ZipFile(template) as tpkg:
            tnames = set(tpkg.namelist())
            if "word/styles.xml" not in tnames or "word/document.xml" not in tnames:
                return {"file": str(src), "ok": False,
                        "error": "the template is not a readable Word template "
                                 "(word/styles.xml / word/document.xml missing)"}
            parts = {i.filename: spkg.read(i.filename) for i in spkg.infolist()}
            src_styles = parts.get("word/styles.xml", b"").decode("utf-8", "replace")
            src_numbering = parts.get("word/numbering.xml", b"").decode("utf-8", "replace")
            tpl_styles = tpkg.read("word/styles.xml").decode("utf-8", "replace")
            s_by_id, _s_names = _style_index(src_styles)
            t_by_id, t_by_name = _style_index(tpl_styles)
            mapping = {}
            for sid, (typ, key) in s_by_id.items():
                if sid in t_by_id:
                    mapping[sid] = sid
                elif (typ, key) in t_by_name:
                    mapping[sid] = t_by_name[(typ, key)]
            mapped_ids = set(mapping.values())
            copied = []
            for name in ("word/styles.xml", "word/fontTable.xml", "word/numbering.xml"):
                if name in tnames:
                    parts[name] = tpkg.read(name)
                    copied.append(name)
            for name in sorted(tnames):
                if name.startswith("word/theme/"):
                    parts[name] = tpkg.read(name)
                    copied.append(name)
            tpl_doc = tpkg.read("word/document.xml").decode("utf-8", "replace")

            # A manuscript-only style the document still references must survive
            # the styles.xml replacement (otherwise its pStyle/rStyle points at
            # a definition that no longer exists).
            doc_part_re = re.compile(r"word/(?:document|header\d*|footer\d*|footnotes|endnotes)\.xml")
            ref_ids = set()
            for name in sorted(parts):
                if doc_part_re.fullmatch(name):
                    xml = parts[name].decode("utf-8", "replace")
                    ref_ids |= {m.group(2) for m in _STYLE_REF_RE.finditer(xml)}
            kept_styles = []
            for sid in sorted(ref_ids - set(t_by_id) - set(mapping)):
                m = re.search(rf'<w:style\b[^>]*w:styleId="{re.escape(sid)}"[\s\S]*?</w:style>',
                              src_styles)
                if m:
                    kept_styles.append(m.group(0))
            if kept_styles:
                tpl_styles = tpl_styles.replace("</w:styles>",
                                                "".join(kept_styles) + "</w:styles>")
                parts["word/styles.xml"] = tpl_styles.encode("utf-8")

            remapped = stripped = carried_lists = 0
            page_ok = False
            front_info = {}
            headings_retagged = []
            roles = template_style_roles(template)
            for name in sorted(parts):
                if not doc_part_re.fullmatch(name):
                    continue
                xml = parts[name].decode("utf-8", "replace")
                new_xml, n = _remap_style_refs(xml, mapping)
                remapped += n
                retag_styles = set()
                if name == "word/document.xml":
                    # Heading STYLE first, then strip: a source heading that only
                    # carries direct formatting must not be flattened into body
                    # text by the strip below.
                    new_xml, headings_retagged = _retag_headings(new_xml, roles, containers)
                    retag_styles = {t["style"] for t in headings_retagged}
                # A paragraph whose style exists in the template follows that
                # style: drop the direct geometry/typography that would hide it.
                edits = []
                for p0, p1, para in paragraphs(new_xml):
                    pstyle = elem_val(ppr_of(para), "pStyle")
                    # The reference was already rewritten to the TEMPLATE id, so
                    # test against the mapped ids, not the manuscript's old ids.
                    # An UNSTYLED paragraph also follows the template's default
                    # (Normal/theme) once its direct font/size/spacing overrides
                    # are gone; a paragraph with an unmapped custom style is left
                    # alone (there is no template equivalent to fall back to).
                    if pstyle and pstyle not in mapped_ids and pstyle not in retag_styles:
                        continue
                    stripped_para, k = _strip_direct_format(para)
                    if k:
                        stripped += k
                        edits.append((p0, p1, stripped_para))
                if edits:
                    new_xml = apply_edits(new_xml, edits)
                if name == "word/document.xml":
                    new_xml, page_ok = _adopt_page_geometry(new_xml, tpl_doc)
                    new_xml, front_info = _front_matter_styles(new_xml, roles, tpl_doc)
                if new_xml != xml:
                    parts[name] = new_xml.encode("utf-8")
            if "word/numbering.xml" in copied and src_numbering:
                carried_lists = len(_merge_source_lists(parts, src_numbering, doc_part_re))
            front_parts = _template_front_parts(tpkg, parts, tnames)
            if front_parts:
                doc_xml = parts["word/document.xml"].decode("utf-8", "replace")
                doc_xml, refs_ok = _apply_front_refs(doc_xml, front_parts)
                if refs_ok:
                    parts["word/document.xml"] = doc_xml.encode("utf-8")
                if front_parts.get("even_odd"):
                    _with_even_odd_headers(parts)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for name, data in parts.items():
                    z.writestr(name, data)
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as e:
        return {"file": str(src), "ok": False, "error": f"{type(e).__name__}: {e}"}

    def _text(p: Path) -> str:
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        return "\n".join(t for t in (text_of(par[2]) for par in paragraphs(xml)) if t.strip())

    try:
        text_ok = _text(src) == _text(out)
        with zipfile.ZipFile(out) as z:
            check_parts = ["word/document.xml", "word/styles.xml"]
            if "word/numbering.xml" in copied or carried_lists:
                check_parts.append("word/numbering.xml")
            for name in check_parts:
                ET.fromstring(z.read(name))
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, RuntimeError,
            NotImplementedError) as e:
        return {"file": str(src), "ok": False, "error": f"verification failed: {e}"}
    changes = [f"copied {len(copied)} template part(s)",
               f"remapped {remapped} style reference(s)"]
    if carried_lists:
        changes.append(f"carried {carried_lists} source list definition(s) the template "
                       f"does not define")
    if stripped:
        changes.append(f"removed {stripped} direct formatting propert(ies)")
    if page_ok:
        changes.append("adopted the template page geometry")
    if front_info.get("title"):
        changes.append("front matter: article title -> Title (centered)")
    if front_info.get("authors"):
        changes.append("front matter: author line -> AuthorList (bold)")
    if front_info.get("abstract"):
        changes.append("front matter: Abstract -> unnumbered AuthorList")
    if front_info.get("keywords"):
        changes.append("front matter: Keywords -> the template's front-matter style")
    if front_info.get("deep_headings_demoted"):
        changes.append(f"demoted {front_info['deep_headings_demoted']} heading(s) deeper than "
                       f"the template's own depth")
    if headings_retagged:
        changes.append(f"tagged {len(headings_retagged)} directly-formatted heading(s) with the "
                       f"template's heading styles")
    if front_parts:
        # Describe what was actually copied: a template with no logo header
        # still made the old line claim "first-page header (logo)".
        got = []
        if front_parts.get("logo"):
            got.append("first-page header (logo)")
        elif front_parts.get("header_first"):
            got.append("first-page header")
        if front_parts.get("header_default"):
            got.append("default header")
        if any(front_parts.get(k) for k in ("footer_first", "footer_default", "footer_even")):
            got.append("page-number footers")
        changes.append("copied the venue's " + ", ".join(got)
                       if got else "copied the venue's front-page furniture")
        if front_parts.get("even_odd"):
            changes.append("enabled the template's odd/even (evenAndOddHeaders) page furniture")
        for role in front_parts.get("footer_replaced") or []:
            changes.append(f"replaced the template's {role}-page footer with the plain "
                           f"page-number footer")
    return {"file": str(src), "template": str(template), "ok": bool(text_ok),
            "text_unchanged": bool(text_ok), "changes": changes,
            "styles_copied": copied, "style_refs_remapped": remapped,
            "direct_format_removed": stripped, "page_geometry": page_ok,
            "headings_retagged": headings_retagged,
            "front_matter": front_info,
            "template_roles": {k: v for k, v in (roles or {}).items() if k != "headings"},
            "front_parts": {k: v for k, v in (front_parts or {}).items() if k != "copied"}}


def validate_latex(path: Path, workdir: Path = None, timeout: int = 300) -> dict:
    """Compile one STANDALONE .tex in a scratch copy of its directory.

    A `.tex` without `\\documentclass` is a FRAGMENT (a `\\input`ed section or a
    generated table): compiling it alone fails on the missing preamble, so it is
    reported SKIP and validated through the document that inputs it -- the main
    file's compile is what proves it.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError as e:
        return {"file": str(path), "kind": "tex", "ok": False,
                "errors": [f"unreadable: {e}"], "detail": str(e)}
    if "\\documentclass" not in head and "\\documentclass" not in \
            path.read_text(encoding="utf-8", errors="replace"):
        return {"file": str(path), "kind": "tex", "ok": None,
                "detail": "fragment (no \\documentclass): validated through the document "
                          "that inputs it"}
    engine = latex_engine()
    if engine is None:
        return {"file": str(path), "kind": "tex", "ok": None,
                "detail": "no TeX engine (latexmk/xelatex/pdflatex) on PATH; "
                          "compilation not verified"}
    name, argv = engine
    scratch = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="paper_tex_check_"))
    owns_scratch = workdir is None
    try:
        try:
            target_dir = scratch / path.parent.name if not workdir else scratch
            if not target_dir.is_dir():
                # A name-based ignore callback (not glob patterns): the tracking
                # token space is open (a1/w2/a3/winner1/...), so only the shared
                # `_is_aux_name()` rule can decide what to leave out.
                shutil.copytree(path.parent, target_dir,
                                ignore=lambda _d, names: [n for n in names
                                                          if n == "work" or _is_aux_name(n)])
            proc = subprocess.run(argv + [path.name], cwd=str(target_dir),
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError, shutil.Error) as e:
            return {"file": str(path), "kind": "tex", "ok": False, "engine": name,
                    "errors": [f"{type(e).__name__}: {e}"],
                    "detail": "the compile step itself failed"}
        out = (proc.stdout or "") + (proc.stderr or "")
        errors = [ln.strip() for ln in out.splitlines() if ln.startswith("!")][:5]
        return {"file": str(path), "kind": "tex", "ok": proc.returncode == 0, "engine": name,
                "errors": errors, "detail": (errors[0] if errors else
                                             ("compiled" if proc.returncode == 0
                                              else f"engine exited {proc.returncode}"))}
    finally:
        # A validation pass over N .tex files must not leak N full project
        # copies; an operator-supplied workdir is not ours to remove.
        if owns_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def validate_paths(paths: list, json_out: Path = None, timeout: int = 300) -> dict:
    """Validate every DOCX (XML/schema) and .tex (compile) under `paths`."""
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += [q for q in docx_files_under(p)
                      if not q.name.startswith("~$") and not _is_aux_name(q.name)
                      and not any(part in EVIDENCE_DIRNAMES for part in q.parts[:-1])]
            files += [q for q in sorted(p.rglob("*"))
                      if q.is_file() and q.suffix.lower() in (".tex", ".ltx")
                      if not any(part in EVIDENCE_DIRNAMES for part in q.parts[:-1])
                      # A difference-tracking copy (a latexdiff file, or the
                      # commented-out logging fallback) is not a document of the
                      # package: compiling it would report the AUXILIARY as a
                      # failed deliverable (a fragment's copy has no preamble).
                      and not _is_aux_name(q.name)]
        elif p.is_file():
            files.append(p)
    results = []
    for p in files:
        if p.suffix.lower() == ".docx":
            results.append(validate_docx_parts(p))
        elif p.suffix.lower() in (".tex", ".ltx"):
            results.append(validate_latex(p, timeout=timeout))
        else:
            # An explicitly named file of an unsupported type is not a
            # zero-file success: report it as a failure, the false-clean the
            # `_missing_paths` check exists to prevent.
            results.append({
                "file": str(p), "kind": (p.suffix.lower().lstrip(".") or "file")[:4],
                "ok": False,
                "errors": [f"unsupported document type {p.suffix or '(none)'}; "
                           f"expected .docx, .tex or .ltx"],
                "detail": "not a document this validator can check"})
    bad = [r for r in results if r["ok"] is False]
    report = {"files": len(results), "failed": len(bad), "results": results,
              "ok": not bad}
    if json_out:
        write_json(json_out, report)
    return report


def _is_aux_name(name: str) -> bool:
    """A difference-tracking auxiliary (see AUX_FILES_RULE in paper_pipeline.py).

    The rule has to match THE PIPELINE'S (`TRACKING_AUX_NAME_RE`): the scanner
    and the corpus builder must agree on which files are submission content, or
    a scan of a package reports rows on files the pipeline itself wrote. The
    name is `<anything>.tracking-<token>.<ext>` (or `.logging-<token>.<ext>` for
    the fallback log), where <token> names the baseline: `original`, a version
    id (`a1`, `w2`, ...) or a published round winner (`winner1`, ...). The
    extension set covers the `.docx`/`.tex`/`.bib` copies AND the compiled
    `.pdf` of a tracking `.tex` compile root.
    """
    low = name.lower()
    return re.search(r"\.(?:tracking|logging)-(?:original|winner[0-9]+|[awi][0-9]+)"
                     r"\.(?:docx|tex|bib|pdf)$", low) is not None


# --------------------------------------------------------------------------
# PDF ARTIFACT SANITY (rules FMT-PDF1..FMT-PDF3).
#
# A submission package ships PDFs that must OPEN and SHOW their content outside
# the author's own machine. Two shapes pass every existing check because they
# are valid PDFs with a valid page:
#   * an Adobe LiveCycle/XFA FORM: the page is a JavaScript shell, so a reader
#     that is not Adobe Acrobat (a journal's converter, a browser view, the
#     submission system's text extractor) renders "Please wait..." and nothing
#     else. A "reporting summary filled.pdf" can therefore be COMPLETELY blank
#     while being 1.6 MB of XFA template.
#   * a PDF whose XFA dataset exists but carries no value: the form was never
#     filled in (or the fill was never saved into the dataset).
# Both are reported as high findings (the pipeline must not certify a package
# whose required form is blank), and the check degrades to the raw byte scan
# when `pdfinfo` is unavailable.
# --------------------------------------------------------------------------

PDF_PLACEHOLDER_RE = re.compile(
    r"(?is)if this message is not eventually replaced by the proper contents")
PDF_PLACEHOLDER_BYTES_RE = re.compile(
    rb"(?is)if this message is not eventually replaced by the proper contents")
# The XFA shell renders "Please wait..." (the ellipsis is part of the
# placeholder). Without it the pattern matched the ordinary English phrase in
# any sentence -- "Please wait for the reviewer assignment..." -- and a healthy
# one-page letter was reported FMT-PDF1 at high severity.
PDF_PLACEHOLDER_STRONG_RE = re.compile(r"(?is)please\s+wait\s*(?:\.{2,3}|\u2026)")
PDF_VERSION_EXTS = (".pdf",)


def _pdfinfo_form(path: Path) -> str:
    """The raw `Form:` value pdfinfo prints ("" when pdfinfo is absent/unreadable).

    `pdfinfo` prints "Form: none" for an ordinary PDF and the form TECHNOLOGY
    (XFA/LiveCycle/AcroForm) for a form, and the two must stay distinguishable:
    a caller that asks "is this (or may it be) a form?" tests for the empty
    string (pdfinfo could not tell) and for "none" (pdfinfo proved there is no
    form) separately, exactly as `pdf_artifact_rows` does.
    """
    exe = shutil.which("pdfinfo")
    if not exe:
        return ""
    try:
        proc = subprocess.run([exe, str(path)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (proc.stdout or "").splitlines():
        if line.lower().startswith("form:"):
            value = line.split(":", 1)[1].strip()
            return value
    return ""


def _xfa_dataset_packets(data: bytes) -> list:
    """Every decompressed `xfa:datasets` packet in a PDF, as (offset, text).

    A LiveCycle form saved more than once carries SEVERAL dataset packets: the
    original template's empty one and the current filled one (an incremental
    update appends the newer). The scan returns all of them, and the caller
    treats the form as filled when ANY packet carries an answer -- the older
    "the first packet decides" reading is how a genuinely filled Reporting
    Summary was reported as UNFILLED by both the round-1 review and the
    publish-time scanner.
    """
    packets = []
    for m in re.finditer(rb"(?<!end)stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        raw = data[start:end]
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            # An UNCOMPRESSED stream is legal (`/Length` with no `/Filter`) and
            # the XFA packet set may be written that way by a non-Adobe tool:
            # skipping it made `all_datasets` read 0 on a form that carries two
            # packet sets (the 2026-10-15 hand-off test).
            dec = raw
        if b"xfa:datasets" in dec:
            packets.append((start, dec.decode("utf-8", "replace")))
    return packets


# XFA answers serialize with whitespace before the closing bracket
# (`<author\n>Xuegong Zhang</author\n>`), which is why the old
# `<tag>value</tag>` pattern counted ZERO answers on a filled form.
# The value class is deliberately unbounded: `[^<>]` cannot cross a tag
# boundary, so the match is confined to one text node and there is nothing to
# backtrack over. The old `{1,400}` cap made a LONGER answer invisible -- a
# filled form whose answer ran past 400 characters counted as UNFILLED
# (FMT-PDF2) and `xfa_export_text` (which promises "every answer") dropped it.
XFA_LEAF_RE = re.compile(r"<([A-Za-z_][\w.\-]*)\s*>\s*([^<>]*?)\s*</\1\s*>")


def _xfa_dataset_report(path: Path):
    """(is_xfa, non_empty_values, is_livecycle_shell) for a PDF's XFA dataset.

    `is_livecycle_shell` is True when the PDF's own rendered text is the Adobe
    placeholder, i.e. the document is a FORM DEFINITION, not a document.
    `non_empty_values` counts the answer leaves of EVERY dataset packet; an
    XFA form with no dataset packet at all returns -1 (unverifiable), which
    never produces the "unfilled" finding.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return (False, -1, False)
    form_line = _pdfinfo_form(Path(path))
    # The byte test requires the AcroForm/XFA object structure, not the bare
    # string: a normal compiled PDF can contain "/XFA" inside its own text.
    is_xfa = ("xfa" in form_line.lower()
              or (b"AcroForm" in data and re.search(rb"/XFA[\s/\[]", data) is not None))
    is_shell = bool(PDF_PLACEHOLDER_RE.search(data.decode("latin-1", "replace")))
    packets = _xfa_dataset_packets(data) if is_xfa else []
    non_empty = -1 if is_xfa and not packets else 0
    for _off, text in packets:
        for em in XFA_LEAF_RE.finditer(text):
            if em.group(2).strip():
                non_empty += 1
    if not is_shell:
        for m in re.finditer(rb"(?<!end)stream\r?\n", data):
            start = m.end()
            end = data.find(b"endstream", start)
            if end < 0:
                continue
            try:
                dec = zlib.decompress(data[start:end])
            except zlib.error:
                continue
            if PDF_PLACEHOLDER_BYTES_RE.search(dec):
                # The placeholder lives in a COMPRESSED stream: the shell is
                # real even when pdftotext cannot render the page.
                is_shell = True
                break
    return (is_xfa, non_empty, is_shell)


def _pdf_object_bodies(data: bytes) -> dict:
    """{object number: raw body} for a PDF, object streams expanded.

    The one thing `_xfa_dataset_packets` cannot see: WHICH packet the form
    actually reads. The AcroForm's `/XFA` array names it by object number, and on
    a form saved more than once those numbers live inside an object stream
    (`/ObjStm`) -- so the array has to be read from the DECOMPRESSED objects, not
    from the raw bytes. Text-level reading served the earlier rounds; it is what
    made a form's live dataset unidentifiable (2026-10-15).
    """
    objs: dict = {}
    # NOT line-anchored: a PDF may use `\r` line endings, and `(?m)^` then
    # matches almost nothing (two top-level objects out of 54 in this file's
    # case), so the object carrying the live /XFA array was never read. A wrong
    # hit inside a stream is harmless as long as it is not the LAST definition
    # of the number we resolve -- the dictionary guard below drops those.
    for m in re.finditer(rb"(\d+)\s+0\s+obj", data):
        num = int(m.group(1))
        start = m.end()
        end = data.find(b"endobj", start)
        body = data[start:end if end >= 0 else len(data)]
        stripped = body.lstrip(b"\r\n \t")
        if not stripped.startswith(b"<<") and b"stream" not in body[:200]:
            continue
        if stripped.startswith(b"<<") and b"stream" not in body:
            close = stripped.find(b">>")
            if close < 0:
                continue
        objs[num] = body
    for num in list(objs):
        body = objs[num]
        if b"/ObjStm" not in body[:400]:
            continue
        sm = re.search(rb"(?<!end)stream\r?\n", body)
        if not sm:
            continue
        raw = body[sm.end():]
        stop = raw.find(b"endstream")
        if stop >= 0:
            raw = raw[:stop]
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        fm = re.search(rb"/First (\d+)", body)
        nm = re.search(rb"/N (\d+)", body)
        if not (fm and nm):
            continue
        first, count = int(fm.group(1)), int(nm.group(1))
        hdr = dec[:first].split()
        for i in range(count):
            try:
                onum, off = int(hdr[2 * i]), int(hdr[2 * i + 1])
            except (IndexError, ValueError):
                break
            nxt = int(hdr[2 * i + 3]) if 2 * i + 3 < len(hdr) else len(dec) - first
            # LAST definition wins: an incremental update appends the newer
            # objects, and a PDF reader resolves an object number to its LATEST
            # definition. `setdefault` kept the first, i.e. the stale XFA packet
            # array -- which is how this helper first read a filled form's live
            # dataset as the empty duplicate (2026-10-15).
            objs[onum] = dec[first + off:first + nxt]
    return objs


def _obj_stream_text(body: bytes):
    """The decompressed (or plain) stream of one object body, or None."""
    sm = re.search(rb"(?<!end)stream\r?\n", body)
    if not sm:
        return None
    raw = body[sm.end():]
    stop = raw.find(b"endstream")
    if stop >= 0:
        raw = raw[:stop]
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def xfa_live_packets(path: Path) -> dict:
    """Which XFA packets the AcroForm READS, and what each one carries.

    Returns {"resolved", "packets": {name: (object number, non-empty leaves,
    text)}, "live_datasets": [names], "all_datasets": <count of dataset packets
    in the file>}. `resolved` is False when the /XFA array cannot be read (an
    older reader's guess is then the best available), and the 2026-10-15
    Audit's question -- "is the empty copy the one the form uses, or a stale
    duplicate?" -- is answered by the /XFA array itself, never by packet order.
    """
    out = {"resolved": False, "packets": {}, "live_datasets": [], "all_datasets": 0}
    try:
        data = Path(path).read_bytes()
    except OSError:
        return out
    objs = _pdf_object_bodies(data)
    out["all_datasets"] = len(_xfa_dataset_packets(data))
    acro = [(num, body) for num, body in objs.items() if re.search(rb"/XFA[\s/\[]", body)]
    if not acro:
        return out
    # An incremental update appends: the object with the HIGHEST number is the
    # live AcroForm (a later save never lowers an object number).
    num, body = max(acro, key=lambda kv: kv[0])
    m = re.search(rb"/XFA\s*\[(.*?)\]", body, re.S)
    if m:
        for name, onum in re.findall(rb"\(([^)]*)\)\s*(\d+)\s+0\s+R", m.group(1)):
            pname = name.decode("latin-1")
            onum = int(onum)
            pbody = objs.get(onum)
            text = _obj_stream_text(pbody) if pbody is not None else None
            if text is None:
                continue
            if b"xfa:datasets" in text or b"<xfa:data" in text:
                answers = [(em.group(1), em.group(2).strip())
                           for em in XFA_LEAF_RE.finditer(text.decode("utf-8", "replace"))
                           if em.group(2).strip()]
                out["packets"][pname] = (onum, len(answers), text)
            else:
                out["packets"][pname] = (onum, 0, text)
        out["resolved"] = bool(out["packets"])
    else:
        # A single-stream /XFA: the whole XDP is in one object; its datasets
        # packet is the part this report needs.
        sm = re.search(rb"/XFA\s+(\d+)\s+0\s+R", body)
        if sm:
            text = _obj_stream_text(objs.get(int(sm.group(1)), b""))
            if text and b"xfa:data" in text:
                answers = [(em.group(1), em.group(2).strip())
                           for em in XFA_LEAF_RE.finditer(text.decode("utf-8", "replace"))
                           if em.group(2).strip()]
                out["packets"]["<single-stream>"] = (int(sm.group(1)), len(answers), text)
                out["resolved"] = True
    out["live_datasets"] = [k for k, v in out["packets"].items()
                            if v[2] and (b"xfa:datasets" in v[2] or b"<xfa:data" in v[2])]
    return out


def _xfa_packet_summary(path: Path) -> dict:
    """The LIVE dataset's answer count, plus any STALE duplicate packet set.

    A form saved twice carries the original (often empty) packet set AND the
    saved one, and the two disagree -- the 2026-10-15 operator's audit of the
    CopyNumBench Reporting Summary reported "the XFA dataset the file actually
    uses is empty" about a form whose live dataset carries 48 answers (the
    empty one is the STALE copy, object 76, while the live /XFA array names
    object 275). Both readings are reachable: a strict reader resolves the
    latest object (the answers show), some XFA processors and text tools take the
    first packet (the form reads BLANK). That is a deliverable defect either way,
    so the count of each side is reported and the caller words its row from
    them.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return {}
    is_xfa, _all_answers, is_shell = _xfa_dataset_report(Path(path))
    live = xfa_live_packets(Path(path))
    out = {"is_xfa": is_xfa, "is_shell": is_shell, "resolved": bool(live.get("resolved")),
           "live_answers": 0, "live_objects": [], "stale_answers": 0, "stale_objects": [],
           "packets": live.get("all_datasets") or 0}
    live_nums = set()
    for name, (onum, count, text) in (live.get("packets") or {}).items():
        if not text or not (b"xfa:datasets" in text or b"<xfa:data" in text):
            continue
        live_nums.add(onum)
        out["live_objects"].append(onum)
        out["live_answers"] = max(out["live_answers"], int(count))
    live_texts = {v[2].decode("utf-8", "replace")
                  for v in (live.get("packets") or {}).values() if v[2]}
    for _off, text in _xfa_dataset_packets(data):
        if not out["resolved"] or text in live_texts:
            continue
        # A dataset packet the /XFA array does not name: a stale copy from an
        # earlier save. Its own answer count is what a reader taking "the first
        # packet" would see.
        answers = sum(1 for em in XFA_LEAF_RE.finditer(text) if em.group(2).strip())
        out["stale_answers"] = max(out["stale_answers"], answers)
    return out


def xfa_dataset_answers(path: Path, limit: int = 400) -> list:
    """[(field name, answer)] of the richest XFA dataset packet (or []).

    `limit` bounds a caller's listing; `None` returns every answer. The
    readable export passes None: it promises "every answer", while the FMT gate
    counts every non-empty leaf (`_xfa_dataset_report`), so a form with more
    than `limit` answers was reported as N filled and exported as N-1.

    The LIVE packet wins when the AcroForm's own `/XFA` array can be read: the
    export must show the answers the form actually carries, and reading a stale
    duplicate instead is how "the form is filled" and "the form is blank" were
    both argued about the same file in 2026-10-15.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    live = xfa_live_packets(Path(path))
    if live.get("resolved"):
        for name in live.get("live_datasets") or []:
            text = live["packets"].get(name, (None, 0, None))[2]
            if not text:
                continue
            answers = [(em.group(1), em.group(2).strip())
                       for em in XFA_LEAF_RE.finditer(text.decode("utf-8", "replace"))
                       if em.group(2).strip()]
            if answers:
                return answers if limit is None else answers[:limit]
    best = []
    for _off, text in _xfa_dataset_packets(data):
        answers = [(em.group(1), em.group(2).strip())
                   for em in XFA_LEAF_RE.finditer(text) if em.group(2).strip()]
        if len(answers) > len(best):
            best = answers
    return best if limit is None else best[:limit]


def xfa_export_text(path: Path) -> str:
    """A readable rendering of a filled XFA form (the answer to the shell).

    This is what the pipeline can produce offline: the editor/reviewer can
    read every answer even when their viewer shows the Adobe placeholder. It is
    NOT a layout reproduction of the journal's form (that needs Acrobat), so the
    pipeline ships it beside the original and says so.
    """
    answers = xfa_dataset_answers(path, limit=None)
    if not answers:
        return ""
    lines = [f"Readable export of the XFA form data in {Path(path).name}",
             "Generated by paper_docx_format.py xfa-export (the PDF's own text layer "
             "shows the Adobe placeholder outside Acrobat).", ""]
    for name, value in answers:
        lines.append(f"[{name}]")
        lines.append(value)
        lines.append("")
    return "\n".join(lines)


def _pdf_carries_an_image(path: Path) -> bool:
    """True when the PDF embeds an image (a text-less figure/scan is EXPECTED).

    `FMT-PDF3` exists for an export that lost its content, not for a figure
    saved as a PDF: the common case of a raster figure (or a scanned page) has
    no extractable text and is perfectly valid, so the check must not report it.
    Reads the object structure first, then looks for a JPEG/PNG stream when the
    object dictionary is compressed.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if re.search(rb"/Subtype\s*/Image", data):
        return True
    for m in re.finditer(rb"(?<!end)stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        raw = data[start:end]
        if raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n":
            return True
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        if dec[:3] == b"\xff\xd8\xff" or dec[:8] == b"\x89PNG\r\n\x1a\n":
            return True
    return False


def pdf_artifact_rows(path: Path, text: str = None, pages=None) -> list:
    """FMT-PDF1..6 for one PDF (empty list = nothing proven wrong)."""
    rows = []
    name = Path(path).name
    if text is None:
        exe = shutil.which("pdftotext")
        if exe:
            try:
                proc = subprocess.run([exe, "-layout", str(path), "-"],
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=60)
                text = proc.stdout or ""
            except (OSError, subprocess.SubprocessError) as e:
                # The module's contract is to REPORT a row, never to raise out of
                # a scan; a stalled/failing pdftotext degrades exactly like the
                # "pdftotext not available" branch below (the sibling helpers
                # catch this same tuple).
                print(f"warning: pdftotext failed on {Path(path).name} "
                      f"({type(e).__name__}); the PDF's text layer was not read",
                      file=sys.stderr)
                text = ""
        else:
            text = ""
    body = (text or "").strip()
    is_xfa, non_empty, is_shell = _xfa_dataset_report(Path(path))
    pack = _xfa_packet_summary(Path(path)) if is_xfa else {}
    if pack.get("resolved"):
        # With the live packet known, the FILLED/UNFILLED question is decided by
        # the packet the AcroForm actually reads (`live_answers`), not by "some
        # packet somewhere has text".
        non_empty = int(pack.get("live_answers") or 0)
    strong = bool(PDF_PLACEHOLDER_STRONG_RE.search(body)) and len(body) < 1500
    if strong and not is_shell:
        # The bare "Please wait..." fallback must not flag ordinary prose. It
        # fires only for a document that is (or may be) a form: pdfinfo reported
        # one, or pdfinfo is unavailable to disprove it.
        form_line = _pdfinfo_form(Path(path))
        strong = form_line == "" or "none" not in form_line.lower()
    placeholder = bool(PDF_PLACEHOLDER_RE.search(body)) or strong or is_shell
    if placeholder:
        evidence = (f"rendered text is the Adobe placeholder ({len(body)} chars)"
                    if body else "the PDF's own streams carry the Adobe placeholder text")
        rows.append({"rule": "FMT-PDF1", "severity": "high", "document": name,
                     "location": "-",
                     "evidence": evidence,
                     "detail": "this PDF is a form SHELL: readers other than Adobe "
                               "Acrobat render only 'Please wait...', so any content it is "
                               "supposed to carry is invisible to the editor, the reviewer "
                               "and the submission system; flatten it before shipping",
                     "fix": "manual", "protected": False})
    if is_xfa and non_empty == 0:
        if pack.get("resolved") and int(pack.get("stale_answers") or 0) > 0:
            # The answers EXIST, but only in a packet set the /XFA array does not
            # name: no reader reaches them, and the form reads blank.
            rows.append({"rule": "FMT-PDF5", "severity": "high", "document": name,
                         "location": "-",
                         "evidence": f"the /XFA array names a dataset with 0 answers while the "
                                     f"file carries a SECOND (unreferenced) packet set with "
                                     f"{pack['stale_answers']} non-empty value(s)",
                         "detail": "the mandatory form's OWN data layer is EMPTY: the answers "
                                   "live in an unreferenced copy of the packet set that no "
                                   "reader, conversion or submission system resolves. Open the "
                                   "file in Adobe Acrobat, re-enter/confirm the answers and "
                                   "export a flattened PDF (the pipeline's `xfa-export` renders "
                                   "the unreferenced copy so nothing is lost in the meantime)",
                         "fix": "manual", "protected": False})
        else:
            rows.append({"rule": "FMT-PDF2", "severity": "high", "document": name,
                         "location": "-",
                         "evidence": "XFA/LiveCycle form whose dataset packet(s) carry no "
                                     "non-empty answer",
                         "detail": "the form ships UNFILLED (every field is empty or default); "
                                   "fill it in the Adobe reader (or replace it with a flattened "
                                   "PDF) before submitting",
                         "fix": "manual", "protected": False})
    elif is_xfa and non_empty > 0 and placeholder:
        # The form IS filled; the defect is only the delivery format. Reported
        # separately so the instruction is "flatten" (an export step), never
        # "fill" (which would overwrite real answers). `xfa-export` writes the
        # readable rendering this row's detail points at.
        rows.append({"rule": "FMT-PDF4", "severity": "high", "document": name,
                     "location": "-",
                     "evidence": f"XFA/LiveCycle form with {non_empty} non-empty answer(s) "
                                 f"but the placeholder is what a non-Acrobat reader shows",
                     "detail": "the mandatory form is FILLED but delivered as a shell: the "
                               "answers live only in the XFA data layer. Open it in Adobe "
                               "Acrobat Reader and export a flattened, text-readable PDF (the "
                               "pipeline's `xfa-export` writes a readable rendering of every "
                               "answer beside the package for reference)",
                     "fix": "manual", "protected": False})
        if pack.get("resolved") and int(pack.get("packets") or 0) > 1:
            # The file carries TWO packet sets. The live one is read here; a
            # strict XFA processor that takes the first shows the other, and the
            # 2026-10-15 audit of this very file read it as BLANK for that reason.
            rows.append({"rule": "FMT-PDF6", "severity": "medium", "document": name,
                         "location": "-",
                         "evidence": f"{pack['packets']} XFA packet set(s) in one file: the "
                                     f"/XFA array names the filled one "
                                     f"({pack.get('live_answers')} answer(s), object(s) "
                                     f"{pack.get('live_objects')}), and a stale copy with "
                                     f"{pack.get('stale_answers')} non-empty value(s) is still "
                                     f"in the file",
                         "detail": "this form was saved twice, so it carries an older and a "
                                   "newer packet set. A reader that resolves PDF objects "
                                   "strictly shows the answers; one that takes the first packet "
                                   "shows an empty form (that is how the same file reads as "
                                   "'blank' to a text tool or a strict XFA processor, including "
                                   "some editorial systems and the operator's own audit). "
                                   "Open it in Adobe Acrobat and use 'Save As' to write a "
                                   "single-set file, or export a flattened PDF "
                                   "(`xfa-export` renders the live answers for reference)",
                         "fix": "manual", "protected": False})
    elif not body and (pages or 0) >= 1 and not _pdf_carries_an_image(Path(path)):
        rows.append({"rule": "FMT-PDF3", "severity": "medium", "document": name,
                     "location": "-",
                     "evidence": f"{pages} page(s), no extractable text",
                     "detail": "the PDF carries no extractable text and no embedded image: "
                               "an empty export rather than a rendered document",
                     "fix": "manual", "protected": False})
    if body:
        note = pdf_production_note(body)
        if note:
            rows.append({"rule": "FMT-PDF7", "severity": "medium", "document": name,
                         "location": "-", "evidence": f"the opening text explains how the "
                         f"document was produced: {note!r}",
                         "detail": "a submitted document may not narrate its own PRODUCTION: "
                                   "this reads as an internal step note to a reviewer, and it "
                                   "tells the journal the file is a substitute for the "
                                   "document it asked for. Ship the document itself (the "
                                   "venue's own form where one was requested), or keep the "
                                   "explanatory note outside the submission.",
                         "fix": "manual", "protected": False})
    return rows


# FMT-PDF7 (2026-10-15): a submitted PDF whose OPENING text narrates how the file
# was produced. The CNB package shipped a rebuilt Reporting Summary whose first
# paragraph read "Reporting Summary Nature Portfolio life-sciences reporting
# summary: a static rendering of the form's own questions and the author's own
# answers, because the submitted PDF is an Adobe LiveCycle form whose static page
# shows only a viewer placeholder. Sections the form leaves empty are omitted."
# -- a reviewer's opening line was an explanation of the pipeline's substitute,
# and the round's own judge filed it (r1-D0016) while no delivered status line
# mentioned it. The match is deliberately narrow: a MANUSCRIPT never opens with
# these phrases, and the pattern is anchored to the first ~1200 characters so a
# Methods sentence about "the rendering pipeline" cannot trigger it.
PDF_PRODUCTION_NOTE_RE = re.compile(
    r"(?i)\b(?:a\s+)?static\s+rendering\s+of\s+the\s+form\b"
    r"|\bsubmitted\s+PDF\s+is\s+an?\s+(?:Adobe\s+)?(?:LiveCycle|XFA|AcroForm)\b"
    r"|\bviewer\s+placeholder\b"
    r"|\bsections\s+the\s+form\s+leaves\s+empty\s+are\s+omitted\b"
    r"|\brendering\s+of\s+the\s+form'?s\s+own\s+questions\b")


def pdf_production_note(text: str) -> str:
    """The FMT-PDF7 evidence string for a PDF's text ("" = no production note)."""
    head = str(text or "")[:1200]
    m = PDF_PRODUCTION_NOTE_RE.search(head)
    if not m:
        return ""
    return head[max(0, m.start() - 60):m.end() + 60].replace("\n", " ").strip()


def check_pdf(path: Path, policy: dict) -> dict:
    if not shutil.which("pdftotext"):
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": None,
                "rows": [{"rule": "FMT-S2", "severity": "low", "document": path.name,
                          "location": "-", "evidence": "pdftotext not available",
                          "detail": "cannot check pages for blankness", "fix": "manual",
                          "protected": False}]}
    try:
        proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        # A timeout/wedged child re-raised subprocess.TimeoutExpired straight out
        # of the scan (60 s in, on exactly the large or pathological PDF this
        # check exists for). Report it like any other unreadable input instead.
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": False,
                "rows": [{"rule": "FMT-S2", "severity": "high", "document": path.name,
                          "location": "-",
                          "evidence": f"pdftotext failed: {type(e).__name__}"
                                      + (f": {e}" if str(e) else ""),
                          "detail": "the PDF could not be read (pdftotext did not finish); "
                                    "no blank-page verdict is possible",
                          "fix": "manual", "protected": False}]}
    if proc.returncode != 0:
        # An unreadable/missing PDF yields empty text, which parses as 0 pages
        # and 0 blank pages: reporting that as clean is a false pass on the one
        # input the check must never pass.
        detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")[:200]
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": False,
                "rows": [{"rule": "FMT-S2", "severity": "high", "document": path.name,
                          "location": "-",
                          "evidence": f"pdftotext exited {proc.returncode}"
                                      + (f": {detail}" if detail else ""),
                          "detail": "the PDF could not be read; no blank-page verdict "
                                    "is possible",
                          "fix": "manual", "protected": False}]}
    txt = proc.stdout
    res = blank_pages_in_text(txt)
    blank = res["blank_pages"]
    rows = [{"rule": "FMT-S2", "severity": "high", "document": path.name,
             "location": f"page {i}", "evidence": "page carries no body text",
             "detail": "blank page in the rendered document (header/footer only)",
             # a PDF page is re-rendered, never patched in place: `_fix_kind`
             # classes FMT-S2 as manual, and a "mechanical" label here promised
             # a repair no tool can perform on the artifact
             "fix": "manual", "protected": False}
            for i in blank if len(blank) > policy["blank_page_tolerance"]]
    # The artifact checks (FMT-PDF1..3) run on the SAME extraction: a form shell
    # has one non-blank page and would otherwise pass as clean.
    rows.extend(pdf_artifact_rows(path, text=txt, pages=res["pages"]))
    return {"file": str(path), "pages": res["pages"], "blank_pages": blank,
            "furniture": res["furniture"][:5], "rows": rows,
            "ok": not rows}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _missing_paths(paths) -> list:
    """The paths the CALLER named that do not exist.

    `scan_paths`/`validate_paths` skip an absent path silently, which is right
    inside a directory walk but wrong for a path the operator typed: a typo
    printed "OOXML formatting: clean" / "validation: 0 file(s), 0 failure(s)"
    with exit 0, i.e. a check that read nothing reported a clean result
    (AGENTS.md: a skipped integrity check is reported as skipped).
    """
    return [str(p) for p in paths if not Path(p).exists()]



# =====================================================================
# LAYOUT INTEGRITY (rules FMT-TB4, FMT-TB5, FMT-S10, FMT-IM4, FMT-IM5,
# FMT-T6h) -- the classes a text-only scan cannot see and a renderer
# resolves differently from Word.
#
# * FMT-TB4: `w:tblGrid` disagrees with the cells' `w:tcW`. Word lays a
#   table out from the cell widths when they are present; LibreOffice (and
#   several PDF converters) use the grid. A package edited on one side
#   only therefore renders one way in Word and another in production. The
#   repair rewrites the grid from the cells (the cells carry the content
#   and sum to the table width).
# * FMT-TB5: an identifier token (a dataset/accession id) cannot fit its
#   column at the cell font size, so it breaks mid-token. The repair takes
#   the deficit from the widest slacker column.
# * FMT-S10: a referenced header/footer part carries more than one PAGE
#   field, so an even page can print two page numbers (or a stale one).
#   The repair keeps the first field-only paragraph and deletes the rest.
# * FMT-IM4: a raster image is placed at a width that yields fewer than
#   `policy["min_image_dpi"]` dpi (advisory by default; the venue profile
#   may set the number it actually states).
# * FMT-IM5: a figure's own label spells a manuscript term differently
#   ("PRIME_BARank" vs "PRIME_BArank", "Hetero clitic" vs
#   "Heteroclitic", "FastQ" vs "FASTQ"). OCR the submitted raster and
#   compare against the manuscript's own vocabulary; no OCR engine is a
#   recorded gap, never a silent pass.
# * FMT-T6h: inside a bibliography entry, a bold run covers a year or a
#   page range. The house style bolds the volume only; a field result that
#   bolds more is a rendered-field defect (the cnb ref 15 shape).
# --------------------------------------------------------------------------

# A token the table must NOT break inside. Three shapes the round-2 CNB/neohet
# packages shipped as broken cells:
#   * dataset/accession ids (`D01M07AA0`, `SRR28357490`) -- the original rule;
#   * allele names (`HLA-A*02:01`, `H2-K^b^`, `H-2Db`) -- the MHC column of the
#     neohet Table 3 printed `HLA-` / `A*02:01`;
#   * hyphenated compound labels that read as one term (`MHC-anchor`,
#     `TCR-facing`) -- the same table printed `MHC-` / `anchor` and
#     `TCR-` / `facing`.
# `*`, `^`, `:` and `.` are part of an identifier; whitespace is the only
# separator the width test needs.
TABLE_IDENTIFIER_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*\d[A-Z0-9]*"            # D01M07AA0
    r"|HLA-[A-Z]\*?\d{2}:\d{2}"                               # HLA-A*02:01
    r"|H2-[A-Za-z0-9^]+"                                      # H2-K^b^
    r"|H-2[A-Za-z0-9^]+"                                      # H-2Db
    # Structural table labels, not every hyphenated adjective: `PWM-derived`
    # may break at its hyphen, while `MHC-anchor`/`TCR-facing` are the cell
    # values that read as one term.
    r"|(?:MHC|TCR|HLA|H2|H-2|CNV|CN|DNA|RNA|scWGS|scRNA|FISH|PCR)"
    r"-(?:anchor|facing|specific|derived|based|positive|negative|like|dependent)"
    r")$")
TABLE_TOKEN_FALLBACK_PT = 10.0
TABLE_CHAR_WIDTH_EM = 0.55          # conservative advance for a serif face
TABLE_MIN_SLACK_TWIPS = 500         # never shrink a column below this slack
# A PAGE field is serialized in one of two shapes: the long `w:fldChar`/
# `w:instrText` form, or a single `w:fldSimple w:instr=" PAGE ..."` element
# (the shape this module's own `_SIMPLE_PAGE_FOOTER` emits). Both are PAGE
# fields to Word, so both count here.
PAGE_FIELD_INSTR_RE = re.compile(
    r"<w:instrText[^>]*>\s*PAGE\b"
    r"|<w:fldSimple\b[^>]*\bw:instr\s*=\s*[\"']\s*PAGE\b", re.I)
RASTER_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|bmp|tiff?)$", re.I)
BIB_SKIP_FIELD_RE = re.compile(
    r"(?is)\b(?:abstract|keywords?|annote|file|urldate|doi|issn|eprint)\s*=\s*\{.*?\}\s*,?")


def _token_width_twips(token: str, font_pt: float) -> int:
    """Conservative rendered width of one unbreakable token, in twips."""
    return int(len(token) * font_pt * TABLE_CHAR_WIDTH_EM * 20)


def _cell_font_pt(styles: dict, cell: str) -> float:
    """The largest run size in a cell, else its paragraph style's, else 10 pt."""
    sizes = [int(x) / 2.0 for x in re.findall(r'<w:sz[^>]*w:val="(\d+)"', cell)]
    if sizes:
        return max(sizes)
    st = re.search(r'<w:pStyle[^>]*w:val="([^"]+)"', cell)
    if st:
        sz = style_sz(styles, st.group(1))
        if sz:
            try:
                return int(sz) / 2.0
            except ValueError:
                pass
    return TABLE_TOKEN_FALLBACK_PT


def _table_grid_widths(tbl: str) -> list:
    grid = re.search(r"<w:tblGrid(?=[\s/>]).*?</w:tblGrid>", tbl, re.S)
    if not grid:
        return []
    return [int(x) for x in re.findall(r'<w:gridCol[^>]*w:w="(\d+)"', grid.group(0))]


def _table_cell_widths(row: str) -> list:
    """[(tcW | None, gridSpan), ...] for one table row, in column order.

    Only a `dxa` width is a number of twips. `pct` says percent and `auto`
    says "let Word decide"; treating either as twips made a 50% column read as
    2500 twips and a 4500-twip table get rewritten to 2500. A non-dxa cell
    yields None, which makes the caller skip the table rather than "repair" it
    from a number that measures something else.
    """
    out = []
    for _s, _e, cell in _spans(row, CELL_TOKENS):
        tcpr = re.search(r"<w:tcPr(?=[\s/>]).*?</w:tcPr>", cell, re.S)
        width, span = None, 1
        if tcpr:
            body = tcpr.group(0)
            m = re.search(r"<w:tcW(?=[\s/>])[^>]*>", body)
            if m:
                kind = (attr_of(m.group(0), "w:type") or "dxa").lower()
                raw = attr_of(m.group(0), "w:w")
                if kind == "dxa" and raw is not None:
                    try:
                        width = int(raw)
                    except ValueError:
                        width = None
            gs = re.search(r'<w:gridSpan[^>]*w:val="(\d+)"', body)
            span = int(gs.group(1)) if gs else 1
        out.append((width, span))
    return out


def _table_cell_margins(tbl: str) -> tuple:
    m = re.search(r"<w:tblCellMar(?=[\s/>]).*?</w:tblCellMar>", tbl, re.S)
    if not m:
        return (108, 108)
    left = re.search(r'<w:left[^>]*w:w="(\d+)"', m.group(0))
    right = re.search(r'<w:right[^>]*w:w="(\d+)"', m.group(0))
    return (int(left.group(1)) if left else 108,
            int(right.group(1)) if right else 108)


def table_layout_rows(xml: str, styles: dict, doc: str, policy: dict = None) -> list:
    """FMT-TB4 (grid vs cells) and FMT-TB5 (an identifier cannot fit)."""
    rows = []
    for ti, (s, e) in enumerate(_table_spans(xml or "")):
        tbl = xml[s:e]
        # A nested table inside a cell makes the flat row/cell spans
        # ambiguous; skip it (the visual check owns that shape).
        if len(re.findall(r"<w:tbl(?=[\s>])", tbl)) > 1:
            continue
        grid = _table_grid_widths(tbl)
        trs = _spans(tbl, ROW_TOKENS)
        if not grid or not trs:
            continue
        first = _table_cell_widths(trs[0][2])
        if len(first) != len(grid) or any(w is None for w, _sp in first):
            continue
        # A merged cell (gridSpan) means the column geometry is not a simple
        # grid; a mechanical width rewrite could misalign it. Report nothing
        # this tool cannot repair -- the visual check owns that table.
        if any(sp != 1 for tr in trs for _w, sp in _table_cell_widths(tr[2])):
            continue
        cells = [w for w, _sp in first]
        header = " ".join(table_first_row_cells(tbl))[:60]
        left, right = _table_cell_margins(tbl)
        if cells != grid:
            rows.append({
                "rule": "FMT-TB4", "severity": "medium", "document": doc,
                "location": f"table {ti + 1} ({header})",
                "evidence": (f"w:tblGrid = {grid}, but the header row's cells carry "
                             f"w:tcW = {cells}; the two disagree about the column widths"),
                "detail": ("Word lays the table out from the cells when w:tcW is present "
                           "and LibreOffice from the grid, so the same package renders "
                           "differently in Word and in a PDF converter (a column can break "
                           "an identifier mid-token in one and not the other). Rewrite "
                           "w:tblGrid from the cells, or edit both together"),
                "fix": "mechanical", "protected": False, "tier": tier_of("FMT-TB4"),
                "_table": ti, "_grid": grid, "_cells": cells})
        widths = [min(g, c) for g, c in zip(grid, cells)]
        widest = {}
        for ci in range(len(grid)):
            toks, pt = [], TABLE_TOKEN_FALLBACK_PT
            for tr in trs:
                cs = _table_cell_widths(tr[2])
                if ci >= len(cs) or cs[ci][1] != 1:
                    continue
                cell = _spans(tr[2], CELL_TOKENS)[ci][2]
                toks += [t for t in re.split(r"\s+", " ".join(text_of(cell).split()))
                         if TABLE_IDENTIFIER_RE.match(t)]
                pt = max(pt, _cell_font_pt(styles, cell))
            if not toks:
                continue
            longest = max(set(toks), key=lambda t: (len(t), t))
            need = _token_width_twips(longest, pt) + left + right
            widest[ci] = need
            if need > widths[ci]:
                rows.append({
                    "rule": "FMT-TB5", "severity": "medium", "document": doc,
                    "location": f"table {ti + 1} ({header}) column {ci + 1}",
                    "evidence": (f"the identifier {longest!r} needs about {need} twips at "
                                 f"{pt:g} pt but the column is {widths[ci]} twips wide "
                                 f"(usable {widths[ci] - left - right}); it will break "
                                 f"mid-token"),
                    "detail": ("an identifier may not wrap inside itself: widen the column "
                               "or narrow the longest label; a broken id cannot be copied or "
                               "matched to Table/Figure call-outs"),
                    "fix": "mechanical", "protected": False, "tier": tier_of("FMT-TB5"),
                    "_table": ti, "_col": ci, "_need": need, "_grid": grid,
                    "_cells": cells, "_widths": widths})
    return rows


def table_layout_fixes(xml: str, rows: list) -> list:
    """(start, end, new_table) edits for FMT-TB4/FMT-TB5, text untouched.

    Every splice is computed against the ORIGINAL table string and applied
    back-to-front: a grid replacement changes the string length, so editing the
    already-replaced table at original row offsets would corrupt it.
    """
    by_table = {}
    for r in rows:
        if r.get("rule") in ("FMT-TB4", "FMT-TB5") and "_table" in r:
            by_table.setdefault(r["_table"], []).append(r)
    edits = []
    spans = _table_spans(xml or "")
    for ti, rs in sorted(by_table.items()):
        if ti >= len(spans):
            continue
        s, e = spans[ti]
        tbl = xml[s:e]
        if len(re.findall(r"<w:tbl(?=[\s>])", tbl)) > 1:
            continue
        grid = _table_grid_widths(tbl)
        trs = _spans(tbl, ROW_TOKENS)
        if not grid or not trs:
            continue
        first = _table_cell_widths(trs[0][2])
        if len(first) != len(grid) or any(w is None for w, _sp in first):
            continue
        if any(sp != 1 for tr in trs for _w, sp in _table_cell_widths(tr[2])):
            continue
        widths = [w for w, _sp in first]
        for r in rs:
            if r.get("rule") != "FMT-TB5":
                continue
            ci, need = r.get("_col"), r.get("_need")
            if ci is None or need is None or need <= widths[ci]:
                continue
            deficit = need - widths[ci]
            slack = [(widths[k] - TABLE_MIN_SLACK_TWIPS, k)
                     for k in range(len(widths)) if k != ci and widths[k] > 800]
            if not slack or max(slack)[0] < deficit:
                continue
            _give, donor = max(slack)
            widths[ci] += deficit
            widths[donor] -= deficit
        if widths == grid:
            # No TB5 need could be met (and no TB4 mismatch), so rebuilding an
            # identical grid would only log a repair that changed nothing.
            continue
        edits_in_tbl = []
        gm = re.search(r"<w:tblGrid(?=[\s/>]).*?</w:tblGrid>", tbl, re.S)
        if gm:
            edits_in_tbl.append((gm.start(), gm.end(),
                                 "<w:tblGrid>" + "".join(
                                     f'<w:gridCol w:w="{w}"/>' for w in widths)
                                 + "</w:tblGrid>"))
        for ri, (r0, r1, row) in enumerate(trs):
            cs = _table_cell_widths(row)
            if len(cs) != len(widths) or any(sp != 1 for _w, sp in cs):
                continue
            cells = _spans(row, CELL_TOKENS)
            for ci, (_w, _sp) in enumerate(cs):
                if ci >= len(cells):
                    break
                cell = cells[ci][2]
                m = re.search(r'<w:tcW[^>]*w:w="(\d+)"', cell)
                if not m:
                    continue
                abs_start = r0 + cells[ci][0] + m.start(1)
                abs_end = r0 + cells[ci][0] + m.end(1)
                edits_in_tbl.append((abs_start, abs_end, str(widths[ci])))
        if edits_in_tbl:
            edits.append((s, e, apply_edits(tbl, edits_in_tbl)))
    return edits


def referenced_header_footer_parts(parts: dict, document_xml: str) -> set:
    """{part name} of the header/footer parts the document actually references.

    `analyse_package` deliberately ignores orphan numbered parts (`footer2.xml`
    a template carries but Word never prints). The fixer and its verification
    must use the same set: repairing or failing on an orphan part made a
    scan-clean document's `fix` return `ok: false`.
    """
    rels_name = "word/_rels/document.xml.rels"
    if rels_name not in parts:
        return set()
    rels_xml = parts[rels_name].decode("utf-8", "replace") \
        if isinstance(parts[rels_name], bytes) else str(parts[rels_name])
    targets = {}
    for m in re.finditer(r"<Relationship(?=[\s/>])[^>]*/>", rels_xml):
        attrs = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', m.group(0)))
        typ = attrs.get("Type", "")
        if attrs.get("Id") and (typ.endswith("/header") or typ.endswith("/footer")):
            target = attrs.get("Target", "").lstrip("/").replace("\\", "/")
            targets[attrs["Id"]] = (target if target.startswith("word/")
                                    else "word/" + target)
    ref_ids = re.findall(r'<w:(?:header|footer)Reference[^>]*r:id="([^"]+)"',
                         document_xml or "")
    return {targets[rid] for rid in ref_ids if rid in targets}


def page_field_rows(aux_parts: list, doc: str) -> list:
    """FMT-S10: a referenced header/footer part carries more than one PAGE field."""
    rows = []
    for name, xml in aux_parts:
        n = len(PAGE_FIELD_INSTR_RE.findall(xml or ""))
        if n <= 1:
            continue
        boxed = 0
        for m in re.finditer(r"<w:txbxContent(?=[\s/>]).*?</w:txbxContent>", xml or "", re.S):
            boxed += len(PAGE_FIELD_INSTR_RE.findall(m.group(0)))
        where = (f"; {boxed} of them sit in a floating text box" if boxed else "")
        rows.append({
            "rule": "FMT-S10", "severity": "medium", "document": doc,
            "location": f"{name}",
            "evidence": f"{n} PAGE fields in one referenced header/footer part{where}",
            "detail": ("two page-number fields print two numbers (or one stale cached "
                       "value) on a page; keep exactly one PAGE field per part"
                       + (". A field inside a floating text box cannot be removed by "
                          "paragraph surgery: delete that text box (or its field) in "
                          "Word, or accept the single remaining field" if boxed else "")),
            "fix": "manual" if boxed else "mechanical",
            "protected": False, "tier": tier_of("FMT-S10"),
            "_part": name})
    return rows


def page_field_fixes(part_xml: str) -> list:
    """Delete the field-only paragraphs after the first PAGE paragraph."""
    if "<w:txbxContent" in (part_xml or ""):
        # A nested paragraph inside a text box breaks the flat paragraph-span
        # model; deleting a span could remove the whole floating box or half of
        # it. Leave this shape to the author (the scan still reports it).
        return []
    spans = [(s, e) for s, e, _frag in _spans(part_xml or "", PARA_TOKENS)
             if PAGE_FIELD_INSTR_RE.search(part_xml[s:e])]
    if len(spans) <= 1:
        return []
    edits = []
    for s, e in spans[1:]:
        para = part_xml[s:e]
        # Only a paragraph whose VISIBLE text is the page number (the field's
        # cached result) may be removed; a page number sharing a paragraph with
        # other furniture needs the author.
        visible = text_of(para).strip()
        if visible and not re.fullmatch(r"[\d\s]+", visible):
            continue
        edits.append((s, e, ""))
    return edits


BIB_PROSE_FIELDS = ("title", "journaltitle", "booktitle", "maintitle", "subtitle",
                    "shorttitle", "note", "series", "publisher", "school", "institution",
                    "eventtitle")


def bib_prose_paragraphs(text: str) -> list:
    """The PROSE fields of a .bib file, without abstracts/keywords/authors/DOIs.

    The text scan read `abstract = {...}` fields as manuscript prose and filed
    44 long-sentence rows on the CNB `.bib` (each closed by hand). Author lists
    are data too: a 40-name `author = {...}` is not a long sentence. Only the
    fields that carry a printed title/venue/note are returned, one paragraph per
    field; a value with nested braces is skipped rather than mis-parsed.
    """
    out = []
    saw_field = False
    pat = re.compile(r"(?is)\b(" + "|".join(BIB_PROSE_FIELDS) + r")\s*=\s*\{(.*?)\}\s*,?")
    for m in pat.finditer(text or ""):
        saw_field = True
        raw_value = m.group(2)
        if "{" in raw_value:
            # The non-greedy pattern stops at the first `}`, so a nested-brace
            # value (`title = {Growth was {100} percent...}`) would be returned
            # TRUNCATED. The docstring's contract is to skip it, not mis-parse.
            continue
        value = re.sub(r"\s+", " ", re.sub(r"[{}]", "", raw_value)).strip()
        if value:
            out.append(value)
    if out:
        return out
    if saw_field:
        # Recognised fields WERE present; only nested/empty values were skipped.
        # Falling back to the whole-text scan would re-introduce the truncated
        # nested value the loop just refused.
        return []
    # No recognised field: fall back to the old cleaning rather than silently
    # scanning nothing (a class the file does carry must not disappear).
    cleaned = BIB_SKIP_FIELD_RE.sub(" ", text or "")
    cleaned = re.sub(r"[{}@]", " ", cleaned)
    return [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]


def _ocr_text(path: Path, psm: str = "3") -> str | None:
    if not shutil.which("tesseract"):
        return None
    try:
        proc = subprocess.run(["tesseract", str(path), "-", "--psm", str(psm)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else ""


def _ocr_text_variants(path: Path) -> list | None:
    """OCR the delivered raster normally and, when ImageMagick is available,
    once more on an inverted/thresholded copy.

    The neohet Figure 1 insets print black type on a dark purple/red disc. The
    normal pass reads the top 'Heteroclitic' and `FastQ` but not the inset
    `Hetero`/`clitic`; a negated grayscale copy reads both. A missing
    `convert` is a recorded gap only for that second pass, never a silent pass
    (the normal pass still runs). None means tesseract itself is missing.
    """
    base = _ocr_text(path)
    if base is None:
        return None
    out = [base]
    if shutil.which("convert"):
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            proc = subprocess.run(
                ["convert", str(path), "-colorspace", "Gray", "-negate",
                 "-threshold", "55%", tmp.name],
                capture_output=True, timeout=120)
            if proc.returncode == 0:
                # psm 6 (uniform block) reads the inset labels that the
                # default page-segmentation pass drops; psm 3 on the normal
                # copy keeps the top-line terms and the acronym spellings.
                for psm in ("6", "11"):
                    inv = _ocr_text(Path(tmp.name), psm=psm)
                    if inv:
                        out.append(inv)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if tmp is not None:
                try:
                    Path(tmp.name).unlink()
                except OSError:
                    pass
    return out


def vocabulary_terms(texts: list, min_count: int = 2) -> list:
    """Capitalised terms the manuscript itself uses at least `min_count` times."""
    counts = Counter()
    for text in texts or []:
        for w in re.findall(r"\b[A-Za-z][A-Za-z0-9_]{3,}\b", text or ""):
            if not any(ch.isupper() for ch in w):
                continue
            if w.lower() in {"this", "that", "these", "those", "with", "from", "table",
                             "figure", "supplementary", "results", "methods", "discussion"}:
                continue
            counts[w] += 1
    return [w for w, n in counts.items() if n >= min_count]


def figure_label_rows(paths: list, terms: list) -> list:
    """FMT-IM5: a figure's OCR text spells a manuscript term differently."""
    rows = []
    # Manuscript terms are only one source of truth. A standard acronym the
    # manuscript happens not to use (the neohet main text never writes "FASTQ")
    # still has one correct spelling, and a figure that prints "FastQ" is a
    # typographic defect even when no manuscript occurrence exists to compare
    # with. Keep the canonical set small and unambiguous.
    canonical = ("FASTQ", "TCR", "MHC", "pMHC", "HLA", "ROC", "AUPRC", "CNV")
    terms = [t for t in dict.fromkeys(
        [t for t in terms or () if t and len(t) >= 3] + list(canonical))
        if len(t) >= 3]
    if not shutil.which("tesseract"):
        return [{"rule": "FMT-IM5", "severity": "low", "document": "-",
                 "location": "figures", "evidence": "tesseract is not installed",
                 "detail": ("figure-label OCR is a categorical gap in this environment: the "
                            "class (artwork label spelling vs the manuscript's terms) was "
                            "NOT examined for these files"),
                 "fix": "manual", "protected": False, "tier": tier_of("FMT-IM5")}]
    def split_form(term: str, text: str) -> bool:
        """True when the term's two halves appear as SEPARATE words.

        The original pattern only allowed whitespace/hyphens BETWEEN the two
        halves. In the delivered neohet artwork the inset labels are split over
        two lines with other OCR words between them ("Hetero" on one line,
        "clitic" several tokens later), so that pattern never matched. This
        version looks for the prefix as a whole word and the suffix as a whole
        word on the same or a nearby line; an intact `Heteroclitic` has no word
        boundary after `Hetero`, so it never matches.
        """
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            return False
        for i in range(3, max(4, len(term) - 2)):
            a, b = term[:i], term[i:]
            if len(a) < 3 or len(b) < 3:
                continue
            for j, line in enumerate(lines):
                if not re.search(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])",
                                 line, re.I):
                    continue
                for k in range(j, min(len(lines), j + 8)):
                    if re.search(r"(?<![A-Za-z])" + re.escape(b) + r"(?![A-Za-z])",
                                 lines[k], re.I):
                        if k > j or re.search(r"\s", line):
                            return True
        return False

    def case_variant(term: str, text: str) -> bool:
        """True when a token matches `term` case-insensitively but NOT exactly.

        The old test was `re.search(term, text, re.I) is not None`, so ANY
        occurrence -- including the exact spelling -- counted as a case variant.
        That both fired on clean figures and, worse, was masked by the caller's
        `if term in text: continue`: one intact occurrence hid every split or
        mis-cased occurrence of the same term in the artwork.
        """
        distinctive = ("_" in term or any(ch.isdigit() for ch in term)
                       or (term.isupper() and 2 <= len(term) <= 8))
        if not distinctive:
            return False
        for m in re.finditer(r"(?<![A-Za-z0-9_])" + re.escape(term)
                             + r"(?![A-Za-z0-9_])", text or "", re.I):
            if m.group(0) != term:
                return True
        return False

    if not shutil.which("convert"):
        rows.append({
            "rule": "FMT-IM5", "severity": "low", "document": "-",
            "location": "figures",
            "evidence": "ImageMagick `convert` is not installed",
            "detail": ("the inverted/thresholded OCR pass was skipped: a split label "
                       "printed black-on-dark (the neohet inset case) may not be read; "
                       "install ImageMagick or inspect the artwork visually"),
            "fix": "manual", "protected": False, "tier": "advisory"})
    for p in paths:
        texts = _ocr_text_variants(Path(p))
        if texts is None:
            continue
        seen = set()
        for term in terms:
            # The split/case checks must run even when an intact occurrence of
            # the same term exists elsewhere in the figure: `Heteroclitic` at
            # the top of the neohet artwork did not make the split
            # `Hetero`/`clitic` in the inset any less broken.
            for text in texts:
                # A short term split into two common words ("Het" + "Mut") is
                # usually an OCR line-wrap artifact in a legend, not a broken
                # label; the long manuscript terms are the class this rule owns.
                split = len(term) >= 10 and split_form(term, text)
                case = case_variant(term, text)
                if not split and not case:
                    continue
                why = ("the term is split across a line/space" if split
                       else "the term's letter case differs")
                key = (term, why)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "rule": "FMT-IM5", "severity": "medium", "document": Path(p).name,
                    "location": "artwork text",
                    "evidence": (f"the figure prints a variant of {term!r}: {why}"
                                 + (" (an intact occurrence elsewhere does not repair "
                                    "the split one)" if split else "")),
                    "detail": ("a figure's own label must spell the manuscript's term "
                               "exactly; regenerate the artwork (OCR reads the delivered "
                               "raster, so this is what a reader sees)"),
                    "fix": "manual", "protected": False, "tier": tier_of("FMT-IM5")})
    return rows


# "shipped" is a delivery claim in any form; "deposited" only as a VERB ("the
# data were deposited"), because "the deposited code" is a normal adjective for
# code that lives in a repository the Data Availability statement locates.
AVAILABILITY_CLAIM_RE = re.compile(
    r"\bshipped\b|\b(?:was|were|is|are|has been|have been)\s+deposited\b", re.I)
AVAILABILITY_LOCATOR_RE = re.compile(
    r"https?://|doi:\s*10\.|\b10\.\d{4,9}/", re.I)
AVAILABILITY_FILE_RE = re.compile(
    r"\b[\w./-]+\.(?:tsv|csv|zip|pdf|docx|tex|bib|py|r|txt|json|xlsx?)\b", re.I)


def availability_claim_rows(para_texts: list, doc: str) -> list:
    """FMT-AV3: a claim that material was shipped/deposited, with no locator.

    The neohet supplement said its tables were "computed from the shipped
    per-candidate tables" while the Data Availability Statement said the tables
    were not in the repository; the submission carried neither. A reader cannot
    resolve "shipped" without a URL, DOI, accession or a file the submission
    carries. A sentence that names a real locator, a filename, or the
    corresponding-author route is accepted.
    """
    rows = []
    for idx, text in enumerate(para_texts or []):
        for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
            if not AVAILABILITY_CLAIM_RE.search(sentence):
                continue
            if len(sentence.split()) < 6:
                continue                      # a heading/group label ("Deposited data")
            if re.search(r"\bshipped\s+with\b", sentence, re.I):
                continue                      # "shipped with the tool" is a distribution fact
            if "from the corresponding author" in sentence.lower():
                continue
            if AVAILABILITY_LOCATOR_RE.search(sentence):
                continue
            if AVAILABILITY_FILE_RE.search(sentence):
                continue
            rows.append({
                "rule": "FMT-AV3", "severity": "medium", "document": doc,
                "location": f"p{idx}",
                "evidence": " ".join(sentence.split())[:160],
                "detail": ("the sentence claims material was shipped/deposited but names no "
                           "URL, DOI, accession, submitted file or corresponding-author route; "
                           "a reader cannot resolve it. Name the locator the submission "
                           "carries, or say the material is available from the authors"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-AV3")})
    return rows


def reference_bold_rows(xml: str, styles: dict, doc: str) -> list:
    """FMT-T6h: a bibliography bold run covers a year or a page range."""
    rows = []
    for idx, (_p0, _p1, para) in enumerate(paragraphs(xml or "")):
        if elem_val(ppr_of(para), "pStyle") != "Bibliography":
            continue
        for r in runs(para):
            text = text_of(r[2]).strip()
            if not text or not run_is_bold(styles, "Bibliography", r[2]):
                continue
            if re.search(r"\(\d{4}[a-z]?\)", text) or re.search(r"\d+\s*[-\u2013]\s*\d+", text):
                rows.append({
                    "rule": "FMT-T6h", "severity": "medium", "document": doc,
                    "location": f"p{idx}",
                    "evidence": f"bold run over a year/page range: {text[:60]!r}",
                    "detail": ("the house style bolds the volume only; a field result that "
                               "bolds the year or the page range is a rendered-bibliography "
                               "defect (fix the CSL/field, then refresh; a submission copy "
                               "may be unlinked and repaired)"),
                    "fix": "style-field", "protected": True, "tier": tier_of("FMT-T6h")})
    return rows


# ---------------------------------------------------------------------------
# CROSS-SURFACE CLAIMS AND ARGUMENT-LEVEL LOGIC (2026-10-19)
#
# The round-2 winners passed every sentence-local rule while shipping claims
# that contradict another paragraph or another submitted document:
#   * neohet: "every parental antigen is ... a held-out antigen" vs the same
#     Methods' "the parental peptides themselves were not screened";
#   * neohet: the supplement's "shipped per-candidate tables" vs Data
#     Availability's "not part of that repository";
#   * CNB: the Reporting Summary's "no overlap" vs Methods' overlapping
#     threshold selection; "no manual scoring" vs the descriptive HG008 read;
#   * CNB: "the near-invariance described above" with no such description, and
#     "negligible" residual aneuploidy vs "does not establish ... negligible".
# These functions enumerate the PAIR, not a verdict: a session must reconcile
# the two quotes, and the audit can drop the pair with evidence.
# ---------------------------------------------------------------------------

_CLAIM_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT = re.compile(r"[.;:!?]")
# `n't` needs no leading word boundary (the "n" follows a letter in "isn't");
# with `\b(?:...|n't)\b` the contraction branch could never match at all.
_NEGATION_RE = re.compile(
    r"\b(?:not|no|none|never|without|neither|nor|cannot)\b"
    r"|n['\u2019]t\b", re.I)


def _claim_sentences(text: str) -> list:
    return [s.strip() for s in _CLAIM_SENT_SPLIT.split(text or "") if s.strip()]


def _affirmative_at(sentence: str, start: int) -> bool:
    """True when the sentence/clause before `start` carries no negation.

    The claim/logic regexes describe positive shapes ("shipped ...",
    "tests whether ..."), but a negative sentence contains the same words:
    "We have not shipped the per-candidate tables" matched the positive
    `shipped` pattern and paired with its own negation as a contradiction.
    A negation in the SAME sentence or clause (before `;`/`:` or a sentence
    boundary) means the predicate is not affirmative, so the positive-shape
    pattern must not fire. The sentence boundary matters for the paragraph-level
    `_EXPECT_IMPLIES_RE`: a negation in an EARLIER sentence must not suppress a
    later affirmative one.
    """
    prefix = _CLAUSE_SPLIT.split(sentence[:start])[-1]
    return not _NEGATION_RE.search(prefix)


def _claim_find(docs: list, pattern: str) -> list:
    """[(doc, sentence)] for every AFFIRMATIVE sentence matching `pattern`."""
    hits = []
    rx = re.compile(pattern, re.I)
    for name, text in docs or ():
        for sentence in _claim_sentences(text):
            m = rx.search(sentence)
            if m and _affirmative_at(sentence, m.start()):
                hits.append((name, sentence))
    return hits


def claim_contradiction_rows(docs: list) -> list:
    """J6/FMT-AV4: opposite claims on two surfaces (or two paragraphs).

    `docs` is [(document_name, full_text)].  Only pairs whose SUBJECT is the
    same are reported: a positive pattern and its negation are matched
    independently, and a row carries both sentences and both documents.  The
    function is deliberately narrow -- every pattern below is a claim shape
    that actually shipped -- so it does not turn ordinary hedging into a
    contradiction.
    """
    rows = []
    docs = [(str(n), str(t)) for n, t in (docs or ()) if t]

    def add(rule, pos_name, pos_pat, neg_name, neg_pat, detail):
        pos = _claim_find(docs, pos_pat)
        neg = _claim_find(docs, neg_pat)
        if not pos or not neg:
            return
        a_name, a_sent = pos[0]
        b_name, b_sent = neg[0]
        # The same sentence is not a pair (a sentence can quote both sides).
        if a_name == b_name and a_sent == b_sent:
            return
        rows.append({
            "rule": rule, "severity": "high" if rule in ("J6-CONTRADICTION", "FMT-AV4")
            else "medium", "document": f"{a_name} + {b_name}",
            "location": "cross-surface claim",
            "evidence": f"A: {a_sent[:220]!r} || B: {b_sent[:220]!r}",
            "detail": detail,
            "fix": "manual", "protected": False, "tier": tier_of(rule)})

    add("J6-CONTRADICTION",
        "held-out", r"\b(?:every|all|the)\s+parental\s+antigens?\b[^.]{0,80}\bheld[-\s]?out\b",
        "not-screened", r"\bparental\s+peptides?\b[^.]{0,100}\bnot\s+screened\b"
        r"|\bnot\s+screened\b[^.]{0,100}\bparental\b",
        ("the paper says the parents are held-out and also that the parents were not "
         "screened against the training pool. A held-out claim needs a parent-overlap "
         "check; if there is none, use the structural within-parent argument instead"))
    add("FMT-AV4",
        "shipped", r"\bshipped\b[^.]{0,60}\b(?:per-candidate|benchmark|tables?|data|results?)\b",
        "not-in-repo", r"\bnot\s+part\s+of\b[^.]{0,80}\b(?:repository|resource)\b"
        r"|\bavailable\s+from\s+the\s+corresponding\s+author\b",
        ("a submitted surface says the material was shipped while another says it is not "
         "in the repository/only available from the authors. Use ONE route: the shipped "
         "file, a public locator, or the corresponding-author sentence, never two"))
    add("J6-CONTRADICTION",
        "no-overlap", r"\bno\s+overlap\s+between\b",
        "overlap-eval", r"\boverlap(?:s|ped|ping)?\s+the\s+evaluation\s+set\b",
        ("the Reporting Summary says parameter selection and evaluation do not overlap, "
         "while the Methods say the selection data are among the evaluated datasets. "
         "Either disclose the overlap in both places or rerun held out"))
    add("J6-CONTRADICTION",
        "no-manual", r"\bno\s+manual\s+scoring\b|\bno\s+manual\s+scoring\s+or\s+subjective\b",
        "manual-read", r"\bqualitative\s+reading\b|\bdescriptive\s+visual\s+reading\b"
        r"|\bvisual\s+reading\b|\bdescriptive\s+comparison\b",
        ("the form says there was no manual scoring/subjective assessment, while the "
         "manuscript describes a descriptive visual reading. Disclose the manual read "
         "or replace it with a pre-specified statistic"))
    add("J6-CONTRADICTION",
        "negligible", r"\bare\s+negligible\s+relative\s+to\b",
        "not-negligible", r"\bnot\s+establish\s+that\b[^.]{0,80}\bnegligible\b",
        ("the design premise calls residual aneuploidy/CNP negligible while the Results "
         "say the data do not establish that it is. Qualify the premise or report the "
         "correction as a limitation"))
    add("FMT-T9A",
        "near-invariance", r"\bnear-invariance\s+described\s+above\b",
        "variability", r"\bmetric-?\s+and\s+caller-specific\b|\bvariability\b",
        ("'the near-invariance described above' has no antecedent: the surrounding result "
         "describes metric- and caller-specific variability. Name the actual result or "
         "delete the phrase"))
    return rows


_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_COUNT_CLAIM_RE = re.compile(
    r"\bthe\s+(two|three|four|five|six|seven|eight|nine|ten)\s+([a-z][a-z-]{2,})\s+are\b",
    re.I)
_METRIC_ID_RE = re.compile(
    r"\b(?:intCN_[A-Za-z_]+|nonintCN_[A-Za-z_]+|CN_[A-Za-z_]+|breakpoint_[A-Za-z_]+)\b")


def count_claim_rows(paras: list) -> list:
    """FMT-CN1: 'The six metrics are ...' but fewer than six are enumerated.

    The CNB Fig. 2 legend listed five metric ids under a 'six metrics' lead.
    The rule only fires when the sentence itself names metric ids; a count
    sentence whose items are ordinary words is left to the reviewer.
    """
    rows = []
    for text in paras or ():
        for sentence in _claim_sentences(text):
            m = _COUNT_CLAIM_RE.search(sentence)
            if not m:
                continue
            want = _NUMBER_WORDS.get(m.group(1).lower())
            ids = list(dict.fromkeys(_METRIC_ID_RE.findall(sentence)))
            if want and ids and len(ids) < want:
                rows.append({
                    "rule": "FMT-CN1", "severity": "medium", "document": "-",
                    "location": "document",
                    "evidence": (f"{m.group(0)!r} enumerates {len(ids)} metric id(s): "
                                 f"{', '.join(ids) or '(none)'}"),
                    "detail": (f"the sentence says {want} items but names {len(ids)}; "
                               "either add the missing item or correct the count"),
                    "fix": "manual", "protected": False, "tier": tier_of("FMT-CN1")})
    return rows


_LOGIC_PATTERNS = (
    (r"\btests?\s+whether\b[^.]{0,160}\bbecause\b", "FMT-T9L",
     "a test whose 'because' clause asserts the premise it is supposed to test"),
    (r"\binvert(?:ing|s|ed)?\s+the\s+downsampling\b", "FMT-T9L",
     "the method downsamples and merges; it does not invert a downsampling"),
    (r"\bwill\s+be\s+flagged\s+as\b", "FMT-T9L",
     "'flagged' by what? the benchmark scores callers; it has no flag mechanism"),
    (r"\bwhich\s+it\s+needs\b", "FMT-T9L",
     "'which' has more than one possible antecedent"),
    (r"\baccompanied\s+chiefly\s+by\b|\bchiefly\s+accompanied\s+by\b", "FMT-T9L",
     "the adverb has no clear verb to modify; say what is associated with what"),
    (r"\bapproximately\s+any\b", "FMT-T9U",
     "'approximately any' is an undefined quantifier"),
    (r"\bmetric-dependent\b", "FMT-T9U",
     "'metric-dependent' is undefined (which metric? which set?)"),
    (r"\bpurity\s+floor\b", "FMT-T9U",
     "'purity floor' is a coined term; define it or use the plain description"),
)
_LIMITATIONS_RE = re.compile(
    r"\bthis\s+study\s+has\s+the\s+following\s+limitations\b[\s\S]{0,80}\bfirst\b", re.I)
_EXPECT_IMPLIES_RE = re.compile(
    r"\b(?:we\s+)?(?:therefore\s+)?expected?\b[\s\S]{0,260}\bwhich\s+implies\b", re.I)
_THEREFORE_OPEN_RE = re.compile(r"^\s*we\s+therefore\b", re.I)
_CAUSAL_CUE_RE = re.compile(
    r"\b(?:because|since|thus|hence|so|as\s+a\s+result|therefore|accordingly)\b", re.I)


def logic_rows(paras: list, is_ref: list = None) -> list:
    """FMT-T9L/T9U: deterministic argument-level defects.

    Each row carries the sentence and a one-line explanation.  The patterns are
    the shapes that shipped in the CNB/neohet round-2 winners; they are
    questions for the reviser, not a style preference.
    """
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    for i, text in enumerate(paras or ()):
        if i < len(is_ref) and is_ref[i]:
            continue
        for pattern, rule, why in _LOGIC_PATTERNS:
            for sentence in _claim_sentences(text):
                m = re.search(pattern, sentence, re.I)
                if m and _affirmative_at(sentence, m.start()):
                    rows.append({
                        "rule": rule, "severity": "medium", "document": "-",
                        "location": f"p{i}",
                        "evidence": sentence[:220],
                        "detail": why + "; rewrite the sentence so the claim and its "
                                  "evidence are in the right order",
                        "fix": "manual", "protected": False, "tier": tier_of(rule)})
                    break
        _expect = _EXPECT_IMPLIES_RE.search(text or "")
        if _expect and _affirmative_at(text or "", _expect.start()):
            rows.append({
                "rule": "FMT-T9L", "severity": "medium", "document": "-",
                "location": f"p{i}",
                "evidence": _first_marker_sentence(
                    text or "", re.compile(r"which\s+implies", re.I)),
                "detail": ("an expectation ('we expected ...') is offered as evidence "
                           "('which implies ...'); state the observed result and its "
                           "implication separately"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-T9L")})
        if _LIMITATIONS_RE.search(text or ""):
            rows.append({
                "rule": "FMT-T9L", "severity": "low", "document": "-",
                "location": f"p{i}",
                "evidence": _first_marker_sentence(
                    text or "", re.compile(r"this\s+study\s+has\s+the\s+following", re.I)),
                "detail": ("formulaic 'the following limitations. First...' enumeration; "
                           "name the limitation in the sentence instead of counting it"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-T9L")})
        # A paragraph that opens "We therefore" needs a premise in the paragraph
        # before it; the CNB Results opened one after a publication-year remark.
        if i and _THEREFORE_OPEN_RE.match(text or ""):
            prev = paras[i - 1] if i - 1 < len(paras) else ""
            # A "We therefore ..." at a section open has no premise at all; the
            # same words mid-section usually follow an argument the previous
            # paragraph just made (the neohet "We therefore do not claim" case).
            if (len((prev or "").split()) <= 10
                    and not _CAUSAL_CUE_RE.search(prev or "")):
                rows.append({
                    "rule": "FMT-T9L", "severity": "medium", "document": "-",
                    "location": f"p{i}",
                    "evidence": (text or "").strip()[:220],
                    "detail": ("the paragraph opens with 'We therefore' but the previous "
                               "paragraph states no premise; add the premise or drop the "
                               "connective"),
                    "fix": "manual", "protected": False, "tier": tier_of("FMT-T9L")})
        # "the X described above" requires an earlier X.
        for m in re.finditer(r"\bthe\s+([a-z][a-z-]{3,})\s+described\s+above\b",
                             text or "", re.I):
            term = m.group(1)
            before = "\n".join(paras[:i]) + "\n" + (text or "")[:m.start()]
            if len(re.findall(r"\b" + re.escape(term) + r"\b", before, re.I)) <= 0:
                rows.append({
                    "rule": "FMT-T9A", "severity": "medium", "document": "-",
                    "location": f"p{i}",
                    "evidence": (text or "")[max(0, m.start() - 80):m.end() + 80],
                    "detail": (f"the phrase points at {term!r} 'described above', but that "
                               "term does not occur in the preceding text"),
                    "fix": "manual", "protected": False, "tier": tier_of("FMT-T9A")})
    return rows


_SCI_P_RE = re.compile(
    r"(?P<mant>[\d.]+)\s*(?:"
    r"(?:[×x]|\\times)\s*10\s*\^?\s*\{?\s*(?P<sign>[+−-])?\s*(?P<exp>\d+)\s*\}?"
    r"|[eE](?P<sign2>[+−-])?(?P<exp2>\d+))")
_PLAIN_P_RE = re.compile(r"^(?P<p>\d+(?:\.\d+)?)$")


def _parse_p(token: str) -> float | None:
    token = (token or "").strip()
    m = _SCI_P_RE.search(token)
    if m:
        try:
            exp = int(m.group("exp") or m.group("exp2") or 0)
            if (m.group("sign") or m.group("sign2")) in ("−", "-"):
                exp = -exp
            return float(m.group("mant")) * (10 ** exp)
        except (TypeError, ValueError):
            return None
    m = _PLAIN_P_RE.match(token)
    return float(m.group("p")) if m else None


def stats_floor_rows(paras: list) -> list:
    """FMT-ST1: a Holm-adjusted p below the floor implied by its family size.

    For a two-sided Wilcoxon signed-rank test on n pairs the smallest attainable
    p is 2/2^n; in a family of m tests the smallest Holm-adjusted p is
    m * 2/2^n.  The CNB Table S3 caption says one 19-test family, its n=9 rows
    print 0.030 (the 8-test floor) and its n=21 rows print 1.81e-5 (the 19-test
    floor): the same table uses two families.  The parser is conservative --
    it only runs when the text says "single pooled family" and at least five
    rows parse -- so it does not flag a table whose family is described
    differently.
    """
    text = "\n".join(str(p or "") for p in (paras or ()))
    if not re.search(r"single\s+pooled\s+family", text, re.I):
        return []
    if not re.search(r"Holm", text, re.I):
        return []
    rows = []
    parsed = []
    for line in text.splitlines():
        if not re.search(r"\b(?:10|none)\b", line):
            continue
        # PDF layout: Method ... 10 9 0.030 1.00 [...]
        m = re.search(
            r"\b(?P<cap>10|none)\s+(?P<n>\d{1,3})\s+"
            r"(?P<p>\d+(?:\.\d+)?(?:\s*[×x]\s*10\s*[+−-]?\s*\d+|[eE][+−-]?\d+)?)\b", line)
        if not m:
            # LaTeX: Method & 10 & 9 & \textbf{0.030} & ...
            m2 = re.search(
                r"&\s*(?P<cap>10|none)\s*&\s*(?P<n>\d{1,3})\s*&\s*"
                r"(?:\\textbf\{)?(?P<p>\d+(?:\.\d+)?(?:\s*\\times\s*10\^\{?[+−-]?\d+\}?|[eE][+−-]?\d+)?)",
                line)
            if not m2:
                continue
            m = m2
        try:
            n = int(m.group("n"))
        except (TypeError, ValueError):
            continue
        p = _parse_p(m.group("p"))
        if p is None or n < 5:
            continue
        parsed.append((n, p, line.strip()[:120]))
    if len(parsed) < 5:
        return []
    # The caption's own family size wins when it states one; otherwise the
    # rows that parsed ARE the family. Never call a fallback "stated".
    stated = re.search(r"(?i)\b(\d{1,3})[-\s]+tests?[-\s]+family\b", text)
    if stated is None:
        stated = re.search(r"(?i)\bfamily\s+of\s+(\d{1,3})\b", text)
    family = int(stated.group(1)) if stated else len(parsed)
    for n, p, line in parsed:
        floor = family * 2.0 / (2 ** n)
        # A table rounds its adjusted p (1.81e-5 vs the exact 1.812e-5); a 2%
        # relative tolerance accepts the rounded floor and still catches the
        # 0.030-vs-0.074 n=9 case.
        if p < floor - max(1e-12, floor * 0.02):
            rows.append({
                "rule": "FMT-ST1", "severity": "high", "document": "-",
                "location": "table caption/rows",
                "evidence": (f"n={n}, p={p:.3g}; the {family}-test family's "
                             f"smallest Holm p is {floor:.3g} ({line!r})"),
                "detail": ("the reported adjusted p is below the floor its own family "
                           "allows. Either the caption's family size is wrong (the n=9 "
                           "rows look like an 8-test family) or the p values were not "
                           "adjusted as stated; do not hand-edit a single p"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-ST1")})
    return rows


# Only the Materials & experimental systems FIELDS that take a Yes/No/n-a
# answer. "Methods", "Human participants" and "Reporting on sex and gender" are
# section headings whose answers are prose, not fields; treating them as fields
# produced six false rows on the first CNB run.
_RS_LABELS = (
    "antibodies", "eukaryotic cell lines", "palaeontology and archaeology",
    "animals and other organisms", "clinical data", "dual use research of concern",
    "plants", "chip-seq", "flow cytometry", "mri", "functional magnetic",
    "electrophysiology", "neurological disease",
)


def reporting_summary_gap_rows(text: str) -> list:
    """FMT-SR1: a Reporting Summary section label with no answer.

    The CNB form prints 'Eukaryotic cell lines Involved in the study' and then
    the next section, with no Yes/No/n-a. This is a required field, not a
    styling difference.
    """
    lines = [ln.strip() for ln in (text or "").splitlines()]
    rows = []
    for i, line in enumerate(lines):
        low = line.lower()
        # The field label opens the line ("Eukaryotic cell lines Involved in the
        # study"); a prose mention of "Methods" mid-sentence is not a field.
        label = next((lab for lab in _RS_LABELS if low.startswith(lab)), "")
        if not label:
            continue
        # An answer may be on the same line after the label.
        tail = low.split(label, 1)[1].strip(" :-")
        answered = bool(re.match(r"^(?:yes|no|n/?a|not applicable)\b", tail))
        if not answered:
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j < len(lines) and not any(lines[j].lower().lstrip().startswith(lab)
                                          for lab in _RS_LABELS):
                answered = bool(re.match(
                    r"^(?:yes|no|n/?a|not applicable)\b", lines[j].lower()))
        if not answered:
            rows.append({
                "rule": "FMT-SR1", "severity": "medium", "document": "-",
                "location": f"line {i + 1}",
                "evidence": line[:160] or label,
                "detail": ("a Reporting Summary section has no Yes/No/n-a answer; the form "
                           "is a submitted document and an unanswered required field is a "
                           "completeness defect. Fill the answer and re-export"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-SR1")})
    return rows


def legend_claim_rows(paras: list) -> list:
    """FMT-LG1/FMT-LG2: a legend that argues or that mixes connectives."""
    rows = []
    for text in paras or ():
        t = text or ""
        if not re.match(r"^\s*(?:Fig\.?|Figure)\s*[A-Z]?\d+", t, re.I):
            continue
        # The title of a quantitative figure may state its result; the class is
        # a DESCRIPTIVE panel whose legend argues the paper's conclusion
        # ("This pattern is consistent with Ginkgo's leading overall balance").
        if re.search(r"\bconsistent\s+with\b[^.]{0,100}\b(?:leading|best|outperform)",
                     t, re.I) and not re.search(
                r"\b(?:p\s*[<=>]|statistic|descriptive|descriptively)\b", t, re.I):
            rows.append({
                "rule": "FMT-LG1", "severity": "medium", "document": "-",
                "location": "legend",
                "evidence": t[:220],
                "detail": ("the legend asserts a comparative/conclusion claim from a "
                           "descriptive panel; report what the panel shows and keep the "
                           "ranking claim in Results, or name the statistic"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-LG1")})
        if re.search(r"from\s+top\s+to\s+bottom", t, re.I) and re.search(
                r"\b(?:below\s+them|this\s+is\s+followed\s+by|next,?)\b", t, re.I):
            rows.append({
                "rule": "FMT-LG2", "severity": "low", "document": "-",
                "location": "legend",
                "evidence": t[:220],
                "detail": ("one enumeration uses several connectives ('from top to "
                           "bottom', 'below them', 'this is followed by'); use one"),
                "fix": "manual", "protected": False, "tier": tier_of("FMT-LG2")})
    return rows


def repair_layout_package(src: Path, out: Path, policy: dict = None) -> dict:
    """Mechanical layout repair: FMT-TB4/TB5 (table widths) and FMT-S10 (PAGE fields).

    Writes `out` with only the affected XML parts changed, verifies the visible
    text of the body is unchanged, and re-scans the result. Returns a report.
    """
    src, out = Path(src), Path(out)
    policy = dict(POLICY_DEFAULTS, **(policy or {}))
    report = {"source": str(src), "output": str(out), "changes": [], "remaining": [],
              "ok": False}
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            data = {n: z.read(n) for n in names}
            styles = parse_styles(z)
    except (OSError, zipfile.BadZipFile) as exc:
        report["error"] = f"unreadable DOCX package: {exc}"
        return report
    if "word/document.xml" not in data:
        report["error"] = "no word/document.xml"
        return report

    def visible(xml_text: str) -> str:
        return "\n".join(text_of(p[2]) for p in paragraphs(xml_text))

    doc_xml = data["word/document.xml"].decode("utf-8")
    before_text = visible(doc_xml)
    rows = table_layout_rows(doc_xml, styles, src.name, policy)
    edits = table_layout_fixes(doc_xml, rows)
    if edits:
        new_doc = apply_edits(doc_xml, edits)
        if visible(new_doc) == before_text:
            data["word/document.xml"] = new_doc.encode("utf-8")
            report["changes"].append(f"rewrote the column grid of {len(edits)} table(s) "
                                     f"from their cell widths")
        else:
            report["error"] = "table repair would change visible text; refused"
            return report
    for name in names:
        if not re.match(r"word/(?:header|footer)[A-Za-z0-9_\-]*\.xml$", name):
            continue
        part = data[name].decode("utf-8")
        part_edits = page_field_fixes(part)
        if part_edits:
            data[name] = apply_edits(part, part_edits).encode("utf-8")
            report["changes"].append(f"removed {len(part_edits)} duplicate PAGE field "
                                     f"paragraph(s) from {name}")
    if not report["changes"]:
        # The command's contract is "write the repaired package to --out", so a
        # clean input still produces an output. Returning without writing one
        # made `repair-layout FILE --out OUT` print "verified: OUT" and exit 0
        # with no file there (a downstream fix/publish step then read nothing
        # or a stale file). A byte-for-byte copy preserves the no-change proof.
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, out)
        except OSError as exc:
            report["error"] = f"could not write the repaired copy: {exc}"
            return report
        report["ok"] = True
        report["remaining"] = rows
        return report
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.writestr(name, data[name])
    os.replace(tmp, out)
    # Re-scan the written copy: only the fixed rows may be left.
    with zipfile.ZipFile(out) as z:
        out_doc = z.read("word/document.xml").decode("utf-8")
        out_styles = parse_styles(z)
        rels_name = "word/_rels/document.xml.rels"
        targets = {}
        if rels_name in z.namelist():
            rels_xml = z.read(rels_name).decode("utf-8", "replace")
            for m in re.finditer(r"<Relationship(?=[\s/>])[^>]*/>", rels_xml):
                attrs = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', m.group(0)))
                typ = attrs.get("Type", "")
                if attrs.get("Id") and (typ.endswith("/header") or typ.endswith("/footer")):
                    tgt = attrs.get("Target", "").lstrip("/").replace("\\", "/")
                    targets[attrs["Id"]] = (tgt if tgt.startswith("word/") else "word/" + tgt)
        ref_ids = re.findall(r'<w:(?:header|footer)Reference[^>]*r:id="([^"]+)"', out_doc)
        aux = [(targets[rid], z.read(targets[rid]).decode("utf-8"))
               for rid in ref_ids if rid in targets and targets[rid] in z.namelist()]
    left = [r for r in table_layout_rows(out_doc, out_styles, out.name, policy)
            if r.get("rule") in ("FMT-TB4", "FMT-TB5")]
    left += [r for r in page_field_rows(aux, out.name) if r.get("rule") == "FMT-S10"]
    report["remaining"] = left
    report["ok"] = not left
    return report

def cmd_scan_figures(args) -> int:
    """FMT-IM5 over one or more figure files."""
    terms = []
    if getattr(args, "terms", None):
        terms = [x.strip() for x in re.split(r"[,;]", args.terms) if x.strip()]
    texts = []
    for f in getattr(args, "from_docx", None) or []:
        try:
            with zipfile.ZipFile(f) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            texts.append("\n".join(text_of(p[2]) for p in paragraphs(xml)))
        except (OSError, zipfile.BadZipFile, KeyError) as e:
            log(f"error: cannot read {f}: {e}")
            return 2
    if texts:
        terms = vocabulary_terms(texts) + terms
    paths = []
    for p in args.paths:
        p = Path(p)
        if p.is_dir():
            paths += [q for q in sorted(p.rglob("*"))
                      if q.is_file() and q.suffix.lower() in (".png", ".jpg", ".jpeg",
                                                              ".tif", ".tiff")]
        elif p.is_file():
            paths.append(p)
        else:
            log(f"error: no such file or directory: {p}")
            return 2
    rows = figure_label_rows(paths, terms)
    out = {"files": [str(p) for p in paths], "terms": terms, "rows": rows,
           "by_rule": dict(Counter(r["rule"] for r in rows))}
    if args.json:
        write_json(args.json, out)
    print(format_note({"rows": rows}))
    for r in rows:
        print(f"  [{r['severity']:6s}] {r['rule']:9s} {r['document']}  {r['evidence'][:100]}")
    return 1 if (args.strict and rows) else 0


def cmd_repair_layout(args) -> int:
    """FMT-TB4/TB5 + FMT-S10 mechanical repair, with a verification re-scan."""
    policy = load_policy(args.policy)
    src, out = Path(args.file), Path(args.out)
    if src.resolve() == out.resolve():
        log("error: --out must differ from the input")
        return 2
    rep = repair_layout_package(src, out, policy)
    if args.json:
        write_json(args.json, rep)
    for c in rep.get("changes") or []:
        log(f"  [fixed] {c}")
    for r in rep.get("remaining") or []:
        log(f"  [left]  {r['rule']} {r['location']}: {r['evidence'][:100]}")
    if not rep.get("ok"):
        log(f"error: {rep.get('error') or 'layout repair left findings; see the report'}")
        return 1
    log(f"layout repair verified: {out}")
    return 0


def cmd_scan(args) -> int:
    policy = load_policy(args.policy)
    missing = _missing_paths(args.paths)
    if missing:
        for m in missing:
            log(f"error: no such file or directory: {m}")
        return 2
    info = scan_paths([Path(p) for p in args.paths], policy)
    if args.pdf:
        pdf = check_pdf(Path(args.pdf), policy)
        info["pdf"] = pdf
        info["rows"].extend(pdf["rows"])
        info["by_rule"] = dict(Counter(r["rule"] for r in info["rows"]))
        for sev in ("high", "medium", "low"):
            info[sev] = sum(1 for r in info["rows"] if r["severity"] == sev)
    out = {"policy": policy, **info}
    if args.json:
        write_json(args.json, out)
    print(format_note(out))
    for r in out["rows"]:
        flag = " (field-protected)" if r.get("protected") else ""
        print(f"  [{r['severity']:6s}] {r['rule']:9s} {r['location']:>12s}  {r['evidence'][:100]}{flag}")
    return 1 if (args.strict and out["rows"]) else 0


def cmd_fix(args) -> int:
    policy = load_policy(args.policy)
    if getattr(args, "unlink_zotero_fields", False):
        # The explicit submission-copy opt-in (README's `--unlink-zotero-fields`):
        # the refresh runs first, then the fields are flattened to their correct
        # visible text. Refused (exit 1) when the refresh cannot make the
        # numbering clean -- flattening stale numbering freezes the wrong numbers.
        policy = dict(policy)
        policy["unlink_zotero_fields"] = True
    src, out = Path(args.file), Path(args.out)
    if src.resolve() == out.resolve():
        log("error: --out must differ from the input")
        return 2
    rep = fix_package(src, out, policy)
    if not rep.get("verified"):
        log(f"error: {rep.get('error') or 'the fix could not be verified'}")
        if args.json:
            write_json(args.json, rep)
        return 1
    v = rep["verified"]
    # `ok: false` is a FAILURE (exit 1): the summary line must not read as a
    # success the exit code contradicts.
    head = "fixed" if rep["ok"] else "fix FAILED for"
    print(f"{head} {src.name} -> {out.name}: {len(rep['changes'])} change(s); "
          f"mechanical findings {v['mechanical_findings_before']} -> {v['mechanical_findings_after']}; "
          f"text identical={v['text_identical']}; parts intact={v['parts_intact']}; "
          f"schema={v['schema_detail']}")
    if not rep["ok"]:
        print(f"  the repaired file was NOT accepted: "
              f"{rep.get('error') or 'a verification check failed -- see the JSON report'}")
        # The rejected artifact must not sit at the requested --out path where a
        # caller (a script that ignores the exit code, a later run) reads it as a
        # good file: the fixer already wrote it there, so it is removed again.
        # The JSON report keeps the verification detail.
        try:
            out.unlink()
            print(f"  removed the rejected output {out.name}")
        except OSError as e:
            log(f"warning: could not remove the rejected output {out}: {e}")
    for c in rep["changes"]:
        print(f"  - {c}")
    if args.json:
        write_json(args.json, rep)
    return 0 if rep["ok"] else 1


def cmd_check_pdf(args) -> int:
    policy = load_policy(args.policy)
    res = check_pdf(Path(args.pdf), policy)
    if res["ok"] is None:
        # A skipped check is not a measured pass (Rule 10). Do not print the
        # 0-page clean summary; exit non-zero with the reason.
        detail = ((res.get("rows") or [{}])[0].get("detail")
                  or "the PDF could not be checked")
        print(f"{args.pdf}: NOT CHECKED: {detail}")
    else:
        print(f"{args.pdf}: {res['pages']} page(s); blank pages: "
              f"{res['blank_pages'] or 'none'}")
    if args.json:
        write_json(args.json, res)
    return 0 if res["ok"] is True else 1


# Field-integrity faults that are Zotero's own shapes ("bad-citation-json", a
# Zotero field without its separate, a duplicate citationID, a stray Zotero
# instruction). `unclosed-field`/`duplicate-separate` can belong to ANY Word
# field, so they count only when their message names a Zotero field kind.
ZOTERO_FAULT_CODES = ("bad-citation-json", "no-separate", "duplicate-citation-id",
                      "zotero-instr-outside-field")
ZOTERO_FAULT_KIND_WORDS = ("the item field", "the bibliography field",
                           "the zotero-other field")


def zotero_structural_faults(report: dict) -> list:
    """The Zotero field-integrity errors of one `zotero_report_for_docx` report.

    A citation field whose instruction does not parse (or which has no
    separate, a duplicate citationID, an unclosed field) drops out of every
    FMT-Z rule, so the parity rows alone read "CLEAN" on a corrupt document.
    These are the faults `zotero-check` must report and fail on before an author
    flattens the fields.

    A multi-part inventory prefixes each message with its part
    ("word/footnotes.xml: [bad-citation-json] ..."), so the code is read after
    an optional part name: a document that carries footnotes.xml (every
    Word-produced file does) is otherwise declared clean again.
    """
    out = []
    for msg in report.get("errors") or []:
        # The part-name prefix can contain a space ("word/my notes.xml: ..."),
        # which `\S+:` could never span: the fault code read as "" and the row
        # was dropped, so `zotero-check` printed CLEAN (exit 0) on a broken
        # field -- the exact regression the multi-part prefix parse closed.
        m = re.match(r"(?:\S[^\n]*?: )?\[([a-z][a-z\-]*)\]", str(msg))
        code = m.group(1) if m else ""
        if code in ZOTERO_FAULT_CODES:
            out.append(str(msg))
        elif code in ("unclosed-field", "duplicate-separate") and \
                any(word in str(msg) for word in ZOTERO_FAULT_KIND_WORDS):
            out.append(str(msg))
    return out


def cmd_zotero_check(args) -> int:
    """`zotero-check`: what a Word/Zotero refresh would rewrite in this DOCX.

    Read-only and library-free: the citation fields embed their own itemData and
    the bibliography entries are ordinary paragraphs, so the check runs on any
    machine. Exit 1 when a high-severity row exists (FMT-Z1/Z2/Z4) -- i.e. the
    document's numbering is not the numbering a refresh produces -- or when a
    Zotero field itself is structurally broken (unparseable citation JSON, no
    separate, duplicate citationID, an unclosed field): such a field is absent
    from every numbering rule, so "no rows" would otherwise print CLEAN on a
    document whose citation cache cannot be trusted.
    """
    path = Path(args.file)
    try:
        with zipfile.ZipFile(path) as pkg:
            names = list(pkg.namelist())
            if "word/document.xml" not in names:
                raise KeyError("word/document.xml")
            # EVERY part that can hold fields, not just the main one: a
            # note-style manuscript keeps its citations in word/footnotes.xml
            # (or endnotes/header/footer/comments), and reading only
            # document.xml printed CLEAN, exit 0 for a document whose
            # footnotes a Word/Zotero refresh would rewrite.
            part_names = [n for n in names
                          if n in ZOTERO_FIELD_PARTS or ZOTERO_FIELD_AUX_PARTS_RE.search(n)]
            parts = [(n, pkg.read(n).decode("utf-8", "replace")) for n in part_names]
            # EVERY store the package-level scan reads, customXml payloads
            # included: the CLI printed "style store(s): ..." and CLEAN while a
            # third store in customXml/item<N>.xml was visible only to the
            # stage gate's scan.
            style_names = [n for n in ("word/settings.xml", "docProps/custom.xml")
                           if n in names]
            style_names += [n for n in names if re.match(r"customXml/item\d*\.xml$", n)]
            style_parts = {n: pkg.read(n).decode("utf-8", "replace")
                           for n in style_names}
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as e:
        print(f"[FAIL] {path}: unreadable DOCX ({type(e).__name__}: {e})")
        return 1
    xml = next(x for n, x in parts if n == "word/document.xml")
    paras = [text_of(p[2]) for p in paragraphs(xml)]
    styles = zotero_style_ids(style_parts)
    rows = zotero_parity_rows_for_parts(parts, styles)
    state = zotero_citation_state(xml, paras, styles)
    # ... over EVERY field-carrying part: the count beside the citation count
    # (itself package-wide) read only document.xml, so a note-style manuscript
    # printed "N citation(s); 0 distinct cited item(s)".
    distinct_items = len(zotero_package_order(parts))
    report = zotero_report_for_docx(path)
    faults = zotero_structural_faults(report)
    counts_report = report.get("counts") or state["report"]["counts"]
    counts = Counter(r["rule"] for r in rows)
    print(f"{path}")
    print(f"  live field(s): {counts_report.get('item', 0)} citation, "
          f"{counts_report.get('bibliography', 0)} bibliography; "
          f"{distinct_items} distinct cited item(s); "
          f"style store(s): {styles or 'none'}")
    if not rows and not faults:
        print("  CLEAN -- the markers, the bibliography order and the style store(s) agree; "
              "a Word/Zotero refresh reproduces this numbering")
    for fault in faults:
        print(f"  [field-integrity] {fault}")
    for r in rows:
        print(f"  [{r['rule']}] {r['severity']}: {r['evidence']}")
        print(f"      {r['detail']}")
    if faults:
        print(f"  {len(faults)} field-integrity fault(s): a field this broken is not "
              f"inventoried by the numbering rules; repair it in Word/Zotero and re-run "
              f"this check before flattening the fields")
    print(f"  {len(rows)} row(s): "
          + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"))
    if args.json:
        write_json(args.json, {"file": str(path), "rows": rows,
                               "style_ids": styles, "counts": dict(counts),
                               "field_integrity_faults": faults})
    return 1 if faults or any(r["severity"] == "high" for r in rows) else 0


def cmd_zotero_refresh(args) -> int:
    """`zotero-refresh`: repair the stale numbering/bibliography offline.

    The repair runs only when every field resolves and the result passes the
    same FMT-Z checks `zotero-check` runs; otherwise nothing is written and the
    reason is printed (exit 1). The NOTHING-TO-DO cases exit 0: "no live citation
    fields" (a document that carries no field to refresh) and the CLEAN document
    whose markers/bibliography already are what a refresh would write (the
    report carries `nothing_to_do: true`). `--out` writes a copy; without it the
    file is replaced in place (the pipeline's own callers do the same on a temp
    copy).
    """
    policy = load_policy(args.policy)
    if getattr(args, "unlink", False):
        # refresh → verify → unlink, as ONE fixer chain: the flatten is refused
        # whenever the refresh could not make the numbering clean.
        src = Path(args.file)
        dst = Path(args.out) if args.out else src
        tmp = dst.with_name(f".{dst.name}.zotunlink{os.getpid()}.tmp")
        upolicy = dict(policy)
        upolicy["unlink_zotero_fields"] = True
        rep = fix_package(src, tmp, upolicy)
        if not rep.get("ok"):
            with contextlib.suppress(OSError):
                tmp.unlink()
            print(f"  no change: {rep.get('error') or 'the fixer refused the chain'}")
            if args.json:
                write_json(args.json, rep)
            return 1
        try:
            os.replace(tmp, dst)
        except OSError as e:                                            # noqa: BLE001
            with contextlib.suppress(OSError):
                tmp.unlink()
            print(f"  could not write {dst}: {e}")
            return 1
        v = rep.get("verified") or {}
        print(f"  unlinked: Zotero fields {v.get('zotero_fields_before', {}).get('zotero', '?')}"
              f" -> {v.get('zotero_fields_after', {}).get('zotero', '?')}"
              f" in {dst}")
        for line in rep.get("changes") or []:
            print(f"  [refresh] {line}")
        if args.json:
            write_json(args.json, rep)
        return 0
    res = refresh_zotero_package(Path(args.file), args.out, policy)
    for line in res.get("changes") or []:
        print(f"  [refresh] {line}")
    zot = res.get("zotero") or {}
    if zot.get("fields_fixed"):
        print(f"  renumbered {zot['fields_fixed']} stale marker(s); "
              f"parity rows: {zot.get('rows_before')} -> {zot.get('rows_after')}")
    if not res.get("changed"):
        print(f"  no change: {res.get('skip') or 'nothing to repair'}")
    if args.json:
        write_json(args.json, res)
    # The docstring's contract: the repair runs only when every field resolves and
    # the result passes the FMT-Z checks; otherwise the reason is printed and the
    # exit status is 1. `ok=True, changed=False` with a recorded skip reason IS
    # that refusal (an unresolvable field, a non-numeric style, a rebuild it
    # declined), and returning 0 here let a caller gating on the exit status read
    # a refused/stale refresh as success. The NOTHING-TO-DO skips stay 0: "no
    # live citation fields" (no field exists to refresh) and a document the
    # refresh found ALREADY clean (`nothing_to_do`) -- a document that needs no
    # repair is a success, not a refusal, and a session that read the exit
    # status as "refused" would file a hand-off for correct numbering.
    refused = (bool(res.get("skip")) and not res.get("nothing_to_do")
               and str(res.get("skip")) != "no live citation fields")
    if not res.get("ok") or refused:
        return 1
    return 0


def cmd_xfa_export(args) -> int:
    """`xfa-export`: readable rendering of a filled XFA form PDF."""
    text = xfa_export_text(Path(args.file))
    if not text:
        print(f"{args.file}: no XFA dataset answers found (nothing to export)")
        return 1
    out = Path(args.out) if args.out else Path(args.file).with_suffix(".xfa-answers.txt")
    out.write_text(text, encoding="utf-8")
    print(f"{args.file}: answers rendered to {out}")
    return 0


def cmd_validate(args) -> int:
    missing = _missing_paths(args.paths)
    if missing:
        for m in missing:
            log(f"error: no such file or directory: {m}")
        return 2
    report = validate_paths([Path(p) for p in args.paths], Path(args.json) if args.json else None,
                            timeout=args.timeout)
    for r in report["results"]:
        mark = {True: "OK  ", False: "FAIL", None: "SKIP"}[r["ok"]]
        detail = r.get("detail") or ""
        if r["ok"] is False and r.get("errors"):
            detail = r["errors"][0]
        print(f"{mark} {r['kind']:4s} {r['file']}  {str(detail)[:140]}")
    print(f"validation: {report['files']} file(s), {report['failed']} failure(s)"
          + ("" if report["ok"] else " -- fix and re-run"))
    return 0 if report["ok"] else 1


def cmd_lookup(args) -> int:
    """`lookup [--kind KIND] Q`: resolve a searchable placeholder.

    Verdicts: found / absent (a verified negative) / error (never fatal).  The
    positional form `lookup "<title>"` still means a preprint search.
    """
    queries = [q for q in ([args.query] if args.query else []) + list(args.q or []) if q]
    if not queries:
        print("ERROR: give at least one query (positional or --q)", file=sys.stderr)
        return 2
    results = [lookup_kind(args.kind, q, timeout=args.timeout) for q in queries]
    if args.json:
        write_json(args.json, results)
    for res in results:
        print(f"[{res['kind']}] {res['query']!r} -> {res['verdict']} "
              f"({len(res['hits'])} hit(s))")
        for h in res["hits"]:
            print(f"  {h.get('source')}: {str(h.get('title'))[:90]} | "
                  f"{h.get('doi') or h.get('orcid') or h.get('sha') or ''} | "
                  f"{h.get('date') or ''}")
        for e in res["errors"]:
            print(f"  [warn] {e}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="report style/formatting findings")
    s.add_argument("paths", nargs="+")
    s.add_argument("--policy")
    s.add_argument("--json")
    s.add_argument("--pdf", help="also check a rendered PDF for blank pages")
    s.add_argument("--strict", action="store_true", help="exit 1 when any finding exists")
    s.set_defaults(func=cmd_scan)
    f = sub.add_parser("fix", help="write a fixed copy of one DOCX")
    f.add_argument("file")
    f.add_argument("--out", required=True)
    f.add_argument("--policy")
    f.add_argument("--unlink-zotero-fields", action="store_true",
                   help="also flatten the (refreshed) Zotero citations/bibliography to plain "
                        "text: the submission-copy policy. Refused when the offline refresh "
                        "cannot make the numbering clean first.")
    f.add_argument("--json")
    f.set_defaults(func=cmd_fix)
    p = sub.add_parser("check-pdf", help="blank-page check of a rendered PDF")
    p.add_argument("pdf")
    p.add_argument("--policy")
    p.add_argument("--json")
    p.set_defaults(func=cmd_check_pdf)
    z = sub.add_parser("zotero-check", help="what a Word/Zotero refresh would rewrite "
                                            "(stale markers, bibliography order, style stores)")
    z.add_argument("file")
    z.add_argument("--json")
    z.set_defaults(func=cmd_zotero_check)
    zr = sub.add_parser("zotero-refresh", help="repair stale Zotero numbering and the "
                                               "bibliography order offline (no Word/Zotero)")
    zr.add_argument("file")
    zr.add_argument("--out", help="output path (default: replace the file in place)")
    zr.add_argument("--policy")
    zr.add_argument("--unlink", action="store_true",
                    help="after the refresh, flatten the citation fields to plain text (the "
                         "submission copy; runs the full fixer chain so the ordering "
                         "refresh→verify→unlink is enforced)")
    zr.add_argument("--json")
    zr.set_defaults(func=cmd_zotero_refresh)
    xe = sub.add_parser("xfa-export", help="render a filled XFA form PDF's answers as "
                                           "readable text (the shell workaround)")
    xe.add_argument("file")
    xe.add_argument("--out")
    xe.set_defaults(func=cmd_xfa_export)
    v = sub.add_parser("validate", help="validate DOCX XML/schema and compile .tex files")
    v.add_argument("paths", nargs="+")
    v.add_argument("--json")
    v.add_argument("--timeout", type=int, default=300)
    v.set_defaults(func=cmd_validate)
    lk = sub.add_parser("lookup", help="resolve a searchable placeholder (preprint / DOI / "
                                       "accession / repository / archive / ORCID)")
    lk.add_argument("query", nargs="?", help="the query (default kind: preprint)")
    lk.add_argument("--q", action="append",
                    help="another query (repeatable; batch a whole placeholder list)")
    lk.add_argument("--kind", default="preprint",
                    choices=["preprint", "paper", "title", "doi", "accession", "repository",
                             "repo", "commit", "archive", "deposit", "orcid", "gene"])
    lk.add_argument("--json")
    lk.add_argument("--timeout", type=int, default=30)
    lk.set_defaults(func=cmd_lookup)
    sf = sub.add_parser("scan-figures", help="OCR submitted figure rasters and compare "
                                              "their labels with the manuscript's vocabulary")
    sf.add_argument("paths", nargs="+")
    sf.add_argument("--terms", help="extra expected terms, comma/semicolon separated")
    sf.add_argument("--from-docx", action="append", help="derive expected terms from this "
                                                         "manuscript DOCX (repeatable)")
    sf.add_argument("--json")
    sf.add_argument("--strict", action="store_true")
    sf.set_defaults(func=cmd_scan_figures)
    rl = sub.add_parser("repair-layout", help="repair table grid/identifier wrapping and "
                                              "duplicate PAGE fields, then verify")
    rl.add_argument("file")
    rl.add_argument("--out", required=True)
    rl.add_argument("--policy")
    rl.add_argument("--json")
    rl.set_defaults(func=cmd_repair_layout)
    args = ap.parse_args(argv)
    return args.func(args)
