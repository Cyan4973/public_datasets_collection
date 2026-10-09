# ISIS-2 topside sounder average ionograms, Fairbanks (ULA) 1974, uint8

Native 8-bit sounder-receiver video amplitude rasters from the ISIS-2
swept-frequency topside sounder (SFS), digitized by the NASA GSFC ISIS
data-restoration project and archived at SPDF/CDAWeb as product `I2_AV_ULA`
("Average" ionograms, 15 km apparent-range resolution). One sample is one
complete ionogram: `rows x 223` uint8 codes, rows = frequency steps (the
fixed-frequency portion, then the 0.1-10 MHz sweep), columns = 100 us
apparent-range bins after each sounder pulse.

- Satellite / instrument: ISIS-2 (1971-024A) SFS topside sounder only. No ISIS-1,
  Alouette or other stations are mixed in.
- Station / period: ULA (Fairbanks, 65N 212E) telemetry, calendar year 1974.
- Source: every CDF under
  `s3://gov-nasa-hdrl-data1/spdf/cdaweb/data/isis/ionogram_cdf/isis2/ULA_65N_212E/1974/`
  (anonymous HTTPS; NASA's public mirror of
  `https://spdf.gsfc.nasa.gov/pub/data/isis/topside_sounder/ionogram_cdf/isis2/ULA_65N_212E/`).
  1,604 files, 304,729,594 bytes, pinned with size and single-part S3 ETag (MD5)
  in `sources.tsv`. `discover.sh` re-lists the prefix and diffs it against the pin.

## License

CC0-1.0. The dataset-level SPASE record
`spase://NASA/NumericalData/ISIS2/SFS/AverageIonogram/Fairbanks/PT22S`
(`hpde/NASA` on GitHub, commit `05bd62ab`, 2026-07-23) lists, inside the access
information of the CDF product itself: `AccessRights Open`,
`RightsIdentifier CC0-1.0`, note "CC0 1.0 Universal is the Creative Commons
license applicable to all publicly available NASA Heliophysics data products".
The digitization is NASA GSFC work (CDF `PI_affiliation` = NASA GSFC). ISIS-2
was a joint Canada-NASA mission; the CC0 statement is NASA's own, made for this
NASA-produced digitized product.

Acknowledgement (please keep): the Coordinated Data Analysis Web (CDAWeb) at
NASA GSFC, ISIS-2 SFS instrument PI J. H. Whitteker, and ISIS data-restoration
project lead R. F. Benson.

## Format and decode

The files are CDF v2.6 (`magic cdf26002 0000ffff`, big-endian network encoding,
4-byte offsets, single file). `scripts/cdf26.py` is a pure-stdlib walker:
CDR -> GDR -> zVDR chain -> VXR tree (nested VXRs allowed) -> CVVR (GZIP, CPR
cType 5) or VVR. For `ampl` it requires CDF_UINT1, dims `[223]`, record
variance, no pad value, GZIP compression; each block must gunzip to exactly
`(last-first+1)*223` bytes and the blocks must cover records `0..MaxRec`
without gaps. `scripts/selftest_cdf26.py` writes synthetic CDF v2.6 files
(nested VXR, several GZIP CVVRs, a plain VVR inside a compressed variable,
attribute entries, trailer artifact) and checks exact round trips plus failures
on truncation, record gaps, corrupt gzip, length mismatch and wrong type; it runs
at the start of `build.sh`.

Value semantics: `VALIDMIN 0`, `VALIDMAX 255`, `FILLVAL -128` (INT4, outside the
uint8 domain, so there is no in-band fill). Code 255 (about 3% of values) is the
saturation level of the archive's 16-to-8-bit reduction (strong echoes and the
transmitter pulse), not fill; code 0 (about 3%) is the floor. Both are kept.

Quirk: the `f_num` scalar is always 223 (the delay-bin count, despite its
CATDESC); `vh_num` holds the number of frequency steps. Many files carry 1-2
extra trailing records beyond `vh_num` whose amplitude row is all zero, `freq`
is 0.0 and Epoch is reset to the first record: a writer artifact. These are
trimmed only when they match that exact signature.

## Keep rule (complete calibrated 0.1-10 MHz ionograms)

A file is kept when all of these hold; otherwise it is dropped with its reason
recorded in `filtered/<id>/selection.tsv`:

1. `MaxRec+1 == vh_num`, or `vh_num < MaxRec+1 <= vh_num+4` with the trailing
   records matching the artifact signature above;
2. `500 <= vh_num <= 1100` rows;
3. `freq` has no fill (`< -1e30`) and lies in (0, 10.6] MHz on every kept row;
4. `min(freq) <= 0.11` MHz (sweep start present) and `max(freq) >= 9.5` MHz (the
   sweep reached the 10 MHz end);
5. Epoch strictly increasing over the kept rows;
6. at most 5% of the kept rows are all-zero amplitude rows.

Realized decisions over all 1,604 files (`filtered/<id>/selection.tsv`):

| decision | files |
|---|---|
| kept | 1,007 |
| row_count_out_of_range (39-499 row fragments, and >1100-row files) | 304 |
| freq_fill (uncalibrated frequency axis) | 210 |
| too_many_zero_rows | 42 |
| sweep_start_missing | 29 |
| freq_out_of_range | 7 |
| sweep_truncated | 5 |

Of the >1100-row files, 142 have an all-fill frequency axis. The other 66 are
day-079 ionograms with a 1.95 MHz fixed frequency where every other row is empty
(about 50% all-zero rows), so a wider row limit would not add clean ionograms.
Rule 6 drops the same interleaved pattern in 24 shorter 1.95 MHz files (days
079/263), plus 18 ionograms with heavier scattered dropout (5-18% zero rows,
mostly day 170, 1.0 MHz fixed frequency). Kept ionograms have 637-680 rows (142,051-151,640
bytes, median 142,720). They differ only in the instrument's fixed-frequency
segment (0.25, 0.48, 1.0 or 1.95 MHz, about 146-216 rows) followed by the same
0.1-10 MHz sweep.

Interior all-zero rows within the 5% bound (telemetry dropouts, mostly in the
fixed-frequency portion) are source content and kept. verify re-checks the 5%
bound, at least 32 distinct codes, and that no code covers more than half of a
sample. Over the kept output, code 0 is 3.3% and code 255 is 3.2% of values, and
all 256 codes occur.

## Output

- `samples/<id>/isis2_ula1974_ampl_u8/<file>.u8`: primary, raw uint8, row-major
  `[frequency_step][223]`, bytes exactly as stored in the CDF after gunzip.
- `samples/<id>/isis2_ula1974_freq_f64/<file>.f64`: auxiliary, the matching
  per-row sounder frequency in MHz (CDF_DOUBLE, converted to little-endian float64).
- `index/<id>/samples.jsonl`: one row per sample file, with shape, source key and
  SHA-256, sample SHA-256, min/max, distinct codes, 0/255 shares, all-zero row count.
- `filtered/<id>/selection.tsv` and `ingest_stats.json`: per-file decisions and totals.

`verify.sh` re-decodes every pinned CDF, re-applies the rule, byte-compares each
sample and checks the index, duplicates, degeneracy guards, floors and manifest totals.

## Novelty

There is no ionogram, ionosonde or topside-sounder family in the local recipes,
registry, ledger or downstream corpus (`novelty.py`). The only shared item is the
SPDF S3 host (ICON IVM drift velocities, HelioCloud IRIS/TRACE frames, which are
unrelated variables). The nearest byte-level neighbours are probably
spectrogram-like rasters (RSTN solar radio spectra) and sonar pings; `zlsim`
decides.
