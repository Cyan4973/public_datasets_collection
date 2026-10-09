# HPRC Revio Fiber-seq HiFi pulse width (CodecV1 uint8) development

## Outcome

Accepted `hprc_revio_fiberseq_hifi_pulse_width_u8`. The family holds per-base polymerase **pulse width** from PacBio Revio HiFi reads. On-instrument `ccs` averages it over the subread passes of each strand. It is stored as 8-bit CodecV1 codes in the BAM `fp` (forward) and `rp` (reverse) tags.

The only comparable local family is `zenodo_pacbio_sequel_subread_ipd_codecv1_u8`. It differs in four ways:
- Quantity: inter-pulse duration (IPD), not pulse width.
- Read type: raw per-pulse subreads, not pass-averaged consensus.
- Instrument: Sequel at 80 Hz, not Revio at 100 Hz.
- Source: a bacterial Zenodo record, not the HPRC bucket.

The downstream corpus has no PacBio kinetics. The novelty is a new quantity within the polymerase-kinetics modality. IPD (`fi`/`ri`) is deliberately excluded, because a probe put it within 0.05 of the Sequel IPD family.

## Source and rights

- Source: AWS Open Data, Human PanGenomics Project, bucket `s3://human-pangenomics` (us-west-2), submission `submissions/4f00ec2d-4533-40e3-b0ca-624ab5a559d9--WUSTL_HPRC_PacBio_FiberSeq/`.
- The submission holds 240 keys: 60 BAMs plus `.pbi` and `.md5` sidecars. The 30 `*.hifi_reads.*.bam` objects are 340.8-515.3 GB each, 13.35 TB in total, from 25 individuals. Five of them (HG06799, HG06800, HG06801, HG06802, HG06805) have two SMRT Cells each.
- Pinning: keys, sizes and S3 ETags are pinned in `scripts/bams.tsv`. `download.sh` HEAD-checks each object before transfer.
- Transfer: bytes 0-12582911 (12 MiB) of each BAM, 377,487,360 bytes in total. Prefix SHA-256s are recorded in `prefix_inventory.tsv` and re-checked by build and verify.
- License: CC0 1.0. The AWS registry entry `hpgp-data.yaml` states `License: "[Creative Commons CC0 1.0 Universal]..."` for `arn:aws:s3:::human-pangenomics`, and `download.sh` re-checks that line and the ARN on every run. The submission prefix contains no separate terms file.
- Material: DNA from openly consented 1000 Genomes / HPRC lymphoblastoid cell lines, treated with an m6A methyltransferase (Fiber-seq). Only pulse-width arrays are emitted. Bases, qualities, IPD, MM/ML, read names and ZMW numbers never reach samples or the index.

## Shape and conversion

Header contract, asserted for all 30 files by the parser and independently by `verify.sh`:
- READTYPE=CCS, Ipd:CodecV1=ip, PulseWidth:CodecV1=pw
- binding kit 103-496-900, sequencing kit 103-496-700, SMRT Cell kit 102-202-200, basecaller 5.0
- ICS 13.3.0.253824, MOVIELENGTH 1800, FRAMERATEHZ 100, PM:REVIO, CM R/P2-C2/5.0-25M
- @PG ccs 8.2.0, pbtrim 1.1.0, jasmine 2.3.0 `--6ma`, lima 2.11.0
- PU equal to the movie, SM equal to `<sample>_FS`, no reference sequences

Natural record: one HiFi read (`<movie>/<zmw>/ccs`). Each non-empty strand array becomes one sample, with length equal to the read length.

Conversion:
- The `fp` and `rp` B:C payloads are copied unchanged.
- `rp` keeps its stored order (last-to-first relative to SEQ, i.e. polymerase traversal order), recorded per sample as `array_order`.
- CodecV1 is the instrument's pinned monotone companding code: 0-63 → 0-63 frames, then steps of 2, 4 and 8 up to 952 frames, with 255 meaning capped. The codes are not decoded or widened, so the series are `derived_operational_numeric`, as in the Sequel IPD family.

Record checks: unaligned (flag 4), single read group, `/ccs` names, no duplicate ZMW, both tags present as B:C with length 0 or l_seq, and integer `fn`/`rn` pass counts.

Prefix handling: the truncated final BGZF block and the truncated final BAM record of each prefix are dropped.

Missing values:
- Empty arrays are dropped and counted (fp 81, rp 133). Every one has pass count 0, and every kept array has a nonzero pass count.
- Constant arrays would be dropped; there were none.
- Flanking zero codes are kept and counted per sample (fp 13 samples, rp 28).

