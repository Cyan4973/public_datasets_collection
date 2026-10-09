# NOAA NEXRAD WSR-88D Level-II Dual-Polarization Correlation Coefficient (RHOHV) Moment Codes, KTBW Tampa Bay During Hurricane Milton (2024-10-09) UInt8

- Candidate id: `unidata_nexrad_level2_ktbw_milton_rhohv_u8`
- Width: uint8
- Quantity: Co-polar cross-correlation coefficient rho_hv per range gate, native 8-bit Level-II moment codes (Message 31 'RHO' data block, word size 8, scale 300, offset -60.5; code 0 = below threshold, 1 = range folded)
- Source: https://registry.opendata.aws/noaa-nexrad/
- Resources: https://unidata-nexrad-level2.s3.amazonaws.com/?list-type=2&prefix=2024/10/09/KTBW/, https://unidata-nexrad-level2.s3.amazonaws.com/2024/10/09/KTBW/KTBW20241009_000313_V06
- License: NOAA open data (NODD): open to the public, use as desired; attribution requested
- License evidence: https://registry.opendata.aws/noaa-nexrad/
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired. NOAA makes data openly available to ensure maximum use of our data... NOAA requests attribution for the use or dissemination of unaltered NOAA data.
- Natural record: One Level-II volume-scan file (AR2V0006 archive): all RHO radials of the volume as a radial x gate uint8 matrix (720-radial super-res and 360-radial cuts in file order, or one sample per sweep at the fixed 1192-gate count if the builder prefers)
- Estimated samples: 40
- Estimated primary values: 400,000,000
- Estimated download bytes: 875,000,000
- Estimated primary bytes: 400,000,000
- Decode path: curl the S3 ListObjectsV2 XML for the day/station prefix (anonymous listing works on unidata-nexrad-level2; skip *_MDM keys) and pick a fixed, evenly spaced subset (~every 5th of 216 volumes). Python stdlib: 24-byte volume header, then repeated [4-byte BE signed length][bzip2 LDM record] -> bz2.decompress; walk the messages and keep type 31; parse data-block pointers and take the block named 'RHO' (word size 8): gate count at +8, scale/offset floats at +20, codes from +28. Emit codes unchanged as uint8.
- Novelty kind: new_quantity
- Measurement type: weather_radar_dualpol
- Instrument line: wsr88d_level2
- Archive collection: unidata-nexrad-level2
- Novelty evidence: novelty.py --url https://unidata-nexrad-level2.s3.amazonaws.com/ --terms rhohv 'correlation coefficient' dual-pol: no URL, recipe, registry, ledger or downstream matches; --type weather_radar_dualpol --archive unidata-nexrad-level2: 0/0. Existing 8-bit radar families are reflectivity-type (noaa_nexrad_level3_nids_radials_u8 is N0Q reflectivity; sevir VIL) plus FMI Doppler velocity; no polarimetric moment exists anywhere in the corpus. Registry noaa_nexrad_level2_moments_i16 was blocked only by an S3 ListBucket 403 on the old noaa-nexrad-level2 bucket; the new unidata-nexrad-level2 bucket lists anonymously, which meets its retry condition (exact keys discoverable).
- Homogeneity: One radar (KTBW), one day/event, one VCP family, one moment (RHO) with a single fixed code mapping (scale 300, offset -60.5) checked per block; ZDR/PHI (16-bit) and REF/VEL/SW/CFP excluded. Build must assert word size 8 and identical scale/offset for every RHO block.
- Risks: Clear-air or sparse-echo volumes are dominated by code 0 (below threshold): 62% zeros in the probe's early clear-air cuts at KTLX. Picking a widespread-precipitation event (Milton landfall day at KTBW) mitigates this; report the zero fraction, since the judge may still ask for a justification. zlsim might compare it to Level-III radials, but rho_hv concentrates at high codes (near 1.0), unlike reflectivity. Files are ~22 MB each; the subset keeps the download under ~0.9 GB.
- Probe evidence: Listing 2024/10/09/KTBW/: 216 V06 volumes, mean 21.9 MB. Range GET 0-2,000,000 of KTLX20240520_000004_V06: header 'AR2V0006.405', 11 bzip2 records decoded; RHO blocks: 720 radials, word size 8, scale 300.0, offset -60.5, 1192 gates; code histogram spans 0..255 (858,240 values in prefix). Also seen: REF/VEL/SW/CFP 8-bit, ZDR/PHI 16-bit.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_004435.jsonl`).
