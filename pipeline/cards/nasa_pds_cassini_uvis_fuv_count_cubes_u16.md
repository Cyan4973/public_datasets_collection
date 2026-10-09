# Cassini UVIS Far-Ultraviolet (FUV) Full-Resolution Spectral-Spatial Photon-Count Cubes (1024 bands x 64 lines), Native UInt16 Counts

- Candidate id: `nasa_pds_cassini_uvis_fuv_count_cubes_u16`
- Width: uint16
- Quantity: Raw photon counts per detector bin (RAW_DATA_NUMBER, COUNTS/BIN) of the Cassini UVIS FUV channel (111-191 nm) imaging spectrograph, 1024 spectral x 64 spatial pixels per integration
- Source: https://pds-rings.seti.org/holdings/volumes/COUVIS_0xxx/
- Resources: https://pds-rings.seti.org/holdings/volumes/COUVIS_0xxx/COUVIS_0030/DATA/D2010_005/FUV2010_005_23_44.LBL, https://pds-rings.seti.org/holdings/volumes/COUVIS_0xxx/COUVIS_0030/DATA/D2010_005/FUV2010_005_23_44.DAT, https://pds-rings.seti.org/holdings/volumes/COUVIS_0xxx/COUVIS_0030/INDEX/INDEX.TAB
- License: NASA SMD open scientific data policy (NASA PDS Ring-Moon Systems Node; volume AAREADME has no use restriction)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One FUV PDS3 QUBE product (FUV<yyyy_ddd_hh_mm>.DAT + .LBL, data set CO-S-UVIS-2-CUBE-V1.2): a BAND x LINE x SAMPLE = 1024 x 64 x N stack of integrations. Only CUBE products with BAND_BIN=1, LINE_BIN=1, UL/LR corners 0..1023 x 0..63 (full detector window) are kept; one sample per product (65,536*N values).
- Estimated samples: 1,500
- Estimated primary values: 150,000,000
- Estimated download bytes: 310,000,000
- Estimated primary bytes: 300,000,000
- Decode path: Pure stdlib: fetch the .LBL (5 KB) per candidate product from the volume INDEX.TAB paths, parse CORE_ITEMS/BAND_BIN/LINE_BIN/corners/CORE_ITEM_TYPE (MSB_UNSIGNED_INTEGER, 2 bytes) and SUFFIX_BYTES; read the .DAT core as '>H' (honoring zero suffix items) and write little-endian uint16. Values of 65535 (CORE_NULL=-1 as unsigned) are treated as missing/flagged.
- Novelty kind: new_source
- Measurement type: raw_space_frame
- Instrument line: Cassini UVIS FUV imaging spectrograph (MCP photon counting)
- Archive collection: pds-rings.seti.org/holdings/volumes/COUVIS_0xxx
- Novelty evidence: novelty.py --url .../COUVIS_0xxx/ returns no URL match and no 'uvis' term hit. The Cassini recipes present are VIMS (accepted i16 and downstream cassini_vims_core_i16), RADAR, RPWS and ISS, none of them UVIS. No ultraviolet photon-counting spectrograph family exists at any width. The closest are IRIS FUV (CCD DN, not photon-counting microchannel-plate counts) and NICER PI events.
- Homogeneity: One channel (FUV), one data set (CUBE, not SPEC/occultation time-series), one geometry (unbinned 1024x64 full window), one unit (counts per bin). Integration time and target (Saturn, rings, Titan, icy moons, stars) vary naturally. LOW/HIGH_RESOLUTION slit states can be split or restricted to one if the judge prefers. EUV, HDAC, HSP and binned or windowed configs are excluded.
- Risks: Counts are small and sparse (Poisson, MCP detector), so most high bytes are zero. The judge may question 16-bit width honesty, though counts do exceed 255 in bright Lyman-alpha/H2 regions and the stored type is native 2-byte unsigned. Onboard SQRT_9 compression means decompressed values lie on a square-root lattice. Many products are single-integration (65,536 values, 131 KB), still well above the 1,000-value median floor. Labels must be fetched per product to filter binning (~5 KB each, a few MB total). Range of volumes (COUVIS_0001-0060) needs pinning.
- Probe evidence: The rings-node listing returns 200 with volumes COUVIS_0001..0060. COUVIS_0030 INDEX.TAB lists 4,031 FUV products, and 29 of 30 sampled FUV labels are CUBE, BAND_BIN=1, LINE_BIN=1, full window, CORE_ITEMS (1024,64,N), N=1-12. The fetched label shows CORE_ITEM_TYPE=MSB_UNSIGNED_INTEGER, CORE_ITEM_BYTES=2, CORE_UNIT COUNTS/BIN, COMPRESSION_TYPE SQRT_9. A 2007 volume (COUVIS_0020) shows mixed binning configs (BAND_BIN 1/2/4/16), so the filter is needed. A one-byte range GET on a .DAT returned 206.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_16bit/scout.20261009_010213.jsonl`).
