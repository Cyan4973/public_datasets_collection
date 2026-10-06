# Newcastle PSG+Accelerometer Study 2015 (Zenodo 1160410): GENEActiv Wrist Tri-Axial Accelerometer Raw 12-bit Counts at 85.7 Hz, Int16

- Candidate id: `zenodo_newcastle_geneactiv_wrist_accel_i16`
- Width: int16
- Quantity: Raw tri-axial wrist accelerometer ADC counts (12-bit two's complement, +/-8 g range, ~256 counts/g) from GENEActiv devices worn overnight by sleep-clinic patients, interleaved x,y,z per sample. Light, button, temperature and page metadata are excluded or auxiliary.
- Source: https://zenodo.org/records/1160410
- Resources: https://zenodo.org/api/records/1160410/files/dataset_psgnewcastle2015_v1.0.zip/content, https://zenodo.org/api/records/1160410
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/1160410
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"}, access_right open. Description: "Accelerometer data from brand GENEActiv ... are stored in .bin files. Per participant two accelerometers were used: One accelerometer on each wrist ... configured to record at 85.7 Hertz."
- Natural record: One device recording (one wrist, one participant, 12-24 h; 3.7-7.4 M samples x 3 axes). Suggested subset: left-wrist recordings excluding the two multi-day files (188 and 283 MB hex), giving 26 recordings and about 0.93 GB int16. The builder may narrow further to stay comfortably under 1 GB.
- Estimated samples: 26
- Estimated primary values: 463,000,000
- Estimated download bytes: 395,000,000
- Estimated primary bytes: 926,000,000
- Decode path: curl the ZIP tail to parse the central directory (87 entries; 55 deflate .bin members, 47-283 MB hex text each at ~5:1 compression). Range-fetch the selected members and inflate with zlib (raw deflate). Parse the GENEActiv text: skip the header block, then per page skip ~9 metadata lines and take one 3600-hex-char data line = 300 samples x 48 bits. x=(w>>36)&0xFFF, y=(w>>24)&0xFFF, z=(w>>12)&0xFFF, sign-extend 12-bit, emit little-endian int16. Never emit header fields.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://zenodo.org/records/1160410 --terms geneactiv newcastle: host-only zenodo match, no recipe, registry, ledger or downstream matches. 16-bit accelerometry locally is honeybee vibration PCM (and CNC vibration queued); the downstream har_body_acc is float smartphone HAR. No raw wearable human-motion accelerometer counts at 16 bits.
- Homogeneity: One device model and firmware mode (GENEActiv, 85.7 Hz, +/-8 g, 12-bit), one wrist side, one protocol (sleep-clinic overnight). Same unit and scale across samples.
- Risks: Source file headers contain participant Date of Birth, sex, height, weight and notes. The study published them openly under CC BY 4.0, but the recipe must strictly exclude headers, and a strict judge may object to sensitive context (sleep-clinic patients). The diagnosis CSV need not be downloaded. Mostly low-activity (sleep) signal with long quasi-static stretches. Uses 12 of 16 bits. Primary size is near the 1 GB cap unless narrowed. Lowest priority of this set.
- Probe evidence: HEAD/range on the ZIP (962,798,652 bytes) OK. Central directory from a 200 KB tail: 55 .bin (left 28, right 27), 4.85 GB hex uncompressed, 0.96 GB compressed; left hex sizes 47-94 MB except 188 and 283. Inflated the first 300 KB of MECSLEEP01_left wrist: header shows 'Accelerometer Range:-8 to 8', 'Measurement Frequency:85.7 Hz', 'Number of Pages:12336' (and Subject DOB/sex/height/weight fields). First data line decodes to 300 samples, e.g. (-13,248,-106), (-13,249,-106).

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_16bit/scout.20261006_035523.jsonl`).
