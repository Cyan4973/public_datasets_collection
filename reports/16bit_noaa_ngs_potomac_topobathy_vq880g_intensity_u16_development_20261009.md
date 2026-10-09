# NOAA NGS Potomac topobathy VQ-880-G intensity uint16 development

## Outcome

Accepted `noaa_ngs_potomac_topobathy_vq880g_intensity_u16`. Each sample is the native LAS `Intensity` field (unsigned 16-bit) of every point in one complete 500 m × 500 m COPC tile. There are 48 tiles, all from one NOAA National Geodetic Survey Coastal Mapping Program topobathymetric lidar project: Digital Coast ID 8727, a Riegl VQ-880-G green+NIR system flown by Quantum Spatial in February–April 2018 over the Potomac River mouth and the Chesapeake Bay shoreline.

This family is separate from the accepted `dc_lidar_2015_intensity_u16` (local) and `dc_lidar_intensity_u16` (downstream). That family is topographic NIR lidar using only 0..255 (about 95 distinct values). This one is a full-range 16-bit topobathy intensity stream. The novelty is new content in a known modality (airborne lidar intensity), not a new modality. It is also separate from `noaa_coastal_maine_topobathy_classification_u8`, which uses the same bucket but a different project, field and width.

## Source and rights

- Source: public NODD bucket `noaa-nos-coastal-lidar-pds`, prefix `laz/geoid18/8727/`. It holds 5,968 COPC tiles (322.6 GB): 3,899 in delivery01 and 2,069 in delivery02.
- Pinned tiles: 48 keys in `sources.tsv`, recording size, S3 multipart ETag, LastModified and header point count. Total 868,443,284 bytes.
- Metadata: `metadata_2018_ngs_topobathy_potomac_river_chesapeake.xml`, 71,682 bytes, SHA-256 `7cbc2f77381f20f7fabea88a2db669085e5f2575f678aaec37222bea74849000` (InPort item 56114).
- License: the AWS Open Data Registry entry `noaa-coastal-lidar.yaml` says "NOAA data disseminated through NODD are open to the public and can be used as desired". It asks for attribution and forbids implying endorsement or presenting modified data as unaltered NOAA data. The metadata states "Access Constraints: None"; its use constraints are only accuracy disclaimers. Access is anonymous HTTPS and the bucket is not requester-pays.

## Shape and conversion

The tiles are LAS 1.4, point data record format 7 (36-byte records), compressed with LASzip compressor 3. They are decoded with the repository decoder `tools/laz/laszip.py`.

Bytes 12–13 of each record (the Intensity field) are copied unchanged in stored COPC order, one little-endian uint16 `.bin` per tile. Nothing is filtered: 0 and 65535 are kept as native readings. RGB is zero in every point and is not emitted.

The intensity is the LAS-standard 16-bit normalized value. QSI/RiProcess stretched about 2,500 instrument levels to 0..65535 with a per-mission gain, giving lattice steps of about 23–28. Green bathymetric and NIR returns are interleaved in the delivered stream. The scanner-channel bits are 0 everywhere, because NOAA converted the data from the original LAS 1.2 PDRF 3, so the two channels cannot be separated.

Selection: per delivery, 24 tiles at evenly spaced positions in name order among tiles of 10–25 MB. This covers 18 of the 19 delivery/flight-date groups. Every tile was decode-probed before download, and none needed replacing.

## Accepted output

- Primary samples: 48 (24 delivery01, 24 delivery02)
- Primary values: 153,398,476
- Primary bytes: 306,796,952
- Minimum sample: 1,602,481 values
- Median sample: 3,421,887.5 values
- Maximum sample: 4,593,319 values
- Distinct values per tile: 981–4,877
- Share of 0: 0.115% overall; 7.4% in one tile, under 0.1% in 45 tiles
- Share of 65535: 0.0055% overall
- Aggregate SHA-256 of the samples, concatenated in sample_path order: `182e5bdf64e99ffd4be389f6502d5f9c90a78fc9823a0dc43e007c265fc69172`

## Judge checks

- The gate passed with no warnings.
- I ran `verify.sh` myself: exit 0, and all 48 samples were byte-compared against a fresh decode using a separate struct-based extraction.
- I decoded `delivery01/20180318_355000e_4226000n` with my own struct layout `<12xHBBBBhH...`. It matched the stored sample exactly (1,939,837 values). Grouping by point source ID showed two missions with lattice steps of about 25.2 and 26.2, and each flight line internally uniform. This is per-mission gain within one process, not mixed regimes. Intensity medians fall with return number (12,661 for return 1 down to 5,085 for return 5) and noise points sit at 366, which is physically consistent.
- Byte statistics across six tiles: order-0 entropy 8.9–11.0 bits, delta entropy 9.4–11.9 bits, low-byte entropy about 7.6–8.0 bits (no hollow width), lag-1 autocorrelation 0.25–0.82. Quantiles are natural for both land/shore and open-water tiles. No degenerate or duplicated samples.
- Rights: I opened the NODD registry YAML (License field, no RequesterPays). I checked the local metadata XML against its SHA-256 and found "Access Constraints: None".
- No credentials appear in any script. `build.sh` and `verify.sh` are local-only.
- Novelty: `novelty.py` (URL and terms, vocabulary, type/instrument/archive) found no prior use of project 8727. The other NOAA bucket recipes use different projects and fields. Same-modality lidar intensity u16 exists only as the 0..255 DC LiDAR family.
- Measured breadth is OK: the nearest family is `hyg_star_apparent_mag_mmag_i16` at 0.0754. There were no fill warnings.
