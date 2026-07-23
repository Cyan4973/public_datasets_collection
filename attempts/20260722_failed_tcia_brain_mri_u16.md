# Failed: tcia_brain_mri_u16 — TCIA API JSON decode error

- Date: 2026-07-22
- Candidate: `staging/tcia_brain_mri_u16`
- Domain: brain MRI T1

## Attempt

```
bash staging/tcia_brain_mri_u16/download.sh
```

Log: `.data/logs/tcia_brain_mri_u16/download.latest.log`

```
File ".../bounded_url_download.py", line 129, in discover_tcia_series
  series = json.loads(fetch_text(url, timeout))
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

Collection: `TCGA-GBM`

## Reason

NBIA API v1/getSeries?Collection=TCGA-GBM returned empty or HTML error page, not JSON array, causing JSON decode error. The existing `tcia_nsclc_radiomics_ct_i16` (collection NSCLC-Radiomics) works and downloads 6 zips 220 MB.

Possible causes: TCGA-GBM collection name case-sensitive, or requires v2 API, or API now requires key, or collection has huge series list that times out.

## Retry

- Use known working collection with MRI modality, e.g., `Brain-Tumor-Progression`, `TCGA-LGG`, `BraTS-2021`, and handle JSON errors with fallback error message
- Add try/except for JSON decode and fallback to empty list with clear message
- Or provide exact SeriesInstanceUIDs via URL list

## Value

MRI T1 distinct from CT.

