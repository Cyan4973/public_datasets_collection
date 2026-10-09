# MIMIC-III Waveform Database: Bedside-Monitor Invasive Arterial Blood Pressure (ABP) 125 Hz, WFDB Format-80 Stored Values Int8

- Candidate id: `physionet_mimic3wdb_abp_i8`
- Width: int8
- Quantity: Invasive arterial blood pressure waveform as stored 8-bit WFDB digits (format 80; gain 1.25 adu/mmHg, baseline -100), 125 Hz ICU bedside monitor
- Source: https://physionet.org/content/mimic3wdb/1.0/
- Resources: https://physionet.org/files/mimic3wdb/1.0/RECORDS-adults, https://physionet.org/files/mimic3wdb/1.0/30/RECORDS, https://physionet.org/files/mimic3wdb/1.0/30/3000003/3000003_0007.hea, https://physionet.org/files/mimic3wdb/1.0/30/3000003/3000003_0007.dat, https://physionet.org/files/mimic3wdb/1.0/LICENSE.txt
- License: ODbL-1.0
- License evidence: https://physionet.org/content/mimic3wdb/1.0/
- License quote: Access Policy: Anyone can access the files, as long as they conform to the terms of the specified license. License: Open Data Commons Open Database License v1.0
- Natural record: One continuous record segment (e.g. 3000003_0007, ~2.16 M frames ≈ 4.8 h). Emit only its ABP channel de-interleaved from the multi-signal format-80 .dat as int8 (byte-128)
- Estimated samples: 60
- Estimated primary values: 120,000,000
- Estimated download bytes: 450,000,000
- Estimated primary bytes: 120,000,000
- Decode path: curl RECORDS (directory 30), then each record's master .hea, then segment .hea headers (all small text). Select deterministically the first N segments with ABP at gain '1.25(-100)/mmHg', fmt 80 and length ≥ 500k frames. curl the segment .dat. In Python: read nsig from the header, take every nsig-th byte at ABP's column index, value = byte-128 (int8; -128 = WFDB invalid sample, keep or count as missing per policy). Verify the per-signal checksum (header field 7, 16-bit sum) against the decoded values. Pure stdlib.
- Novelty kind: new_source
- Measurement type: clinical_monitor_waveform
- Instrument line: philips_intellivue_icu_monitor_abp
- Archive collection: physionet.org/content/mimic3wdb
- Novelty evidence: novelty.py --url mimic3wdb --terms mimic 'arterial blood pressure' ABP: no MIMIC-III recipe or registry entry. The only 'ABP' match is physionet_charis_icp_i16 (16-bit ICP). clinical_monitor_waveform exists only at 16 bits (BIDMC PPG/resp, CHARIS ICP). The 8-bit physiological family is the MIT-BIH ECG (different waveform shape). ABP is a smooth, strongly periodic pressure wave, not an ECG.
- Homogeneity: Single quantity (ABP only), single storage convention (fmt 80, 125 Hz, gain 1.25(-100)/mmHg, confirmed on 3000003, 3000105 and 3013395). Skip ECG/PLETH/PAP/RESP channels and any ABP with a different gain. Adults only (RECORDS-adults) to avoid neonatal regimes.
- Risks: The whole multi-signal .dat must be downloaded to keep one channel (2-5x overhead). ODbL is share-alike, though accepted precedent exists (OSM/taginfo/NCLT recipes). MIMIC is de-identified clinical data released open access (no credentialing for mimic3wdb), but it is clinical-patient origin, so the judge should check the privacy reading. PhysioNet host count is high (5 prior autocollect acceptances). Flat-line or invalid (-128) stretches occur and need a missing-value policy.
- Probe evidence: Landing page: Open Access, ODbL v1.0, 6.7 TB total. Directory listing of /files/mimic3wdb/1.0/ shows 30/..39/, RECORDS, RECORDS-adults (712 KB) and RECORDS-waveforms. 30/RECORDS has 6,823 records. Header 3000003_0007.hea: '3 125 2155174', lines '3000003_0007.dat 80 29/mV ... II', '... 80 1.25(-100)/mmHg 8 0 125 29742 0 ABP'. 3000105_0008 and 3013395_0001 show the same ABP gain in format 80.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_182652.jsonl`).
