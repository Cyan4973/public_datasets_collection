# Blocked: Zenodo Radiometric Thermal UInt16

- Date: 2026-08-04
- Candidate: `zenodo_radiometric_thermal_u16`
- Intended domain: terrestrial radiometric thermal-camera frames
- Intended representation: native single-channel uint16 or int16 TIFF/PNG
- Intended natural sample: one complete detector frame

## Discovery performed

A metadata and bounded-header search queried Zenodo for radiometric thermal,
thermal-camera, infrared-thermography, 16-bit thermal-image, LWIR, and
thermography-PNG records. The search:

- examined 141 unique records;
- required an explicit CC0 or CC BY license;
- required thermal/radiometric semantics in record metadata;
- considered direct `.tif`, `.tiff`, and `.png` files between 100 KiB and
  100 MiB; and
- range-read at most the first 256 KiB for strict TIFF/PNG header inspection.

Thirteen direct image files were found. One was rejected for license and two
for missing thermal semantics, leaving ten bounded licensed candidates for
header inspection.

## Result

None of the ten candidates was native 16-bit numeric material:

- four PNG files were 8-bit RGB or RGBA visualizations;
- four TIFF files were single-channel 8-bit rasters; and
- two TIFF files were three-channel 8-bit RGB rasters.

The qualified native-16-bit file count, pixel count, and source-byte total
were all zero. No complete image payloads were downloaded, and no samples were
built.

This is blocked rather than permanently rejected because Zenodo records may
package original radiometric frames inside ZIP/TAR archives while exposing
only 8-bit previews directly. A valid retry requires an exact permissively
licensed archive or direct source known to contain single-channel native
16-bit thermal frames. Re-running the same direct-file queries without a new
source is not useful.

Ephemeral evidence:

- `.data/logs/zenodo_radiometric_thermal_u16/discover.latest.log`
- `.data/discovery/zenodo_radiometric_thermal_u16/summary.json`
- `.data/discovery/zenodo_radiometric_thermal_u16/probe_failures.json`
- `.data/discovery/zenodo_radiometric_thermal_u16/candidates.tsv`
