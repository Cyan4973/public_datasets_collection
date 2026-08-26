# NASA TESS Light Curves Float32 — Discovery

This staged candidate targets time-domain stellar photometry from the NASA
Transiting Exoplanet Survey Satellite (TESS), distributed through the official
Mikulski Archive for Space Telescopes (MAST).

The intended natural sample is the quality-filtered `PDCSAP_FLUX` column from
one public SPOC target/sector light-curve product. Unlike the accepted HYG
photometry catalogue, which contains one brightness value for each of many
stars, each proposed sample follows one star through time and therefore
contains transit, variability, flare, rotation, noise, and instrumental-trend
structure. It is also a FITS binary-table series rather than an image plane.

The discovery is intentionally metadata-only. It queries a fixed cone near the
southern TESS continuous-viewing zone, selects public SPOC time-series
observations, discovers their official light-curve products, and requests only
the initial FITS bytes needed to inspect table schemas. A product qualifies
only when `PDCSAP_FLUX` is a native FITS `E` column (IEEE-754 float32) with at
least 1,000 table rows.

Run from the repository root:

```bash
bash staging/nasa_tess_lightcurves_f32/discover.sh
```

Results are written under `.data/discovery/nasa_tess_lightcurves_f32/` and the
durable log under `.data/logs/nasa_tess_lightcurves_f32/`. No complete FITS
light-curve payload is downloaded by this step.

Discovery qualified 64 products covering eight stars and sectors 61–68. The
source tables contain 1,247,392 rows and total about 126.7 MB. Every selected
product is marked `PUBLIC` by MAST and declares native float32 `PDCSAP_FLUX`
plus int32 `QUALITY` columns.

Download the selected complete FITS products with:

```bash
bash staging/nasa_tess_lightcurves_f32/download.sh
```

The table layout is fixed-width and uncompressed, so a small standard-library
parser can extract the two required columns directly; no Astropy or additional
compiled dependency is needed.

Build and independently verify the raw little-endian samples with:

```bash
bash staging/nasa_tess_lightcurves_f32/build.sh
bash staging/nasa_tess_lightcurves_f32/verify.sh
```

The pinned build produces 64 variable-length one-dimensional samples, one for
each target-sector product. It retains 1,015,204 finite `PDCSAP_FLUX` values
(4,060,816 bytes): 224,940 rows with nonzero `QUALITY` and 7,248 remaining
non-finite values are excluded. Individual samples contain 13,040–18,854
float32 values. The extractor preserves each retained IEEE-754 word exactly,
changing only FITS big-endian byte order to the corpus-standard little-endian
order.

The official NASA reuse page and the official MAST TESS mission page are
captured and identity-pinned during download. MAST marked all selected products
`PUBLIC` during discovery; the FITS headers identify NASA/Ames and TESS, and
the emitted samples contain scientific measurements rather than protected
logos or images of people.
