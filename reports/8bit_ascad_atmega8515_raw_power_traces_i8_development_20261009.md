# ASCAD ATMega8515 raw side-channel traces int8 development

## Outcome

Accepted `ascad_atmega8515_raw_power_traces_i8`: 1,500 complete raw electromagnetic side-channel oscilloscope acquisitions from ANSSI's ASCAD v1 fixed-key campaign. The device is an ATMega8515 running Boolean-masked AES-128. Values are native signed int8 digitizer codes.

This is the corpus's first cryptographic side-channel material and its first 8-bit oscilloscope family. The only other `oscilloscope_trace` family is `zenodo_lecroy_oscilloscope_i16`, which holds 16-bit RF-antenna and photomultiplier traces of hypervelocity impacts. The novelty is therefore a new source and material, not a new modality.

## Source and rights

- Source: data.gouv.fr dataset `ascad` (id `5aaa829dc751df2fbd43eacb`), organization Agence Nationale de la Sécurité des Systèmes d'Information (ANSSI)
- Archive: `https://static.data.gouv.fr/resources/ascad/20180530-163000/ASCAD_data.zip`
  - 4,435,199,469 B
  - sha1 `fb8c8a71423c80795b4f8592c50891134902666a` (API)
- Member: `ASCAD_data/ASCAD_databases/ATMega8515_raw_traces.h5`
  - method 8 (DEFLATE), crc32 `1cf4a0bf`
  - compressed 2,966,104,128 B, uncompressed 6,003,842,144 B
  - local header at offset 72,006,934
- License: Licence Ouverte / Open Licence (`fr-lo`; flags `okd_compliant`, `domain_data`, `domain_content`; attribution required)
  - The API record of the dataset declares it.
  - The record lists `ASCAD_data.zip` as one of its resources, so the license covers this exact object.
- Not used:
  - the variable-key ASCAD dataset, whose license is `notspecified`
  - the BSD license of the GitHub companion repo, which covers code only

## Shape and conversion

- Natural record: one row of the HDF5 dataset `/traces` (60,000 × 100,000, `H5T_STD_I8LE`), i.e. one 100,000-point acquisition of one AES execution.
- Acquisition: a 4,096 B zip tail (zip64 EOCD and central directory, sha256 `bbc7bb44…d3`) plus a pinned 92,000,000 B range from the member's local header (sha256 `256f0a93…cc41`). The 4.4 GB archive is never fetched.
- Decode steps:
  1. Check the local header against the central directory.
  2. Stream-inflate the prefix with `zlib.decompressobj(-15)`.
  3. Parse HDF5 with pure stdlib:
     - superblock v0, whose EOF must equal the member size
     - root B-tree, local heap and SNOD, giving links `metadata` and `traces`
     - the `/traces` object header: dataspace, signed 1-byte fixed-point datatype, no filter pipeline, v3 contiguous layout at 3,842,144 with size 6,000,000,000

     Each parsed value is asserted against its expected value.
- Rows 0..1499 are written verbatim in acquisition order; only complete traces are written.
- The `/metadata` compound dataset (plaintext, key, masks) is not emitted.
- The subset is the first N traces because a DEFLATE stream cannot be seeked. A spread-out selection would require the full 2.97 GB stream.

## Accepted output

- Primary series: `ascad_atmega8515_raw_trace_i8`
- Samples: 1,500 (trace_00000 … trace_01499) of 60,000 upstream
- Values / bytes: 150,000,000 / 150,000,000; every sample is 100,000 values
- Value range: −71 … 58
- Distinct values per trace: 115 / 119 / 122 (min / median / max)
- Order-0 entropy: about 6.4 bits per trace
- Most common value share: at most 0.0255
- Total variance: 693.5 LSB²
- Mean per-time-index inter-trace variance: 5.80 LSB² (0.84%)
- Adjacent-trace mean |diff|: 0.91 / 2.10 / 7.61 LSB (min / median / max); 0 identical traces
- Aggregate SHA-256: `8de1a40097e501b2ddf9dd5b4173bfa189d7b6b61396d694c2963fd9be75a657`
- Download: 92,004,096 B, plus the API JSON
- Breadth (zlsim): OK. The nearest family is `noaa_wcsd_em302_water_column_i8` at distance 0.0595 with 5.85% compression loss.

## Judge checks

- `gate.py staging/ascad_atmega8515_raw_power_traces_i8`: PASS, no warnings.
- I re-ran `bash verify.sh`: selftest ok, zip-tail validation ok, `verify=ok samples=1500 total_bytes=150000000`, and the aggregate sha256 above.
- build, verify and the parser contain no network calls (no curl, urllib or socket), and no script contains credentials.
- Bytes: I decoded traces 0, 1, 2, 500, 1000 and 1499 with `struct`.
  - Values fall in −70..56, with sd about 26.4 and 118–120 distinct values.
  - Odd-value fraction is 0.501 and mod-4 residues are uniform, so codes are native, not widened.
  - The waveforms are smooth and clock-driven, with no fill.
- Near-duplicate test, in the style of earlier judges:
  - Traces correlate at r≈0.99.
  - xz conditional gain for a neighbour or distant trace is 8.7–11.5%.
  - Ten traces compressed jointly save 16%.
  - The residual against a 50-trace mean has sd 1.41 LSB and still compresses to 25 KB per trace, against 43 KB for the raw trace.

  These are synchronized but distinct acquisitions, which is the intrinsic shape of side-channel trace sets, not duplicated content.
- Rights: I fetched the data.gouv.fr API record and its license list myself. They show `license: fr-lo`, publisher ANSSI, and the ASCAD_data.zip resource with matching size and sha1.
- Signal claim: the upstream fixed-key README (github.com/ANSSI-FR/ASCAD, ATM_AES_v1_fixed_key) is titled "ATMEGA8515, AES Boolean masking, fixed key, EM acquisition" and states 60,000 synchronized, fixed-key traces. This confirms the manifest's "electromagnetic" wording. "power" in the dataset id is the generic side-channel term only.
- Novelty: `novelty.py` on the archive URL, dataset page and GitHub repo, plus the terms ascad, atmega8515, side-channel and anssi, found no match outside this staging recipe. The downstream u8 source list has no side-channel or oscilloscope family. The type/instrument/archive query matched only `zenodo_lecroy_oscilloscope_i16` (16-bit) on measurement type.
- Homogeneity: one device, key, setup and campaign, with identical length and scale.
