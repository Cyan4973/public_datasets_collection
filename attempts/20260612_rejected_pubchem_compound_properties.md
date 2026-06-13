# pubchem_compound_properties

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: PubChem compound properties for aspirin
- Source: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/property/MolecularWeight,XLogP,TPSA/JSON`
- Why it looked promising: Public scientific source with native numeric molecular properties.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single fixed-compound lookup. It emits only `4` total values and `16` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one pinned CID (`2244`). There is no additional pagination or time range inside this recipe. Making it materially useful would require switching from one-compound lookup to a multi-compound corpus, which is a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `pubchem_compound_properties` at `4` total values, `16` total sample bytes, and `4` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `pubchem_compound_properties` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader multi-compound PubChem recipe with documented compound selection scope.
