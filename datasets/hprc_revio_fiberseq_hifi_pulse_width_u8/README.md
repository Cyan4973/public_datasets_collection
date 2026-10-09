# HPRC PacBio Revio Fiber-seq HiFi read pulse width (fp/rp, CodecV1 uint8)

Per-base polymerase kinetics of PacBio Revio HiFi reads. For every base of
a HiFi consensus read, on-instrument `ccs` averages the **pulse width** (how
long the fluorescent incorporation pulse lasted, in 100 Hz camera frames)
separately over the forward-strand and reverse-strand subread passes, and
stores each strand as an 8-bit CodecV1 code array: `fp` (forward) and `rp`
(reverse), BAM type `B:C`. This recipe emits those arrays unchanged.

- Series `hifi_forward_pulse_width_codecv1_u8`: one sample per non-empty
  `fp` array, so one forward strand of one HiFi read.
- Series `hifi_reverse_pulse_width_codecv1_u8`: one sample per non-empty
  `rp` array.

Layout choice: fp and rp are kept as two series of the same quantity, so
each series has exactly one source field. The index also records `strand`
per sample.

## Source and license

- AWS Open Data, Human PanGenomics Project, bucket `s3://human-pangenomics`
  (us-west-2), managed by the Human Pangenome Reference Consortium.
- Registry entry `awslabs/open-data-registry/datasets/hpgp-data.yaml`:
  `License: "[Creative Commons CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/deed.en)"`
  for resource `arn:aws:s3:::human-pangenomics`. `download.sh` re-fetches
  this entry and requires that line and the ARN on every run.
- Submission
  `submissions/4f00ec2d-4533-40e3-b0ca-624ab5a559d9--WUSTL_HPRC_PacBio_FiberSeq/`.
  An anonymous S3 ListObjectsV2 call returns 240 keys: 60 BAMs (hifi_reads
  and fail_reads) with `.pbi` and `.md5` sidecars. The 30 `*.hifi_reads.*.bam`
  objects are 340.8 to 515.3 GB each, 13.35 TB in total. They come from 25
  individuals: 20 with one SMRT cell, and HG06799, HG06800, HG06801, HG06802
  and HG06805 with two each. Keys, sizes and ETags are pinned in
  `scripts/bams.tsv`, in listing order.
- Human-derived material: DNA from openly released 1000 Genomes / HPRC
  lymphoblastoid cell lines. Only the pulse-width arrays are written. Bases,
  qualities, IPD (`fi`/`ri`), MM/ML methylation calls, read names and ZMW
  numbers never reach samples or the index.

## Header contract (checked for all 30 files)

Every BAM has one `@RG` line, and on 2026-10-09 all 30 headers matched
apart from the per-file ID, PU, SM, barcode and SMRT cell ID:

```
@HD VN:1.6 SO:coordinate pb:5.0.0
@RG DS:READTYPE=CCS;Ipd:CodecV1=ip;PulseWidth:CodecV1=pw;
       BINDINGKIT=103-496-900;SEQUENCINGKIT=103-496-700;BASECALLERVERSION=5.0;
       SMRTCELLKIT=102-202-200;ICSVERSION=13.3.0.253824;MOVIELENGTH=1800.0;
       FRAMERATEHZ=100.000000;...  PM:REVIO  CM:R/P2-C2/5.0-25M  SM:<sample>_FS
@PG ccs 8.2.0 | pbtrim 1.1.0 | jasmine 2.3.0 (--6ma) | lima 2.11.0
```

`scripts/hifi_bam.py:header_problems` checks exactly these fields, plus
PU = movie and SM = `<sample>_FS`. `download.sh` reports any file that
differs, and `build.sh` skips it and lists it in `ingest_stats.json`. Such a
file could be non-Revio, use another kit, store raw-frame kinetics, or lack
`--6ma`. `verify.sh` fails if fewer than the claimed 30 files were used. A
record missing `fp`/`rp` (kinetics stripped) fails the build.

## The quantity, CodecV1 and strand order

