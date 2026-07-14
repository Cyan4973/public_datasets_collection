# Sentinel-1 GRD Measurement Uint16

Collects native 16-bit Sentinel-1 Level-1 GRD measurement rasters as raw
uint16 samples. The default downloader selects medium-resolution GRD scenes
from the Microsoft Planetary Computer STAC catalog and downloads only the
configured polarization measurement assets.

The natural sample boundary is one source measurement GeoTIFF: each sample is one
full uint16 measurement raster. Polarizations are separate homogeneous families:

| Family | Meaning |
| --- | --- |
| `sentinel1_grd_vv_dn_u16` | VV-polarized GRD measurement digital numbers |
| `sentinel1_grd_vh_dn_u16` | VH-polarized GRD measurement digital numbers |
| `sentinel1_grd_hh_dn_u16` | HH-polarized GRD measurement digital numbers |
| `sentinel1_grd_hv_dn_u16` | HV-polarized GRD measurement digital numbers |

Default selection uses `POLARIZATIONS="HH HV"` and `SCENE_LIMIT=2`. The
medium-resolution GRD hits in the default search windows are dual-pol `1SDH`
(HH+HV) products, so each of the two scenes contributes one HH and one HV
raster — two homogeneous families of two samples each, kept under the
repository's 1 GB raw primary-output cap. Other polarization selections are
possible; each polarization remains a separate family and the build rejects
output above the cap.

Each index row records the sample's full-raster `min`/`max` value range, which
`verify.sh` re-derives and cross-checks.

The Planetary Computer serves these COGs Zstandard-compressed, which the build
decodes via the `zstd` CLI (no Python packages required); Deflate tiles decode
via `zlib`. `zstd` must be on `PATH` (override with `ZSTD_BIN`).

```bash
datasets/sentinel1_grd_measurement_u16/download.sh
datasets/sentinel1_grd_measurement_u16/build.sh
datasets/sentinel1_grd_measurement_u16/verify.sh
```

Tunables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCENE_LIMIT` | `2` | Number of GRD scenes to select |
| `POLARIZATIONS` | `HH HV` | Comma/space list drawn from `VV VH HH HV` |
| `ZSTD_BIN` | `zstd` | Path to the `zstd` decompressor |

Exact URL mode is preferred when stable measurement TIFF URLs are known:

```bash
SENTINEL1_URLS_FILE=/path/to/sentinel1_measurement_urls.tsv \
  datasets/sentinel1_grd_measurement_u16/download.sh
```

The exact URL file may be either a TSV with header
`local_name url scene_id polarization asset_key search_label datetime platform`,
or a plain list of TIFF URLs. Plain-list mode infers the polarization from the
URL path or filename.
