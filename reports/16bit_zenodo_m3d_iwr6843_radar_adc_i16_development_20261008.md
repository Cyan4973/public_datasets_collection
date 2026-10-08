# M3D Motion IWR6843AOP FMCW radar raw-ADC int16 development

## Outcome

Accepted `zenodo_m3d_iwr6843_radar_adc_i16`. The recipe collects all 16 DCA1000 captures from Zenodo record 22811456 that share one exact TI IWR6843AOP chirp profile at 100 ms frames. Each capture becomes one sample of native little-endian int16 FMCW radar IF ADC codes.

This is the first FMCW (chirp) radar raw-ADC family, locally or downstream, at any width. Its nearest relatives are different measurement processes:
- impulse GPR radargrams: `zenodo_gpr_rd3_i16`, `svalbard_gpr_radargram_i16`;
- decoded weather-radar products: NEXRAD, RADOLAN, FMI;
- SDR complex-baseband recordings: `zenodo_crab_giant_pulse_sigmf_ci16`, `v16_nb_iot_iq_ci16`.

The measured zlsim verdict is OK. The nearest family is `zenodo_mimii_valve_mic_array_i16` at 0.0553 feature distance with 15.7% compression loss.

**Archive-cap note:** this is the third autocollect acceptance from zenodo.org after `zenodo_pacbio_sequel_subread_ipd_codecv1_u8` and `zenodo_mimii_valve_mic_array_i16`. The driver's archive-cap rule should hold it for user sign-off.

## Source and rights

- Source: Zenodo record 22811456, "M3D Motion - Millimeter-Wave Motion and Dynamics Dataset".
  - Author: G. Marinaro, VSB - Technical University of Ostrava.
  - Published 2026-09-17. It is the second version of concept 21802511 and has no version string.
- File: `dataset_260917.zip`, 3,712,631,577 bytes, Zenodo MD5 `ce7e75179bcabac8fd3f934f75a863f4`.
- Pin: central directory SHA-256 `7038083082f33d9ba0e7dc2e1b82c35a07d6375ce6f3a74a4402eb3269064f4f` (349 entries, offset 3,712,592,250, 39,305 bytes), plus per-member CRC-32 and sizes in `selection.tsv`.
- License: CC-BY-4.0.
  - The record API gives `metadata.license.id = cc-by-4.0` and `access_right = open`. I re-checked it live on 2026-10-08.
  - The record holds a single file, so the license covers the exact data object. `download.sh` re-checks the license on every run.
- Safety: people appear only as radar reflections. Legends are activity labels only. There is no personal data.

## Shape and conversion

- The archive is never fetched whole.
  - Downloads: the 64 KiB tail, 158 small metadata members (69 cfgs, 80 DCA1000 logs, 9 legends) and 16 exact local-header-plus-DEFLATE ranges.
  - Download directory total: 453,893,791 bytes.
- Selection rule, re-derived on every download and compared byte for byte with `selection.tsv`:
  - exact `profileCfg 0 61.2 60 17 50 657930 0 55.27 1 64 2000 2 1 36`;
  - `channelCfg 15 7 0`, `adcCfg 2 1`, `adcbufCfg -1 0 1 1 1`, `lvdsStreamCfg -1 1 1 1`;
  - three TX chirpCfgs;
  - `frameCfg 0 2 L 0 100 1 0` with L in {48, 64}.
- Excluded:
  - 4 captures with the same chirp profile at 224 loops and 120 ms frames (862.8 MB, would breach the cap);
  - 11 captures without a cfg;
  - 49 captures in 5 other configurations.
- Natural record: one capture file, `datacard_record_hdr_0ADC_0.bin`.
  - It is a sequence of 1,088-byte HSI records: a 64-byte header plus 512 int16 values (RX0..RX3 × 64 complex samples).
  - The header is byte-identical in every chirp, carries no counter, and is validated and dropped.
  - Payloads are written unchanged in stored order. Nothing is reordered, rescaled or split.
- The DCA1000 log must report 0 out-of-sequence and 0 zero-filled packets, and received packets equal to the chirp count.

## Accepted output

- Primary samples: 16 (13 at 48 loops, 3 at 64 loops)
- Sample sizes: 14 × 24,576,000 values (48,000 chirps) and 2 × 12,288,000 values (24,000 chirps)
- Primary values: 368,640,000
- Primary bytes: 737,280,000
- Median sample: 24,576,000 values
- Chirp records: 720,000. HSI header bytes dropped: 46,080,000.
- Per-sample min −4,069..−4,033, max 3,951..4,002, 1,786–2,222 distinct codes, zero fraction 0.62–1.38%, 0 all-zero chirps.

## Judge checks

- `gate.py staging/zenodo_m3d_iwr6843_radar_adc_i16`: PASS, no warnings.
- `bash verify.sh`: VERIFY OK, re-run independently.
  - It is a separate implementation that re-derives every sample byte for byte from the ZIP ranges.
  - It recomputes min/max/SHA-256 and the distinct count, and checks index and manifest totals.
- `build.sh` and `verify.sh` use only local files under `.data/` (no curl/wget/http).
- `selftest_synthetic.py`, run from `/tmp/autocollect/...`: SELFTEST OK, with CRC, header and partial-record negatives.
- Bytes, inspected with stdlib `array`:
  - All integer codes in the core ±270 range are used.
  - Large near-constant transients occur only at the last complex sample of each 128-value RX block. This is consistent with the cfg timing: ADC window 17 µs + 32 µs = 49 µs against a 50 µs ramp end.
  - Lag-3 (same TX) mean abs chirp difference is 6–9, vs 28–65 at lag 1, confirming 3-TX TDM.
  - There are 0 duplicate 1,024-byte chirps within or across captures.
- Config diff: selected cfgs differ only in the frameCfg loop count (48 vs 64).
- Novelty:
  - `novelty.py` URL/term search, `--vocabulary` and `--type/--instrument/--archive` all show no same measurement type or instrument line.
  - The downstream 16-bit family list has no FMCW radar ADC.
- Rights: `record.json` and a live API call both show cc-by-4.0, open access, single file.
- Known documentation points (they do not affect the bytes):
  - The manifest's `semantic_meaning` says "60 GHz-start chirp". Per TI profileCfg field order, the start frequency is 61.2 GHz and 60 is the idle time in µs. Worth correcting on promotion.
  - The Q-then-I order within each pair is documentation-derived, as the README states. A positive-frequency energy test supports it on two of three captures (0.80/0.81) and is ambiguous on one (0.39).
