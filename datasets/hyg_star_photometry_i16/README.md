# HYG Star Photometry (millimagnitude int16)

Collects genuine stellar **photometric** quantities from the public
[HYG database](https://github.com/astronexus/HYG-Database) (a compilation of the
Hipparcos, Yale Bright Star, and Gliese catalogues, ~120k stars):

| Series | Source column | Meaning |
| --- | --- | --- |
| `hyg_star_apparent_mag_mmag_i16` | `mag` | Apparent visual magnitude |
| `hyg_star_absolute_mag_mmag_i16` | `absmag` | Absolute visual magnitude |
| `hyg_star_color_index_mmag_i16` | `ci` | Johnson B–V colour index |

Each is one homogeneous column (one sample of ~120k stars). Magnitudes are
real-valued, so they are stored as integer **millimagnitudes** (`value × 1000`,
rounded) in **signed** int16 — signed because bright stars are negative
(e.g. Sirius ≈ −1.46 mag → −1460). This is a documented `derived_operational_numeric`
scaling, not a native integer; it fills the astronomy-photometry gap in the
corpus and mirrors the downstream star-catalogue magnitude series (`sao_MAG`).

## Usage

```bash
datasets/hyg_star_photometry_i16/download.sh
datasets/hyg_star_photometry_i16/build.sh
datasets/hyg_star_photometry_i16/verify.sh
```

The downloader tries several upstream URLs and accepts the first CSV carrying the
`mag`/`absmag`/`ci` columns. Upstream paths move between HYG versions, so if all
defaults fail, supply one explicitly:

```bash
HYG_CSV_URL=https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv \
  datasets/hyg_star_photometry_i16/download.sh
```

Tunables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `HYG_CSV_URL` | — | Explicit HYG CSV URL (overrides the candidate list) |
| `HYG_MMAG_SCALE` | `1000` | Magnitude → integer scale factor (millimag) |
| `HYG_MIN_VALUES_PER_SAMPLE` | `10000` | Minimum values for a column to be accepted |

Only numeric photometric measurements are extracted — no names, identifiers, or
positions.
