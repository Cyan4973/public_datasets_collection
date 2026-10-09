# Unified human genealogy: tree-sequence node ages (float64)

This recipe collects the native float64 tskit node-table `time` column from
every chromosome-arm tree sequence in the unified genealogy of Wohns et al.
(2022). The genealogy covers the 1000 Genomes phase 3, Human Genome Diversity
(HGDP), and Simons Genome Diversity (SGDP) Projects, and is published on
Zenodo as record 5495535, v1.0.0, under CC BY 4.0. Each sample is the complete
node-age vector of one autosome arm in native node order: 39 samples, from
201,179 to 1,475,035 values each, 29,149,715 float64 values (233,197,720
bytes) in total.

## What the values are

The topology was inferred with tsinfer 0.2.1, and nodes were dated with
tsdate 0.1.4. `nodes/time` is the age of each node in generations before
present: tsdate's posterior mean, adjusted by tsdate so that every parent is
strictly older than its children. Raw posterior means and variances live in
node metadata and are not collected. The values are model-derived, but they
are the native typed column of a published artifact, not a local
transformation.

Node order is kept as published. The first 7,508 nodes are the sample genomes
and have time exactly 0. This is 292,812 values in total, about 1.0% overall
(0.5% to 3.7% per arm). Those zeros are part of the column and are kept.
`build.sh` and `verify.sh` require that the zeros are exactly that leading
block in every arm. The remaining nodes are inferred ancestors. For chr16_p
they range from 0.54 to 81,718.57 generations, with 305,940 distinct values
among 418,376, and none of them are f32-exact or integral.

Realized build (2026-10-09): all 39 arms have exactly 7,508 leading zeros.
Distinct values per arm are about 70% to 77% of node count. The smallest
nonzero value is 0.20 to 0.62 generations. In every arm the maximum is
between 81,718.57338 and 81,718.57341 generations: the oldest root-adjacent
nodes pile up at the top of tsdate's time grid. Only a few dozen to a few
hundred nodes per arm sit there (55 in chr16_p, 199 in chr2_q). Quantiles for
chr2_q are p5 14, median 742, p95 17,647, and p99.9 67,611 generations.
Consecutive node times are not sorted: about 50% of steps are non-decreasing.
The aggregate SHA-256 over the per-arm sample digests is recorded in
`.data/filtered/wohns_unified_genealogy_node_time_f64/ingest_stats.json`.

No genotypes, haplotypes, sites, mutations, individual or population metadata,
or edges are fetched. Edge `left`/`right` are integer base-pair positions
stored as f64, which would be a widening. The ancient-genome genealogy
(record 5512994) is also not used.

## Access and decoding

Each `.tsz` file is a zarr v2 `ZipStore` with stored (uncompressed) ZIP
members. `download.sh` does the following:

1. Validates the Zenodo record: id, title, version 1.0.0, license
   `cc-by-4.0`, and all 39 pinned file sizes and MD5s.
2. Range-fetches each file's central directory with its EOCD record, and one
   contiguous range holding `nodes/time/.zarray` and the single chunk
   `nodes/time/0`. It requires HTTP 206 with the exact `Content-Range`.
3. Checks the member offsets, sizes, and CRC32 against `resources.tsv` and
   against both the central directory and the local headers.
4. Checks the zarr schema (`<f8`, a single chunk, blosc/zstd/shuffle) and the
   blosc header (`nbytes = shape * 8`).

The download is about 196.7 MB of the 3.45 GB deposit.

`scripts/blosc1.py` is a pure-stdlib Blosc1 decoder. It handles the 16-byte
header, the byte-shuffle, memcpyed, and dont-split flags, and the block-start
table. Blocks may appear in any order, but their extents must tile the frame
exactly; the probed chr16_p frame lists its blocks in reverse order. A per-block
`csize` equal to the raw size means the block is stored as-is. zstd blocks go
through the `zstd` CLI. Unshuffling is per block, and any trailing bytes are
copied verbatim. The decoder self-tests on synthetic frames at every build,
and rejects bitshuffle, split streams, and non-zstd codecs. `verify.sh`
re-derives every sample with a separate member reader driven by the central
directory and a second Blosc walker, then byte-compares the results.

`discover.py` documents how `resources.tsv` was generated (2026-10-09).

## Run

```bash
bash staging/wohns_unified_genealogy_node_time_f64/download.sh
bash staging/wohns_unified_genealogy_node_time_f64/build.sh
bash staging/wohns_unified_genealogy_node_time_f64/verify.sh
```

Requires `curl`, `python3` (stdlib only), and the `zstd` CLI. Logs are
written under `.data/logs/wohns_unified_genealogy_node_time_f64/`.

## Citation

Wohns, A. W. et al. A unified genealogy of modern and ancient genomes.
Science 375, eabi8264 (2022). Data: https://doi.org/10.5281/zenodo.5495535
(CC BY 4.0).
