# Boreas Autonomous-Driving Dataset (UTIAS, Toronto 2020-11..2021-11): Velodyne Alpha Prime 128-Beam Roof LiDAR Per-Point Calibrated Intensity, Native 8-bit, UInt8

- Candidate id: `boreas_velodyne_alpha_prime_intensity_u8`
- Width: uint8
- Quantity: Per-point calibrated return intensity/reflectivity from a Velodyne Alpha Prime (VLS-128) spinning automotive lidar. The sensor natively reports this as 8-bit (0-100 diffuse, 101-255 retroreflective). Boreas stores it as exactly integral float32 in field 4 of each 24-byte (x,y,z,i,r,t float32) point, so emitting it as u8 restores the native width without loss.
- Source: https://registry.opendata.aws/boreas/
- Resources: https://boreas.s3.amazonaws.com/?list-type=2&delimiter=/, https://boreas.s3.amazonaws.com/?list-type=2&prefix=boreas-2021-01-26-11-22/lidar/, https://boreas.s3.amazonaws.com/boreas-2021-01-26-11-22/lidar/1611678138564575.bin, https://raw.githubusercontent.com/utiasASRL/pyboreas/master/DATA_LICENSE.md
- License: CC BY 4.0
- License evidence: https://raw.githubusercontent.com/utiasASRL/pyboreas/master/DATA_LICENSE.md
- License quote: The Boreas and Boreas Road Trip datasets are licensed under a Creative Commons Attribution 4.0 International Public License ("CC BY 4.0"). (Also the AWS ODR entry: License: "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode)", ARN arn:aws:s3:::boreas)
- Natural record: One lidar sweep file (lidar/<timestamp>.bin, one 10 Hz revolution, about 220k points), with intensity in native point order. Suggested bounded subset: 6-8 evenly spaced sweeps from each of the 44 boreas-2020-*/boreas-2021-* sequences (four seasons, rain/snow/sun), about 264-352 samples.
- Estimated samples: 300
- Estimated primary values: 66,000,000
- Estimated download bytes: 1,600,000,000
- Estimated primary bytes: 66,000,000
- Decode path: curl each pinned .bin from the public S3 bucket over HTTPS (anonymous, not requester-pays). Python: struct.iter_unpack('<6f') or array('f') with stride 6. Take element 3, assert it is integral and within 0..255, then write bytes(). Assert len % 24 == 0. Pure stdlib.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: velodyne_alpha_prime_vls128_automotive_lidar
- Archive collection: boreas.s3.amazonaws.com
- Novelty evidence: novelty.py on boreas/velodyne/'alpha prime'/'lidar intensity': no recipe or downstream family carries lidar intensity at 8 bits. The only lidar intensity is dc_lidar_2015_intensity_u16 (airborne LAS, 16-bit). Velodyne material in the corpus is geometry only: goose_vls128_lidar_scan_xyz_f32 (a different dataset) and umich_nclt_velodyne_hdl32e_xyz_u16 (NCLT intensity was not taken, and is off-limits as the same source file). The earlier ledger card boreas_applanix_sbet_navigation_f64 was screened out only because the license was unverified. DATA_LICENSE.md now resolves that: it states CC BY 4.0, consistent with the AWS ODR yaml.
- Homogeneity: One sensor (the roof Velodyne Alpha Prime on the same Buick test vehicle), one firmware and calibration lineage, one quantity. Restrict to the 44 sequences from 2020-11-26 to 2021-11-28. Exclude the 2022/2024/2025 sequences, whose sensor suite changed (e.g. an Aeva FMCW lidar appears in 2024) and which may use a different lidar. Seasonal and weather variation is the content, not mixed regimes.
- Risks: (1) Extraction ratio is 1/24 (float32 x,y,z,i,r,t). The kept signal is still about 60 MB+, and there is no leaner source. (2) Zeros are common: 23-45% in the probed windows. Not single-value dominated, but the judge may note it. (3) The ring index (field 5) is a laser ID proxy and must not be emitted as primary. (4) Byte gate vs other small-value u8 families (EK60/WCSD amplitudes, MAPQ) is unmeasured. Point order follows the firing sequence across 128 interleaved beams, which differs structurally from rasters.
- Probe evidence: The S3 listing is anonymous: 127 top-level prefixes, 44 from 2020-2021. Sweep sizes are 5.28-5.30 MB, i.e. 220k points x 24 B. 48 KB range GETs at offset 0 and at 2.4 MB of 2021-01-26-11-22 and 2020-11-26-13-58 sweeps showed intensity always integral, min 0, max 173 (101 mid-scan), 54-92 distinct values, ring 0..127 and a time offset field. Radar PNGs (3371x400 gray8) are also present but not proposed: likely byte-redundant with polar weather-radar/sidescan u8.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_224222.jsonl`).
