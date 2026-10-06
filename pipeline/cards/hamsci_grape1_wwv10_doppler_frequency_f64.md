# HamSCI PSWS Grape V1 HF-Doppler Received Carrier Frequency of WWV 10 MHz (1 Hz station-day series) Float64

- Candidate id: `hamsci_grape1_wwv10_doppler_frequency_f64`
- Width: float64
- Quantity: Received carrier-frequency estimate [Hz] of the NIST WWV 10 MHz time-standard broadcast, measured once per second by GPSDO-disciplined Grape V1 receivers. It is about 10,000,000 Hz ± ionospheric Doppler, mHz resolution (about 10 significant digits, beyond float32), giving an HF ionospheric-propagation Doppler time series. Primary is the 'Freq' column. 'Vpk' amplitude may be a separate optional series.
- Source: https://zenodo.org/records/6590283
- Resources: https://zenodo.org/api/records/6590283, https://zenodo.org/records/6590283/files/2020-07-21T000000Z_N00009_G1_FN20ge_FRQ_WWV10.csv.gz?download=1
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/6590283
- License quote: Zenodo record 6590283 'Grape V1 Data: Frequency Estimation and Amplitudes of North American Time Standard Stations' — metadata license: {'id': 'cc-by-4.0'} (Creative Commons Attribution 4.0 International), covering all 3,017 deposited files.
- Natural record: One station-day file <date>T000000Z_<node>_G1_<grid>_FRQ_WWV10.csv.gz: '#' metadata header, then 'UTC,Freq,Vpk' rows at 1 Hz, i.e. 86,400 Freq values per sample. WWV10 population: 920 station-days from 6 stations (N00009 FN20ge, N0000007 EN91fh, N0000014, N0000015, N00010, N0000029), 2020-07-21..2021-05-15. Suggest about 400 files spread across all six stations (or all 920 if the cap allows; 636 MB primary).
- Estimated samples: 400
- Estimated primary values: 34,560,000
- Estimated download bytes: 267,000,000
- Estimated primary bytes: 276,480,000
- Decode path: gzip (stdlib) then line parsing: skip '#' lines and the 'UTC,Freq,Vpk' header, split on commas, float(Freq) gives a little-endian double. The decimal text has about 10 significant digits, so the float64 round-trip is exact to the printed value. Validate the per-row 1 s cadence and record gaps; skip the 71-byte empty files. The Zenodo API provides per-file md5 checksums for download.sh to verify.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://zenodo.org/records/6590283 --terms grape doppler wwv hamsci found no URL, recipe, registry or downstream match for Grape, WWV or HamSCI. The only 'doppler' hits are 8/16-bit weather-radar velocity and ADCP families, which are different instruments and quantities. There is no HF-radio ionospheric Doppler material at any width locally or downstream. It is in the radio/SDR focus domain.
- Homogeneity: Restricted to one beacon (WWV 10 MHz), so every value sits on the same ~1e7 Hz scale with the same mHz print resolution. Do NOT mix WWV2p5/WWV5 files (2.5/5 MHz carriers are different scales: the bookticker lesson) or the S1-receiver files. All receivers are Grape Gen-1 with GPSDO references. Station-to-station noise differences are within one regime.
- Risks: Zenodo per-file downloads of hundreds of files need polite pacing and retries. Some station-days may be partial (receiver restarts) or contain outliers when the beacon fades. Builder should keep files with near-full 86,400 rows, or document partial-day handling, and verify cadence. A judge might ask whether mHz-quantized decimals are 'native' f64: the 10-significant-digit values exceed float32, and f64 is the conventional decoded representation.
- Probe evidence: Zenodo API: 3,017 files, 1.99 GB total, license cc-by-4.0, md5 checksums listed. Station/beacon tally from filenames: WWV10 = 920 files / 614,396,212 bytes (median 687 KB gz); WWV5 = 836; WWV2p5 = 308. A Range GET of the first 16 KB of a WWV5 file, partially inflated, shows the '#' metadata block (node, callsign, lat/lon, 'Frequency Standard LB GPSDO') and rows like '2020-03-23T00:00:00Z, 4999999.446, 0.016339' at 1 s cadence. One-byte range GET (-L) on a WWV10 file returned 206/1 byte.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_231243.jsonl`).
