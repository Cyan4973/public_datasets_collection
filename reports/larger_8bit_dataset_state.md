# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, and median primary sample size at least `1000` values.

## `emnist_byclass_images_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 2
- primary_values: 638375920
- primary_bytes: 638375920
- primary_value_count_range: 91197232 / 319187960 / 547178688 min/median/max
- primary_size_range_bytes: 91197232 / 319187960 / 547178688 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `emnist_byclass_images` | primary | uint | 8 | 2 | 638375920 | 638375920 | 91197232 / 319187960 / 547178688 | 91197232 / 319187960 / 547178688 | 0 |
| `emnist_byclass_labels` | auxiliary | uint | 8 | 2 | 814255 | 814255 | 116323 / 407127.5 / 697932 | 116323 / 407127.5 / 697932 | 0 |

## `medmnist_pathmnist_images_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 3
- primary_values: 252087360
- primary_bytes: 252087360
- primary_value_count_range: 16887360 / 23529408 / 211670592 min/median/max
- primary_size_range_bytes: 16887360 / 23529408 / 211670592 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `pathmnist_images` | primary | uint | 8 | 3 | 252087360 | 252087360 | 16887360 / 23529408 / 211670592 | 16887360 / 23529408 / 211670592 | 0 |
