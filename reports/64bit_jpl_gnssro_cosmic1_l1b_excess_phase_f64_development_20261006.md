# COSMIC-1 GNSS radio-occultation L1 excess-phase float64 development

## Outcome

Accepted `jpl_gnssro_cosmic1_l1b_excess_phase_f64`: native IEEE-754 float64 calibrated GPS L1 excess phase from individual COSMIC-1 radio-occultation soundings, as processed by NASA JPL (institution_version v2.6) and hosted in the AWS Open Data "Earth Radio Occultation" archive (format v2.0). There is one sample per occultation: the L1 row of the NetCDF4 variable `excess_phase`, in metres, at 50 Hz.

This is new to the corpus. The nearest local recipes are `noaa_cors_rinex_observations_f64` (ground-station RINEX carrier phase in cycles) and `igs_final_satellite_clock_bias_f64` (satellite clock offsets in seconds). RO excess phase is a spaceborne limb-sounding atmospheric phase delay after calibration. It is a different quantity, platform and generation process.

## Source and rights

- Source: `https://gnss-ro-data.s3.amazonaws.com/contributed/v2.0/gnssro_cosmic1_jpl_l1b/YYYY/MM/DD/`. Anonymous, not requester-pays.
- Selection: 2,393 pinned keys (`sources.tsv`, SHA-256 `5debe8b2bad08a9f38427568b37c7b62a3ec79852c56de572f4cc26648a56c75`), each with its S3 size and single-part MD5 ETag.
  - One day per month for 2007-01..2016-12: the 15th, except 2016-07-03, 2016-08-28, 2016-11-02 and 2016-12-30.
  - 20 evenly spaced keys of each day's sorted listing; 2016-08-28 had only 13 files.
- Download size: 1,702,213,576 bytes of whole files.
- License: CC BY 4.0 for JPL-contributed data. Three agreeing statements:
  - The AWS open-data-registry entry `gnss-ro-opendata.yaml` applies a CC BY 4.0 legal-code link to "the data contributed by the NASA JPL", with the per-file license given in `data_use_license`.
  - The `gnss-ro/aws-opendata` Readme "Data use licenses" section gives the same link. Both documents misspell the host as `creativecommmons`.
  - Every file carries `data_use_license = "http://creativecommons.org/licenses/by/4.0/"` and `institution = "jpl"`.
- UCAR and ROM SAF contributions carry other terms and are excluded.

## Shape and conversion

- **Natural record:** one occultation file. Each sample is the L1 row of `excess_phase (signal, time)`.
- **Decoding:** a pure-stdlib HDF5 reader (`h5lite.py`, taken from the accepted `noaa_cdr_seaice_conc_nh_daily_u8` reader plus v3 contiguous-layout decoding, with lookup3 checksums verified) resolves `excess_phase`, `phase_observation_code`, `carrier_frequency` and `time`.
- **Row selection:** the L1 row is the unique row with code `L1*` at 1575.42 MHz. In every realized file it is row 0, `L1W`, with 2 signals.
- **Type and copy:** `excess_phase` must be exactly little-endian IEEE f8, contiguous and unfiltered. The raw bytes are copied unchanged, with no rescaling or differencing.
- **Missing values:** the policy strips leading and trailing `_FillValue` (-9.99e20) and non-finite values. A sample is dropped on interior gaps, fewer than 1,000 values, a constant span or a non-50 Hz time axis. None of this triggered: fill occurs only in the excluded L2 rows.

## Accepted output

- Source files validated (size + MD5 + product identity): 2,393
- Dropped: 0
- Primary samples: 2,393 (240 per year for 2007-2015, 233 for 2016)
- Receivers c1/c2/c3/c4/c5/c6: 620/347/105/398/468/455; 32 GPS transmitters
- Primary values: 13,471,361
- Primary bytes: 107,770,888
- Sample length: min 1,799, median 5,550, max 10,850 values (36-217 s)
- Time step: 0.0199995-0.0200005 s in every sample
- Aggregate SHA-256: `1e6708153562e527f675c8b6de5d6b1451562d64a0f8237f1a2b65fa8cdc53d0`
- Extraction ratio: about 6.3%. Whole files were downloaded so each could be checked against its S3 MD5.

## Judge checks

- **Gate:** `gate.py` passed with no warnings. I ran `verify.sh` myself: `verify=ok` with the aggregate SHA-256 above. The verifier re-derives every sample through the creation-order link index with separate array-based logic, byte-compares it, rejects fill, non-finite, short, constant, low-diversity and duplicate samples, and checks manifest totals.
- **Bytes:**
  - Each sample appears exactly once in its source file, as a contiguous extent.
  - The bytes that follow are the L2 row: fill in its lower part, and L1−L2 offsets of -49 to +21 m where valid. This confirms row and stride.
  - Values are physical: about 3-50 m at the top of the atmosphere, ramping to 3,000-6,800 m. The median 20 ms step is 0.4-0.8 m.
  - Mantissas are fully used (about 0 values per sample with the low 29 bits zero), all values in a sample are distinct, and xz compresses samples to 0.64-0.70.
  - 7 of 2,393 samples contain native open-loop tracking glitches: steps of about 288 m in 4, and swings of about 20 km in 3. They were kept as source values. The builder disclosed them.
- **Index and uniqueness:** `ntimes == value_count` in every sample, so no trimming happened. All source keys are unique, and every sample has a unique (receiver, start time).
- **Rights:** I fetched the AWS registry YAML myself and read the downloaded Readme. A byte scan of all 2,393 files found the CC BY 4.0 string in every one, and no UCAR or EUMETSAT terms.
- **Novelty:** `novelty.py` with the bucket URL, registry URL and RO terms matched nothing in recipes, registry, ledger or downstream.
- **Network:** `build.sh` and `verify.sh` make no network calls, and no credentials appear in any script.
