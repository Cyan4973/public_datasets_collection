# SEVIR storm-event VIL uint8 development

## Outcome

Accepted `sevir_vil_storm_events_u8`: native uint8 digital vertically integrated liquid (VIL) codes from the SEVIR Storm EVent ImageRy dataset. One sample is one complete STORMEVENTS event cube.

The family is distinct from the accepted `noaa_nexrad_level3_nids_radials_u8`. That recipe holds single-station polar N0Q reflectivity radial bins from the Unidata Level-III archive. This recipe holds a different quantity and geometry from a different source: a multi-radar, column-integrated liquid-water mosaic on a fixed Cartesian event grid with a 49-frame time axis, produced by MIT Lincoln Laboratory. The NEXRAD radar network is the only thing the two share.

## Source and rights

- Source: official SEVIR bucket `s3://sevir` (`https://sevir.s3.amazonaws.com/`, us-west-2), anonymous access. Objects were last modified 2020-04-15.
- Containers: the six files `data/vil/{2017,2018,2019}/SEVIR_VIL_STORMEVENTS_{YYYY}_{0101_0630,0701_1231}.h5`. They hold N = 193 / 685 / 793 / 847 / 851 / 541 events and range from 1.39 to 6.15 GB. Each is pinned by size and S3 ETag in `containers.tsv`.
- Catalog: `CATALOG.csv`, 33,838,047 bytes, SHA-256 `3209386cde96ffa80ccec3c1919090ffc601333cc651116f9fc48f224a5c2f57`.
- License: the AWS Open Data registry entry (`awslabs/open-data-registry/datasets/sevir.yaml`, ManagedBy Mark S. Veillette, MIT LL) says verbatim *"License: There are no restrictions on the use of this data."* for Resources ARN `arn:aws:s3:::sevir`. `download.sh` re-fetches the YAML and fails unless the exact license line, the maintainer line and the bucket ARN are all still present. The underlying radar data comes from NOAA NEXRAD (US Government).
- Citation: Veillette, Samsi and Mattioli (2020), SEVIR, NeurIPS 33.

## Shape and conversion

Each natural record is one SEVIR storm event: the HDF5 slice `vil[i]` of shape (384, 384, 49). The grid is a 384 km × 384 km Lambert azimuthal equal-area grid at 1 km per pixel, with 49 frames at 5-minute spacing (4 hours).

The recipe never downloads whole containers. For each container it range-reads:
- the metadata head `[0, 2048)`;
- the metadata tail (from the end of the `vil` payload to EOF);
- one exact 7,225,344-byte range per selected event at `2048 + i × 7,225,344`.

A pure-stdlib HDF5 parser checks the metadata:
- superblock v0, and the root symbol table holds exactly `id` and `vil`;
- `vil` has dataspace (N, 384, 384, 49) and an unsigned 8-bit fixed-point datatype;
- the layout is v3, contiguous at 2048, with size N × 7,225,344, and there is no filter pipeline;
- every entry of the `id` dataset equals the catalog id at its index.

Because the dataset is contiguous and unfiltered, each range is the decoded typed array. Build writes it unchanged in stored C order (grid_row, grid_column, frame), with frame innermost.

The values are SEVIR's native digital-VIL codes 0–254, where 255 means missing. The documented code-to-kg/m² law is not applied:
- 0 kg/m² for codes ≤ 5;
- (X − 2) / 90.66 kg/m² for codes 6–18;
- exp((X − 83.9) / 38.9) kg/m² for codes 19–254.

Selection is a fixed rule in `scripts/select_events.py`, re-derived from the pinned catalog by download, build and verify:
1. Keep STORMEVENTS VIL rows with `pct_missing == 0` and `data_max > 0`. This leaves 3,536 of 3,910 events.
2. Keep only the first event of each NWS episode.
3. Take 10 evenly spaced events per container.

RANDOMEVENTS and the ir069, ir107, vis and lght types are excluded.

