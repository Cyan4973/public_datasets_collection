# Crossref Member DOI Counts (per name initial)

Per-member DOI counts from the full Crossref members list, organized as **one family per
quantity** with **one sample per member-name initial** — "many series of the same
quantity". Supersedes the earlier single-page recipe (100 members, below floor).

- Source: https://api.crossref.org/members (open Crossref REST API)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/crossref_members/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `crossref_member_total_dois_u32` | total DOIs registered | uint32 |
| `crossref_member_current_dois_u32` | current-year DOIs | uint32 |
| `crossref_member_backfile_dois_u32` | backfile DOIs | uint32 |

- **A sample** = all members whose primary name starts with a given letter, that count.
- **Samples/family** = number of initials (A–Z) with `>= CROSSREF_MIN_LETTER_RECORDS`
  members (default 1000). With ~33k members, most common initials qualify.

## How it's pulled

The full members list (~33k) is crawled via cursor pagination (`rows=1000`, ~33 pages).
The nested `counts` object is not select-able, so full member objects are fetched and the
counts extracted in the build. De-duplicated by member id.

## Run

```sh
bash datasets/crossref_members/download.sh   # ~33 cursor pages
bash datasets/crossref_members/build.sh
bash datasets/crossref_members/verify.sh
```

Tuning env vars: `CROSSREF_ROWS` (default 1000), `CROSSREF_MAX_PAGES` (default 200),
`CROSSREF_MIN_LETTER_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/crossref_members/`.
