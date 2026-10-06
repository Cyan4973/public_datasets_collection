# PhysioNet Term-Preterm EHG Database Unfiltered Uterine Electrohysterogram Int16

- Candidate id: `physionet_tpehg_ehg_i16`
- Width: int16
- Quantity: Electrohysterogram (abdominal uterine EMG) bipolar channels 1-3, unfiltered, 16-bit ADC over +/-2.5 mV (gain 13107 ADC/mV), 20 Hz, ~30-minute recordings in pregnancy
- Source: https://physionet.org/content/tpehgdb/1.0.1/
- Resources: https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1/tpehgdb/, https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1/RECORDS, https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1/SHA256SUMS.txt
- License: ODC-By 1.0 (Open Data Commons Attribution License v1.0)
- License evidence: https://physionet.org/content/tpehgdb/1.0.1/
- License quote: Anyone can access the files, as long as they conform to the terms of the specified license. License Open Data Commons Attribution License v1.0
- Natural record: One complete recording (tpehgNNNN): the three unfiltered EHG channels '1', '2', '3' (signal indices 0, 4, 8 of the 12-signal frame), 15,060-39,873 frames per record (median 35,360). Emit either as one 3-channel interleaved sample per record or one sample per channel.
- Estimated samples: 300
- Estimated primary values: 31,967,703
- Estimated download bytes: 256,100,000
- Estimated primary bytes: 63,935,406
- Decode path: curl the 300 .hea/.dat pairs listed in RECORDS and verify them against SHA256SUMS.txt. Parse the header: 12 signals, all format 16, gain 13107, 16-bit. Read the .dat with array('h') little-endian, stride 12, keeping signals 0, 4 and 8 (names '1', '2', '3'). Check nsamp and the per-signal checksum. Drop the 9 DOCFILT-* signals, which are digitally filtered derivatives.
- Novelty kind: new_modality
- Novelty evidence: novelty.py on the tpehgdb URL found only same-host matches (CirCor PCG). No hits for the terms electrohysterogram, EHG, uterine, or TPEHG in any layer: recipes, registry, ledger, downstream or downstream_registry. Uterine electrophysiology is absent from the corpus at all widths.
- Homogeneity: All 300 headers fetched and checked: 12 signals, format 16, gain 13107/mV, 16-bit resolution, 20 Hz (174 headers say 20.000000 and 126 say 20.000110). This is one device, one protocol, and one quantity. Only the unfiltered channels are primary. A range probe of tpehg1007 shows dense step-1 lattices: raw channels have 769-1,343 distinct values per 2,000 samples, spanning about -2,500..2,100.
- Risks: Small total (~64 MB primary), but it is the complete population of 300 records. The 1/4 extraction ratio is acceptable at a 256 MB download. 126 headers declare 20.000110 Hz; record the header value as-is. The judge might question whether channels 1-3 are 'raw': per the database description they are the unfiltered signals, with only analog acquisition filtering.
- Probe evidence: S3 listing: 300 .dat totaling 255,741,624 bytes (page: 245.4 MB total). All 300 .hea files fetched (300 KB); frames total 10,655,901. A 48 KB range GET of tpehg1007.dat decoded into 12 interleaved int16 channels with plausible EHG ranges. The PhysioNet page shows ODC-By 1.0 with an open access policy.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_215706.jsonl`).
