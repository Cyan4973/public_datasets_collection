# NOAA/IHO DCDB crowdsourced-bathymetry vessel tracks, LON/LAT float64: development report

## Outcome

Accepted `noaa_dcdb_csb_vessel_track_lonlat_f64`. Each sample is one complete IHO DCDB crowdsourced-bathymetry (CSB) submission file. It is stored as one sequential vessel GNSS track: interleaved little-endian float64 `LON, LAT` pairs, in the trusted node's file row order.

This is a new upstream source within the geographic-coordinate modality, and the first 64-bit sequential geodetic trajectory family drawn from decimal-degree source text. The nearest existing families differ:

- `noaa_marinecadastre_ais_2024_01_01_f32` holds AIS vessel reports at 32-bit, from a different source.
- `comma2k19_global_pose_ecef_positions_f64` holds car-camera ECEF metres.
- `citibike_2024_trip_geocoords_f64` holds station endpoints.
- `natural_earth_10m_geometry_xy_f64` holds cartographic vertices.

## Source and rights

- Source: NOAA Open Data Dissemination bucket `noaa-dcdb-bathymetry-pds` (IHO Data Centre for Digital Bathymetry, hosted by NOAA NCEI). Access is anonymous HTTPS; the bucket is not requester-pays.
- Scope: contribution-date prefixes `csb/csv/2024/06/01..07/`, a documented size cap.
  - The window holds 2,125 listed objects, 1,583,536,283 B. The full month of June 2024 is 9,904 objects, 6.06 GB.
  - 900 kept objects (1,172,429,139 B) are pinned in `selection.tsv` (sha256 `725be897…0536`), each with its size and S3 composite ETag.
- License: CC0 1.0. `docs/FAQ.html` (sha256 `86017f3863f94913646e6ca50f59f30cfb0c929207193b3d5ea5398a04ad2b1a`) states: "Regardless of whether the data are provided to the IHO DCDB by a Trusted Node or an individual, the data is dedicated to the public domain in accordance with the 'Creative Commons Zero' universal public domain dedication (CC0 1.0)."
- Safety: vessel names (`PLATFORM_NAME`) are never emitted. Per the FAQ, only data from international waters, or from coastal states that agreed to public sharing, are published.

## Shape and conversion

- Natural record: one trusted-node submission CSV. Header: `UNIQUE_ID,FILE_UUID,LON,LAT,DEPTH,TIME,PLATFORM_NAME,PROVIDER`.
- Primary series: LON and LAT parsed with `float()`, the correctly rounded binary64, which equals `n/1e6` exactly. Written as interleaved `<d` pairs, so value_count = 2 × kept rows. float32 cannot hold these values (for example `-124.100532`).
- Selection rules, applied before download:
  - AquaMap is excluded: binary-float text such as `41.037144999999995`.
  - PGS is excluded: files split between the 1e-4 and 1e-6 lattices.
  - FarSounder is excluded: hourly rolling re-uploads with overlapping time ranges, plus a test file uploaded 58 times.
  - 118 exact re-uploads from GLOS and COMIT USF are dropped.
- Build exclusions, recorded in `ingest_stats.json`:
  - 2 one-row files.
  - 3 Rosepoint files on the coarse 1/60,000° sub-lattice (3-decimal NMEA minutes), holding 1,724,494 rows.
- Missing values: rows with empty, non-finite, out-of-range or (0,0) coordinates are dropped and counted; more than 1% dropped is fatal. Realized drops: 0.
- Fatal checks: wrong header, a row without 8 fields, identity columns changing within a file, duplicate payloads, time overlap between kept files of one vessel.
- Homogeneity:
  - Every value is WGS84 decimal degrees on the printed 1e-6° lattice.
  - The effective quantum is 1/600,000° for 605 samples (85% of bytes) or 1e-6° for 259 samples (15%). 31 small samples are unclassified. The class is recorded per sample in `coordinate_quantum`.
  - Cadence is about 1 s for 91.7% of bytes and about 60 s for 8.0%. Both occur within the same Rosepoint logger population.

## Accepted output

- Primary samples: 895 (Rosepoint 779, GLOS 106, COMIT USF 10)
- Vessels: 46. The largest holds 7.9% of bytes.
- Primary values: 10,182,222 float64
- Primary bytes: 81,457,776
- Values per sample: min 4, p10 714, median 3,442, p90 38,540, max 261,024
- Source rows: 6,815,607 kept, 0 dropped
- Kept fraction-digit histogram (0..6 digits): 17 / 118 / 1,531 / 14,176 / 144,274 / 1,448,288 / 8,573,818
- Extent: lon −136.394175..−66.102492, lat 18.429918..59.229967
- Aggregate output SHA-256: `f17f68579da75162f88b3af234c9be8bdca11cee60a171652f1e63a8fab11c4f`

## Judge checks

- **Gate:** `gate.py` PASS with no warnings (values 10,182,222; bytes 81,457,776; 895 samples; median 3,442; width 64).
- **Verify:** I ran `verify.sh` myself: exit 0 in 29.5 s, 895 samples, 5 exclusions, 0 dropped rows. It uses integer micro-degree parsing and an exact `n/1e6` check, independent of the build code.
- **Logs:** the download log shows 900/900 objects validated by size, ETag and header. The build log reproduces the pinned aggregate SHA-256. `build.sh` reads only local files.
- **Independent byte check:** for 40 random samples, a fresh csv-module parse matches the stored bytes in all 40. No time step goes backwards (0 of 166,133).
  - Residues: in a 1/600,000° sample, n mod 5 takes only {0,2,3}; in a 1e-6° sample all five residues appear.
  - Tracks: one vessel's 27 files are contiguous, non-overlapping 6-hour 1 Hz windows down the Mississippi.
  - Near-stationary material: samples under 11 m hold 1.17% of bytes; samples under 1 km hold 4.65%. Within-vessel shared fixes occur only at docks.
- **Rights:** fetched `docs/FAQ.html` myself. The SHA-256 matches and the CC0 sentence is present. No credentials appear in any script.
- **Excluded providers:** range-probed one AquaMap file (binary-float text confirmed) and one PGS file. Both exclusions are conservative.
- **Novelty:** `novelty.py --url https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/ --terms dcdb bathymetry crowdsourced csb rosepoint trajectory gnss` finds no other use of this source. AIS and vessel terms find only MarineCadastre AIS at 32-bit (local and downstream). The label is new_source.
- **Noted, not blocking:**
  - Rosepoint is 96.2% of bytes.
  - The ~60 s cadence subset is 8% of bytes.
  - About 298 MB of the download is discarded at build.
  - `selection.tsv` (610 KB) would be the largest committed recipe file.
