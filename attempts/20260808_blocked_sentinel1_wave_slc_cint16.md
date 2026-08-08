# Blocked: Sentinel-1 Wave Mode SLC Complex Int16

- Date: 2026-08-08
- Candidate: `staging/sentinel1_wave_slc_cint16`
- Intended domain: coherent complex synthetic-aperture radar
- Intended primary: native signed-int16 real/imaginary SLC measurement components
- Status: blocked before payload acquisition

## Value

Sentinel-1 SLC preserves complex I/Q samples before GRD magnitude detection and
phase removal. It would therefore provide a materially different numeric field
from the accepted unsigned Sentinel-1 GRD measurement rasters, despite sharing
the same satellite instrument family.

## Discovery result

The metadata-only preflight queried the official Copernicus Data Space OData
catalogue for `_WV_SLC__` products and found 30 real online products. The
bounded result was not actionable:

- complete SAFE product sizes were 2,125,664,756 through 14,705,739,736 bytes;
- all ten tested official download endpoints returned HTTP 405 to HEAD;
- no tested endpoint exposed an unauthenticated binary response;
- the official SentiWiki Sentinel-1 products page exposed no direct Wave-SLC
  ZIP, TIFF, or SAFE download;
- the SAR Mission Performance Centre test-data page exposed no matching
  direct archive;
- the legacy ESA sample-products page returned HTTP 502; and
- no radar product bytes were downloaded.

Even the smallest catalogue product exceeds both the collection's 1 GB primary
output cap and a reasonable bounded-source acquisition. The catalogue's
`S3Path` values point into Copernicus `/eodata/` storage, but no
unauthenticated per-measurement object URL was exposed.

The previously used Sentinel legal-notice URL also returned HTTP 404 during
this preflight. Copernicus reuse terms are already established for the accepted
Sentinel-1 GRD family, but the stale URL should be replaced before any future
promotion.

## Evidence

- `.data/discovery/sentinel1_wave_slc_cint16/summary.json`
- `.data/discovery/sentinel1_wave_slc_cint16/candidates.tsv`
- `.data/discovery/sentinel1_wave_slc_cint16/catalog_products.json`
- `.data/logs/sentinel1_wave_slc_cint16/discover.latest.log`

## Retry condition

Retry only with an exact official, unauthenticated Wave-SLC sample archive or
measurement TIFF that is individually bounded below 1 GB, or an official
endpoint that supports bounded retrieval of individual SAFE measurement
members. Also pin a current Copernicus Sentinel reuse-notice URL. Do not
download a multi-gigabyte complete SAFE merely to extract one imagette.
