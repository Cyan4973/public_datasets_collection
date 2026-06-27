# GLEIF LEI Records

This recipe collects a bounded prefix of the public GLEIF LEI record catalog
and emits homogeneous numeric fields from entity and registration metadata.

The previous accepted recipe fetched only one 100-record API page. This version
follows GLEIF pagination up to a bounded record cap and writes one numeric field
per homogeneous series. Textual LEIs, names, statuses, jurisdictions, legal
forms, and addresses are not emitted.

## Numeric Families

- `gleif_entity_creation_days_i32`: entity creation date as days since Unix epoch.
- `gleif_initial_registration_days_i32`: initial LEI registration date as days since Unix epoch.
- `gleif_last_update_days_i32`: registration last-update date as days since Unix epoch.
- `gleif_next_renewal_days_i32`: next-renewal date as days since Unix epoch, where present.
- `gleif_legal_address_line_count_u16`: legal-address line count.
- `gleif_other_names_count_u16`: other-name count.
- `gleif_other_validation_authority_count_u16`: other validation-authority count.

## Usage

```bash
bash datasets/gleif_lei_records/download.sh
bash datasets/gleif_lei_records/build.sh
bash datasets/gleif_lei_records/verify.sh
```

The download is bounded by `GLEIF_MAX_RECORDS` and `GLEIF_MAX_PAGES`. The
defaults fetch enough records to satisfy acceptance floors while keeping the
local source payload modest.
