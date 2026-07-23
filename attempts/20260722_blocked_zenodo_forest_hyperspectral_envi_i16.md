# Blocked: zenodo_forest_hyperspectral_envi_i16 — records contain txt not ENVI

- Date: 2026-07-22
- Candidate: `staging/zenodo_forest_hyperspectral_envi_i16`
- Domain: drone forest hyperspectral ENVI

## Attempt

User ran download, log `.data/logs/zenodo_forest_hyperspectral_envi_i16/download.latest.log`

```
inspected_records=4 failures=4
failure record=13846686 reason=no_envi_like_file_suffixes
...
no Zenodo ENVI candidate files downloaded
```

Inventory shows records 13846686,13846724,13846747,14535368 each have single file `HYPER X.txt` (884,275,322,902 bytes), CC-BY-4.0, but no .hdr/.img/.dat/.zip ENVI payloads.

## Reason

Zenodo records for Lithuanian drone flights are metadata txt placeholders, not ENVI cubes. The ENVI data may be external or require additional steps. Suffix filter finds no candidates.

## Retry

Need to locate Zenodo records that actually host ENVI .dat/.hdr or .zip with ENVI inside, or parse txt files for external URLs.

