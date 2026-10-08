# PacBio Sequel subread IPD (CodecV1 uint8) development

## Outcome

Accepted `zenodo_pacbio_sequel_subread_ipd_codecv1_u8`. The family is per-base polymerase timing from one PacBio Sequel SMRT Cell: the inter-pulse duration (IPD) of each called base, as stored in the `ip` tag of the unaligned subreads BAM.

No local family holds single-molecule polymerase timing. The local 8-bit genomics families hold scores or symbols:
- base quality (`ena_fastq_quality_phred`)
- mapping quality (`bam_read_mapq_u8`)
- sequence letters (`ncbi_refseq_viral_genomes_u8`, `pfam_seed_alignments_u8`)

`zenodo_nanopore_slow5_i16` is nanopore ionic current, a different instrument and quantity.

## Source and rights

- Source: Zenodo record 13306684, "Material for LORA paper (Veillonella Parvula case)", Thomas Cokelaer, DOI 10.5281/zenodo.13306684.
- File: `veillonella.subreads.bam`, 5,927,559,159 bytes, md5 `5c2a00da331ed1b8479e7c080b800835`. download.sh re-checks both against the record listing.
- Transfer: bytes 0-268435455 (256 MiB, about 4.5% of the file). Prefix SHA-256 `1f5b05dd9f69dcbcc3b6c595b3a0d328d7f238f2eba2f96106dabf5b0b782ecb`, pinned in download.sh, build.sh, verify.sh and the manifest.
- License: CC BY 4.0. The record metadata declares `license.id = cc-by-4.0` (checked live on 2026-10-08), with open access.
- Provenance: the record says the subreads BAM "was kindly provided by the authors" of the original study (PubMed 32817093) for reproducibility. ENA run ERR3958992 holds only FASTQ.
- Organism: a *Veillonella parvula* bacterial isolate. No human or personal data.

## Shape and conversion

Header facts, asserted by all three scripts from the single `@RG` line:
- READTYPE=SUBREAD, Ipd:CodecV1=ip, PulseWidth:CodecV1=pw
- binding kit 100-862-200, sequencing kit 100-861-800
- basecaller 5.0.0.6236, FRAMERATEHZ=80, PM:SEQUEL, PU m54091_180306_141024

The Zenodo text says "Sequel II", but the header (PM:SEQUEL) and the 54xxx movie name indicate Sequel I. The recipe records what the header says.

Natural record: one subread, i.e. one BAM record (movie/ZMW/qStart_qEnd). Its `ip` array (type B, subtype C) is copied unchanged as one uint8 sample.

Record checks:
- unaligned (flag 4), read group dbce2615
- zm/qs/qe tags agree with the read name
- `ip` length equals both l_seq and qe-qs
- no duplicate names

Prefix handling: the truncated final BGZF block and the final incomplete record are dropped.

The 8-bit codes are CodecV1, the lossy, monotone companding code that the PacBio BAM spec says the default production configuration writes. Codes 0-63 cover frames 0-63; 64-127 cover 64-190 in steps of 2; 128-191 cover 192-444 in steps of 4; 192-255 cover 448-952 in steps of 8; durations above 952 frames cap at 952. The codes are kept as stored, not decoded or widened. The series is labelled `derived_operational_numeric`, following `asterisk_core_sounds_ulaw_u8`.

Pulse width (`pw`), bases, qualities, `sn`, `rq`, `np` and `cx` are excluded.

## Accepted output

- BGZF blocks inflated (CRC and length checked): 10,038
- Complete subread records: 14,550, all kept (0 empty, 0 constant)
- Distinct ZMWs (molecules): 9,840
- Primary samples: 14,550
- Primary values and bytes: 139,127,891 uint8
- Subread length: min 52, p05 622, p10 1,310, p25 3,858, median 9,561.5, p75 13,878, p90 17,720, p95 20,481, max 72,253
- Samples under 1,000 values: 1,139 (7.8%), kept as natural records
- Code mass: 83.9% in 0-63, 10.4% in 64-127, 2.7% in 128-191, 3.0% in 192-255; capped code 255 is 1.95%
- Distinct codes: 145 of 256
- Aggregate SHA-256 of all samples concatenated in index order: `951d71fd4863f42288ebd305301f464b642506e9250321cef93b70499e917a99`
- Measured breadth (zlsim): OK. The nearest family is `noaa_wcsd_em302_water_column_i8` at distance 0.0651 (loss 0.14); the family's own compression ratio is about 1.24.

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** I ran `verify.sh` myself and it passed (14,550 samples, 139,127,891 values, prefix SHA matches). build.sh, verify.sh and the parser have no network calls and no credentials.
- **Third independent parse:** the Python `gzip` module plus my own record and aux walker matched all 14,550 samples byte for byte, in order. It found one more record (zmw 12386881) only by using partially inflated bytes from the truncated final BGZF block. That block's CRC cannot be checked, so the build is right to drop it.
- **Code lattice:** 145 codes occur: all of 0-64; only even codes from 66 to 190; only multiples of 4 from 192 to 252; and 255. Every code is valid CodecV1. The lattice is coarser than the codec allows, because of quantization upstream of baz2bam; the recipe does not cause it.
  - README erratum: in frames, the stored steps are 1 for 0-63, 4 for 64-188, 8 for 192-440 and 32 for 448-928, plus the 952 cap. The README's "by 4 up to about 444 frames, and by 32 above that" is slightly off; this is documentation only and does not affect the bytes.
- **Physical plausibility:** median code 20 means 20 frames, i.e. 0.25 s at 80 Hz. The mean is 61 decoded frames. Per-subread mean IPD runs from 8.4 to 300.6 frames. Order-0 entropy is 6.32 bits.
- **Fill and degeneracy:** per-sample mode share has median 0.040 and max 0.219 (the cap code in one slow read). No sample is dominated by one value.
- **Near-duplicates:** none by MD5. Over 387 same-molecule subread pairs, equal codes at the same position occur 1.71% of the time vs 1.72% expected by chance. Lag-1 autocorrelation median is 0.087. These are independent stochastic measurements, not repeated content.
- **Spec:** the PacBio BAM spec page confirms the CodecV1 table and that "in the default production instrument configuration, the lossy encoding will be used".
- **Rights:** the live Zenodo API shows cc-by-4.0 and open access for the record containing this exact file.
- **Novelty:** `novelty.py` found no pacbio, kinetics, subread, polymerase or SMRT hits in datasets, the registry or downstream. The 'ipd' hits are Citi Bike substrings. The breadth-key search (polymerase_kinetics / pacbio_sequel_smrt / zenodo) matched 0 families.
- **Host cap:** Zenodo already hosts many accepted families, so the driver's same-host sign-off rule applies.
