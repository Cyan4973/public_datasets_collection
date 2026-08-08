# PhysioNet BIDMC PPG and respiration int16 development — 2026-08-08

## Outcome

Accepted `physionet_bidmc_ppg_resp_i16`: 53 complete native signed-int16
photoplethysmographic optical-pulse waveforms and 53 complete native
signed-int16 respiratory waveforms from the public BIDMC clinical dataset.

## Domain and shape distinction

This family contributes two bedside-monitor physiological modalities that are
not present in the accepted corpus as native int16 series: optical blood-volume
pulse and respiration. Although the source records also contain ECG, the
recipe deliberately excludes it because ECG is already represented elsewhere.

Each output is a fixed-length one-dimensional temporal signal with 60,001
values sampled at 125 Hz, or about eight minutes. Keeping each patient-record
channel separate preserves the natural recording boundary and avoids
cross-record prediction artifacts.

## Source and license

PhysioNet publishes version 1.0.0 at DOI `10.13026/C2208R` with public access
under the Open Data Commons Attribution License v1.0. That license permits
reuse, including model-training use, subject to its attribution requirements.
The recipe preserves dataset, authorship, article, DOI, and PhysioNet citation
information in the manifest.

The downloader obtains all 53 official `.hea`/`.dat` pairs and verifies every
file against PhysioNet's `SHA256SUMS.txt` before processing.

- source records: 53
- checked source files: 106
- interleaved waveform bytes: 34,200,570
- source failures or exclusions: 0

## Native type and decoding

All selected channels are ordinary scalar WFDB format `16` with one sample per
frame, zero skew, and zero byte offset. WFDB format 16 is signed two-byte
little-endian storage. The decoder does not apply gain, calibration, rounding,
or physical-unit conversion; it preserves the stored integer code sequence.

For every record, the recipe enforces:

- record identity, 125 Hz frequency, and 60,001 frames
- 5–7 interleaved format-16 channels in one data file
- exactly one whole-token `PLETH` and one whole-token `RESP` description
- source byte size implied by frames and channel count
- declared initial value for every channel
- declared WFDB 16-bit checksum for every channel

Selected channels are deinterleaved and written explicitly as canonical
little-endian int16, including on a big-endian host.

## Accepted material

- 106 complete output samples
- 6,360,106 signed-int16 values
- 12,720,212 primary bytes
- 53 PLETH samples and 53 RESP samples
- 60,001 values and 120,002 bytes per sample
- all output hashes unique

PLETH samples contain 325–3,465 distinct values and 44,008–59,794 adjacent
transitions. RESP samples contain 270–4,096 distinct values and
6,999–58,285 adjacent transitions. Both families span the observed stored-code
range from -32,767 to 32,767 and are nonconstant.

Independent verification reparses all official sources, rechecks their
SHA-256 values and WFDB invariants, regenerates all canonical byte streams,
and compares every emitted byte, index row, and aggregate statistic.

## Safety and exclusions

This is sensitive human clinical waveform material from critically ill
patients. Upstream WFDB header comments contain demographic and contextual
fields, so the manifest conservatively marks the source as containing personal
and sensitive data. The emitted training samples include only one raw PLETH or
RESP integer sequence. They exclude age, sex, ward/location, dates, source
references, annotations, record metadata, and all ECG channels.
