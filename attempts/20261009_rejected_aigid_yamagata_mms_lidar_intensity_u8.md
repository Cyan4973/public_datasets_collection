# aigid_yamagata_mms_lidar_intensity_u8

- Status: rejected
- Date: 2026-10-09
- Source: AWS Open Data s3://japan-pointcloud, Yamagata/2023/01/MMS/Road/LAS/ (AIGID; CC BY 4.0 per the aigidjp/opendata_japan_pointcloud README and the AWS registry YAML)
- Target width: 8-bit

## What was tried

1. **Original card plan.** The plan was the full-tile 8-bit intensity code (LAS intensity / 255) from LAS 1.2 PDRF 3 tiles.
   - Head probes of 932 tiles of 30–120 MB found that the prefix mixes streams by point source ID:
     - full 16-bit: IDs 2, 5, 6, 7 (~82% of tiles)
     - code ×257: IDs 3, 8
     - code ×255: IDs 1 and 4, which come from different processing chains
   - A 48-tile pool of ID-4 tiles (3.49 GB) was downloaded in full. All 48 failed whole-tile ×255 purity.
2. **Tile structure.** Every ID-4 tile stores each acquisition pass as two blocks:
   - Sensor A: 2.3–7.1% of points, intensity = code ×255, camera RGB.
   - Sensor B: the rest, full 16-bit intensity.
   - No LAS field labels the sensor. The boundary was identified as the first non-×255 point coinciding with the GPS-time restart of block B (−12.7 to −328 s). The two markers coincided in all 48 tiles.
3. **Redesigned recipe.** One sample per tile = the leading sensor-A block.
   - Download: pinned range prefixes only (225 MB, SHA-256 pinned).
   - Output: 48 samples, 11,339,918 uint8 values, median 215,993.
   - build.sh, verify.sh and gate.py all passed.

## Why rejected

zlsim gate verdict: WEAK (redundant).

- Match: downstream nasa_pds_themis_ir_mosaic_u8, distance 0.0379, loss 0.003.
- The candidate's own compression ratio is 1.30.
- The ordering is not smooth: about 28% of neighbour steps are within ±2 codes. It behaves like near-incompressible image noise, so the "scan-profile ordering" novelty argument against Boreas did not hold.

## Evidence

- Recipe: staging/aigid_yamagata_mms_lidar_intensity_u8/ (head_probes.tsv, sources.tsv, README)
- Logs: .data/logs/aigid_yamagata_mms_lidar_intensity_u8/
- zlsim report: /tmp/autocollect/aigid_yamagata_mms_lidar_intensity_u8/zlsim.json

## Possible follow-up

The dominant 16-bit intensity streams of the same archive are unexplored as a separate 16-bit candidate:
- sensor B inside the ID-4 tiles
- point source IDs 2, 5, 6, 7

They need their own homogeneity analysis, because several systems are involved.
