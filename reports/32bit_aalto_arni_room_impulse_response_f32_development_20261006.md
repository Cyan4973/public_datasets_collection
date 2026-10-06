# Aalto Arni room impulse response float32: development report

## Outcome

Accepted `aalto_arni_room_impulse_response_f32`: measured room impulse responses (RIRs) from the variable-acoustics laboratory "Arni" at the Aalto University Acoustics Lab, kept as native IEEE float32.

It is the first 32-bit audio or RIR family. The RIR modality already exists at 16-bit (`openslr_rirs_noises_pcm16` locally, `measured_room_impulse_response_i16` downstream), so the novelty is a new source, not a new modality. The upstream WAVs are natively WAVE_FORMAT_IEEE_FLOAT, so this is not a width mirror.

Acceptance took two judge repair cycles:

1. **Duplicated receivers.** In four configurations of the out-of-sequence special block (numComb 5, 7, 21, 27), several receiver labels held one acoustic response (r ≥ 0.9995).
   - Fix: exclude numComb 2..31, and add a fatal receiver-distinctness check (max pairwise |r| < 0.5 on samples [1500, 17884)) in two separate implementations.
   - That check then caught the same fault at the first regular configuration of numClosed 11, 27 and 35. Probes found it across those blocks too, so the three levels are excluded entirely.
2. **One hollow-width sample.** The member numClosed 16 / numComb 1542 / mic 5 held int16-quantized data written as float32: 100% of values on the 2^-15 lattice and 192 distinct codes.
   - Fix: a metadata-only selection rule requiring at least 200,000 compressed bytes per member, plus a fatal float-lattice and distinct-pattern check written twice.
   - Only 4 of the 132,037 members fall below 200,000 B (12.8–13.8 KB, all numClosed 16 / mic 5). The rule moves level 16 from numComb 1542 to 1545.

## Source and rights

- Source: Zenodo record 6985104, "Dataset of impulse responses from variable acoustics room Arni at Aalto Acoustic Labs" (Prawda, Schlecht, Välimäki; published 2022-08-12; DOI 10.5281/zenodo.6985104).
- Upstream: 132,037 WAVs covering 5,342 panel configurations × 5 receivers × up to 5 sweeps.
  - They sit in six DEFLATE ZIP archives of 4.27–9.66 GB, 50,887,756,849 B in total.
  - One archive has a classic end-of-central-directory record; the other five are ZIP64.
  - `combinations_setup.csv` (1,206,376 B, SHA-256 `6cd64c3f…5fbd98`) gives the panel states.
- Integrity pins:
  - each archive's size, Zenodo MD5 (provenance only) and central-directory SHA-256, in `zip_archives.tsv` (17,635,185 B of directories);
  - each member's CRC-32 and byte range, in `selection.tsv`.
- License: CC-BY-4.0, set in the record metadata (`metadata.license.id = cc-by-4.0`, `access_right = open`) for every file of the record. `download.sh` re-validates it on every run.
- No credentials. Empty-room acoustic measurements; no personal data.

## Shape and conversion

- **Natural record:** one impulse-response WAV member, `IR_numClosed_<k>_numComb_<c>_mic_<m>_sweep_1.wav`.
  - Layout: fmt (3, 1, 44100, 176400, 4, 32), then fact, PEAK and data chunks.
  - The data chunk is 423,360 B, i.e. 105,840 float32 values (2.4 s).
- **Acquisition:** curl byte ranges only.
  - Fetch a 64 KiB tail and then the exact central directory of each archive.
  - Fetch one exact local-header-plus-DEFLATE range per member (with 4 KiB of slack).
  - Every 206 response's Content-Range total is checked against the pinned archive size.
- **Decoding:**
  - Raw inflate with an exact-boundary check, then CRC-32 against the central directory.
  - A RIFF walk validates fmt, fact and PEAK (PEAK must equal max |x| and its position).
  - The data chunk is written unchanged as one raw little-endian float32 sample.
