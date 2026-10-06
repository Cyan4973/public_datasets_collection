# M3D Motion (Zenodo 22811456): TI IWR6843AOP 60 GHz FMCW Radar Raw ADC Captures of Human Motion (DCA1000), Native Int16 IF Samples, Single Chirp Profile

- Candidate id: `zenodo_m3d_iwr6843_radar_adc_i16`
- Width: int16
- Quantity: Raw complex baseband IF ADC samples (int16 I/Q, 4 RX channels) of a 60 GHz FMCW radar observing one or two people walking, running, doing squats or falling. Per chirp: a 64-byte TI HSI header (magic 0x0CDA0ADC0CDA0ADC, constant fields) followed by a 1024-byte payload of 512 int16 values (64 ADC samples x 4 RX x I/Q). Only the payload is primary.
- Source: https://zenodo.org/records/22811456
- Resources: https://zenodo.org/api/records/22811456/files/dataset_260917.zip/content, https://zenodo.org/api/records/22811456
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/22811456
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"} (Creative Commons Attribution 4.0 International). Description: "Raw data from mmwave radar (model: IWR6843AOP from Texas Instruments) were meticulously recorded... Each measurement was saved as a binary file using a Data Capture (DCA1000) from Texas Instruments."
- Natural record: One capture file dataset_260917/<session>/<nn>/datacard_record_hdr_0ADC_0.bin (one measurement of one motion trial), with HSI chirp headers stripped. The ZIP holds 80 captures across 10 exact chirp configurations. Suggested coherent subset: the 16 captures sharing profileCfg '0 61.2 60 17 50 657930 0 55.27 1 64 2000 2 1 36', 3-TX chirpCfg and 100 ms frames: 260722/07-10 and 260729/00-06, 260730/00-04 (48-loop frames), plus 260722/08-10 (64-loop frames). Each is 26.1-52.2 MB, i.e. 13-26 M int16 values. Fallback: the strict 13-capture 48-loop group (~590 MB).
- Estimated samples: 16
- Estimated primary values: 368,600,000
- Estimated download bytes: 460,000,000
- Estimated primary bytes: 737,300,000
- Decode path: curl the last ~2 MB of the ZIP (Range supported) to parse the central directory (349 entries, deflate members). Range-fetch each selected member's compressed bytes (local header offset + compressed size from the central directory) and inflate with zlib.decompressobj(-15). Validate the CRC32 and size from the central directory. Parse conf_file.cfg to assert the exact profile. Split the stream into 1088-byte chirp records: assert the 8-byte magic and constant header words, then emit the 1024-byte payload as little-endian int16. Assert file size % 1088 == 0 (verified: 26,112,000 / 1088 = 24,000 chirps). Pure stdlib.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://zenodo.org/records/22811456 --terms mmwave DCA1000 iwr6843: host-only URL match (zenodo.org, 51 unrelated recipes); no recipe or registry matches. The only ledger hit is illinois_radical_fmcw_radar_adc_frames_i16, screened out for access (robots/403), not material. No FMCW radar raw ADC exists in datasets/ or downstream families at any width.
- Homogeneity: Single device (IWR6843AOP) and one exact chirp profile (64 complex samples, 4 RX, ADC 16-bit complex 1x, 3 TX TDM, 100 ms frames). The only variation inside the suggested subset is loops per frame (48 vs 64); per-chirp records are byte-identical in structure. Other configurations (96-, 128- and 256-sample profiles, 2-TX, 55/120 ms frames) are excluded rather than mixed.
- Risks: Very recent record (published 2026-09-17, version unset); no file checksums are published, so pin the central-directory CRC32s and sizes. 16 samples is below the ~20 ideal, but it is the largest single-profile set under the 1 GB cap; the 18-capture 260727 group is 2.7 GB. HSI header semantics are inferred (constant words, magic-validated); headers must stay auxiliary or be dropped. Human subjects appear only as radar reflections; no identifying data.
- Probe evidence: HEAD: 200, content-length 3,712,631,577. Central directory parsed from a 2 MB tail range: 80 .bin captures, 5.48 GB uncompressed, 3.71 GB compressed. Fetched all config members and grouped them by exact chirp lines: 10 configurations (18/13/12/11/6/6/4/4/3/2/1 captures). Inflated a 400 KB prefix of 250619/03: HSI header every 4160 bytes (64 + 4096 payload for its 256-sample profile). Inflated the prefix of 260729/00 (target profile): 324 magics, constant spacing 1088, payload int16 range -3975 to 3885; member size 26,112,000 = 24,000 x 1088 exactly. Legends: walking, squared/circular paths, squats, two persons, falls.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_16bit/scout.20261006_035523.jsonl`).
