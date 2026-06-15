# Deferred: chembl_molecules

Date: 2026-06-15

Reason: the original accepted recipe was a tiny first-page ChEMBL molecule
sample with `400` primary values and median sample size `100`. A first repair
attempt produced one native descriptor matrix from the only reliably downloaded
1,000-row page, but that matrix was only `43,560` primary bytes. For a single
matrix sample, this is too marginal to count as a satisfactory repair.

The stricter repair target was raised to at least `250 KiB` primary output:
seven fixed 1,000-row pages, at least 6,000 retained molecule rows, and one
row-major 11-descriptor matrix. The public ChEMBL API repeatedly returned HTTP
`500` for offset `1000`, after retries, while offset `0` remained cached and
valid.

Decision: remove the accepted recipe for now. Do not accept the 43 KiB salvage.
Revisit only with a reproducible public acquisition path that can exceed the
single-file size target, preferably a ChEMBL bulk distribution or a fixed API
route that can download multiple pages reliably.

Observed failure:
- endpoint: `https://www.ebi.ac.uk/chembl/api/data/molecule.json?limit=1000&offset=1000&order_by=molecule_chembl_id`
- status: HTTP `500`
- log: `.data/logs/chembl_molecules/download.latest.log`

