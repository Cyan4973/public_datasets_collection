# HGNC Complete Set

Pinned HGNC approved gene set with row-level gene metadata.

Selected series:
- `hgnc_entrez_id_u32`
- `hgnc_symbol_length_u16`
- `hgnc_name_length_u16`
- `hgnc_pubmed_count_u16`
- `hgnc_uniprot_count_u8`
- `hgnc_gene_group_count_u16`
- `hgnc_location_length_u16`
- `hgnc_status_length_u8`
- `hgnc_approved_date_u32`
- `hgnc_modified_date_u32`

Missing-value policy: preserves zero counts and filters malformed date or identifier rows.
