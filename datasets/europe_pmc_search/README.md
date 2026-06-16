# Europe PMC Search

Bounded Europe PMC bibliographic metadata recipe. The repaired recipe replaces
the old single first-page slice with a complete cursor-paginated January 2024
first-publication-date window.

Run:

```bash
datasets/europe_pmc_search/download.sh
datasets/europe_pmc_search/build.sh
datasets/europe_pmc_search/verify.sh
```

Default scope:

- API: Europe PMC REST search
- query: `FIRST_PDATE:[2024-01-01 TO 2024-01-31]`
- page size: `1000`
- source cap: `300 MB`
- natural sample boundary: one homogeneous metadata field sequence sorted by
  first publication date, source, and record id
- primary fields: citation count, author count, title length, publication-type
  count, full-text id count, and journal-title length
- auxiliary fields: first publication date, used only for alignment and
  verification

The downloader is cache-aware and writes `download_inventory.json`. The build
rejects missing inventories, tiny output, constant primary series, and primary
payloads above the repository `1 GB` cap. The verifier independently checks the
sample index, byte sizes, sort order, date window, primary floors, and
non-constant primary series.