## Accepted output

- Files used: 30 of 30, none skipped. Individuals: 25.
- Complete records: 4,461 (134-167 per file).
- `hifi_forward_pulse_width_codecv1_u8`: 4,380 samples, 102,223,623 bytes, median length 22,347.5.
- `hifi_reverse_pulse_width_codecv1_u8`: 4,328 samples, 100,843,397 bytes, median length 22,336.
- Total: 8,708 samples, 203,067,020 uint8 values and bytes. Median sample 22,341.5 values, min 9,840, max 51,655. No sample is under 1,000 values.
- fp code mass: 98.85% in 0-63, 1.106% in 64-127, 0.041% in 128-191, 0.002% in 192-255. rp is nearly identical.
- Codes overall: median 15, mean 18.07. Top codes 10, 12, 14, 8, 16. All 256 codes occur (fp 245 distinct, rp 253).
- Rare codes: code 0 occurs 81 times in fp and 830 in rp; code 255 occurs 6 times in fp and 11 in rp.
- Order-0 entropy: 5.14 bits (fp), 5.13 bits (rp).
- Strand pass counts: 1-9 (mode 2).
- Aggregate SHA-256 of all samples in index order: `6666a8ec7f826a353accea07f230c088223baa59f28ffcdc28b2227e3ba06722`.
- Measured breadth (zlsim): OK.
  - The nearest family is `midi_note_velocity_u8` at 0.0723 (fp) and 0.0721 (rp), loss about 0.14. Own OpenZL ratio: 1.557 (fp), 1.566 (rp).
  - Against the Sequel IPD family the builder measured loss 0.0048 (compression-equivalent) and feature distance 0.094-0.096, so it is not redundant under the two-condition rule.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Verify:** I ran `verify.sh` myself: `verify ok files=30 samples=8708 primary_bytes=203067020`. build.sh, verify.sh and `scripts/hifi_bam.py` have no network calls and no credentials. download.sh uses anonymous HTTPS only.
- **Third independent parse:** I used my own zlib gzip-member inflater and aux walker on file 23 (HG06800, m84081_250725_154042_s1).
  - The header matched the claimed contract.
  - All 12 fp/rp arrays of the first 6 records were byte-identical to the emitted samples, and every length equalled l_seq.
- **Strand independence:** over 40 random paired reads:
  - fp vs SEQ-aligned rp: median correlation 0.085 (range 0.017-0.146), with 4.0% equal codes at the same base.
  - Interleaving fp and rp before lzma saves only 0.2%.
  - The two series are independent measurements on complementary strands, not duplicated views.
  - Lag-1 autocorrelation median: 0.079.
- **Duplicates and fill:** no duplicate payloads among 8,708 samples (SHA-1). Per-sample mode share has median 0.069 and max 0.149. No fill warnings.
- **Lattice:** all 256 CodecV1 codes occur, as expected when ccs re-encodes pass-averaged widths; the Sequel subread family's upstream quantization leaves gaps. Even codes are over-represented at low range: 67.5% of codes 4-31 for single-pass strands, falling to about 53% at 6+ passes. This is native basecaller granularity smoothed by averaging and appears identically in both series, so it is not a recipe artifact.
- **Plausibility:** median code 15 is 15 frames (0.15 s at 100 Hz). Per-read mean ranges from 10.6 to 33.8. Pulse widths are shorter and less heavy-tailed than the Sequel IPD codes, as expected.
- **Sampling:** ZMW numbers at the file heads are unordered (for example 257.6M, 250.9M, 238.0M), so each prefix is an effectively random draw of reads, not one spatial block of the SMRT Cell.
- **Rights:** I read the downloaded `hpgp-data.yaml` (CC0 1.0 for `arn:aws:s3:::human-pangenomics`) and listed the submission prefix (240 BAM/pbi/md5 keys, no separate terms).
- **Novelty:** `novelty.py --url` had no hits beyond this draft. The term search hit only the Sequel IPD family. The breadth-key search found 1 family of the same measurement type and 0 of the same instrument line or archive. The downstream 8-bit genomics families are only phred, MAPQ and bases.
- **README erratum:** the README and builder summary say no values are code 255. The build actually contains 6 (fp) and 11 (rp); `ingest_stats.json` rounds the fraction to 0.0. This is documentation only and does not affect the bytes. The manifest correctly says code 255 is preserved.
