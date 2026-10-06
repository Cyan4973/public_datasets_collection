# MIMII Industrial Valve Sound Recordings, 8-Channel Microphone Array 16 kHz PCM16 (6 dB SNR, Hitachi, Zenodo 3384388)

- Candidate id: `zenodo_mimii_valve_mic_array_i16`
- Width: int16
- Quantity: Acoustic pressure as signed 16-bit PCM from an 8-channel circular microphone array (TAMAGO-03) recording real industrial solenoid valves (4 product models, normal and anomalous operation such as contamination/leakage), with real factory background noise mixed in by the publisher at 6 dB SNR; 16 kHz, interleaved 8-channel frames.
- Source: https://zenodo.org/records/3384388
- Resources: https://zenodo.org/api/records/3384388/files/6_dB_valve.zip/content, https://zenodo.org/api/records/3384388, https://github.com/MIMII-hitachi/mimii_baseline/
- License: CC BY-SA 4.0
- License evidence: https://zenodo.org/records/3384388
- License quote: "This dataset is made available by Hitachi, Ltd. under a Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) license." (record metadata license id: cc-by-sa-4.0)
- Natural record: One 10-second 8-channel WAV clip (valve/id_XX/{normal,abnormal}/NNNNNNNN.wav): 160,000 frames x 8 channels = 1,280,000 int16 values (2,560,000 data bytes).
- Estimated samples: 200
- Estimated primary values: 256,000,000
- Estimated download bytes: 340,000,000
- Estimated primary bytes: 512,000,000
- Decode path: download.sh: 1-byte range check, then curl -r the tail of 6_dB_valve.zip (6,915,951,837 B) → parse the zip64 EOCD locator and central directory (4,183 entries; cd_off 6,915,459,463, cd_size 492,276) → choose a deterministic member list (e.g. per model id_00/02/04/06: first 40 normal + 10 abnormal) → curl -r each member's local header + compressed span (deflate method 8, ~1.6 MB each); verify CRC32 after inflate. build.sh (stdlib): local header → zlib.decompressobj(-15) → RIFF/WAVE with fmt WAVE_FORMAT_EXTENSIBLE (0xFFFE), channels 8, 16000 Hz, 16 bits → 'data' chunk of 2,560,000 B → int16 LE interleaved frames written as one sample per clip; assert exact size and format.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://zenodo.org/records/3384388 --terms MIMII 'industrial machine' Hitachi valve: no URL or MIMII matches. Term hits are coincidental (monado 'Valve Index' IMU, Hitachi SEM in an EBSD recipe). No MIMII/ToyADMOS/DCASE entries in registry or ledger. No industrial machine-condition acoustics or multichannel microphone-array audio exists locally or downstream.
- Homogeneity: One machine type (valve), one SNR product (6 dB), one array, one rate and format (8ch/16 kHz/PCM16), fixed 10 s clips. Normal and abnormal clips are operating states of the same regime. Do not mix machine types (fan/pump/slider) or SNR levels (-6/0/6 dB) in one family.
- Risks: (1) Breadth: this would be the third audio family at 16-bit in this collection effort, after physionet_circor_pcg_i16 and figshare_rousettus_vocalizations_i16, and many PCM16 audio recipes exist locally (ESC-50, LibriSpeech, NSynth, RIRs). The judge may rate it lower value despite the industrial focus and multichannel array. (2) CC BY-SA share-alike, which has accepted precedents (exomol, GOOSE). (3) The publisher mixed in factory noise (not a clean machine recording), but that mixed SNR product is the published material. (4) Each zip is 6.9–10.9 GB, so the recipe must range-read zip64 members rather than download whole archives.
- Probe evidence: Zenodo API record 3384388: 12 zips (6.92–10.88 GB), license cc-by-sa-4.0, version 'public 1.0'. 6_dB_valve.zip range 0-0 → 206 'bytes 0-0/6915951837'. A 3 MB tail read parsed the zip64 central directory: 4,170 WAV members (valve id_00/02/04/06; normal 708–1000 per id, abnormal 119–120), all deflate, each 2,560,080 B uncompressed. An 8 KB range of member 0 (offset 129) inflated to RIFF/WAVE fmt 0xFFFE, 8 ch, 16000 Hz, 16-bit, data 2,560,000 B; first samples [77,141,157,189,...].

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_16bit/scout.20261006_024243.jsonl`).