The missing-value policy is shared by download, build and verify. Each cube must have:
- no code 255;
- max and min equal to the catalog data_max and data_min;
- at least 16 distinct codes;
- a zero fraction below 0.9999;
- at least 2 distinct frames.

## Accepted output

- Source events validated against the HDF5 `id` dataset: 3,910 (all six containers)
- Eligible events (pct_missing 0, data_max > 0): 3,536
- Primary samples: 60 (10 per container)
- Primary values: 433,520,640
- Primary bytes: 433,520,640
- Sample size: 7,225,344 values (all samples equal, so the median is the same)
- Coverage: 2017-06-13 to 2019-09-21. The 2017 first-half file only starts in June 2017; the 2019 second-half file ends 2019-09-27.
- Geography: 25.7–50.3°N, −124.5 to −67.4°
- Event types: thunderstorm wind, hail, tornado, flash flood, flood, heavy rain, lightning, funnel cloud
- Distinct codes: 254 in the union (1 and 255 absent)
- Code shares: 0 is 48.7%; 2–5 (sub-threshold) is 20.8%; 6–18 is 8.8%; 19–254 is 21.7%; 85,146 values sit at the saturation code 254
- Per-event zero fraction: 0.18–0.84 (median 0.48)
- Per-event distinct codes: 133–254
- Download: 467,529,701 bytes in 195 s
- Aggregate SHA-256 of the samples concatenated in index order: `742700951e156ad4bb24215f0356d9fa4e5f7675cace3242dcd47014ddbec281`

## Judge checks

- **Gate:** `gate.py staging/sevir_vil_storm_events_u8` passes with no warnings: 60 samples, median 7,225,344, width 8. `check_repo_hygiene.py` passes.
- **Verify:** I re-ran `verify.sh` myself and it passes: verify_ok samples=60 bytes=433520640 distinct_codes=254 missing_255=0. build.sh and verify.sh use only local files and contain no network calls.
- **HDF5 metadata:** I parsed the `vil` object header in all six fetched heads with my own struct code, separate from the recipe's parser. It confirms dims (N,384,384,49), class 0 size 1 unsigned with offset 0 and precision 8, and layout v3 class 1 at addr 2048 with size N×7,225,344. The only messages are dataspace, datatype, fill value, layout, mtime and nil, so there is no filter. The fetched response headers show 206, the exact Content-Range and the pinned ETag.
- **Axis order:** mean absolute differences at lag 49 (next column) and lag 18816 (next row) are the smallest, 0.7–2.9. Lag 1 (next 5-minute frame) is small. Lag 7 and lag 1,000,003 are 3–10× larger. This confirms frame-innermost C order. An ASCII render of one frame shows coherent convective cells.
- **Degeneracy:** all 60 events have 49 distinct, nonzero frames. In the two sparsest events, 5–17% of pixels change between consecutive frames, so there are no stale or duplicated frames. All 60 sample SHA-256s are distinct.
- **Pins:** all 60 `event_sha256.tsv` pins equal the SHA-256s in the driver's download log, the sample files and the index rows. I recomputed the aggregate SHA-256 and it matches the manifest.
- **Compressibility:** xz -1 ratios across all 60 samples are 1.6–20.1× (median 3.2×). The builder's 2.3–6.9× figure was inaccurate. The most compressible events are sparse isolated-cell storms (S753130, S789519), and their contents are legitimate.
- **Rights:** I read the downloaded registry YAML (SHA-256 matches the manifest) and the live registry page. Both carry the verbatim no-restrictions statement for `arn:aws:s3:::sevir`. There are no credentials and no personal data.
- **Novelty:** `novelty.py` (URL plus SEVIR/VIL/radar/NEXRAD terms) finds no SEVIR or VIL family locally, downstream, in the registry or in the ledger. The only 8-bit weather-radar family is the NIDS N0Q radials, whose manifest restricts it to N0Q reflectivity.
