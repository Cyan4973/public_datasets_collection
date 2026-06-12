# gdc_projects

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: GDC project catalog
- Source: https://api.gdc.cancer.gov/projects
- Why it looked promising: Public cancer data source with stable structured metadata from an important biomedical family.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The project catalog is finite, low-density, and not large enough to justify a dedicated recipe even when fully queried.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `gdc_projects` at `364` total values and `546` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `gdc_projects` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only through a larger GDC entity family such as cases, files, or another higher-volume source with materially richer numeric content.
