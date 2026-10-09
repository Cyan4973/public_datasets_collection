# USGS 3DEP NC Geiger-mode lidar LAS int32 X development

## Outcome

Accepted `usgs_3dep_nc_geiger_laz_x_i32` from the official USGS 3DEP staged LPC
delivery of project `NC_Phase_4_CentralWestNC_GEIGER_A16`, Anson County block
(`NC_Phase4_Anson_2016`).

LAS int32 lidar record coordinates already exist in the corpus:
`swisstopo_swisssurface3d_alps_las_z_i32` holds elevation Z. This recipe
adds:

- the first planimetric (X, easting) LAS int32 coordinate family;
- the first Geiger-mode (single-photon-sensitive avalanche-photodiode array)
  lidar source, the Harris IntelliEarth GmAPD sensor S/N003.

Novelty kind: new content in a known modality. Measured breadth: OK.

The recipe needed two documentation-only repair cycles; the output was
byte-identical throughout.

1. The VPC `datetime` 2016-08-10 had been described as a flight date. It is
   the LAS file-creation date (2016 day 223). Point GPS times place the
   acquisition on 2016-03-16/17, and the build now measures that window and
   writes it to `build_stats.json`.
2. The selection sentence was garbled, and system identifiers were wrongly
   attributed to the excluded creation-date groups. Both are fixed.

## Source and rights

- Source: USGS 3DEP LPC project VPC (STAC FeatureCollection, 2,533 tiles,
  sha256 `ee9caf02…cb3a`).
- Link list: `0_file_download_links.txt` (sha256 `df88e022…c9fe`).
- Both come from `prd-tnm.s3.amazonaws.com`. The LAZ tiles come from
  `rockyweb.usgs.gov`.
- Tiles: 25 LAZ files, 1,225,170,780 bytes. Size, ETag, header X bounds and
  sha256 for each file are pinned in `sources.tsv`.
- License: U.S. Government public domain.
  - Per-tile FGDC metadata (checked for tile 10646116) gives origin
    "U.S. Geological Survey", pubdate 20190701, accconst "None." and a
    useconst that asks only for acknowledgement and a description of
    modifications. The time period of content is 2016-03-16 to 2016-03-30.
  - The USGS policy page states: "USGS-authored or produced data and
    information are considered to be in the U.S. Public Domain."
- Access: anonymous HTTPS, no credentials. The data are terrain point
  coordinates, with no personal data.

## Shape and conversion

Each natural record is one complete published LAZ tile, 2,500 x 2,500 ft.
A sample is the X field of every point record in file order:

- X is the native LAS 1.4 point format 6 little-endian int32 at byte 0 of each
  30-byte record (scale 0.01 US survey ft, offset 0, NAD83(2011) North Carolina
  State Plane).
- It is copied byte for byte after decoding with the repository's pure-stdlib
  `tools/laz/laszip.py` (layered compressor, POINT14 v3).
- Y, Z, intensity, GPS time and flags are not emitted.

Selection, implemented in `scripts/geiger_tiles.py select` and documented by
`discover.sh`:

- Take VPC features with datetime 2016-08-10, i.e. the LAS creation batch
  2016/223 (1,785 tiles).
- Keep those with `pc:count` < 9,000,000 and sort by tile id, giving 25 tiles.
- Every tile is checked for system identifier `IntelliEarthGmAPDSensorS/N003`,
  ESP ANALYST, scale 0.01, offset 0, point format 6, and the NC State Plane
  WKT.

The count cap keeps the output under 1 GB, because interior tiles hold 17-31M
points. It favours partial edge and water tiles; this bias is documented.

Missing values: LAS X has no sentinel. Every record is kept, the decoded count
must equal the header count and the VPC `pc:count`, and every X must lie within
the header bounds ±1 tick.

## Accepted output

- Primary samples: 25
- Primary values: 167,277,065
- Primary bytes: 669,108,260
- Minimum sample: 673,724 values
- Median sample: 7,614,983 values
- Maximum sample: 8,950,333 values
- Value range: 161,249,999 to 173,749,999 (tile-dependent base, at most about
  250,000 ticks per tile)
- Distinct values per tile: 118,373 to 250,001; largest single-value share
  0.007%
- Acquisition window (point GPS time, adjusted standard):
  - 142,123,327.99994 to 142,211,440.00092 s
  - 2016-03-16 00:28:47 to 2016-03-17 00:57:20 GPS calendar time
- Aggregate SHA-256 (samples concatenated in index order):
  `498960f71a39178d6a7174d0125d9b213f2dc4804e8960d28a11da3e559b0ad1`

The local build and the independent value-by-value verification both completed
against the pinned tiles.

## Judge checks

- `gate.py staging/usgs_3dep_nc_geiger_laz_x_i32`: PASS, no warnings.
- `verify.sh`, run by the judge: exit 0 in 2m04s, `verify=ok samples=25
  values=167277065 bytes=669108260`. The concatenated sample SHA-256,
  recomputed independently, matches the pin.
- `build.sh` reads only `.data/downloads/`. The scripts make no network calls
  outside `download.sh`, and contain no credentials.
- Bytes, checked with stdlib over all 25 samples:
  - The last digit is uniform (3.322 bits), so the 0.01 ft resolution is real.
  - Byte lanes 0/1 carry about 8 bits each and lane 3 is constant per tile:
    native magnitude, not widening.
  - Median |delta| is 1,180-2,796 ticks.
  - All 25 heads are distinct, with no fill.
- Full independent decode of tile 10646116 (7,267,272 points), a tile neither
  earlier judge checked:
  - X is identical to the stored sample.
  - Y and Z lie inside the header bounds.
  - ASPRS classes are 2/5/4/3/13/9/1/10.
  - Every point is a single return on channel 0, with point source 0.
  - GPS times run 2016-03-16 03:07-06:22, inside the documented window.
- Documentation: no flight-date or single-sensor claims remain, and the
  excluded groups are described as carrying a mix of identifiers. The UTC
  offset (GPS-UTC = 17 s in March 2016) and the EDT conversion are correct.
- Rights: the judge fetched the FGDC XML for a selected tile and the USGS
  copyrights page.
- Novelty: `novelty.py --url/--terms/--type/--vocabulary` found no URL, term
  or downstream match apart from this recipe's own staging directory and
  ledger rows. The 32-bit downstream families have no lidar/LAS coordinates.
  The only same-modality family is swisstopo Z i32.
- Breadth (zlsim): OK. The nearest family is downstream
  `urban_das_channel_day_f32` at distance 0.0508 with 3.65% loss, so it is
  neither feature-close nor compression-equivalent. No fill warnings.
