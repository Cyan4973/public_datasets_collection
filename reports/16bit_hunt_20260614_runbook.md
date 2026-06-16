# 16-bit Dataset Hunt Runbook

This round stages scripts only. No dataset payload has been downloaded by the agent.

## Candidates

| dataset_id | domain | native 16-bit material | natural sample | expected primary output | key risk |
|---|---|---|---|---:|---|
| `librispeech_dev_clean_i16` | speech audio | losslessly compressed PCM speech decoded to signed int16 | one utterance | about 600-650 MB | requires `flac` or `ffmpeg` locally |

## Promoted Candidate

`librispeech_dev_clean_i16` has been promoted to:

```bash
datasets/librispeech_dev_clean_i16/download.sh
datasets/librispeech_dev_clean_i16/build.sh
datasets/librispeech_dev_clean_i16/verify.sh
```

Focused material report: `reports/librispeech_dev_clean_i16_state.md`.

The temporary `skadi_srtm_bay_area_hgt_i16` staging recipe was not promoted as
a separate dataset. It was the same `N37W122` SKADI/SRTM tile as
`datasets/skadi_srtm_hgt`, and its whole-tile boundary repair has been applied
to `skadi_srtm_hgt` directly.

## Original Commands For User Download

```bash
staging/librispeech_dev_clean_i16/download.sh
```

## Commands After Downloads Exist

```bash
python3 tools/benchmark_16bit_hunt_20260614.py
```

The benchmark builds and verifies each recipe from local files and writes:

- `reports/16bit_hunt_20260614_dataset_state.md`
- `reports/16bit_hunt_20260614_dataset_state.tsv`
- `reports/16bit_hunt_20260614_dataset_state.json`

Use `--skip-build` only to summarize already-built local samples. Use `--download` only when intentionally running the download scripts yourself.

## Rejected Before Validation

- `landsat8_l1tp_bayarea_multispectral_u16`: rejected because the build path depends on GDAL, which is not locally available through `feature` and is too specific to require as an ambient system dependency.
