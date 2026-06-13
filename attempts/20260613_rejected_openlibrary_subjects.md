# openlibrary_subjects

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: OpenLibrary subject works for `data`
- Source: `https://openlibrary.org/subjects/data.json?limit=100`
- Why it looked promising: Public bibliographic metadata with native edition counts, publish years, and collection counts.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one subject page, `data`, rather than a coherent corpus definition. It emits `305` primary values, `692` primary sample bytes, and has a median primary sample size of `41` values.
- Why more download does not save this recipe: The current recipe identity is one subject listing, `data`. Expanding it honestly would require changing the subject strategy or switching to a broader OpenLibrary corpus recipe, which is materially different.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `openlibrary_subjects` at `305` primary values, `692` primary sample bytes, `6` primary sample rows, and median primary sample size `41` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `openlibrary_subjects` from `datasets/` and reject this exact one-subject OpenLibrary recipe.
- Retry conditions: Retry only as a materially broader bibliographic corpus with a scope definition that is not one topical subject page.
