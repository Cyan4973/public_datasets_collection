# Unified human genealogy tree-sequence node-age float64 development

## Outcome

Accepted `wohns_unified_genealogy_node_time_f64` from Zenodo record 5495535, version 1.0.0.

This is the first ancestral-recombination-graph (genealogy) material in the corpus, local or downstream, at any width. The existing genomic families hold different quantities:

- observed sequence symbols (`ncbi_refseq_viral_genomes_u8`, `pfam_seed_alignments_u8`);
- read quality and MAPQ (`ena_fastq_quality_phred`, `bam_read_mapq_u8`);
- methylation (`encode_methylation_pct_u8`);
- feature coordinates;
- Pfam profile-HMM emissions.

This recipe holds the inferred age of every node of a population-scale human genealogy. The values are model-derived (tsdate posterior means, then the tsdate constraint that every parent is older than its children). They are still the natively published typed column of the artifact, not a local transformation, in the same way the accepted Pfam profile-HMM recipe keeps fitted model parameters.

## Source and rights

- Source: Zenodo record 5495535, "A unified genealogy of modern and ancient genomes: Unified, inferred tree sequences of 1000 Genomes, Human Genome Diversity, and Simons Genome Diversity Projects", v1.0.0. Authors: Wohns, Wong, Jeffery, Akbari, Mallick, Pinhasi, Patterson, Reich, Kelleher, McVean (2021).
- Files: 39 `hgdp_tgp_sgdp_chr{N}_{p,q}.dated.trees.tsz`, 3,454,705,766 bytes. Every per-file size and MD5 is pinned in `resources.tsv` and re-checked against the live record on every download.
- License: CC BY 4.0. The record declares `"license": {"id": "cc-by-4.0"}` with `access_right` open for the deposited files.
- Personal data: none emitted. Only the node-time column is fetched. Sample nodes carry time 0, and no genotypes, sites, mutations, individual or population metadata are fetched.

## Shape and conversion

Each `.tsz` is a zarr v2 ZipStore with stored ZIP members. Per arm, `download.sh` fetches two byte ranges, each requiring HTTP 206 with the exact Content-Range:

- the central directory plus EOCD;
- one contiguous range covering `nodes/time/.zarray` and the single chunk `nodes/time/0`.

Member offsets, sizes and CRC32s are pinned and checked against both the central directory and the local headers.

The chunk is a Blosc1 frame (flags 0x91: byte-shuffle, dont-split, zstd; typesize 8; 1 MiB blocks; blocks may be stored out of order). `scripts/blosc1.py` decodes it with the stdlib plus the zstd CLI and self-tests at every build (8 decode cases, 7 rejection cases). Decoded bytes must equal blosc nbytes, which must equal shape × 8. They are written unchanged as little-endian float64, one file per arm, in native tskit node order.

Excluded:

- edge `left`/`right` (integer bp positions stored as f64, which would be a widening);
- site, mutation, individual, population and provenance tables;
- node metadata;
- the ancient-genome record 5512994.

The first 7,508 nodes of every arm are the sample haplotypes, with time exactly 0. That is 1.0% of values overall and 0.5–3.7% per arm. The zeros are kept as native semantics, and build and verify require that they form exactly that leading block. Every arm's maximum sits at the tsdate time-grid ceiling, about 81,718.573 generations, reached by 7–167 nodes per arm.

## Accepted output

- Samples: 39 (every arm in the deposit)
- Primary values: 29,149,715
- Primary bytes: 233,197,720
- Smallest sample: 201,179 values (chr18_p)
- Median sample: 673,050 values
- Largest sample: 1,475,035 values (chr2_q)
- Download: 196,693,409 bytes (CD + member ranges) of the 3.45 GB deposit
- Sample-node zero share: 0.010045
- Maximum stored value: 81,718.57340573934 generations
- Aggregate SHA-256 over per-arm digests: `502cb98e434eaaaa1c5ae07fa00ed53bc16524d950b74441e4ecbf603b16aca3`

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Verify:** I re-ran `verify.sh`; it reported `verify ok` after re-deriving all 39 samples independently and byte-comparing them.
- **Third decoder:** I wrote my own decoder, which walks the local headers, checks CRC32 and does a byte-loop unshuffle placing blocks by bstarts. It reproduced the chr18_p sample byte for byte.
- **Bytes:** No nonzero value in the inspected arms is f32-exact or integral. Mantissa trailing-zero counts are geometric, so the full float64 precision is used. Distinct values are 69.7–76.9% per arm; repeats are tsdate's 1e-6 constraint chains, with a largest nonzero multiplicity of 114–524 per arm. About 50% of steps are non-decreasing and 0.1% are equal, so there are no sorted runs. All 39 SHA-256 digests are unique, and per-arm medians are 700–1,172 generations.
- **Rights:** The live Zenodo API reports license cc-by-4.0, access open, version 1.0.0. No credentials appear in any script, and build.sh and verify.sh make no network calls.
- **Novelty:** `novelty.py` with the URL, ARG-specific terms, measurement type and instrument line found nothing outside this candidate's own rows. zlsim measured OK, with the nearest family downstream:H2_IpChi2 at 0.0937.
