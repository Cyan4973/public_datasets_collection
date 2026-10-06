# GRACE-FO Calibrated Platform-Magnetometer Magnetic Field B_NEC (GFZ ACAL_CORR v0201) Float64

- Candidate id: `gfz_gracefo_fgm_acal_bnec_f64`
- Width: float64
- Quantity: Calibrated, aligned and corrected geomagnetic field vector in the local North-East-Center frame (nT), 1 Hz, from the AOCS fluxgate magnetometers on GRACE-FO 1 and 2 (CDF variable B_NEC, double, shape [86400,3] per day).
- Source: https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/
- Resources: https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF1/ACAL_CORR/, https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF2/ACAL_CORR/, https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF1/ACAL_CORR/GF1_OPER_FGM_ACAL_CORR_20240315T000000_20240315T235959_0201.cdf, https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF1/README.txt, https://doi.org/10.5880/GFZ.2.3.2021.002
- License: CC-BY-4.0
- License evidence: https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF1/README.txt
- License quote: References: Michaelis, I., Stolle, C., Rother, M. (2021): GRACE-FO calibrated and characterized magnetometer data. V. 0201. GFZ Data Services. https://doi.org/10.5880/GFZ.2.3.2021.002 ... License: CC BY 4.0
- Natural record: One daily per-satellite CDF file (GFn_OPER_FGM_ACAL_CORR_<day>_0201.cdf); the sample is that day's complete B_NEC array, 86,400 epochs x 3 components = 259,200 float64 values (2.07 MB). Timestamp (CDF_EPOCH) and B_FLAG may be emitted as auxiliary.
- Estimated samples: 62
- Estimated primary values: 16,070,400
- Estimated download bytes: 516,000,000
- Estimated primary bytes: 128,563,200
- Decode path: Pure stdlib. The file starts with magic cdf30001 cccc0001 (whole-file compressed): CCR at offset 8 (size, type 10, CPR offset, uSize), and the CPR says GZIP (ctype 5, level 1). zlib.decompressobj(16+MAX_WBITS) over bytes [40:], prepended with the uncompressed magic, gives a CDF v3 image. CDR encoding at byte 36 = 1 (network, big-endian). GDR -> zVDR chain (name at +84, dtype 45 = CDF_DOUBLE, zDims [3]) -> VXR (4 blocks of 21,600 records) -> CVVR records (type 13; cSize at +16, data at +24), each a separate gzip stream (per-variable GZIP CPR) -> struct '>d'. Verified on 2018-06-01 and 2024-03-15 GF1 files: B_NEC decodes to e.g. [6472.616, 1566.596, -51235.214], range -51,805..48,436 nT, 0 NaN, 0% float32-exact mantissas.
- Novelty kind: new_source
- Novelty evidence: novelty.py on the ISDC URL: no URL matches. Term matches only usgs_geomag_observatory_minute_f32 (ground observatories, 32-bit) and downstream usgs_geomag_xyz_minute_f32. No magnetic-field family exists at 64 bits, locally or downstream. A LEO platform magnetometer along orbit (±50,000 nT orbital swing at 1 Hz) is a different instrument class and regime. No registry or ledger history for GRACE-FO or GFZ.
- Homogeneity: Single product (ACAL_CORR v0201), single variable (B_NEC, nT, NEC frame), same instrument type and processing on both GRACE-FO satellites, uniform 1 Hz lattice, 86,400 records per file. Exclude B_FGM (instrument frame) and the dB_* correction terms, which are different quantities. Suggested scope: one calendar month (2024-03) for GF1+GF2, all v0201 files (31+31).
- Risks: Calibration is regression-based (documented in README/DOI paper), so values are a calibrated product rather than raw ADC. Some months were reprocessed to v0202, so pin exact filenames and sizes for 2024-03 (both satellites show 31 files that month). Two gzip layers make the CDF decoder slightly involved, though it is fully deterministic. Files are about 8.3 MB in 2024 vs 17.9 MB in 2018, and only about 25% of bytes are B_NEC.
- Probe evidence: Directory listings: GF1 has 3,011 daily files and GF2 has 2,911 (2018-06..2026). A one-byte range GET on the 2024-03-15 files for GF1 and GF2 returned 206; Content-Length is 8,317,204 and 8,350,631. Range-fetched 4.5 MB and 3.6 MB prefixes and parsed the variable lists (18 zVariables, maxrec 86399). Decoded three B_NEC CVVR blocks (64,800 values each): finite, physical, full-precision float64.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_215706.jsonl`).