From the PacBio BAM spec (<https://pacbiofileformats.readthedocs.io/en/latest/BAM.html>):
`fp` = "Forward PulseWidth (codec V1)" and `rp` = "Reverse PulseWidth
(codec V1)". These are "averaged from subreads during CCS" and "computed and
stored independently for both orientations of the insert". `fn`/`rn` count
the complete passes per strand.

CodecV1 (lossy, monotone): codes 0-63 = 0-63 frames; 64-127 = 64-190 in
steps of 2; 128-191 = 192-444 in steps of 4; 192-255 = 448-952 in steps of
8, with 255 meaning capped at 952 frames. **The codes are emitted as stored.**
They are not decoded to frames and not widened, so the series are
`derived_operational_numeric`, the same treatment as the accepted
`zenodo_pacbio_sequel_subread_ipd_codecv1_u8`.

Orientation: "Forward is defined and stored with respect to the
orientation represented in SEQ ... Reverse tags are stored in the opposite
direction, e.g. from the last base to the first." `fp[i]` is therefore SEQ
base i, while `rp[0]` is the last base of SEQ, which is the order in which
the polymerase traversed the reverse strand. `rp` is **not** reversed. The
index field `array_order` records this per sample.

The spec says flanking zero codes mark bases without usable kinetics on
that strand. They are kept as stored and counted per sample
(`leading_zero_codes`, `trailing_zero_codes`). A strand filtered out
entirely gets an empty array and pass count 0. Such empty arrays are
dropped and counted, and so would constant arrays be.

## Scope and boundaries

- Transfer: bytes `0-12582911` (12 MiB) of each of the 30 BAMs, 377,487,360
  bytes in total, about 0.003% of the submission. Prefixes are taken in
  listing order, one per file, so samples cover all 30 SMRT cells and 25
  individuals. Before transfer, a HEAD request must return the pinned size
  and ETag, and a one-byte range GET must answer 206. Transfers use offset
  ranges that resume a partial file. Only a 206 whose Content-Range starts
  at the current offset is appended. Stalls are caught with
  `--speed-limit/--speed-time`. Prefix SHA-256s go to
  `prefix_inventory.tsv`, and build and verify re-check them.
- Each prefix loses its truncated final BGZF block and its truncated final
  BAM record. Every other record is used, in physical order, so the realized
  count is fixed by the prefixes.
- Natural record: one HiFi read (one ZMW, one `<movie>/<zmw>/ccs` record).
  A sample holds one strand's array, whose length equals the read length.
  Different reads are never concatenated.
- Real-data probe, 4 MiB of HG02717: 48 complete records. One read had
  fn=0 (empty `fp`), giving 47 fp and 47 rp arrays with median length
  23,502. fp: 191 distinct codes, range 1-198, top codes 10, 12, 14, 8, 16;
  no zero and no 255 codes. rp is near-identical, with 186 distinct codes and
  range 2-200. Extrapolating, the 12 MiB prefixes should give roughly 140
  reads per file, about 4,200 reads, about 8,400 samples and about 200 MB in
  total.
- Realized (first build, 2026-10-09): all 30 files passed the header
  contract (none skipped), 25 individuals, 4,461 complete records (134-167
  per file). 8,708 samples, 203,067,020 bytes:
  - `hifi_forward_pulse_width_codecv1_u8`: 4,380 samples, 102,223,623
    bytes. 81 empty fp arrays dropped, 0 constant. Lengths range from 9,840
    to 51,655 with a median of 22,348 (the library is size-selected, so no
    read is under 1,000 bases). 245 distinct codes. 98.85% of values are
    codes 0-63, 0.0001% are zero codes, and none are 255. 13 samples have
    flanking zero codes.
  - `hifi_reverse_pulse_width_codecv1_u8`: 4,328 samples, 100,843,397
    bytes. 133 empty rp arrays dropped, 0 constant. Median length 22,336.
    253 distinct codes. 28 samples have flanking zero codes.
  - Every empty array had a pass count (fn/rn) of 0, and every non-empty
    array had a nonzero pass count.
  - Full statistics, including per-file counts and code histograms, are in
    `filtered/<id>/ingest_stats.json`.
- Breadth (zlsim gate, 2026-10-09): verdict OK, not redundant. The nearest
  feature distance is 0.072 (downstream `midi_note_velocity_u8`, loss 0.14),
  against a redundancy threshold of 0.05. The candidate's own OpenZL ratio is
  only about 1.56, so many generic 8-bit compressors come close to it. Against
  the accepted Sequel IPD family `zenodo_pacbio_sequel_subread_ipd_codecv1_u8`,
  the compression loss is 0.005, which is compression-equivalent, while the
  feature distance is 0.094-0.096, which is above the threshold.

## Homogeneity

One HPRC submission (WUSTL Fiber-seq): one instrument (Revio, movies
m84081_*), one chemistry (CM R/P2-C2/5.0-25M, the same binding, sequencing
and SMRT cell kits), one ICS/ccs/jasmine/lima build, a 100 Hz frame rate and
one codec. The DNA is human LCL DNA treated with an m6A methyltransferase.
That mainly perturbs IPD, and IPD is excluded here. fp and rp are the same
quantity on the two strands of the same molecules.

## Parsing

`scripts/hifi_bam.py` is a pure-stdlib BGZF/BAM reader, adapted from the
accepted Sequel IPD recipe. It walks BGZF blocks via the `BC` BSIZE
subfield, raw-inflates each one and checks CRC32/ISIZE, then parses the
header and records, including every aux type (A, c, C, s, S, i, I, f, Z, H
and all B subtypes). `verify.sh` re-derives every sample independently: it
inflates gzip members with `zlib.decompressobj(31)` without using BSIZE,
checks the header at string level, and uses its own skip-only aux walker.
It then compares bytes, order, per-sample min/max/distinct, scope (30
files and 25 individuals per series) and manifest totals. It fails on stale
files, constant samples, or a degenerate or one-code-dominated alphabet.

Self-tests (in `/tmp`, not shipped):
- A copy of the recipe was run on 30 synthetic prefixes that carried the
  real headers and records covering every aux type, empty `fp`, constant
  `rp` and flanking zeros. Build and verify passed, and verify caught a
  flipped sample byte and a stale file.
- On the real 4 MiB probe, both decoders produced byte-identical arrays
  (94 of 94).

## Reproduce

```
bash staging/hprc_revio_fiberseq_hifi_pulse_width_u8/download.sh
bash staging/hprc_revio_fiberseq_hifi_pulse_width_u8/build.sh
bash staging/hprc_revio_fiberseq_hifi_pulse_width_u8/verify.sh
```

All scripts honor `DATA_DIR` (default `.data`) and log under
`$DATA_DIR/logs/hprc_revio_fiberseq_hifi_pulse_width_u8/`.
