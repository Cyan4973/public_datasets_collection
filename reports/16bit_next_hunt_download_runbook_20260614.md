# 16-bit Next Hunt Download Runbook

This runbook covers the first robust script wave from the license-first slate. The agent has not downloaded dataset payloads.

## Included Recipes

| dataset_id | domain | natural sample | default bounded scope | known risk |
|---|---|---|---|---|
| `dwd_radolan_rw_precip_i16` | weather radar raster | one RADOLAN RW composite | newest 192 visible files | all files are same raster dimensions |
| `nsynth_test_notes_i16` | musical instrument audio | one WAV note | NSynth test split | fixed-duration notes, so size diversity is weak |

## Download Commands

```bash
staging/dwd_radolan_rw_precip_i16/download.sh
staging/nsynth_test_notes_i16/download.sh
```

After the follow-up user run, both active recipes downloaded, built, and verified successfully. The original DWD script failure was a `.gz` versus `.bz2` discovery bug and has been patched.

Optional bounds:

```bash
FILE_LIMIT=96 staging/dwd_radolan_rw_precip_i16/download.sh
```

## Build, Verify, And Report

After downloads complete:

```bash
python3 tools/benchmark_16bit_next_hunt_20260614.py
```

The benchmark writes:

- `reports/16bit_next_hunt_20260614_dataset_state.md`
- `reports/16bit_next_hunt_20260614_dataset_state.tsv`
- `reports/16bit_next_hunt_20260614_dataset_state.json`

Use `--skip-build` only to summarize already-built local samples. Use `--download` only when intentionally running the download scripts yourself.

## Trainer Selector Metadata

Geometry is machine-readable in both the per-recipe manifest and the generated sample index:

- Manifest `[[series]]` fields: `sample_geometry`, `sample_rank`, `sample_shape`, and `sample_axes`.
- Per-sample `.data/index/<dataset_id>/samples.jsonl` fields with the same names.
- DWD uses `sample_geometry = "2d_raster"`, `sample_shape = [900, 900]`, `sample_axes = ["y", "x"]`.
- NSynth uses `sample_geometry = "1d_waveform"`, `sample_shape = [64000]`, `sample_axes = ["time"]`.

## Failed Or Deferred From First Wave

`sdss_corrected_frame_fits_i16` is removed from the active benchmark for now. The scripted SDSS directory discovery returned HTTP 503 for all selected directories and produced an empty plan, so it is not locally reproducible in the current form.

The PDS and SDO candidates remain deferred until exact integer-product URLs and simple parser assumptions are confirmed. That avoids writing brittle scripts that would only create cleanup work.
