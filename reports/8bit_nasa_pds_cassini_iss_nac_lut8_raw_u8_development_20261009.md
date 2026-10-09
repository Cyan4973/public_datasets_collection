# Cassini ISS narrow-angle TABLE-converted raw frames uint8 development

## Outcome

Accepted `nasa_pds_cassini_iss_nac_lut8_raw_u8`. Each sample is one full-resolution 1024 × 1024 uint8 frame from the Cassini ISS narrow-angle CCD camera. The values are the camera's own 8-bit data numbers: the camera converted each 12-bit count on board with its fixed square-root-like lookup table (`DATA_CONVERSION_TYPE = TABLE`), and the frame was downlinked losslessly.

The family is distinct from two accepted 8-bit raw space-camera recipes:
- `nasa_pds_voyager_iss_saturn_raw_u8`: a vidicon tube with a linear 8-bit converter and 800 × 800 frames.
- `nasa_pds_juno_junocam_perijove_rgb_framelets_u8`: square-root companded like this one, but a Jupiter pushframe camera with 128 × 1648 framelets.

The breadth measurement confirms the distinction on the bytes. It is the same modality, so novelty is `new_content_same_modality`.

## Source and rights

- **Source:** NASA PDS Imaging Node, data set `CO-S-ISSNA/ISSWA-2-EDR-V1.0`, volumes COISS_2050, COISS_2051 and COISS_2052, fetched anonymously over HTTPS.
- **Frames:** 314 pinned `N<sclk>_1.IMG` frames, 1,077,344 bytes each, 338,286,016 bytes in total. Each is pinned by size and by the MD5 from the PDS Rings Node checksum manifest.
- **Selection evidence:** the three volume `index.tab`/`index.lbl` pairs, 33,407,546 bytes, MD5-pinned.
- **Evidence file:** COISS_2050 `aareadme.txt`, also pinned.
- **Total download:** 371,827,288 bytes.
- **Rights:** the NASA SMD Scientific Information Policy says SMD-funded information is made publicly available and mission data are released as soon as possible. This is the same basis as the accepted Voyager ISS, JunoCam, Cassini VIMS and Cassini RADAR recipes. The aareadme carries acknowledgments only and no copyright or use restriction, and download.sh fails if that changes.

## Shape and conversion

**Selection rule.** It is applied to the 10,881 rows of the three indexes and keeps rows with:
- ISSNA, TABLE conversion, FULL mode, LOSSLESS compression
- MISSING_LINES 0 and no missing packets
- gain 29 e/DN
- SCIENCE and EDR
- target not SKY
- no SATELLORB dark-sky astrometry

That leaves 2,932 eligible frames in 37 observations. At most 10 evenly spaced frames are taken per observation, giving 314 pinned frames.

**Decode.** LBLSIZE, RECSIZE, NL, NS, NBB and NLB are parsed from each VICAR label (3144, 1048, 1024, 1024, 24, 1). The decoder skips the label and the NLB=1 binary telemetry record, and asserts that every 24-byte line prefix begins with the 1-based big-endian line number. It drops the prefix and keeps the 1024 DN per line unchanged: no inverse lookup table, bias removal or calibration.

**Exclusion.** Build and verify apply the same rule: a frame is dropped if one DN holds more than 50% of its pixels or it has fewer than 16 distinct values. It removed 34 frames, all for mode share at DN 8-9, including the whole Helene close-approach observation.

## Accepted output

- Pinned source frames: 314
- Excluded by the mode-share rule: 34
- Primary samples: 280 (COISS_2050: 152, COISS_2051: 10, COISS_2052: 118)
- Observations represented: 36
- Primary values and bytes: 293,601,280 (1,048,576 per sample)
- Time range: 2008-312T03:52:25 to 2009-041T17:00:16
- Targets: Saturn rings 226, Prometheus/F-ring 18, Titan 10, Mimas 9, Enceladus 9, Rhea 5, Tethys 3
- Filters: 240 clear (CL1+CL2); 40 colour, IR, methane or polarizer
- DN levels present: 253 (3-255); largest aggregate share 0.170 (DN 9)
- Per-frame mode share: median 0.196, maximum 0.499
- Aggregate sample SHA-256: `3233aae91c71fc5ff51ed0cebe5636e2f5e5434409ff0e44cea724f0360fe143`

## Judge checks

- **Gate:** `gate.py` passes with no warnings.
- **verify.sh:** I re-ran it; it passed in 18 s with `selection_ok selected=314`, 280 samples and a byte-compare against an independent re-derivation.
- **Independent decode:** I decoded `N1606425716_1` with my own struct/regex code and it is byte-identical to its sample. Prefixes read 0001, 0002, ... 0200, 0400, so the lines are aligned.
- **Edge columns:** column 0 sits about 1.7x above column 1 but correlates 0.986 with it down the rows. Together with column 1023 (about +6 DN), this is a native CCD edge effect, not a decode offset.
- **Near-duplicates:** across 244 consecutive pairs within observations, the median mean absolute difference is 3.8 DN. The minimum is 0.59 DN (Titan haze frames, differing in noise only). There are no exact duplicates.
- **Breadth:** zlsim OK. The nearest is `video_chroma_cb_u8` at distance 0.0487 with compression loss 0.154, so it is not equivalent. `mitbih_v4_u8` has loss 0.027 but distance 0.057. Voyager ISS and JunoCam are not among the top-10 neighbours.
- **Novelty search:** novelty.py finds no Cassini ISS, COISS or ISSNA source in recipes, the registry, the ledger or downstream.
- **Rights:** I fetched the NASA SMD policy page myself and grepped the aareadme for restrictions; there are none. No credentials appear in any script, and build and verify make no network calls.
- **Nit, not blocking:** the manifest `semantic_meaning` still lists Helene among the resolved moons, although every Helene-target frame was excluded. The `filtering` field documents that exclusion.
