# Voyager ISS Saturn-Encounter Decompressed Raw Vidicon Frames UInt8

- Candidate id: `nasa_pds_voyager_iss_saturn_raw_u8`
- Width: uint8
- Quantity: Raw 8-bit vidicon data numbers (DN) from the Voyager 1/2 Imaging Science Subsystem cameras during the 1980-81 Saturn encounters. Each frame is 800x800 uncalibrated DN, losslessly decompressed from the archival IMQ files.
- Source: https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0004/AAREADME.TXT
- Resources: https://asc-pds-voyager.s3.us-west-2.amazonaws.com/?list-type=2&prefix=VGISS_0004/&delimiter=/, https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0004/SATURN/C3452XXX/C3452943_RAW.LBL, https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0004/SATURN/C3452XXX/C3452943_RAW.IMG
- License: Public domain / NASA SMD open data (NASA PDS Rings Node data set VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0, hosted by the PDS Imaging Node at USGS)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: NASA SMD: information produced from SMD-funded scientific research is held as a public trust, made publicly available, and openly shared. The AAREADME only asks for a citation: 'please cite the work of the PDS Rings Node... Showalter, M.R., M.K. Gordon, and D. Olson, VG1/VG2 SATURN ISS PROCESSED IMAGES V1.0, VGISS_0001-0038, NASA Planetary Data System, 2006.' The NASA policy page was not re-fetched this session (proxy).
- Natural record: One decompressed raw frame Cxxxxxxx_RAW.IMG (PRODUCT_TYPE=DECOMPRESSED_RAW_IMAGE): 800x800 uint8 pixels.
- Estimated samples: 600
- Estimated primary values: 384,000,000
- Estimated download bytes: 494,000,000
- Estimated primary bytes: 384,000,000
- Decode path: Detached PDS3 label: RECORD_BYTES=1024, FILE_RECORDS=804, ^VICAR_HEADER record 1, ^IMAGE record 2, LINES=800, LINE_SAMPLES=800, LINE_PREFIX_BYTES=224, SAMPLE_BITS=8, then the VICAR extension header at record 804. For each of the 800 image records, drop the 224-byte binary prefix and keep 800 bytes. Pure stdlib. Verified on one frame: 640,000 pixels extracted.
- Novelty kind: new_source
- Novelty evidence: novelty.py with --url .../VGISS_0004/ and --terms voyager vidicon vgiss saturn found no URL, registry, ledger or downstream matches. Term hits are only mast_iue_swp_raw_image_u8 (IUE ultraviolet spectrograph vidicon frames, a different mission and scene type) and the Cassini VIMS i16 cubes. No outer-planet imaging-camera raw frames exist at any width. Local 8-bit planetary imagery is only the THEMIS IR controlled mosaic.
- Homogeneity: One instrument family (Voyager ISS vidicon) with a single DN generation process. Recommended restriction: INSTRUMENT_ID='ISSN' (narrow-angle) and SCAN_MODE_ID='1:1' to avoid partial-readout frames. Use a pinned bounded selection, e.g. ~600 frames from one volume/target set. VGISS_0005 SATURN alone has 553; VGISS_0004 satellite targets ≈ 907. The bucket holds 33,099 RAW frames across VGISS_0004, 0005 and 0026-0038, so a subset is required for the 1 GB cap. Exclude CALIB directories.
- Risks: 1) Same broad modality (raw 8-bit vidicon camera frames) as the accepted IUE recipe, so the novelty is new_source, not new_modality. 2) Many frames are mostly dark sky: the probed Tethys frame had mean DN 12, 3.9% zeros, zlib 0.28. 3) Mixed Voyager 1/2 and narrow/wide-angle cameras unless filtered by label. 4) The 224-byte binary line prefix (engineering data) must be stripped, not kept. 5) The license relies on NASA SMD policy (precedent: accepted PDS recipes). 6) Only part of VGISS_0001-0038 is mirrored on this bucket (0004, 0005, 0026-0038), so pin to those.
- Probe evidence: The asc-pds-voyager top level lists VGISS_0004, VGISS_0005, VGISS_0026..0038, qedr/ and vg_0001..0038. Full enumeration found 33,099 *_RAW.IMG (823,296 bytes each) and no other IMG types. Per-target counts in VGISS_0004: SATURN 854, S_RINGS 789, TITAN 363, RHEA 143, and so on. The label shows DATA_SET_ID VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0 and the 800x800 8-bit 224-byte-prefix layout. I fetched one RAW.IMG (823 KB, HTTP 200): VICAR 'LBLSIZE=1024 FORMAT='BYTE' NL=800 NS=800' and 159 distinct values. A one-byte range GET on VGISS_0005/AAREADME.TXT returned 206.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_174424.jsonl`).
