# github_linux_repo_snapshot

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: GitHub metadata snapshot for `torvalds/linux`
- Source: `https://api.github.com/repos/torvalds/linux`
- Why it looked promising: Public software metadata with native numeric counters and timestamps.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single repository snapshot with only `6` total values and `24` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one repository endpoint and one metadata row. There is no within-recipe expansion beyond refetching a new snapshot of the same row. Making it useful would require a multi-repository or time-series repository recipe, which is materially different.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `github_linux_repo_snapshot` at `6` total values, `24` total sample bytes, and `6` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `github_linux_repo_snapshot` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a broader homogeneous repository-metadata family or repository-history recipe.
