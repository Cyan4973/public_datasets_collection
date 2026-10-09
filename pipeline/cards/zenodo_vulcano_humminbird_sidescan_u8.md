# Vulcano Summer School 2018 Humminbird Side-Imaging Sonar: Native .SON Port/Starboard Side-Scan Ping Amplitudes UInt8 (Zenodo 1401000)

- Candidate id: `zenodo_vulcano_humminbird_sidescan_u8`
- Width: uint8
- Quantity: Side-scan sonar backscatter amplitude per range bin (8-bit) from Humminbird side-imaging transducer channels B002/B003, shallow-water survey around Vulcano (Aeolian Islands)
- Source: https://zenodo.org/records/1401000
- Resources: https://zenodo.org/records/1401000/files/Data-19-2006.zip?download=1, https://zenodo.org/api/records/1401000
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/1401000
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"}; description: 'This dataset of Humminbird Sonar data was acquired during the Vulcano Summer School in June 2018 ... standard Humminbird DAT file format'
- Natural record: One sidescan channel file of one recording (R000NN/B002.SON or B003.SON), emitted as concatenated per-ping uint8 sample blocks (pings x range bins) with the per-ping tag headers stripped
- Estimated samples: 20
- Estimated primary values: 820,000,000
- Estimated download bytes: 540,000,000
- Estimated primary bytes: 820,000,000
- Decode path: curl range-fetch only the 20 B002/B003 .SON members of Data-19-2006.zip (it contains all recordings R00021-R00030; local-header offsets from the central directory, no zip64) -> zlib raw inflate -> walk pings: each starts with magic C0 DE AB 21, followed by tagged fields (0x80.., 0x81.., ... 0xA0 + 4-byte BE sample count, then 0x21), then <count> uint8 samples. Verified on R00027/B002.SON: ping stride 947 B, header 72 B, 875 samples.
- Novelty kind: new_source
- Measurement type: sidescan_sonar
- Instrument line: humminbird_side_imaging_sonar
- Archive collection: zenodo.org/records/1401000
- Novelty evidence: novelty.py --terms humminbird sidescan vulcano: the only sidescan family is usgs_grandbay_klein3900_sidescan_xtf_u16 (16-bit Klein). usgs_sidescan_sonar_tiff_u8 is blocked (404 mosaic, a different source and product: mosaics, not pings). There is no 8-bit sidescan ping family locally or downstream, and no Humminbird/Vulcano match.
- Homogeneity: One recreational Humminbird unit, one survey (June 2018), side-imaging channels only (B002 port, B003 starboard; same frequency and quantity). Down-imaging B000 and 83/200 kHz down-sonar B001 are excluded. Ping length can differ between recordings with the range setting, but is constant within a file. If size is a concern, keep B002+B003 for all 10 recordings (~820 MB, under the cap) or one side only (~410 MB).
- Risks: Sidescan speckle might sit close to the 8-bit SAR families (Magellan/Cassini) in zlsim, though water-column dead zones and the ping geometry differ. The SON tag layout should be confirmed per recording (tag set may vary). Data-1406/1506/1606 zips duplicate recordings in Data-19-2006, so use only the latter. The per-file volume is large (126 MB for R00025).
- Probe evidence: Zenodo API: 4 zips. A 200 KB tail range GET of Data-19-2006.zip (1,176,823,667 B) parsed its central directory: R00021-R00030, each with B001/B002/B003 (and B000 for some) .SON plus .IDX. Range GET of R00027/B002.SON (1 MB) inflated to 1.65 MB. Pings at offsets 0, 947, 1894, ... start with c0deab21; sample bytes range 0..199.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_182652.jsonl`).
