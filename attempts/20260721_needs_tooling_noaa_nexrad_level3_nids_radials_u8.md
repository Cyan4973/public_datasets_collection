# Accepted: noaa_nexrad_level3_nids_radials_u8

Date: 2026-07-21

Status: accepted on 2026-07-21

Source:
- https://unidata-nexrad-level3.s3.amazonaws.com/
- NOAA/NCEI NEXRAD Level-III product documentation

Expected value:
- Decoded NEXRAD Level-III product values would add operational weather-radar
  radial or raster structure, distinct from station time series and optical or
  categorical imagery.
- The previous bounded `N0Q` local run proved public product files are reachable
  and large enough in aggregate, but not yet decoded correctly.

Intended accepted shape:
- One coherent Level-III product code per recipe.
- One decoded product field, radial sweep, raster packet, or product file per
  natural primary sample, depending on the documented packet layout.
- Primary values must be documented radar bin/product values, not NIDS message
  headers, block wrappers, transport text, compression bytes, or complete
  product-message payloads.

Missing capability:
- A reproducible local NIDS Level-III parser for message headers, description
  blocks, packet codes, radial/raster packet payloads, and product-code-specific
  value interpretation.

Acceptance outcome:
- The replacement recipe `datasets/noaa_nexrad_level3_nids_radials_u8` was
  accepted after implementing a local NIDS packet-16 parser.
- The accepted local run decoded 96 N0Q product files into 15,897,600 primary
  uint8 radial-bin values.

Retry condition:
- Already accepted for the bounded N0Q packet-16 shape. Future NEXRAD Level-III
  products should remain separate unless they share the same documented packet
  semantics.
