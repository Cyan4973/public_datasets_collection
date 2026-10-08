# LoRaIQ SF10 over-the-air LoRa frame I/Q (cf32) development

## Outcome

Accepted `zenodo_epfl_loraiq_sf10_iq_frames_f32` from the immutable EPFL
LoRaIQ v1.0.0 Zenodo record.

This family adds 32-bit complex-baseband RF I/Q to the corpus. The modality is
already present at 16 bits, in `zenodo_v16_nb_iot_sigmf_ci16` and
`zenodo_crab_giant_pulse_sigmf_ci16` (downstream `crab_giant_pulse_iq_ci16`),
so the novelty is new content in a known modality, not a new modality.
This recipe uses a different source and receiver chain: terrestrial LoRa
chirp-spread-spectrum uplinks from a UAV, received by four USRP-2920 rooftop
remote radio heads. The source publishes the recordings natively as SigMF
`cf32_le` with continuous float values; they are not a widened copy of an
existing int16 file. The measured breadth verdict is OK: the nearest family
is downstream `susy_lepton1_eta` at feature distance 0.0517, with compression
loss 0.0569.

## Source and rights

- Source: Zenodo record 17708397, "LoRaIQ: Experimental LoRa Dataset with
  Annotated IQ Samples", Joachim Tapparel and Andreas Burg (EPFL), version
  1.0.0, 2025-12-01, doi:10.5281/zenodo.17708397
- `sigmfs.zip`: 49,746,561,196 B, md5 `3dc5fbc66ad24aeaa1d1d2a1801c400a`
  (ZIP64, 143,275 entries; central directory 17,305,251 B at offset
  49,729,255,847, sha256 `67649655…b634fa`)
- `dataset.csv`: 18,306,157 B, md5 `b92831a0c897154e95430e399122791c`
  (75,086 frame rows)
- License: CC BY 4.0. The record metadata declares license id `cc-by-4.0`
  for the whole open-access record. `download.sh` re-checks the id, title,
  version, license, and both files' sizes and MD5s on every run.

## Shape and conversion

Each natural record is one SigMF recording (`<n>.sigmf-data` plus
`<n>.sigmf-meta`) holding exactly one detected LoRa frame and the surrounding
channel noise. Each sample is the complete `.sigmf-data` stream, which is
headerless little-endian interleaved float32 I,Q, written unchanged.

Scope is pinned to one configuration: SF10, CR 4/5, BW 250 kHz, 500 ksps,
862.5 MHz, UAV transmitter, `drone_los` and `drone_nlos`. That covers 41,229
rows with one frame per file. The SF7 / 125 kHz / 250 ksps `pedestrian_nlos`
sessions (33,857 rows) are excluded. Selection is stratified by (session,
RRH): 16 sessions × 4 RRHs = 64 strata, with 4 files per stratum at positions
floor((k+0.5)·N/4) in file-number order. The four 2025-09-18 sessions carry a
longer payload (frame 307,712 samples, against 82,432) in the same waveform
regime, and they contribute 64 of the 256 samples.

Access fetches exact ZIP byte ranges. Each range is the data local header and
member followed immediately by the meta local header and member. The steps
are:

- inflate the members as raw DEFLATE (wbits -15), which must end exactly at
  the member boundary;
- check size and CRC32 against the pinned values;
- require SigMF `cf32_le`, 500000 sps, 862.5, one channel and one capture,
  with `core:sha512` equal to the data;
- require exactly one annotation whose sf/cr/bw/file agree with the row, and
  have build cross-check it against `dataset.csv`.

Index min/max are computed from the stored float32 values.

## Accepted output

- Source recordings available in scope: 41,229
- Primary samples: 256 (64 `drone_los`, 192 `drone_nlos`; 16 sessions,
  RRH 1–4)
- Primary values: 89,624,782 float32 (44,812,391 complex samples)
- Primary bytes: 358,499,128
- Minimum sample: 210,834 values
- Median sample: 240,028 values
- Maximum sample: 694,660 values
- Global stored min/max: -0.026155980 / 0.026235074
- Worst sample: 4.2e-5 of values on the 1/32768 grid, unique fraction 0.960
- Download footprint: about 338 MB (CSV plus 319,698,270 B of member ranges)
- Aggregate SHA-256 of samples in index order:
  `10901407d9aa912119729c65f9d7ea461bb0d0f17518bdbc7e1b2bd40fd0db9d`

## Judge checks

- `gate.py` PASS with no warnings. I re-ran `verify.sh` and it passed: 256
  samples, 358,499,128 B, 16 sessions, 4 RRHs, both area types. All recipe
  scripts were last modified before the driver's 16:08 download run.
- `build.sh` and `verify.sh` are local-only (no network calls), and there are
  no credentials in any script.
- I reproduced the 256 picks exactly from the local `dataset.csv` using the
  stated selection rule. The local CSV confirms that only three PHY
  configurations exist and that the selection uses SF10 only.
- Bytes, from 8 samples across sessions, RRHs and SNR from -11 to +29 dB:
  - Noise RMS is 6e-4 to 1.4e-3, and frame RMS rises with SNR.
  - There is no DC offset and no zero values.
  - Lag-1 autocorrelation fits 2× oversampling.
  - Mantissa trailing zeros fall off geometrically, and the low byte is 0 in
    about 0.4% of values.
  - Fractions on the 2^-15 and 2^-16 grids are ≤2e-5.
  - |x|^2 shows no integer lattice, and the smallest magnitudes are 98%
    distinct, so this is not widened or rotated sc16.
  - SHA-1 of full files and of 64 KB prefixes found 0 duplicates.
- Rights: I opened the record JSON and the live Zenodo API and confirmed
  license `cc-by-4.0`, open access, version 1.0.0, covering `sigmfs.zip` and
  `dataset.csv`. No personal data is emitted.
- Novelty: `novelty.py` found the URL only in this staging recipe. The
  `rf_iq_baseband` type exists only at 16 bits (two local families, one
  downstream), and there is no 32-bit IQ family. The label is therefore
  `new_content_same_modality`; the scout's `new_modality` overclaimed. zlsim
  measured breadth as OK at nearest distance 0.0517. There are no fill
  warnings.
