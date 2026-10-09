# LRO LOLA Level-3 RDR Per-Spot Lunar Surface Radius and Two-Way Laser Range (mm), Native LSB Int32

- Candidate id: `nasa_pds_lola_rdr_spot_radius_range_i32`
- Width: int32
- Quantity: Per-laser-spot lunar radius from Moon centre (RADIUS_1..5, LSB_INTEGER, millimetres, ~1.737e9) and per-spot 2-way range (RANGE_1..5, LSB_UNSIGNED_INTEGER mm, ~3e7-1.1e8), time-ordered 5 spots per 28 Hz shot
- Source: https://pds-geosciences.wustl.edu/missions/lro/lola.htm
- Resources: https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_rdr/, https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/label/lolardr.fmt, https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_rdr/lro_no_03/lolardr_093281318.dat
- License: NASA PDS public scientific data (LicenseRef-NASA-SMD-Open-Data), same basis as accepted grail_lgrs_kbr1c_ka_band_ranging_f64 / nasa_pds_mola_megdr_i16
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One LOLA RDR orbit product (lolardr_<DOYHHMM>.dat, ~51 MB, ~199k fixed 256-byte rows = one ~2 h orbit); one sample per orbit per series (radius stream, range stream) in shot/spot order
- Estimated samples: 60
- Estimated primary values: 42,000,000
- Estimated download bytes: 1,530,000,000
- Estimated primary bytes: 168,000,000
- Decode path: Pure struct: fixed 256-byte LE records per lolardr.fmt; RADIUS_k = int32 at byte offset 48+40*(k-1), RANGE_k = uint32 at 52+40*(k-1), SHOT_FLAG_k uint32 at 72+40*(k-1). Drop spots with RADIUS == -1 (MISSING_CONSTANT) / RANGE == 4294967295 and use SHOT_FLAG to reject noise returns (probe found an off-surface 1.81e9 mm return in an extended-mission file). Emit int32 radius and range (range fits int32: < 2^31 mm).
- Novelty kind: new_content_same_modality
- Measurement type: laser_range
- Instrument line: lro_lola
- Archive collection: pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1
- Novelty evidence: novelty.py --url: same host only (grail, gravity harmonics, mola, sharad); no LOLA/RDR recipe, ledger or downstream entry. laser_range has orex_ola f64 (WEAK), goose/cartographer/diode f32. No int32 laser-altimeter family exists. This would be integer mm radii ~1.737e9 that use all 4 bytes, a byte structure unlike any existing i32 family (seismic counts, geonames DEM, GTFS seconds, IDs).
- Homogeneity: Single instrument/product version (LRO-L-LOLA-3-RDR-V1.0, V1.04 products), fixed record layout, two series of one unit (mm) each. Recommend restricting to nominal-mission (lro_no_*) or a fixed phase set: the probe found ~40-100% valid spots in a nominal file vs ~4% in an ES-10 file. Pick ~30 orbits spread across the lro_no/lro_sm phases with a dir-listing discovery that is robust to drift.
- Risks: pds-geosciences.wustl.edu already has one autocollect acceptance (grail), so this is the 2nd. Missing-spot fraction varies by mission phase (choose phases with a high valid fraction). Noise returns must be filtered by documented SHOT_FLAG, not ad hoc thresholds. Range and radius are correlated per shot but are different quantities. Keep them as two primary series, or make radius primary and range auxiliary if the judge prefers.
- Probe evidence: Directory listing lro_es_10: 415 .dat files averaging 51.0 MB, 206 phase dirs under lola_rdr/. Label LOLARDR_131991412.LBL: FILE_RECORDS=199164, RECORD_BYTES=256, 66 columns, BINARY. FMT: RADIUS_1 LSB_INTEGER mm MISSING_CONSTANT=-1; RANGE_1 LSB_UNSIGNED_INTEGER mm MISSING 4294967295. Range GET of 25.6 KB from lro_no_03/lolardr_093281318.dat at offset 25.6 MB: 500/500 valid spots, example radius 1735129996 mm; at offset 12.8 MB 201/500 valid.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_183620.jsonl`).
