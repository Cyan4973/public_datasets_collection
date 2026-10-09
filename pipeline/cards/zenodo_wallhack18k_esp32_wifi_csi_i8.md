# Wallhack1.8k (TU Wien, Zenodo 13950918): ESP32-S3 Wi-Fi Channel State Information, Raw Per-Packet Int8 Subcarrier I/Q (LLTF+HT-LTF, 128 subcarriers, 100 Hz), LoS and Through-Wall Recordings

- Candidate id: `zenodo_wallhack18k_esp32_wifi_csi_i8`
- Width: int8
- Quantity: Per-packet Wi-Fi channel frequency response (CSI): the ESP32 firmware's native signed 8-bit imaginary/real pairs for 128 OFDM subcarriers (LLTF + HT-LTF, 256 int8 values per packet), packets at about 100 Hz while people are absent, walking, or walking and arm-waving in LoS or through-wall settings
- Source: https://zenodo.org/records/13950918
- Resources: https://zenodo.org/records/13950918/files/wallhack1.8k.zip, https://zenodo.org/api/records/13950918, https://github.com/StrohmayerJ/wallhack1.8k
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/13950918
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"} (Creative Commons Attribution 4.0 International). Creators: Strohmayer, Julian; Kampel, Martin. DOI 10.5281/zenodo.13950918
- Natural record: One raw CSI recording CSV (one session of one antenna system in one scenario, e.g. LOS/BQ/w1.csv). Each row is one received packet (type=CSI_DATA, len=256) whose quoted 'data' column holds 256 int8 values. One sample = the concatenated per-packet CSI vectors of one recording file, in packet order (natural boundary = the file)
- Estimated samples: 44
- Estimated primary values: 180,000,000
- Estimated download bytes: 135,133,863
- Estimated primary bytes: 180,000,000
- Decode path: download.sh: curl the single 135 MB zip (CC BY 4.0, pinned size 135133863, plus md5 from the Zenodo API). build.sh: stdlib zipfile reads the 44 *.csv members (skip spectrograms/*.png and the label CSVs). csv.reader parses rows; keep rows with type=='CSI_DATA' and len=='256' (also assert sig_mode/bandwidth are constant per file). Parse the 'data' field '[i0,r0,i1,r1,...]' into 256 ints, assert -128..127, and pack with array('b'). Write one .bin per CSV. Optional auxiliary rssi/noise_floor series (int8) must not count toward the floor
- Novelty kind: new_modality
- Measurement type: wifi_channel_state_information
- Instrument line: espressif_esp32s3_wifi_csi (custom BQ biquad / PIFA antenna receivers)
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/13950918 --terms wallhack CSI ESP32 'channel state': URL is 'same host only' (generic zenodo); the only term hit is the substring 'csi' inside 'csiro'. No downstream match. novelty.py --type wifi_csi: same_measurement_type 0. The vocabulary has no CSI or channel-response type: the nearest are rf_iq_baseband (raw time-domain I/Q) and rf_signal_strength (scalar RSSI). This is per-subcarrier frequency-domain channel estimates from a commodity Wi-Fi chip
- Homogeneity: One chip (ESP32-S3), one firmware CSI format (HT20, LLTF+HT-LTF, len=256), one packet rate (100 Hz), one unit (raw int8 channel-estimate codes). The 44 files are 4 groups {LOS,NLOS} x {BQ biquad antenna, PIFA antenna}: 4 long b1.csv (about 50 MB text each) and 40 w*/ww*.csv (about 10.5 MB each). Antenna and wall change only the channel, not the representation. If the judge wants it tighter, restrict to one antenna system (22 files, about 90M values) and stay well above the floors
- Risks: (1) Guard and null subcarriers are always 0 (about 22% of values; positions 0-11, 64-65, 118-139 and so on), so samples carry a structured zero pattern. That is genuine CSI layout, not fill, but the judge may question it. (2) Some rows may have a different len or be malformed; the builder must filter on len==256 and log the drop counts. (3) A possible byte-level neighbour is pending zenodo_ata_spacecraft_telemetry_iq_i8 / SHARAD int8, but CSI is smooth across subcarriers with structured zeros rather than near-white noise, so a WEAK verdict seems unlikely. (4) A small population (44 files) limits sample count, but natural records are large (3-15M values)
- Probe evidence: Zenodo API: one file wallhack1.8k.zip, 135,133,863 bytes, cc-by-4.0. A tail range GET parsed the zip central directory: 1,894 entries, 44 raw CSI CSVs (uncompressed 9.7-51.3 MB each), 1,822 spectrogram PNGs and readme.txt. A range GET plus raw-inflate of LOS/BQ/b1.csv and LOS/BQ/w1.csv shows the header 'type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,...,len,first_word,data,class,x,y,z' and rows like 'CSI_DATA,62111,...,-48,...,len=256,..., "[0,0,...,6,-1,6,-2,...,35,-2,36,-4,...]"'. local_timestamp steps by about 10,000 us, i.e. 100 Hz. Values seen span about -38..36, signed int8 pairs

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_015508.jsonl`).
