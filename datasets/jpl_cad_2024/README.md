# JPL Small-Body Close Approaches 2024

JPL/CNEOS close-approach data (CAD) for the 2024 date window, extracted into one numeric column sample per native field.

- Source: https://ssd-api.jpl.nasa.gov/cad.api (NASA/JPL SSD/CNEOS)
- Scope: all small-body close approaches with `date-min=2024-01-01`, `date-max=2024-12-31` (~1,638 rows).
- Local raw payload: `${DATA_DIR:-.data}/downloads/jpl_cad_2024/cad_2024.json`

## Series (each a `table_column` sample, one value per close-approach row, float64)

| series_id | CAD field | meaning |
|---|---|---|
| `jpl_cad_jd` | `jd` | close-approach Julian date |
| `jpl_cad_dist` | `dist` | nominal distance (au) |
| `jpl_cad_dist_min` | `dist_min` | min 3σ distance (au) |
| `jpl_cad_dist_max` | `dist_max` | max 3σ distance (au) |
| `jpl_cad_v_rel` | `v_rel` | relative velocity (km/s) |
| `jpl_cad_v_inf` | `v_inf` | velocity vs massless body (km/s) |
| `jpl_cad_h` | `h` | absolute magnitude H |

7 columns × ~1,638 rows ≈ 11,466 values — clears the acceptance floor via the value-count criterion. Malformed rows are dropped atomically so all columns stay equal length.

## Run

```sh
bash datasets/jpl_cad_2024/download.sh
bash datasets/jpl_cad_2024/build.sh
bash datasets/jpl_cad_2024/verify.sh
```

Logs under `${DATA_DIR:-.data}/logs/jpl_cad_2024/`.
