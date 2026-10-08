# PacBio Sequel subread inter-pulse duration (IPD, CodecV1 uint8)

Per-base polymerase kinetics from one PacBio SMRT Cell movie: for every
called base of a subread, the instrument's 8-bit CodecV1 code for the
inter-pulse duration (IPD), as stored in the `ip` tag of the unaligned
subreads BAM. One sample = one subread = one BAM record.

## Source and license

- Zenodo record 13306684, "Material for LORA paper (Veillonella Parvula case)",
  Thomas Cokelaer, DOI 10.5281/zenodo.13306684, published 2024-08-12.
- Record metadata: `"license": {"id": "cc-by-4.0"}` (CC BY 4.0). The record
  text says the subreads BAM "was kindly provided by the authors and is shared
  here to ensure full reproducibility of our analysis". The original study is
  PubMed 32817093. ENA/SRA run ERR3958992 holds only FASTQ, without kinetics.
- File: `veillonella.subreads.bam`, 5,927,559,159 bytes, md5
  `5c2a00da331ed1b8479e7c080b800835` (Zenodo listing, re-checked by
  `download.sh`).
- Organism: a *Veillonella parvula* bacterial isolate. No human data.

## What the header says

`download.sh`, `build.sh` and `verify.sh` all assert the single `@RG` line:

```
@RG ID:dbce2615 PL:PACBIO
    DS:READTYPE=SUBREAD;Ipd:CodecV1=ip;PulseWidth:CodecV1=pw;
       BINDINGKIT=100-862-200;SEQUENCINGKIT=100-861-800;
       BASECALLERVERSION=5.0.0.6236;FRAMERATEHZ=80.000000
    PU:m54091_180306_141024 PM:SEQUEL
```

The Zenodo text says the study used a "PacBio Sequel II", but the BAM header
says `PM:SEQUEL`, with an 80 Hz frame rate and a 54xxx (Sequel I) movie name.
This recipe records what the header says: Sequel. `@PG` is
`baz2bam 5.0.0.6236` with `--minSubLength 50`. The BAM is unaligned
(`n_ref = 0`, flag 4), and the PacBio spec version is `pb:3.0.3`.

## The quantity and CodecV1