- **Selection** (deterministic, central directory only):
  - For each numClosed 0..55 except 11, 27 and 35, take the lowest numComb outside 2..31 whose sweep_1 member exists for all five mics, with each member at least 200,000 compressed bytes.
  - Sweep_1 fallbacks: numClosed 1 → 94, 30 → 2943, 49 → 4843.
  - Repeat sweeps 2..5 are excluded as near-duplicates.
- **Fatal guards** in both the download/build path and the separately written verify:
  - finiteness, plus non-zero and non-constant data;
  - receiver distinctness;
  - int16-lattice fraction < 1%;
  - at least 50,000 distinct bit patterns;
  - in verify, the compressed-size floor;
  - the panel table must agree with numClosed.

## Accepted output

- Primary series: `arni_room_impulse_response_f32` (float, 32-bit, little-endian).
- Samples: 265 (53 levels × 5 receivers), each 105,840 values / 423,360 B.
- Primary values: 28,047,600.
- Primary bytes: 112,190,400.
- Value range: -2.228e-2 .. 2.376e-2.
- Peak |x|: 1.609e-3 .. 2.376e-2 (median 6.465e-3).
- Noise-tail RMS over 2.0–2.4 s: 2.633e-7 .. 2.407e-6 (median 2.071e-6).
- Receiver distinctness: 53 configurations, max |r| 0.0863, median 0.0597.
- Largest cross-configuration same-mic |r|: 0.9715 (mic 4, numClosed 54 vs 55, one panel apart). Informational only.
- Float lattice: max int16-lattice fraction 0.000009; min distinct bit patterns 105,039.
- Aggregate decoded SHA-256: `3fa1c77f27d43159b369240c86c971f9cd2487f829c3482e3b0c6c99cbef3229`.
- Download footprint: about 122 MB transferred and 131,542,939 B on disk, against a 50.9 GB upstream.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/aalto_arni_room_impulse_response_f32` passes with no warnings.
- **Verify:** I ran `bash staging/aalto_arni_room_impulse_response_f32/verify.sh` myself (exit 0). It reported compressed_size_ok (min 370,163), receiver_distinctness_ok, float_lattice_ok and verify_ok, with totals matching the manifest.
- **Local-only build:** `build.sh` reads only `.data/downloads/<id>/`. Network calls appear only in download.sh and discover.sh, through fetch_lib.sh. The latest download log shows the 1542 WAVs pruned, the 1545 WAVs fetched and validated, and every final check passing. The WAV cache holds exactly 265 files.
- **Bytes** (stdlib struct over all 265 samples):
  - share of values with a set mantissa LSB: 0.496–0.504, i.e. full 23-bit mantissas;
  - exponents 85..121;
  - int24-lattice fraction ≤ 8.5e-5;
  - zlib-6 ratio 0.877–0.929;
  - direct-sound peak at samples 1802–2745.
- **Physics:** the Schroeder -30 dB time rises steadily with numClosed (0.26 s at 0, 0.33 s at 20, 0.46 s at 45, 0.67 s at 55). Mic 2's peak is a reflection after the direct arrival.
- **Not duplicates:** noise-tail |r| for 25 random pairs is ≤ 0.11 (median 0.03). The most similar pair (54 vs 55, mic 4) has full r 0.97 but tail r 0.02, so it holds independent recordings.
- **Size evidence:** my own central-directory parser, written separately from the recipe's, found 132,037 members, all 423,440 B uncompressed. Exactly 4 are below 200,000 compressed bytes (16/1594/5 at 12,811 B, 16/1542/5 at 13,037, 16/1543/5 at 13,349, 16/1544/5 at 13,840). The next smallest is 342,676 B. The numComb 1545 members are 376,482–393,117 B.
- **Rights:** I read the license from the local record.json and from a live API probe: cc-by-4.0, open, published. The record description explains the missing sweeps (discarded upstream for non-stationary noise), which matches the documented fallbacks.
- **Novelty:** `novelty.py` finds no URL match except this staging recipe. RIR terms match only the 16-bit families. There is no 32-bit audio family locally, downstream or in this effort's accepted ledger.
- **Accepted caveats:**
  - Scope is 53 of 56 levels; the excluded levels have faulty upstream receiver files, with the evidence documented.
  - Much of each record is the measured noise tail; it is real material.
  - Session gain varies by about 10× in peak.
