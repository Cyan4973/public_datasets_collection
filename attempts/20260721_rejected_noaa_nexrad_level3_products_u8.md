# Rejected: noaa_nexrad_level3_products_u8

Date: 2026-07-21

Status: rejected

Source:
- https://unidata-nexrad-level3.s3.amazonaws.com/

Expected value:
- NEXRAD Level-III products are a valuable weather-radar domain.
- A decoded product-code-specific recipe could add operational radar radial or
  raster bin values with natural product-file or sweep boundaries.

Rejected shape:
- The active recipe targeted one product code (`N0Q`) from station `ABC` on
  2020-04-08 and emitted one sample per Level-III product file.
- The build read each local product as bytes, stripped only an optional simple
  text transport header, and wrote the remaining NIDS product-message bytes
  unchanged as `uint8`.

Evidence:
- The local build produced 96 samples and 1,833,134 primary bytes.
- The first local sample still began with message/transport text:
  `01 0d 0d 0a 30 32 32 20 0d 0d 0a 53 44 55 53 35 38`, corresponding to
  `\\x01\\r\\r\\n022 \\r\\r\\nSDUS58...`.
- No Level-III product blocks, radial packets, raster packets, or bin values
  were decoded into typed radar fields.

Reason:
- Repository policy requires primary numeric series to be decoded typed values,
  not opaque file-container or serialized product-message bytes.
- NIDS product-message bytes are not a clean `uint8` radar series, even when
  the product contains useful 8-bit radar bin values internally.

Retry condition:
- Do not retry this dataset ID as product-message bytes.
- Retry only with a parser that extracts documented Level-III packet/product
  values for one coherent product code, with headers and block metadata kept
  auxiliary only.
