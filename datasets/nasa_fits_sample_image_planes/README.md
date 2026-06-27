# NASA FITS Sample Image Planes

This recipe collects public astronomical FITS sample files from NASA's FITS
Support Office and emits homogeneous image pixel arrays.

The recipe is intentionally strict about series homogeneity:

- tables, spectra, and binary-table HDUs are not emitted;
- each output series contains only one FITS numeric storage type;
- scaled integer image planes are emitted only in a separate float64 physical
  pixel-value series;
- 3D image cubes are emitted only in a separate cube series and are not mixed
  with 2D image planes;
- HDUs with missing integer pixels or non-finite floating pixels are skipped.

## Usage

```bash
bash staging/nasa_fits_sample_image_planes/download.sh
bash staging/nasa_fits_sample_image_planes/build.sh
bash staging/nasa_fits_sample_image_planes/verify.sh
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
