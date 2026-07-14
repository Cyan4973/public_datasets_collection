# NASA FITS Sample Image Planes

This recipe collects public astronomical FITS sample files from NASA's FITS
Support Office and emits two homogeneous image pixel-array series:

- `fits_scaled_image_pixels_f64` — 2D integer image planes with the FITS
  `BSCALE`/`BZERO` transform applied, giving float64 physical pixel values;
- `fits_image_cubes_f32` — 3D float32 image cubes.

The recipe is intentionally strict about series homogeneity:

- tables, spectra, and binary-table HDUs are not emitted;
- raw stored-value 2D planes are **not** collected: their per-`BITPIX` storage
  width (u8/i16/i32/f32/f64) is a property of the source file, not a distinct
  numeric quantity, so mirroring the same pixels across widths is avoided;
- 3D image cubes are emitted only in a separate cube series and are not mixed
  with 2D image planes;
- HDUs with missing integer pixels or non-finite floating pixels are skipped.

## Usage

```bash
bash datasets/nasa_fits_sample_image_planes/download.sh
bash datasets/nasa_fits_sample_image_planes/build.sh
bash datasets/nasa_fits_sample_image_planes/verify.sh
```

The default URL list is a bounded set of public NASA FITS Support Office sample
files. To provide a different bounded list of public FITS image files, set:

```bash
NASA_FITS_URLS_FILE=/path/to/urls.txt
```

or:

```bash
NASA_FITS_URLS=https://example.invalid/a.fits,https://example.invalid/b.fits.gz
```

The build step is local-only and reads files already present under
`.data/downloads/nasa_fits_sample_image_planes/`.
