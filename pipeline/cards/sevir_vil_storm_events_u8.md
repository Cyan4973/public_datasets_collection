# SEVIR Storm-Event Vertically Integrated Liquid (VIL) Radar-Mosaic Cubes UInt8

- Candidate id: `sevir_vil_storm_events_u8`
- Width: uint8
- Quantity: NEXRAD-mosaic-derived vertically integrated liquid (VIL) on a 384x384 1-km grid, 49 frames at 5-min spacing per storm event, stored as uint8 digital-VIL codes 0-254 (SEVIR's piecewise linear/log encoding of kg/m^2)
- Source: https://registry.opendata.aws/sevir/
- Resources: https://sevir.s3.amazonaws.com/data/vil/2017/SEVIR_VIL_STORMEVENTS_2017_0101_0630.h5, https://sevir.s3.amazonaws.com/data/vil/2017/SEVIR_VIL_STORMEVENTS_2017_0701_1231.h5, https://sevir.s3.amazonaws.com/data/vil/2018/SEVIR_VIL_STORMEVENTS_2018_0101_0630.h5, https://sevir.s3.amazonaws.com/data/vil/2018/SEVIR_VIL_STORMEVENTS_2018_0701_1231.h5, https://sevir.s3.amazonaws.com/data/vil/2019/SEVIR_VIL_STORMEVENTS_2019_0101_0630.h5, https://sevir.s3.amazonaws.com/data/vil/2019/SEVIR_VIL_STORMEVENTS_2019_0701_1231.h5, https://sevir.s3.amazonaws.com/CATALOG.csv
- License: No restrictions on use (AWS Open Data registry statement by the SEVIR maintainer, MIT Lincoln Laboratory)
- License evidence: https://registry.opendata.aws/sevir/ (read via https://s3.amazonaws.com/registry.opendata.aws/sevir/index.html)
- License quote: There are no restrictions on the use of this data.
- Natural record: One SEVIR storm event: the vil[i] slice of shape (384, 384, 49) uint8, stored contiguously as 7,225,344 bytes at file offset 2048 + i*7,225,344. Keep the stored H,W,T order (frames are the innermost axis).
- Estimated samples: 30
- Estimated primary values: 216,760,320
- Estimated download bytes: 216,800,000
- Estimated primary bytes: 216,760,320
- Decode path: HDF5 superblock v0 with a classic root symbol table (TREE/HEAP/SNOD) naming two datasets, 'id' and 'vil'. The 'vil' v1 object header has Dataspace (N,384,384,49), Datatype class 0 (fixed-point) size 1 unsigned LE, and Layout v3 class 1 (contiguous) at addr 2048, size N*7,225,344, with no filters. download.sh range-reads the first 8 KB plus the 'id' dataset (contiguous fixed 10-byte strings near EOF), verifies layout and shape, then range-GETs the selected events (5 per file x 6 STORMEVENTS files). build.sh emits each event's bytes as a uint8 sample, with event id as auxiliary metadata. No decompression is needed; pure stdlib struct.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://sevir.s3.amazonaws.com/data/vil/ with terms SEVIR / 'vertically integrated liquid' / VIL / storm returns no relevant matches (only an unrelated f64 NOAA Storm Events table and an ADCP substring hit). Local 8-bit weather radar is limited to noaa_nexrad_level3_nids_radials_u8 (single-station N0Q reflectivity radials). VIL is a different quantity (column-integrated liquid water) on a CONUS-mosaic event grid with a 49-frame time axis, from a new source.
- Homogeneity: VIL type only. ir069/ir107/vis are int16 and lght is event lists, so do not mix them. Use STORMEVENTS files only (all share grid, encoding and 5-min frame cadence). The layout was verified identical (contiguous at 2048, shape (N,384,384,49), u8) in 2017H1 (N=193), 2018H2 (N=847) and 2019H1 (N=851).
- Risks: Source files are 1.4-6.1 GB, so the recipe must use HTTP range GETs (S3 returned 206) and never fetch whole files. Pin offsets, event indices and file sizes. VIL is derived from NEXRAD, the same radar network as the accepted N0Q recipe, though it is a distinct quantity and product. The license is only the registry statement (no license file in the bucket). Some events have nonzero pct_missing in CATALOG.csv (33.8 MB, optional), so choose events with pct_missing == 0. Many zero pixels (no precipitation) is normal.
- Probe evidence: Bucket listing shows data/vil/2017-2019 STORMEVENTS and RANDOMEVENTS HDF5 files (1.39-17.1 GB). One-byte range GET returned 206. Parsing the 8 KB header of SEVIR_VIL_STORMEVENTS_2017_0101_0630.h5 gave superblock v0 and root entries 'id' (obj hdr 1394493440) and 'vil' (obj hdr 800). 'vil' has DSPACE (193,384,384,49), DTYPE class 0 size 1 unsigned, contiguous at 2048 with size 1,394,491,392 (= 193 x 7,225,344). A 64 KB range read inside event 5 showed 253 distinct values, min 0, max 254, mostly 0 with a tail of small codes. Registry license read via the S3-hosted registry page.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_194855.jsonl`).
