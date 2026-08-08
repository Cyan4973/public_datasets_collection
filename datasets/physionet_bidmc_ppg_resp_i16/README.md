# PhysioNet BIDMC PPG and respiration int16

This recipe extracts the native signed-16-bit `PLETH` and `RESP` waveform
channels from all 53 records in PhysioNet's BIDMC PPG and Respiration Dataset.
One complete channel from one record is one fixed-length sample of 60,001
values at 125 Hz.

Run:

1. `bash datasets/physionet_bidmc_ppg_resp_i16/download.sh`
2. `bash datasets/physionet_bidmc_ppg_resp_i16/build.sh`
3. `bash datasets/physionet_bidmc_ppg_resp_i16/verify.sh`

The downloader checks every `.hea` and `.dat` file against PhysioNet's
official SHA-256 inventory. The dependency-free builder validates WFDB format,
geometry, initial values, and per-channel checksums, then deinterleaves the two
selected raw channels. The verifier independently repeats the source decode
and compares every output byte and metadata record.

Outputs are canonical little-endian int16. The recipe deliberately excludes
ECG channels and every source-header comment, including record context,
demographic, location, date, and source-reference fields. This remains human
clinical waveform material and should be handled accordingly.
