# ANSSI ASCAD v1 (fixed key): Raw ATMega8515 AES Side-Channel EM/Power Oscilloscope Traces (100,000 samples per acquisition, native int8)

- Candidate id: `ascad_atmega8515_raw_power_traces_i8`
- Width: int8
- Quantity: Signed 8-bit oscilloscope ADC samples of the electromagnetic/power side-channel of an 8-bit AVR (ATMega8515) running masked AES-128. One full 100,000-sample acquisition per trace. These are native int8 digitizer codes stored as the HDF5 dataset 'traces' (60000 x 100000 int8) in ATMega8515_raw_traces.h5.
- Source: https://www.data.gouv.fr/datasets/ascad
- Resources: https://static.data.gouv.fr/resources/ascad/20180530-163000/ASCAD_data.zip, https://www.data.gouv.fr/api/1/datasets/5aaa829dc751df2fbd43eacb/, https://github.com/ANSSI-FR/ASCAD
- License: Licence Ouverte / Open Licence (Etalab, fr-lo; OKD-compliant), publisher ANSSI
- License evidence: https://www.data.gouv.fr/api/1/datasets/5aaa829dc751df2fbd43eacb/
- License quote: data.gouv.fr dataset 'ASCAD' (organization: Agence Nationale de la Sécurité des Systèmes d'Information): "license": "fr-lo" -> {'title': 'Licence Ouverte / Open Licence', 'flags': ['domain_data', 'okd_compliant', 'domain_content'], 'url': 'https://www.etalab.gouv.fr/wp-content/uploads/2014/05/Licence_Ouverte.pdf'}. The companion GitHub repo states 'The files in this project are provided under a BSD license.' Both are permissive, so there is no conflict.
- Natural record: One acquisition trace (100,000 int8 samples = one AES execution capture). Bounded subset: the first about 2,000 traces in acquisition order. These are reachable without the 4.4 GB zip by range-GETting the start of the deflated zip member and inflating a prefix.
- Estimated samples: 2,000
- Estimated primary values: 200,000,000
- Estimated download bytes: 105,000,000
- Estimated primary bytes: 200,000,000
- Decode path: The zip member ASCAD_data/ASCAD_databases/ATMega8515_raw_traces.h5 uses method 8 (deflate), compressed 2,966,104,128 B, uncompressed 6,003,842,144 B, local header at offset 72,006,934 (zip64 central directory). download.sh: curl -r 72006934-<72006934+~105MB> into .part and pin its sha256. build: skip the 30+name+extra local header and inflate with zlib.decompressobj(-15) until 3,842,144 + N*100,000 bytes are available. Check the HDF5 superblock v0 signature, then confirm (or parse) the v3 contiguous layout message: 'traces' at address 3,842,144, size 6,000,000,000. Slice traces of 100,000 B and write them as int8. Pure stdlib, no h5py needed, because the layout is contiguous and uncompressed inside the member.
- Novelty kind: new_source
- Measurement type: oscilloscope_trace
- Instrument line: lecroy_oscilloscope_side_channel_em_probe_atmega8515
- Archive collection: static.data.gouv.fr/resources/ascad
- Novelty evidence: novelty.py on the static.data.gouv.fr URL and the terms ascad/atmega8515/side-channel/'power trace': no matches in recipes, registry, ledger or downstream. At 8 bits there is no oscilloscope or side-channel waveform family. The only oscilloscope_trace is zenodo_lecroy_oscilloscope_i16 (16-bit detector pulses). data.gouv.fr is an archive the corpus has never used.
- Homogeneity: One device (ATMega8515 smartcard), one fixed key, one oscilloscope setup and sampling configuration, one campaign. Traces are synchronized and share length and scale. The first N in acquisition order form a coherent bounded subset.
- Risks: (1) Traces are synchronized captures of the same operation, so adjacent traces differ by about 1.1 LSB mean absolute difference. A judge may read this as near-duplicate fixed-length series. The counterpoint is that each sample is a rich 100k-point waveform, and the inter-trace variation (noise plus data-dependent leakage) is the scientific content. (2) The range-plus-inflate path depends on traces starting at uncompressed offset 3,842,144. This was verified from the inflated prefix, but the builder should parse rather than hard-code, or assert both. (3) The variable-key ASCAD dataset on data.gouv.fr has license 'notspecified' and must not be used. Only the fixed-key 'ascad' dataset (fr-lo) qualifies.
- Probe evidence: Zip tail range GET (64 KB): zip64 EOCD, 13 entries, member table shown in decode_path. A 4.2 MB range GET of the member start inflated to 6.29 MB: '\x89HDF\r\n\x1a\n' superblock v0, 8-byte offsets/lengths, names metadata/traces/plaintext/key/masks. Contiguous layout messages: addr 2144 size 3,840,000 (metadata) and addr 3,842,144 size 6,000,000,000 (traces). Trace 0 decoded as int8: min -70, max 52, 118 distinct values, smooth clock-driven waveform (52,45,39,39,41,45,47,45,39,27,14,0,-15,-31,...). Trace 0 vs trace 1 mean |diff| = 1.13.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_224222.jsonl`).
