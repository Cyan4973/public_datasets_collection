# PhysioNet CHARIS Intracranial Pressure (ICP) Waveforms Int16

- Candidate id: `physionet_charis_icp_i16`
- Width: int16
- Quantity: Invasive intracranial pressure waveform, raw stored ADC codes (gain ~80-98 ADC/mmHg in most records; 129.2 and 60.8 in one record each), 50 Hz, multi-day neuro-ICU recordings of traumatic brain injury / SAH patients
- Source: https://physionet.org/content/charisdb/1.0.0/
- Resources: https://physionet-open.s3.amazonaws.com/charisdb/1.0.0/, https://physionet-open.s3.amazonaws.com/charisdb/1.0.0/SHA256SUMS.txt, https://physionet-open.s3.amazonaws.com/charisdb/1.0.0/RECORDS
- License: ODC-By 1.0 (Open Data Commons Attribution License v1.0)
- License evidence: https://physionet.org/content/charisdb/1.0.0/
- License quote: Anyone can access the files, as long as they conform to the terms of the specified license. License Open Data Commons Attribution License v1.0
- Natural record: One complete patient recording's ICP channel (signal 3 of the 3-signal ABP/ECG/ICP WFDB format-16 interleaved .dat), 7.2M-67.5M values per record.
- Estimated samples: 13
- Estimated primary values: 293,817,494
- Estimated download bytes: 1,762,910,168
- Estimated primary bytes: 587,634,988
- Decode path: curl the 13 charisN.hea/.dat pairs and verify them against SHA256SUMS.txt. Parse the .hea text: 3 signals, format 16, 50 Hz, nsamp. Read the .dat as array('h') (WFDB format 16 = little-endian int16) and de-interleave the frame stride 3, keeping index 2 (ICP). Check length = nsamp and the header checksum field (sum of samples mod 65536) per signal. Do not emit header comments (age/sex/diagnosis/outcome).
- Novelty kind: new_quantity
- Novelty evidence: novelty.py on the charisdb URL found only same-host matches (physionet_circor_pcg_i16). No hits for the terms intracranial, CHARIS, or ICP (only an irrelevant substring in usgs_chirp_segy_i16) in recipes, registry, ledger, downstream or downstream_registry. There are no intracranial or arterial pressure waveforms at any width locally or downstream.
- Homogeneity: One quantity (ICP, mmHg) from one ICU monitoring setup at 50 Hz across all 13 patients, the whole published population. The ADC codes form a dense integer lattice: range probes on charis1/2/5/9/12 gave step 1 with 334-3,862 distinct values per 10k samples and no -32768 fill. Gains are 80-98 ADC/mmHg in 11 records; charis9 is 129.2 and charis12 is 60.8. ABP (also novel) is deliberately left out to keep one quantity. It could be a sibling family.
- Risks: Only 13 samples, but that is the complete population and each sample is huge (24-135 MB), so this is acceptable when sources are limited. Download extraction ratio is 1/3, because ICP is interleaved with ABP and ECG in each .dat (1.76 GB download for 0.59 GB primary). Per-record gain differences (60.8-129.2 ADC/mmHg) could draw a homogeneity question, and the stored codes are raw ADC, not mmHg. Long artifact or flat segments may exist inside multi-day ICU recordings. Keep them as source-native values.
- Probe evidence: S3 listing: 13 .dat totaling 1,762,904,964 bytes (PhysioNet page: 1.6 GB total). All 13 headers fetched: 3 signals ABP/ECG/ICP, format 16, 50 Hz, nsamp 7,199,999-67,499,794 (sum 293,817,494 = dat bytes / 6). Range GETs (60 KB) on charis1, charis2, charis5, charis9 and charis12 decoded to plausible waveforms, e.g. charis1 ICP -366..1633 and ABP 5251..11487. The PhysioNet page shows ODC-By 1.0 with an open access policy.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_215706.jsonl`).
