# ISIS-2 topside sounder average ionogram uint8 development

## Outcome

Accepted `spdf_isis2_topside_ionogram_amplitude_u8`. The source is the NASA SPDF/CDAWeb ISIS-2 Swept-Frequency Sounder (SFS) "Average" ionogram product `I2_AV_ULA`, station ULA (Fairbanks, 65N 212E), calendar year 1974.

This is the first ionospheric-sounding family in the corpus. No ionogram, ionosonde or topside-sounder family exists in the local recipes, registry, ledger or downstream corpus. Related radar-sounder echo rasters do exist (SHARAD radargram f32, SHARAD raw echo i8, GPR i16), as do radio dynamic spectra (RSTN SRS u8, Parkes UWL u8), so the novelty is labelled `new_source` rather than a new modality. zlsim measured it `OK`. The nearest family is downstream `google_fonts_ofl_font_binaries` at feature distance 0.0426, but with a 6.4% compression loss it is not compression-equivalent.

## Source and rights

- Source: every CDF under `s3://gov-nasa-hdrl-data1/spdf/cdaweb/data/isis/ionogram_cdf/isis2/ULA_65N_212E/1974/`. This is NASA's anonymous HDRL mirror of `https://spdf.gsfc.nasa.gov/pub/data/isis/topside_sounder/ionogram_cdf/isis2/ULA_65N_212E/`.
- Files: 1,604 in 31 day directories, 304,729,594 bytes, each pinned by size and single-part S3 ETag (MD5) in `sources.tsv`. `discover.sh` re-lists the prefix.
- Format: CDF v2.6, big-endian network encoding, single file, GZIP-compressed zVariables.
- License: CC0-1.0. The dataset-level SPASE record `spase://NASA/NumericalData/ISIS2/SFS/AverageIonogram/Fairbanks/PT22S` (hpde/NASA, commit `05bd62ab61858558d70006b4035588994386265a`) declares AccessRights Open and RightsIdentifier CC0-1.0. The declaration sits inside the AccessInformation of the CDF product at exactly the ULA_65N_212E directory (ProductKey `I2_AV_ULA`), with the note "applicable to all publicly available NASA Heliophysics data products". The digitization was done by NASA GSFC (Data Evaluation Laboratory; CDF `PI_affiliation` NASA GSFC). ISIS-2 itself was a joint Canada-NASA mission.
- Acknowledgement kept in the manifest: CDAWeb at NASA GSFC, ISIS-2 SFS PI J. H. Whitteker, and data-restoration lead R. F. Benson.

## Shape and conversion

Each natural record is one digitized ionogram, i.e. one CDF file: about 14 s of sounding at 45 pulses/s. A sample is the `ampl` zVariable (CDF_UINT1, dims [223]) written row-major as `[frequency_step][223]`. Rows are the fixed-frequency portion followed by the 0.1-10 MHz sweep.

Each 223-bin row is one complete inter-pulse period of receiver video. The source digitized at 40 kHz and averaged every four samples into 100 us / 15 km bins; at 45 pps, 888.9 samples / 4 gives about 222 bins. The tail bins therefore contain the next transmitter pulse, and the CDF's own `v_height` axis spans 0-3330 km over all 223 bins. Frequency and range markers are burned into the video, as on the original analog ionograms. All of this is archived source content.

Decoding uses a pure-stdlib walker (`scripts/cdf26.py`): CDR -> GDR -> zVDR -> VXR tree -> GZIP CVVR or VVR. It enforces:
- exact decompressed lengths;
- gap-free coverage of records 0..MaxRec;
- structural checks: no pad value, FILLVAL -128 (outside the uint8 domain), VALIDMIN/MAX 0/255, `f_num` 223, year 74.

The first `vh_num` records are kept. Only 1-2 trailing writer-artifact records are trimmed, and only when they match the exact signature: all-zero row, freq 0.0, Epoch reset. The per-row `freq` (CDF_DOUBLE) is emitted as an auxiliary little-endian float64 series.

Keep rule (declared, applied per file, decisions recorded in `selection.tsv`):
- 500-1,100 rows;
- calibrated freq (no fill) within (0, 10.6] MHz;
- sweep start at or below 0.11 MHz and sweep end at or above 9.5 MHz;
- strictly increasing Epoch;
- at most 5% all-zero rows.

Decisions over all 1,604 files:

| decision | files |
|---|---|
| kept | 1,007 |
| row_count_out_of_range (96 fragments <500 rows, 208 files >1,100 rows) | 304 |
| freq_fill (uncalibrated axis; all of days 244/345/350) | 210 |
| too_many_zero_rows (day-079/263 1.95 MHz interleaved, day-170 dropout) | 42 |
| sweep_start_missing (day-174 fixed-frequency-only runs, freq 1.0 MHz throughout) | 29 |
| freq_out_of_range | 7 |
| sweep_truncated | 5 |

## Accepted output

- Source files decoded: 1,604
- Primary samples: 1,007, from 24 day directories (days 170-363)
- Primary values / bytes: 143,655,485
- Minimum / median / maximum sample: 142,051 / 142,720 / 151,640 values (637-680 rows x 223)
- Fixed-frequency prefix: 0.25 MHz in 288 samples, 0.48 MHz in 303, 1.0 MHz in 162, 1.95 MHz in 254
- Code shares: 0 = 3.31%, 255 = 3.17%; all 256 codes occur
- Auxiliary freq series: 1,007 samples, 5,153,560 bytes (not counted toward floors)
- Aggregate SHA-256 of primary samples in index order: `568b907baf1d3b1cb6341799f35d271c4a89e94e53ca787fd232000549808f8c`

## Judge checks

- `gate.py` passed with no warnings. I re-ran `verify.sh`: it re-decodes all 1,604 CDFs, re-applies the rule, byte-compares every sample, and checks the index, hashes, duplicates, degeneracy guards, floors and manifest totals.
- Independent decode: a brute-force scan for gzip members in the raw CDF bytes, which does not use the recipe parser, reproduced 40 of 40 random samples byte for byte.
- Visual check: I rendered 7 samples across the year as PNG. All show coherent topside ionograms (plasma resonances, O/X echo traces, frequency markers), confirming the decode and row order.
- Value checks:
  - global histogram: noise mode at codes 24-56, long echo tail, 255 saturation spike;
  - odd/even code ratio 0.99, so the 16-to-8-bit reduction left no lattice gaps;
  - every sample has at least 238 distinct codes;
  - 941 of 1,007 samples have no all-zero rows.
- Per-column profile: transmitter-pulse structure sits at bins 0 and ~200-212, with mostly-zero bins 218-222. This is consistent with the 45 pps inter-pulse period described in the CDF TEXT attribute.
- Near-duplicates: consecutive ionograms differ by a median of about 20 codes per byte (minimum 10.1), with at most 10.8% identical bytes. Of 644,195 rows, 643,649 are distinct; the duplicates are dropout zero rows.
- Rights: I opened PT22S.xml at the pinned commit and confirmed CC0-1.0 in the AccessInformation for the CDF product (ProductKey `I2_AV_ULA`, matching the CDF `Logical_source`). No credentials in any script.
- Novelty: `novelty.py` URL, term and type/instrument/archive checks show no same-type, same-instrument or same-archive family. The vocabulary lists the related radargram, radar-sounder raw-echo and radio dynamic-spectrum types.
- Builds: build and verify are local-only. The driver's download log shows all 1,604 files fetched and validated.