The IPD of a base is the number of camera frames (80 per second here)
between the previous incorporation pulse and this base's pulse. The Sequel
default production configuration stores it with the lossy, monotone 8-bit
CodecV1 described in the PacBio BAM spec
(<https://pacbiofileformats.readthedocs.io/en/latest/BAM.html>), with a
reference implementation in pbcore:

| code     | frames represented | step |
|----------|--------------------|------|
| 0-63     | 0-63               | 1    |
| 64-127   | 64-190             | 2    |
| 128-191  | 192-444            | 4    |
| 192-255  | 448-952            | 8    |

Decoding: `frames = c` for c < 64; `64 + 2(c-64)` for c < 128;
`192 + 4(c-128)` for c < 192; `448 + 8(c-192)` otherwise. Durations over 952
frames are capped at 952 (code 255). Other durations are rounded to the
nearest representable value before encoding.

**The recipe emits the codes as stored.** It does not decode them to frames
and does not widen them to uint16. CodecV1 is a pinned, per-value companding
code, the same kind of instrument-native representation as G.711 mu-law
(cf. `asterisk_core_sounds_ulaw_u8`). The series is therefore declared
`derived_operational_numeric`. The table above is documentation only.

Pulse width (`pw`, also CodecV1) is excluded so the family holds a single
quantity. Bases, qualities, `sn`, `rq`, `np`, `cx` and the other tags are
also excluded.

## Scope and boundaries

- Transfer: a fixed prefix of the BAM, bytes `0-268435455` (256 MiB, about
  4.5% of the file), fetched with curl offset ranges. A partial file is
  resumed from its current size. Each response must be a 206 whose
  Content-Range starts at that offset. Stalls are detected with
  `--speed-limit/--speed-time`, never `--max-time`. The prefix is pinned by
  size and SHA-256. The full-file md5 does not apply to a prefix.
- The truncated final BGZF member and the final, incomplete BAM record are
  dropped. Every other record in the prefix is used, in physical file order,
  so the realized count is fixed by the pinned prefix and no other cap
  applies.
- Natural record: one subread (movie/ZMW/qStart_qEnd), i.e. one
  adapter-delimited pass of one molecule. Subreads of the same ZMW are
  separate samples and are never concatenated.
- Short subreads, including those under 1,000 bases, are kept. Only empty
  or single-valued `ip` arrays would be dropped and counted. A 4 MiB probe
  had none.
- 4 MiB probe (229 subreads, 160 ZMWs, 2,164,337 values): subread length min
  78, p10 1,452, median 9,470, p90 17,965, max 26,469; 16 of 229 under 1,000.
  Code mass: 82.9% in 0-63, 10.9% in 64-127, 2.9% in 128-191, 3.2% in
  192-255 (2.1% at the capped code 255); 145 distinct codes.
- Realized from the pinned 256 MiB prefix (SHA-256
  `1f5b05dd9f69dcbcc3b6c595b3a0d328d7f238f2eba2f96106dabf5b0b782ecb`):
  10,038 complete BGZF members and 14,550 complete subread records, all
  kept (0 empty, 0 constant), from 9,840 distinct ZMWs. That is 139,127,891
  uint8 values (139.1 MB). Subread length: min 52, p05 622, p10 1,310, p25
  3,858, median 9,562, p75 13,878, p90 17,720, p95 20,481, max 72,253;
  1,139 subreads (7.8%) are under 1,000 values. The 65,280 decompressed bytes
  of the final incomplete record were dropped.
- Code mass: 83.9% in 0-63, 10.4% in 64-127, 2.7% in 128-191, 3.0% in
  192-255; 1.95% at the capped code 255.

### Sparse code lattice (a property of the source)

Only 145 of the 256 codes occur. Codes 0-64 all appear. Above 64 only even
codes appear (66, 68, ..., 190). From 192 only multiples of 4 appear (192,
196, ..., 252), plus the cap code 255. In frames, the stored durations
therefore step by 1 up to 64 frames, by 4 up to about 444 frames, and by 32
above that, which is coarser than CodecV1 itself allows. This looks like
upstream quantization in the Sequel 5.0 basecaller/BAZ pipeline before the
BAM was written. It is reproduced exactly as stored and is not introduced by
this recipe, which copies the bytes unchanged.

## Homogeneity

One movie, one Sequel instrument, one binding and sequencing kit, one
basecaller version, one frame rate, one organism, one codec and one tag.
Diversity comes from many independent single molecules (ZMWs).

## Parsing

`scripts/pacbio_bam.py` is a pure-stdlib BGZF/BAM reader. It walks gzip
members using the `BC` BSIZE subfield, inflates them with raw deflate and
checks CRC32/ISIZE, then parses the BAM header and the records (32-byte core,
name, cigar, 4-bit seq, qual, aux). The aux parser handles A, c, C, s, S, i,
I, f, Z, H and B (all subtypes), because several tags (`cx`) precede `ip`. It
was self-tested on synthetic BGZF/BAM data with every aux type, truncated
prefixes at many cut points and a corrupted CRC.

`verify.sh` re-derives every sample with independent code: gzip-member
inflation via `zlib.decompressobj(31)` without using BSIZE, and a separate
skip-only aux walker. It compares bytes, order, read names, per-sample
min/max/distinct, index fields and manifest totals, and fails on stale
files, duplicates, constant samples or a degenerate code alphabet.

## Reproduce

```
bash staging/zenodo_pacbio_sequel_subread_ipd_codecv1_u8/download.sh
bash staging/zenodo_pacbio_sequel_subread_ipd_codecv1_u8/build.sh
bash staging/zenodo_pacbio_sequel_subread_ipd_codecv1_u8/verify.sh
```

All scripts honor `DATA_DIR` (default `.data`) and log under
`$DATA_DIR/logs/zenodo_pacbio_sequel_subread_ipd_codecv1_u8/`.
