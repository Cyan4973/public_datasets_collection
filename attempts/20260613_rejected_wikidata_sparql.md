# wikidata_sparql

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Wikidata SPARQL result set for `instance of human`
- Source: `https://query.wikidata.org/sparql?query=SELECT%20%3Fitem%20%3FitemLabel%20WHERE%20%7B%20%3Fitem%20wdt%3AP31%20wd%3AQ5.%20SERVICE%20wikibase%3Alabel%20%7B%20bd%3AserviceParam%20wikibase%3Alanguage%20%22en%22.%20%7D%20%7D%20LIMIT%20100&format=json`
- Why it looked promising: Public knowledge-graph source with native entity identifiers and reproducible query text.
- Failure class: arbitrary_query_slice
- What happened: The accepted recipe was audited and found to be one hard-coded SPARQL query with `LIMIT 100`, not a stable corpus definition. It emits `200` primary values, `600` primary sample bytes, and has a median primary sample size of `100` values.
- Why more download does not save this recipe: Removing or raising the limit would change the query result set definition rather than deepen the same pinned recipe. A meaningful salvage would require a different corpus strategy than one arbitrary SPARQL query.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `wikidata_sparql` at `200` primary values, `600` primary sample bytes, `2` primary sample rows, and median primary sample size `100` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `wikidata_sparql` from `datasets/` and reject this exact one-query SPARQL recipe.
- Retry conditions: Retry only as a materially broader Wikidata recipe with a corpus definition that is not one arbitrary limited query.
