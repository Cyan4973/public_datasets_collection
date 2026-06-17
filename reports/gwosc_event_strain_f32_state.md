# GWOSC Event Strain F32 State

Status: promoted to `datasets/gwosc_event_strain_f32/` and validated on 2026-06-17.

## Material

- Dataset ID: `gwosc_event_strain_f32`
- Series ID: `detector_strain_f32`
- Source: Gravitational Wave Open Science Center public event strain text gzip files
- Event coverage: `GW150914`
- Detector coverage: `H1`, `L1`
- Natural sample boundary: one detector-event strain segment per source text gzip
- Geometry: `1d_detector_strain_timeseries`
- Numeric output: little-endian `float32`
- Role: primary

## Download State

| Resource | Event | Detector | Source bytes | Parsed values | URL |
|---|---:|---:|---:|---:|---|
| `GW150914_H1_32s_4k` | `GW150914` | `H1` | 1,285,956 | 131,072 | `https://www.gw-openscience.org/GW150914data/H-H1_LOSC_4_V2-1126259446-32.txt.gz` |
| `GW150914_L1_32s_4k` | `GW150914` | `L1` | 1,219,487 | 131,072 | `https://www.gw-openscience.org/GW150914data/L-L1_LOSC_4_V2-1126259446-32.txt.gz` |

Download failures: none recorded.

## Output State

| Metric | Value |
|---|---:|
| Sample count | 2 |
| Total primary values | 262,144 |
| Total primary bytes | 1,048,576 |
| Min sample values | 131,072 |
| Median sample values | 131,072 |
| Max sample values | 131,072 |
| Min sample bytes | 524,288 |
| Median sample bytes | 524,288 |
| Max sample bytes | 524,288 |
| Source bytes | 2,505,443 |

## Sample Rows

| Sample | Detector | Values | Output bytes | Source value range |
|---|---:|---:|---:|---:|
| `GW150914_H1_32s_4k` | `H1` | 131,072 | 524,288 | -7.044665943156067e-19 to 7.706262192397465e-19 |
| `GW150914_L1_32s_4k` | `L1` | 131,072 | 524,288 | -1.8697138664279764e-18 to -4.60035111311666e-20 |

## Validation

The promoted recipe passed offline cache validation plus local build/verify:

```bash
OFFLINE=1 bash datasets/gwosc_event_strain_f32/download.sh
bash datasets/gwosc_event_strain_f32/build.sh
bash datasets/gwosc_event_strain_f32/verify.sh
```

The offline download run revalidated the already-present gzip payloads without fetching. The verifier re-read the source gzip files, checked one finite numeric strain value per row, confirmed output byte sizes and sample-index metadata, rejected constant-prefix samples, and confirmed the protocol floors.
