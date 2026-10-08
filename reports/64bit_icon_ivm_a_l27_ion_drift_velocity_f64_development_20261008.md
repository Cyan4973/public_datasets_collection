# ICON IVM-A Level-2.7 in-situ ion drift velocity float64 development

## Outcome

I accepted `icon_ivm_a_l27_ion_drift_velocity_f64`. It contains native IEEE-754 float64 thermal-ion drift velocities measured in situ at about 590 km by Ion Velocity Meter A on NASA's Ionospheric Connection Explorer (ICON). The source is the IVM-A Level-2.7 version 6 daily NetCDF4 product.

This is the corpus's first in-situ space-plasma velocity material at any width; the nearest families measure other quantities:
- the accepted orbital magnetometer (GRACE-FO B_NEC) measures magnetic field in nT;
- the accepted HamSCI HF Doppler is a ground-based radio measurement.

This is the second acceptance from the HelioCloud bucket in this effort, after `nasa_heliocloud_iris_l1_fuv_frames_i16`. The sibling staging draft `icon_mighti_l22_thermospheric_vector_wind_f64` would be the third, so it needs the user's sign-off.

## Source and rights

**Source**
- NASA GSFC HelioCloud public bucket `gov-nasa-hdrl-data1`, prefix `spdf/cdaweb/data/icon/l2-7_ivm-a/YYYY/`. It is the SPDF/CDAWeb mirror, read anonymously and not requester-pays.
- The prefix holds 1,000 daily files, 2019-11-18 to 2022-09-01, in revisions r000–r003 of v06, totaling 45.5 GB.

**Selection**
- 120 days at sorted indexes `floor((2k+1)·1000/240)`, k = 0..119.
- Days per year: 5 in 2019, 44 in 2020, 42 in 2021, 29 in 2022.
- `sources.tsv` pins each key, size, multipart S3 ETag and LastModified. Its SHA-256 `5a24feca57bb015b…540893` is enforced by the scripts.

**License: CC0-1.0, under the NASA Science Data license page**
- The page reads: "Unless the data file is marked with a restrictive notice or license, data that is provided from a NASA-led mission including observations, engineering, calibration, and auxiliary data are licensed as Creative Commons Zero. There are no restrictions on the usage of these data."
- ICON is a NASA Explorer mission. Every file carries `Project = "NASA > ICON"`.
- The in-file `Rules_of_Use = "Public Data for Scientific Use"` is the standard ISTP release label.
- The ICON Rules of the Road say: "All data released to the public may be utilized for scientific analysis and publication with no restrictions imposed by the ICON mission". They add only courtesy citation and consultation requests.
- I treat the label as a public-release label, not a restrictive notice. This is the same NASA open-data basis as the accepted IRIS recipe from the same bucket.

## Shape and conversion

**Natural record:** one velocity component of one UTC-day file. The three variables are:
- `ICON_L27_Ion_Velocity_Zonal`
- `ICON_L27_Ion_Velocity_Meridional`
- `ICON_L27_Ion_Velocity_Field_Aligned`

Each is a float64 `(Epoch,)` variable in m/s, relative to corotation, at 1 Hz.

**Fetching:** `download.sh` fetches by HTTP range request only:
- the 16 KiB HDF5 metadata blocks the parser walks (4,321 blocks in total);
- one contiguous chunk span per (day, component), 193 MB in total;
- one complete control file, 2021-04-07.

**Decoding:** a pure-stdlib HDF5 reader, derived from the accepted COSMIC-1 recipe, verifies every lookup3 metadata checksum. Each 512-value chunk is then inflated and byte-unshuffled (filter pipeline shuffle(8) + deflate). The result is truncated to the dataset length, NaN fill is dropped, and the stored 8-byte patterns are written unchanged.

**Missing values and quality flags**
- `+-inf` is fatal.
- Values outside the ±500 m/s valid range are kept, not clipped.
- The DM and RPA quality flags are not applied and not emitted; this is documented.

**Excluded material**
- density and temperature, which have other units;
- the instrument-frame, raw, ENU and footpoint-mapped velocities, which are re-projections of the same measurement;
- flags and geolocation;
- all IVM-B files.

## Accepted output

| Measure | Value |
|---|---|
| Days | 120, 2019-11-22 to 2022-08-28; all three components emitted for each, 0 skipped |
| Primary samples | 360 (15 from 2019, 132 from 2020, 126 from 2021, 87 from 2022) |
| Primary values | 27,929,904 |
| Primary bytes | 223,439,232 |
| Sample size | min 5,054 (partial-day file 2021-09-03), median 79,598.5, max 86,195 values |
| Source records | 30,861,720 |
| NaN fill dropped | 2,931,816 (9.5%); per sample median 7.97%, max 30.4% |
| Kept values outside ±500 m/s | 237,362 (0.85%); per sample median 0.22%, max 12.7% |
| Value extremes | −4,634.15 to +4,140.11 m/s |
| Download | 309,399,913 bytes, against 5,463,353,792 for the 120 whole files |
| Aggregate SHA-256 (samples in index order) | `2a2b2d07b7cc4f8fdd21665c2ea7e7628b3b0fb9df7946dac38e5c1d1c135a29` |

## Judge checks

- **Gate:** `gate.py` passes with no warnings: values=27,929,904, bytes=223,439,232, samples=360, median 79,598.5.
- **verify.sh:** I ran it myself and it finished with `verify_ok`, including all 360 samples byte-compared and the control file identical for all 3 components.
- **Local-only:** a grep of `build.sh`, `verify.sh` and the scripts found no network calls and no credentials.
- **Independent decode:** a stdlib inflate plus index-arithmetic unshuffle of my own reproduced the emitted samples byte for byte for 20210407, 20200127 and 20220623.
- **Chunk order:** median |Δ| at 512-record chunk boundaries (0.33–0.82 m/s) is no larger than within chunks (0.37–0.86 m/s).
- **NaN masks:** identical across the three components on every day.
- **Bytes**, from 14 samples across all years, components and the partial day:
  - 0 of 20k values per sample survive a float32 round trip;
  - 100% of values are distinct;
  - there are no zeros and no equal-value runs;
  - mantissa trailing-zero counts are near geometric, i.e. full precision;
  - the time series are smooth (median |Δ| about 0.6 m/s) and physically plausible: tens of m/s by day, larger excursions at night and near the terminators.
- **Rights:** I re-read the CC0 sentence in the downloaded NASA page. I also fetched the ICON Rules of the Road PDF and decoded its substitution-encoded text; it confirms the "no restrictions imposed by the ICON mission" sentence.
- **Novelty:**
  - `novelty.py` URL and term search found only own, sibling and same-host rows and spurious "icon" substrings.
  - The `--type`, `--instrument` and `--archive` searches found 0 matches each.
  - The DSCOVR solar-wind staging directory is an orphan draft, absent from both the ledger and the registry.
  - Measured zlsim breadth is OK: the nearest family is `mace_mp_foundation_model_weights_f64` at distance 0.0556, with loss 0.073.
- **Homogeneity:** one instrument, product, unit, cadence and orbit. The three components of one vector form one series, matching the accepted GRACE-FO B_NEC and USGS geomag XYZ precedent.
