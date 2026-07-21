# 8-bit Variety Hunt Runbook 2026-06-14

This batch targets byte-native domains that are different from FASTA, fixed-size
image benchmarks, and tiny tabular code streams.

Note: `natural_earth_vector_shp_u8` was later rejected because it emitted
Shapefile container bytes as `uint8`. Do not run that staged recipe; use the
decoded successor `natural_earth_10m_geometry_xy_f64`.

Hard bounds:

- accepted primary output must be at most `1,000,000,000` bytes
- candidates are not wins until user-run download, local build, local verify, and measured report complete
- measured reports must include sample count, total size, min/p10/p25/median/p75/p90/max sample sizes, unique sample-size count, and same-size concentration

## Staged Recipes

| dataset_id | domain | natural sample | expected value |
|---|---|---|---|
| `google_fonts_ofl_ttf_u8` | typography / font engineering | one `.ttf` or `.otf` source font file | binary font programs and tables, variable file sizes |
| `natural_earth_vector_shp_u8` | rejected/superseded cartographic vector data | one Natural Earth `.shp` layer geometry file | rejected opaque Shapefile container bytes |

## User-run Downloads

```sh
bash staging/google_fonts_ofl_ttf_u8/download.sh
```

## Local Processing

After downloads complete:

```sh
python3 tools/benchmark_8bit_variety_20260614.py
```

If some downloads fail but others are present, continue and record partial
results:

```sh
python3 tools/benchmark_8bit_variety_20260614.py --keep-going
```

To benchmark only the remaining completed staged dataset:

```sh
python3 tools/benchmark_8bit_variety_20260614.py --datasets google_fonts_ofl_ttf_u8
```

The benchmark runs each `build.sh` and `verify.sh`, then writes:

- `reports/8bit_variety_hunt_20260614_benchmark.json`
- `reports/8bit_variety_hunt_20260614_benchmark.tsv`
- `reports/8bit_variety_hunt_20260614_dataset_state.md`
- `reports/8bit_variety_hunt_20260614_dataset_state.tsv`

## Acceptance Notes

- `google_fonts_ofl_ttf_u8` uses a large source archive but emits a bounded selected primary payload; this is accepted for this hunt per user review.
- `natural_earth_vector_shp_u8` was rejected on 2026-07-21 because it emitted opaque Shapefile container bytes instead of decoded coordinate values.

## Current Local Run Notes

- `google_fonts_ofl_ttf_u8`: local `fonts-main.zip` archive was reused; download validation, build, and verify completed.
- `natural_earth_vector_shp_u8`: historical download, build, and verify completed locally, but the acceptance was overturned by the opaque-container cleanup.
- `mutopia_midi_files_u8`: rejected separately because the repository archive contains zero `.mid`/`.midi` files.
