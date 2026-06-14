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

## `fashion_mnist_images_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 2
- primary_values: 54880000
- primary_bytes: 54880000
- primary_value_count_range: 7840000 / 27440000 / 47040000 min/median/max
- primary_size_range_bytes: 7840000 / 27440000 / 47040000 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `fashion_mnist_images` | primary | uint | 8 | 2 | 54880000 | 54880000 | 7840000 / 27440000 / 47040000 | 7840000 / 27440000 / 47040000 | 0 |
| `fashion_mnist_labels` | auxiliary | uint | 8 | 2 | 70000 | 70000 | 10000 / 35000 / 60000 | 10000 / 35000 / 60000 | 0 |

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

## `uci_letter_recognition_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 1
- primary_values: 320000
- primary_bytes: 320000
- primary_value_count_range: 320000 / 320000 / 320000 min/median/max
- primary_size_range_bytes: 320000 / 320000 / 320000 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `letter_labels_ascii` | auxiliary | uint | 8 | 1 | 20000 | 20000 | 20000 / 20000 / 20000 | 20000 / 20000 / 20000 | 0 |
| `letter_ocr_features` | primary | uint | 8 | 1 | 320000 | 320000 | 320000 / 320000 / 320000 | 320000 / 320000 / 320000 | 0 |

## `uci_optdigits_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 2
- primary_values: 359680
- primary_bytes: 359680
- primary_value_count_range: 115008 / 179840 / 244672 min/median/max
- primary_size_range_bytes: 115008 / 179840 / 244672 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `optdigits_features` | primary | uint | 8 | 2 | 359680 | 359680 | 115008 / 179840 / 244672 | 115008 / 179840 / 244672 | 0 |
| `optdigits_labels` | auxiliary | uint | 8 | 2 | 5620 | 5620 | 1797 / 2810 / 3823 | 1797 / 2810 / 3823 | 0 |

## `uci_skin_segmentation_bgr_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 1
- primary_values: 735171
- primary_bytes: 735171
- primary_value_count_range: 735171 / 735171 / 735171 min/median/max
- primary_size_range_bytes: 735171 / 735171 / 735171 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `skin_bgr_channels` | primary | uint | 8 | 1 | 735171 | 735171 | 735171 / 735171 / 735171 | 735171 / 735171 / 735171 | 0 |
| `skin_binary_labels` | auxiliary | uint | 8 | 1 | 245057 | 245057 | 245057 / 245057 / 245057 | 245057 / 245057 / 245057 | 0 |

## `uci_statlog_landsat_satellite_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 2
- primary_values: 231660
- primary_bytes: 231660
- primary_value_count_range: 72000 / 115830 / 159660 min/median/max
- primary_size_range_bytes: 72000 / 115830 / 159660 min/median/max

| series_id | role | kind | width | samples | values | bytes | value range min/median/max | byte range min/median/max | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `landsat_class_labels` | auxiliary | uint | 8 | 2 | 6435 | 6435 | 2000 / 3217.5 / 4435 | 2000 / 3217.5 / 4435 | 0 |
| `landsat_spectral_features` | primary | uint | 8 | 2 | 231660 | 231660 | 72000 / 115830 / 159660 | 72000 / 115830 / 159660 | 0 |
