# 16-bit Dataset Hunt Runbook

This round stages scripts only. No dataset payload has been downloaded by the agent.

## Candidates

| dataset_id | domain | native 16-bit material | natural sample | expected primary output | key risk |
|---|---|---|---|---:|---|
| `librispeech_dev_clean_i16` | speech audio | losslessly compressed PCM speech decoded to signed int16 | one utterance | about 600-650 MB | requires `flac` or `ffmpeg` locally |
| `skadi_srtm_bay_area_hgt_i16` | elevation raster | existing local SRTM HGT signed int16 row shards repaired to whole-tile form | one upstream HGT tile | 25,934,402 bytes | single-sample registration of existing material |

## Commands For User Download

```bash
staging/librispeech_dev_clean_i16/download.sh
staging/skadi_srtm_bay_area_hgt_i16/download.sh
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

`skadi_srtm_bay_area_hgt_i16/download.sh` is a local import step, not a network download. By default it reads the already-present row shards from:

```text
/home/cyan/dev/openzl/training_data/numeric_datasets/16bit/datasets/srtm_skadi_elevation
```

It can also be pointed at a different local row-shard directory with `LOCAL_ROWS_DIR=/path/to/srtm_skadi_elevation`.

## Rejected Before Validation

- `landsat8_l1tp_bayarea_multispectral_u16`: rejected because the build path depends on GDAL, which is not locally available through `feature` and is too specific to require as an ambient system dependency.
