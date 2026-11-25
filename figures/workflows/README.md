# Workflow figure panels

These vector diagrams correspond to the implemented workflow modes. Each panel is supplied as editable Graphviz source (`.dot`), SVG and PDF. Regenerate every panel with `python figures/workflows/render.py` (Graphviz required).

| Panel | Workflow | Journal response |
| --- | --- | --- |
| [Fig. 1a](fig1a-continue.pdf) | Continue / general review and revision | None |
| [Fig. 1b](fig1b-init.pdf) | New submission, starting with conformance | None |
| [Fig. 1c](fig1c-transfer.pdf) | Transfer to a new journal, starting with conformance | None |
| [Fig. 1d](fig1d-resubmit.pdf) | Resubmit to the same journal | Required after the last completed round |
| [Fig. 1e](fig1e-major.pdf) | Major revision against admitted concerns | Required |
| [Fig. 1f](fig1f-minor.pdf) | Minor revision against admitted concerns | Required |
| [Fig. 1g](fig1g-llm.pdf) | Revision against filtered LLM feedback | None |
| [Auxiliary](aux-add-venue.pdf) | Venue profile authoring | Not applicable |

**Suggested caption.** Agent interactions in the manuscript refinement workflows. Blue boxes denote authoring or repair agents; green boxes denote agents with read/report mandates; gray boxes denote inputs, artifacts or deterministic orchestration; yellow boxes denote acceptance gates. Every reviser, response writer, conformer and venue profile writer is independently audited. A repairable audit plan triggers one separate bounded-repair session followed by independent verification. Arrows into acceptance represent passing checks only; failed verification, malformed evidence and unresolved prerequisites block downstream use. Rewriters, integrators and bounded repairs are exempt from recursively starting a post-write repair chain. Dashed arrows denote optional stages, diagnostic branches or the explicitly selected automatic promotion alternative.

The general-round panels show the configured revision branch, with optional rewrites and integrations. Guided and cold-start review are independently configurable; cold-start discovery applies to full-scope rounds. A review auditor disposes findings and is distinct from the mandatory post-write auditor. The revision chain also performs an independent final check when its first audit has an empty repair plan; response, conform and profile writers with empty plans need no repair or second verifier. The drawn acceptance gate groups deterministic checks that can run both before and after auditing; it does not imply they execute only once.

Major and minor share a topology: both include an actual revision agent and mandatory audit/repair gate, restricted to admitted concerns and regressions caused by their edits. Their scientific edit scope comes from the journal concerns; neither mode introduces general reviewing, rewriting, integration or a judge panel.

Conformance in both init and transfer uses an applicable official Word template, otherwise the destination guidelines and the package's native format. An explicit `--no-template-stage` remains the operator's opt-out. Conformance uses the selected producer backend. A passed result cannot be silently reused for a different source or destination rule set.

In general modes, judges score the final candidate field and deterministic code selects the champion; a registered automatic-promotion policy skips the panel and yields a provisional result. Optional panel audits are diagnostics rather than manuscript writers. A valid registered early stop ends the scheduled rounds and still runs the required journal finalization; resubmit writes its audited response against the actual final manuscript. Continue, init and LLM-only modes do not produce journal response letters.

Each auditor is a new session with its own context. “Independent” here describes role and session separation; the default configuration can use the same model backend for several roles. Actual model diversity must be configured separately.
