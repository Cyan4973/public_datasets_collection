# Natural Boundary Audit

This report distinguishes physical sample files from natural records inside those files. A `natural_record_below_floor` status means the recipe currently uses block samples whose natural record size is below the 1,000-value median-sample floor.

| dataset_id | status | natural records | natural record values min/median/max | physical sample values |
|---|---|---:|---:|---:|
| `medmnist_pathmnist_images_u8` | `ok` | 107180 | 2352 / 2352 / 2352 | 252087360 |

## Samples

| dataset_id | series_id | split | natural record kind | natural records | values per natural record | physical sample values |
|---|---|---|---|---:|---:|---:|
| `medmnist_pathmnist_images_u8` | `pathmnist_images` | train | image | 89996 | 2352 | 211670592 |
| `medmnist_pathmnist_images_u8` | `pathmnist_images` | val | image | 10004 | 2352 | 23529408 |
| `medmnist_pathmnist_images_u8` | `pathmnist_images` | test | image | 7180 | 2352 | 16887360 |
