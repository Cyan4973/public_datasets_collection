# GOES-18 ABI CMI band 13 full-disk brightness-temperature codes (uint16)

This recipe collects twelve complete GOES-18 (GOES-West) Advanced Baseline
Imager full-disk images of band 13, the 10.3 µm clean longwave infrared
window. Each pixel is the native packed 12-bit uint16 code of NOAA's L2 Cloud
and Moisture Imagery variable `CMI_C13`. The codes encode top-of-atmosphere
brightness temperature:

    brightness_temperature_K = 89.620003 + 0.06145332 * code     (code 0..4095)
    65535 = fill (space / off-disk, or a pixel NOAA marked unavailable)

Scale and offset are recorded per sample in the index and are **not applied**.

## Scope

- One natural record is one complete Mode-6 full-disk scan (about 10 minutes).
  It is a 5424 × 5424 grid on the GOES-R fixed grid, 2 km at nadir. Each
  sample is 58,839,552 bytes and holds 29,419,776 values.
- Twelve scans: the 20:00 UTC full-disk slot on the 15th of every month from
  **October 2025 to September 2026**. That gives one annual cycle at a fixed
  local time over the Pacific and the western Americas. The output is
  706,074,624 bytes and 353,037,312 values.
- GOES-18 only, band 13 only, full disk only, and the 2 km MCMIP COG only.
  GOES-16/19, other bands, CONUS and mesoscale sectors, and the 0.5/1 km
  products would each be separate families.
- Samples are whole scans. They are not tiled or sharded.

Why October 2025 to September 2026 and not calendar 2025: the Planetary
Computer COGs for January to March 2025 were written by an older exporter
(stactools-goes 0.1.6). It stored the band as SampleFormat 2 (int16 with GDAL
nodata -1). From April 2025 on (stactools-goes 0.1.8) the band is stored as
SampleFormat 1 (uint16, nodata 65535). The bit patterns are the same, but the
container encoding is not. In addition, 2025-04-15 has no 20:00 scan in the
catalogue. The chosen window has the same encoding and the exact 20:00 slot
in every month. download.sh rejects any file whose header deviates.

## Source and decode

- STAC: `https://planetarycomputer.microsoft.com/api/stac/v1/collections/goes-cmi`,
  asset `C13_2km` of items `OR_ABI-L2-F-M6_G18_s<start>`.
- Blob: `https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/<yyyy>/<doy>/20/OR_ABI-L2-MCMIPF-M6_G18_s…_CMI_C13.tif`.
  The blob is Microsoft's COG export of NOAA's
  `OR_ABI-L2-MCMIPF-M6_G18_s…_e…_c….nc` NetCDF4 file. The COG's GDAL
  metadata names that file (`NC_GLOBAL#dataset_name`), and download.sh checks
  it against the pin.
- The blob requires an anonymous SAS query string. download.sh requests a
  fresh one on every run from
  `https://planetarycomputer.microsoft.com/api/sas/v1/token/goeseuwest/noaa-goes-cogs`.
  There is no account, key, or login. A request without the SAS gets
  404/409.
- Each file has a pinned exact size and the Azure `Content-MD5`. Total
  download is 431,073,260 bytes.
- Required TIFF structure: classic little-endian TIFF, 5 IFDs (primary plus
  4 overviews, which are ignored). The primary IFD must have 5424 × 5424,
  BitsPerSample 16, SampleFormat 1, Deflate (8), Predictor 1, 512 × 512
  tiles (11 × 11 = 121), and GDAL_NODATA `65535`. The GDAL metadata must have
  NETCDF_VARNAME `CMI_C13`, scale 0.06145332, offset 89.620003, units K,
  valid_range {0,4095}, sensor_band_bit_depth 12, platform G18, and scene
  Full Disk.
- Decode (pure standard-library Python, `scripts/goes_cog.py`): inflate each
  tile with zlib, require exactly 524,288 bytes per tile, copy rows into the
  row-major grid (north row first, west column first), and crop the
  304-pixel right and bottom edge tiles (5424 = 10 × 512 + 304). The
  little-endian uint16 bytes are written unchanged.

