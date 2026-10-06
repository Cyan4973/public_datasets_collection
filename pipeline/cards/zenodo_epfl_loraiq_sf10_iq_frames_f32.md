# LoRaIQ (EPFL): Over-the-Air LoRa SF10/250 kHz Frame Recordings from Rooftop USRP Remote Radio Heads, SigMF cf32_le Complex Baseband IQ

- Candidate id: `zenodo_epfl_loraiq_sf10_iq_frames_f32`
- Width: float32
- Quantity: Complex baseband I/Q samples (cf32_le, 500 ksps, centre 862.5 MHz) captured by four EPFL-campus rooftop USRP-2920 remote radio heads. Each SigMF data file holds one detected LoRa SF10 / CR1 / BW 250 kHz uplink frame plus surrounding channel noise, transmitted from drones in LOS and NLOS conditions.
- Source: https://zenodo.org/records/17708397
- Resources: https://zenodo.org/api/records/17708397/files/sigmfs.zip/content, https://zenodo.org/api/records/17708397/files/dataset.csv/content, https://zenodo.org/api/records/17708397
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/17708397
- License quote: Zenodo record metadata license id 'cc-by-4.0' (Creative Commons Attribution 4.0 International) for 'LoRaIQ: Experimental LoRa Dataset with Annotated IQ Samples' (2025-12-01), covering sigmfs.zip and dataset.csv.
- Natural record: One SigMF recording (<n>.sigmf-data plus its sigmf-meta) holding exactly one detected LoRa frame. For SF10 sessions the median is ~960 KB, ~240k float32 values (120k complex samples); range 942 KB–1.8 MB.
- Estimated samples: 400
- Estimated primary values: 96,000,000
- Estimated download bytes: 395,000,000
- Estimated primary bytes: 385,000,000
- Decode path: Download dataset.csv (18.3 MB) and select rows with sf=10, bandwidth=250000, rx_sample_rate=500000, fc=862.5 (41,229 frames in 71,582 unique files). Range-fetch the ZIP64 EOCD/locator and then the 17.3 MB central directory (offset 49,729,255,847; 143,275 entries). For about 400 evenly spaced selected files, range-fetch each local header plus the deflated member. Inflate with zlib.decompressobj(-15), check CRC32 against the CD, and parse the sibling sigmf-meta JSON: assert core:datatype=='cf32_le', sample_rate 500000, and that the sha512 matches the data. Write the little-endian float32 I/Q stream unchanged.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://zenodo.org/records/17708397 --terms LoRaIQ sigmf cf32 'IQ samples' found the Zenodo host only (51 recipes, unrelated records). Term hits are only 16-bit families: zenodo_v16_nb_iot_sigmf_ci16, zenodo_crab_giant_pulse_sigmf_ci16 and the downstream crab_giant_pulse_iq_ci16. The ledger has nothing. No over-the-air SDR IQ capture exists at 32-bit locally or downstream. The 8-bit LoRa family (zenodo_lora24_indoor_rssi_i8) is RSSI, not IQ.
- Homogeneity: Pin a single radio configuration: SF10, CR1, BW 250 kHz, 500 ksps, 862.5 MHz, USRP-2920 RRHs, drone campaigns (drone_los/drone_nlos, September 2025 sessions). Exclude the SF7 / BW 125 kHz / 250 ksps pedestrian_nlos sessions (30,353 files): they are a different sample rate and occupancy regime. Spread the selection over sessions and RRH 1–4.
- Risks: The 17 MB central-directory and 18 MB CSV fetches are metadata overhead. Members are deflated (ratio ~0.89), so extraction needs zlib, which is stdlib. Amplitudes are small (~±0.006) because the USRP stream was scaled and filtered by the capture software. Values are genuinely continuous: in a probe only 0.009% fell on a 1/32768 grid and 99.6% were unique, so this is not widened int16. Each file includes noise margins around the frame; that is part of the natural record. The dataset is recent (v1, 2025) and the version should be pinned.
- Probe evidence: A Zenodo API record fetch confirmed license cc-by-4.0, 5 files, and sigmfs.zip at 49,746,561,196 B. A one-byte range GET returned 206. A 64 KB tail range gave the ZIP64 EOCD: 143,275 entries, CD size 17,305,251 at offset 49,729,255,847. Three 256 KB CD slices showed deflate (method 8) members. SF7 session 25_01_15 has a median of 127 KB uncompressed; SF10 session 25_09_17 has a median of 960,824 B uncompressed (859,627 compressed). One meta member inflated to core:datatype 'cf32_le', sample_rate 250000, freq 862.5, SigMF 1.2.0, with a 'Detected LoRa Frame' annotation. One data member (127,640 B) inflated with a CRC match to 31,910 float32 values in ±0.006, 99.6% unique. The dataset.csv (18.3 MB) has 75,086 frames: 41,229 SF10/250k/500ksps and 33,857 SF7/125k/250ksps, across 22 sessions. Total transfer about 19.5 MB.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261006_035508.jsonl`).
