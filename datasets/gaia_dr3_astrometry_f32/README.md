# Gaia DR3 Astrometry (float32)

Collects **stellar astrometry** — parallax and proper motions — from the
[ESA Gaia DR3](https://gea.esac.esa.int/archive/) `gaia_source` catalogue, the
definitive all-sky astrometric survey (~1.8 billion sources). Three float32
series, one per astrometric quantity:

| Series | Quantity | Unit |
| --- | --- | --- |
| `gaia_parallax_mas_f32` | parallax | mas |
| `gaia_pmra_masyr_f32` | proper motion in RA (incl. cos δ) | mas/yr |
| `gaia_pmdec_masyr_f32` | proper motion in Dec | mas/yr |

This is a **new scientific domain** for the corpus — astrometry — distinct from the
existing `hyg_star_photometry_i16` (which is *photometry*: magnitudes/colour). The
values are published in Gaia's CSV as text; parsing text → float32 is the same
conversion the corpus already uses for real-valued series (e.g. `electricity_load`),
and the real astrometric precision (a few significant figures) sits comfortably
inside float32.

## Usage

```bash
datasets/gaia_dr3_astrometry_f32/download.sh
datasets/gaia_dr3_astrometry_f32/build.sh
datasets/gaia_dr3_astrometry_f32/verify.sh
```

### Source resolution (honest caveat)

Unlike the UCI/S3 recipes, this source is **not a mechanism previously proven in
this repo**. To de-risk it, `download.sh` resolves file names by discovery rather
than hard-coding them: it first parses the directory checksum manifest
(`_MD5SUM.txt`), then falls back to autoindex HTML, under
`https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/`. Each downloaded file is
validated (must gunzip and contain `source_id,parallax,pmra,pmdec`), so a wrong
path or HTML error page fails the download instead of building. If discovery
fails, override:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GAIA_BASE_URL` | `…/Gaia/gdr3/gaia_source/` | Directory of `GaiaSource_*.csv.gz` files |
| `GAIA_CSV_URL` | — | A single explicit `.csv.gz` URL (skips discovery) |
| `GAIA_CSV_URLS_FILE` | — | File listing `.csv.gz` URLs (one per line) |
| `GAIA_MAX_FILES` | `2` | Number of bulk files to fetch (= samples per series) |

Downloads are resumable and stall-based (`curl -C -`, no hard timeout) because the
bulk files are large (~100–200 MB gzipped each).

## Structure

Each bulk `GaiaSource_*.csv.gz` file is the natural record boundary → **one sample
per series per file**. With the default two files that is 6 samples across the
three series. Rows lacking a value for a given quantity (two-parameter solutions)
are dropped for that series only; remaining values are stored in catalogue row
order as raw little-endian float32. Recorded `min`/`max` are computed from the
stored float32 values and re-checked by `verify.sh`.
