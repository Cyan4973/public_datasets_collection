# Blocked: NOAA ETOPO1 global relief int16

## Candidate

- Dataset ID: `noaa_etopo1_global_relief_i16`
- Product: ETOPO1 1 Arc-Minute Global Relief Model, ice-surface,
  grid-registered two-byte integer binary grid
- DOI: `10.7289/V5C8276M`
- Intended sample: one complete global land-topography and ocean-bathymetry
  field

## Numeric preflight

Range-only inspection of the official NOAA archive succeeded without
downloading the numeric grid:

- archive URL:
  `https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO1/data/ice_surface/grid_registered/binary/etopo1_ice_g_i2.zip`
- archive size: 322,504,559 bytes
- payload member: `etopo1_ice_g_i2.bin`
- ZIP Deflate compressed bytes: 322,504,083
- uncompressed numeric bytes: 466,624,802
- CRC32: `362c61a3`
- header member: `etopo1_ice_g_i2.hdr`
- shape: `10,801 × 21,601`
- values: 233,312,401
- representation: signed two-byte integer, LSB-first, metres
- declared range: -10,898 through 8,271
- no-data sentinel: -32,768

The source therefore qualifies technically as native little-endian int16 and
fits below the 1 GB decoded-output cap.

## License blocker

The official NCEI product page was accessible and explicitly documents ETOPO1,
the DOI, citation, and download links. Automated retrieval of the main NOAA
disclaimer returned HTTP 403. An accessible NOAA Ocean Service disclaimer did
not expose explicit public-domain/free-use language under the bounded text
check.

ETOPO1 is a compilation of many contributed source datasets. Therefore NOAA
hosting and open download access are not, by themselves, treated as adequate
authorization for model-training use.

## Decision

Do not download or accept the 322 MB archive yet. Retry only when an official
ETOPO1-specific metadata, FAQ, or rights statement explicitly establishes
training-compatible reuse terms. Preserve the DOI citation and access date if
the candidate is later accepted.
