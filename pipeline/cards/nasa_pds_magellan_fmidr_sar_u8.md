# Magellan Venus Full-Resolution SAR Mosaic (F-MIDR) Framelets UInt8

- Candidate id: `nasa_pds_magellan_fmidr_sar_u8`
- Width: uint8
- Quantity: Magellan S-band SAR normalized backscatter at 75 m/pixel, sinusoidal projection. Stored as uint8 DN = INT((sigma + 20) * 5) + 1, where sigma is backscatter divided by the Muhleman law, in dB.
- Source: https://asc-pds-magellan.s3.us-west-2.amazonaws.com/mg_0001/aareadme.txt
- Resources: https://asc-pds-magellan.s3.us-west-2.amazonaws.com/?list-type=2&prefix=mg_0001/&delimiter=/, https://asc-pds-magellan.s3.us-west-2.amazonaws.com/mg_0001/f05s335/ff01.lbl, https://asc-pds-magellan.s3.us-west-2.amazonaws.com/mg_0001/f05s335/ff20.img
- License: Public domain / NASA SMD open data (US government mission data from the NASA PDS Imaging Node at USGS)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: NASA SMD: information produced from SMD-funded scientific research is held as a public trust, made publicly available, and openly shared. This is the same evidence accepted for nasa_pds_mastcamz_raw_i16 and nasa_pds_cassini_vims_qube_i16; I could not re-fetch it this session because the proxy blocks it.
- Natural record: One F-MIDR framelet file (ffNN.img with its own detached PDS label ffNN.lbl): a 1024-byte VICAR2 header followed by 1024x1024 uint8 pixels. Each F-MIDR has 56 framelets (7x8). Alternative: reassemble each MIDR into its 7168x8192 mosaic.
- Estimated samples: 560
- Estimated primary values: 587,202,560
- Estimated download bytes: 587,776,000
- Estimated primary bytes: 587,202,560
- Decode path: Detached PDS3 label gives RECORD_BYTES=1024, FILE_RECORDS=1025, ^IMAGE=(FFNN.IMG,2), LINES=1024, LINE_SAMPLES=1024, SAMPLE_TYPE=UNSIGNED_INTEGER, SAMPLE_BITS=8. Skip the 1024-byte VICAR header (it starts 'LBLSIZE=1024 FORMAT='BYTE' ... NL=1024 NS=1024') and read 1,048,576 bytes. Pure stdlib; no compression.
- Novelty kind: new_modality
- Novelty evidence: novelty.py with --url .../mg_0001/ and --terms magellan midr venus framelet found no URL match, no registry, ledger or downstream families. The only hit is the stale staging draft nasa_pds_magellan_sar_i16: download-only via catalog.data.gov, unregistered, and targeting the wrong width since F-MIDR is 8-bit. Planetary SAR imagery is absent at 8 bits locally and downstream. The only 8-bit radar is NEXRAD weather radials; SAR exists only as Sentinel-1 GRD u16.
- Homogeneity: Use full-resolution F-MIDRs only: directories f* in volumes mg_0001-mg_01xx, ~765 F-MIDRs ≈ 42,800 framelets ≈ 45 GB. Exclude C1/C2/C3 compressed-resolution MIDRs (225/675/2025 m), P-MIDRs, and the later FMAP volumes mg_11xx-14xx (fl/fr/fo). All F-MIDR pixels share one DN-to-dB law. Suggested bounded subset: the 10 F-MIDRs on volume MG_0001 (560 framelets, ~587 MB), or ~8 F-MIDRs spread across volumes. Drop all-zero edge framelets.
- Risks: 1) The license rests on NASA SMD public-trust policy plus US-government public-domain status. Precedent: two accepted PDS recipes. 2) The stale staging draft nasa_pds_magellan_sar_i16 may confuse id or novelty checks; it is a different width and was never registered. 3) Framelet vs. full-MIDR natural record: both are defensible because framelets are separate PDS-labelled files of 1 MiB each. The builder should pick one and document it. 4) Some framelets at mosaic edges may be mostly or entirely zero fill. 5) Download is uncompressed (~1.05 MB/framelet), so download ≈ primary size. 6) The MISSION_PHASE_NAME of cycle-2/3 MIDRs may differ; filter on the label if needed.
- Probe evidence: The S3 bucket asc-pds-magellan lists 439 volumes (mg_0001..mg_0127 MIDR CD volumes, mg_11xx-14xx, mg_3001-3002 GxDR, edr/). mg_0001/f05s335 lists ff01..ff56.img at 1,049,600 bytes each. The ff01.lbl label confirms 8-bit 1024x1024 with the DN formula. I fetched one framelet (ff20.img, 1 MB, HTTP 200): VICAR header present, 0% zeros, 150 distinct values, range 45-200, mean 112, zlib ratio 0.70. That is rich speckled SAR texture. The aareadme.txt describes '56 framelets... 1024 lines by 1024 samples, with one byte per sample'.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_174424.jsonl`).
