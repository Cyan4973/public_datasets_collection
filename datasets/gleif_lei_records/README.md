# GLEIF LEI Records Snapshot

Pinned GLEIF LEI record page with registration timing and nested count metrics.

Pinned source: `https://api.gleif.org/api/v1/lei-records?page%5Bsize%5D=100`

Selected series:
- `gleif_entity_creation_year`
- `gleif_initial_registration_year`
- `gleif_next_renewal_year`
- `gleif_other_names_count`
- `gleif_address_line_count`
- `gleif_other_validation_authority_count`

Missing-value policy: Preserves missing renewal year as sentinel 0; otherwise rows missing registration/entity blocks are dropped.
