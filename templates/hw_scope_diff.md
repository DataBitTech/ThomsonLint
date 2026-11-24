# Review Scope — Diff Review

This is a **diff review**: review what changed from the baseline design to the
revised design.

- **Board:** {{board}}
- **Baseline revision:** {{rev_a}}
- **Revised revision:** {{rev_b}}
- **project_name:** `{{project_name}}` — use exactly this value as `project_name`
  in the findings JSON, and in its file name.

## Design files

Baseline exports, in `exports/baseline/`:

{{baseline_files}}

Revised exports, in `exports/revised/`:

{{revised_files}}

{{layout_note}}

## Mechanical diff

`exports/DIFF.json` holds a precomputed, deterministic diff of the baseline and
revised exports (written by `tools/thomson-diff.py`). Use it as the map of what
changed, as described under "Diff Reviews" in the review instructions.

## Output

Write the findings to **`exports/{{project_name}}-findings.json`**, then run
`python tools/validate_findings.py exports/{{project_name}}-findings.json` and
fix what it reports, as described under "Structured Findings Output" in the
review instructions. Cite the design files above by their paths (e.g.
`exports/...`) and datasheets as `datasheets/<file name>` in `evidence[].source`
and `source_documents[]`.