## Missing values

In the realized output, 6,373,440 of the 29,419,776 pixels in every grid
(21.66%) lie off the Earth disk and are 65535 in the source. The off-disk mask
is the same pixel set in every scan. This fill is preserved in place, together
with any on-disk pixels NOAA marked unavailable; there is exactly one such
pixel in the whole output, in the 2026-07 scan. Each scan therefore holds about
23.05 million valid codes. build.sh and verify.sh both enforce the following:

- every value is ≤ 4095 or exactly 65535;
- the fill fraction is between 0.15 and 0.35;
- all four corners are fill and the centre pixel is valid;
- each sample has at least 1,000 distinct valid codes;
- the median on-disk brightness temperature is between 200 and 305 K.

The DQF_C13 quality layer is not emitted.

## Realized output

The output is 12 samples totalling 706,074,624 bytes (353,037,312 values).
Across all scans, valid codes span 1513..3955, which is 182.6 K to 332.7 K
(cold cloud tops to hot land). Each scan has 1,744 to 2,057 distinct codes,
and median on-disk brightness temperatures range from 283.3 K to 287.2 K.
verify.sh re-derives every sample byte-identically with a separate decoder.

## License

NOAA data are distributed through the NOAA Open Data Dissemination (NODD)
program. Microsoft Azure / Planetary Computer is one of NODD's three cloud
partners. Sources:

- NODD GOES license statement (https://registry.opendata.aws/noaa-goes/):
  "NOAA data disseminated through NODD are open to the public and can be
  used as desired … NOAA requests attribution for the use or dissemination
  of unaltered NOAA data. However, it is not permissible to state or imply
  endorsement by or affiliation with NOAA. If you modify NOAA data, you may
  not state or imply that it is original, unaltered NOAA data."
- NODD FAQ (https://www.noaa.gov/big-data-project-frequently-asked-questions):
  "free for all users to access with no use restrictions and do not require
  any registration".
- The Planetary Computer collection lists NOAA as licensor. Its STAC
  `license` field says "proprietary" and links a NESDIS policy page titled
  "Public Domain". That field is not relied on as the grant.
- Caveat: every GOES-R NetCDF, and therefore this COG's GDAL metadata,
  carries the boilerplate global attribute `license = "Unclassified data.
  Access is restricted to approved users only."`. It is a legacy
  ground-segment attribute. NOAA's open public distribution of these exact
  products through NODD contradicts it.

Attribute NOAA/NESDIS GOES-R ABI L2 CMIP (GOES-18). Do not imply NOAA
endorsement. The samples are decoded codes from Microsoft's COG export, not
unaltered NOAA files.

## Novelty

This adds a new modality to the local corpus: geostationary thermal-infrared
brightness temperature. The existing 16-bit Earth-observation families are
different material:

- Sentinel-2 L2A optical reflectance;
- Sentinel-1 GRD SAR amplitude;
- SRTM, MOLA and SoilGrids terrain and soil rasters;
- RADOLAN radar precipitation;
- DC LiDAR intensity.

The registry's only other GOES item, `noaa_goes16_abi_cloud_mask_netcdf_u8`,
was rejected for shipping container bytes. It is an 8-bit cloud-mask product
from a different satellite. novelty.py finds no URL or downstream matches.

## Run

```bash
bash staging/mpc_goes18_abi_cmi_c13_fulldisk_u16/download.sh   # ~431 MB, resumable
bash staging/mpc_goes18_abi_cmi_c13_fulldisk_u16/build.sh
bash staging/mpc_goes18_abi_cmi_c13_fulldisk_u16/verify.sh
```

`discover.sh` is optional and fetches metadata only. It re-runs the STAC
search and HEAD requests that produced the pins and writes a TSV under
`.data/logs/<id>/` to compare with the plan in download.sh. All scripts honour
`DATA_DIR` (default `.data`) and log to `$DATA_DIR/logs/<id>/`.
