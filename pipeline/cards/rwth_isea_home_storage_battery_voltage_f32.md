# RWTH ISEA Multi-Year Residential PV Home-Storage Battery Systems 1 Hz Pack Terminal Voltage Float32 (48 V class)

- Candidate id: `rwth_isea_home_storage_battery_voltage_f32`
- Width: float32
- Quantity: System-level battery pack terminal voltage V_in_V (volts) measured once per second on privately operated PV home storage systems in Germany (ISEA/CARL RWTH Aachen field campaign 2014-2022). Scope restricted to the 15 low-voltage systems IDs 7-21 (13-16 cells in series, 46-51.8 V nominal, NMC/LFP, manufacturers B-E).
- Source: https://zenodo.org/records/12091223
- Resources: https://zenodo.org/api/records/12091223/files/Data_ID_18.zip/content, https://zenodo.org/api/records/12091223/files/Data_ID_07.zip/content, https://zenodo.org/api/records/12091223/files/Data_ID_21.zip/content, https://zenodo.org/api/records/12091223/files/Metadata_and_Code.zip/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/12091223
- License quote: Zenodo record metadata license: {'id': 'cc-by-4.0'} (Creative Commons Attribution 4.0 International) for 'Data for: Multi-year field measurements of home storage systems and their use in capacity estimation' (Figgener et al., Nature Energy 2024, DOI 10.1038/s41560-024-01620-9).
- Natural record: One system-month CSV inside a per-system zip (e.g. 18/2017_05_System_ID_18.csv), emitting its V_in_V column as one float32 1 Hz time series of about 2.4-2.7M values for a complete month. Columns P_in_W, I_in_A, T_Bat_in_C and T_Room_in_C are not mixed in. The Interpolated flag column is auxiliary/missing-value policy.
- Estimated samples: 30
- Estimated primary values: 72,000,000
- Estimated download bytes: 550,000,000
- Estimated primary bytes: 288,000,000
- Decode path: curl byte-range fetch of selected deflated monthly members, located via the zip central directory (Zenodo serves Range: 206). Whole Data_ID zips are 0.33-2.1 GB, so per-member range fetch is preferred. Then zlib.decompressobj(-15) raw inflate, csv module, struct.pack('<f'). Values are MATLAB %g prints with at most 6 significant digits (e.g. 51.842, 51.8419), so float32 round-trips them exactly (FLT_DIG=6). Pure stdlib.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url https://zenodo.org/records/12091223 --terms 'home storage' figgener isea 'battery voltage': no URL match beyond the generic Zenodo host. No registry, ledger or downstream term matches (one spurious 'isea' substring hit in disease_sh_countries). The local 32-bit battery family zenodo_battery_eis_complex_f32 is lab impedance spectra, a different quantity and record. Kollmeyer drive-cycle cell voltage exists only at 64-bit from a different lab source. All 7 pipeline-accepted 32-bit families are neuro or medical.
- Homogeneity: One quantity (pack terminal voltage, V), one measurement campaign and logger, 1 Hz. Metadata_Systems.xlsx shows IDs 1-6 are 40-series LMO/NMC packs at 146.7 V nominal, a different scale regime. Exclude them and keep IDs 7-21 (46-51.8 V nominal). Pick complete months; don't mix power/current/temperature.
- Risks: Zenodo returned HTTP 503 rate-limit pages during later probes; download.sh needs retries and per-member range fetches. Some months are partial or have interpolated gap fills (Interpolated=1). The builder must define a policy and report the share. The value range in a 48 V class is narrow (about 44-58 V). Per-system months differ in length. Sample selection should be spread across systems and years and stated explicitly.
- Probe evidence: Data_ID_18.zip (333,321,035 B) central directory via range GET: 35 entries, 34 monthly CSVs from 2016-08 (2,230,590,430 B uncompressed). Range-fetched and inflated the first 400 KB of member 18/2017_05_System_ID_18.csv. Header 'Time,P_in_W,V_in_V,I_in_A,T_Bat_in_C,T_Room_in_C,Interpolated', rows like '01-May-2017 00:00:00,-280.545,51.842,-5.4122,20.9782,20.3526,0'. V_in_V had 17,516 distinct values in 39k rows. Record lists 21 Data_ID zips (0.33-2.15 GB) plus a 31 KB Metadata_and_Code.zip, fetched and read for nominal voltages. Description: 21 systems, 106 system-years, 14 billion data points, 1,270 monthly files, 1 s sample rate.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_234311.jsonl`).
