# BBBC038 Nuclei Masks (u8)

Candidate `uint8` recipe for microscopy nuclei segmentation mask PNGs from
BBBC038.

The download script uses direct Broad Bioimage Benchmark Collection archive
URLs by default and validates that downloaded ZIPs contain mask PNGs. The build
emits one raw `uint8` mask sample per source mask PNG.

## Run

```bash
bash staging/bbbc038_nuclei_masks_u8/download.sh
bash staging/bbbc038_nuclei_masks_u8/build.sh
bash staging/bbbc038_nuclei_masks_u8/verify.sh
```

Optional:

- `BBBC038_URLS_FILE=/path/to/urls.tsv` supplies exact `source_id<TAB>url` rows.
- `BBBC038_MIN_VALUES=1000` controls the minimum decoded mask size.
