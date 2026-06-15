# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `hf_smolllm2_135m_safetensors_f16`

- status: `ok`
- reasons: `none`
- primary_samples: 272
- primary_values: 134515008
- primary_bytes: 269030016
- primary_value_count_range: 576 / 331776 / 28311552 min/median/max
- primary_size_range_bytes: 1152 / 663552 / 56623104 min/median/max
- primary_size_distribution_bytes: 1152 / 1152 / 221184 / 663552 / 1769472 / 1769472 / 56623104 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.330882

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `smolllm2_135m_tensor_f16` | primary | float | 16 | 272 | 134515008 | 269030016 | 576 / 576 / 110592 / 331776 / 884736 / 884736 / 28311552 | 1152 / 1152 / 221184 / 663552 / 1769472 / 1769472 / 56623104 | 0.330882 | 0 |

