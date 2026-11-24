# Review Scope — Full Design Review

This is a **full design review** of one design.

- **Board:** {{board}}
- **Revision:** {{revision}}
- **project_name:** `{{project_name}}` — use exactly this value as `project_name`
  in the findings JSON, and in its file name.

## Design files

The design's ThomsonLint exports, in `exports/`:

{{design_files}}

{{layout_note}}

## Output

Write the findings to **`exports/{{project_name}}-findings.json`**, then run
`python tools/validate_findings.py exports/{{project_name}}-findings.json` and
fix what it reports, as described under "Structured Findings Output" in the
review instructions. Cite the design files above by their paths (e.g.
`exports/...`) and datasheets as `datasheets/<file name>` in `evidence[].source`
and `source_documents[]`.
