#!/usr/bin/env python3
"""Render exact vector workflow panels; requires Graphviz's `dot` command."""
from pathlib import Path
import json
import subprocess

DEST = Path(__file__).resolve().parent
COLORS = {"write": "#DBEAFE", "read": "#DCFCE7", "code": "#F1F5F9", "gate": "#FEF3C7"}

class Diagram:
    def __init__(self, title):
        self.lines = ["digraph workflow {", 'graph [rankdir=TB, bgcolor="white", pad=0.18, nodesep=0.24, ranksep=0.33, fontname="DejaVu Sans", fontsize=15, labelloc=t, label=' + json.dumps(title) + '];',
            'node [shape=box, style="rounded,filled", color="#475569", penwidth=0.8, fontname="DejaVu Sans", fontsize=10, margin="0.14,0.08"];',
            'edge [color="#475569", arrowsize=0.65, fontname="DejaVu Sans", fontsize=8];']
    def node(self, key, label, kind="code"):
        self.lines.append(f'{key} [label={json.dumps(label)}, fillcolor="{COLORS[kind]}"];')
        return key
    def edge(self, start, end, label="", dashed=False):
        attrs = f'label={json.dumps(label)}' + (', style=dashed' if dashed else '')
        self.lines.append(f'{start} -> {end} [{attrs}];')
    def quality(self, key, label):
        writer = self.node(key, label, "write")
        auditor = self.node(key+"_audit", "Independent write auditor", "read")
        repair = self.node(key+"_repair", "Bounded repair\nreverify every planned row", "write")
        verify = self.node(key+"_verify", "Independent final verifier", "read")
        accepted = self.node(key+"_accept", "Code checks + exact-byte acceptance", "gate")
        self.edge(writer, auditor)
        self.edge(auditor, repair, "repairable rows")
        self.edge(repair, verify)
        self.edge(auditor, verify if key == "revise" else accepted, "empty plan")
        self.edge(verify, accepted, "passes")
        return writer, accepted
    def render(self, filename):
        source = DEST / (filename + ".dot")
        source.write_text("\n".join(self.lines + ["}"]) + "\n")
        for extension in ("svg", "pdf"):
            subprocess.run(["dot", "-T"+extension, str(source), "-o", str(source.with_suffix("."+extension))], check=True)

MODES = [("continue", "a", "General revision"), ("init", "b", "New submission"),
         ("transfer", "c", "Transfer to a new journal"), ("resubmit", "d", "Resubmit to the same journal"),
         ("major", "e", "Major revision"), ("minor", "f", "Minor revision"),
         ("llm", "g", "LLM feedback revision")]
for mode, letter, title in MODES:
    d = Diagram(f"({letter}) {title}")
    source = d.node("source", "Original manuscript + read-only evidence")
    base = source
    if mode in ("init", "transfer"):
        w, base = d.quality("conform", "Conformer\ndestination template or native-format guidelines")
        rules = d.node("rules", "Destination journal rules", "code")
        d.edge(source, w); d.edge(rules, w)
    if mode in ("major", "minor"):
        feedback = d.node("feedback", "Journal / permitted LLM feedback")
        concerns = d.node("concerns", "Concern assessor\nread/report only", "read")
        d.edge(feedback, concerns); d.edge(base, concerns)
        writer, accepted = d.quality("revise", "Concern-scoped reviser")
        d.edge(concerns, writer); d.edge(base, writer)
    else:
        feedback = None
        if mode in ("transfer", "resubmit", "llm"):
            raw = d.node("feedback", "Filtered LLM feedback only" if mode == "llm" else "Prior journal / permitted LLM feedback")
            feedback = d.node("assessor", "Feedback assessor\nread/report only", "read")
            d.edge(raw, feedback)
        guided = d.node("guided", "Guided reviewer", "read")
        cold = d.node("cold", "Cold-start reviewer\nwhen enabled and full scope", "read")
        findings = d.node("findings", "Frozen findings\noptional read-only review auditor", "read")
        rewrite = d.node("rewrite", "Rewriter(s)\noptional; exempt from write audit", "write")
        d.edge(base, guided); d.edge(base, cold); d.edge(base, rewrite, dashed=True)
        if feedback:
            d.edge(feedback, guided); d.edge(feedback, rewrite, dashed=True)
        d.edge(guided, findings); d.edge(cold, findings)
        writer, accepted = d.quality("revise", "Reviser(s)")
        d.edge(findings, writer); d.edge(base, writer)
        pool = d.node("pool", "Candidate pool\nbase + rewrites + accepted revisions")
        d.edge(base, pool); d.edge(rewrite, pool, dashed=True); d.edge(accepted, pool)
        integrate = d.node("integrate", "Integrator(s)\noptional; exempt from write audit", "write")
        field = d.node("field", "Candidate field + prior champions")
        d.edge(pool, integrate, "whole pool", True); d.edge(pool, field); d.edge(integrate, field, dashed=True)
        judges = d.node("judges", "Independent judge sessions", "read")
        diagnostics = d.node("diagnostics", "Panel conflict / defect auditors\noptional diagnostics", "read")
        accepted = d.node("selection", "Code selection + pin\nrepeat round if scheduled")
        d.edge(field, judges); d.edge(judges, accepted); d.edge(judges, diagnostics, dashed=True)
        d.edge(field, accepted, "auto-promotion option\nprovisional; no panel", True)
    if mode in ("major", "minor", "resubmit"):
        response, response_ok = d.quality("response", "Response writer\nletter + concern map")
        d.edge(accepted, response, "final manuscript")
        if mode in ("major", "minor"):
            d.edge("concerns", response, "concern ledger")
        else:
            d.edge("assessor", response, "concern ledger")
        output = d.node("output", "Code publication\njournal submission + response")
        d.edge(accepted, output); d.edge(response_ok, output)
    else:
        output = d.node("output", "Code publication\njournal submission; no response" if mode == "transfer" else "Final manuscript\nno response letter")
        d.edge(accepted, output)
    d.render("fig1"+letter+"-"+mode)
print("Rendered seven PDF/SVG workflow panels.")

# Administrative authoring uses the same mandatory gate but no manuscript round.
d = Diagram("Auxiliary workflow: add or update a venue profile")
evidence = d.node("evidence", "Authoritative venue evidence + existing store\nread-only")
writer, accepted = d.quality("profile", "Venue profile writer\nstaged profile + README + downloads")
d.edge(evidence, writer)
schema = d.node("schema", "Code schema validation + publication\nonly the audited staged store")
d.edge(accepted, schema)
d.render("aux-add-venue")
