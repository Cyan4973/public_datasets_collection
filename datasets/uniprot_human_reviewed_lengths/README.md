`uniprot_human_reviewed_lengths` emits native numeric protein length and mass fields from a pinned UniProt TSV query.

Series:
- `uniprot_length`
- `uniprot_mass`

Missing-value policy:
- blank values are filtered independently per series
- malformed rows are fatal
