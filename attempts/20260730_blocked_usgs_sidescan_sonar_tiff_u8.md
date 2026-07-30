# Blocked: USGS sidescan-sonar TIFF uint8

- Date: 2026-07-30
- Status: blocked
- Candidate dataset ID: `usgs_sidescan_sonar_tiff_u8`
- Intended material: decoded single-band 8-bit USGS sidescan/backscatter
  GeoTIFF mosaics, one complete mosaic per natural sample.

## Motivation

No accepted corpus recipe currently contributes sonar samples. Native 8-bit
seafloor acoustic-backscatter mosaics would add a genuinely new physical
domain, distinct from optical imagery, spaceborne radar, depth cameras, and
the previously failed 16-bit chirp/GLORIA attempts.

## Metadata-only investigation

No TIFF payload was downloaded. User-run probes queried official ScienceBase
metadata and HTTP headers.

The broad query `sidescan sonar GeoTIFF` identified official ScienceBase item
`5bfd6022e4b0815414ca39cf`:

> 5-m backscatter mosaic from south and west of Martha's Vineyard and north of
> Nantucket produced from sidescan-sonar and interferometric backscatter
> datasets

The item belongs to USGS data release DOI `10.5066/P9E9EFNE`. Its raster facet
documents `MV_ACK_backscatter_5m.tif` as a `7,965,938`-byte GeoTIFF and tags the
material as sidescan sonar, backscatter, grey scale, and mosaic.

## Blocking evidence

1. The exact raster-facet TIFF `downloadUri` returned HTTP 404.
2. Enumerating the item's data-release parent
   `5afee3bfe4b0da30c1bfbd28` found no additional sidescan/backscatter raster
   siblings; it resolved only the same mosaic item.
3. The item advertises a generic attached-files ZIP that may still contain the
   TIFF, but even if that ZIP works, it yields only one natural mosaic sample.
   A single product entity is too narrow under the corpus protocol.
4. Because no live multi-mosaic source set was established, no TIFF-header
   probe could prove 8-bit sample type, single-band geometry, compression, or
   decoder compatibility across multiple samples.

## Decision

Block this route before acquisition. Do not retry from this ScienceBase item
alone and do not treat the browse PNG as sonar measurement material.

Retry only after identifying a coherent set of multiple official USGS
sidescan/backscatter mosaics with:

- exact live direct TIFF or bounded attached-files URLs
- aggregate source and decoded output below 1 GB
- user-run header evidence proving single-band 8-bit TIFF pixels
- supported lossless compression and nonconstant raster contents
- consistent acoustic-backscatter semantics across all natural samples
