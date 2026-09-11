# Blocked: NASA/JPL UAVSAR Polarimetric MLC Float32

- Date: 2026-09-11
- Candidate: `nasa_uavsar_mlc_polarimetric_f32`
- Intended domain: airborne polarimetric synthetic-aperture radar
- Intended representation: separate homogeneous little-endian float32 planes
  for real and imaginary multilook-complex covariance components
- Decision: blocked because the tested official payload routes require
  authentication

## Expected value

UAVSAR multilook-complex (MLC) products would add dense two-dimensional
polarimetric covariance fields. Complex off-diagonal elements would be split
into independent real and imaginary planes; diagonal real elements would also
remain separate. No heterogeneous fields or complex components would be
interleaved.

This would differ from the accepted Sentinel-1 GRD uint16 magnitude imagery,
where complex phase has already been discarded, and from the accepted EHT
one-dimensional interferometric visibility sequences. The expected MLC fields
would carry radar speckle, cross-polarization structure, and wrapped phase on a
regular azimuth-by-range grid.

## Discovery result

The official ASF Search API returned 250 UAVSAR products, including 23
`COMPLEX` MLC archives. Seventeen had both a bounded size and a direct ASF URL.
The smallest selected result was:

| Field | Value |
|---|---|
| Filename | `pchame_06021_26008_022_260506_L090_CX_01_mlc.zip` |
| Size | 424,321,888 bytes |
| MD5 | `c7d54e3c25090ba388506022385108c0` |
| Polarization | Full |
| Start time | `2026-05-06T16:36:48Z` |
| ASF URL | `https://datapool.asf.alaska.edu/COMPLEX/UA/pchame_06021_26008_022_260506_L090_CX_01_mlc.zip` |

No radar payload was downloaded. Consequently, native element type, archive
members, dimensions, byte order, and complete-record sizing could not be
verified from the selected product.

## Access failure

A bounded 4 MiB tail request to the ASF URL followed this official redirect
chain:

1. `datapool.asf.alaska.edu` returned HTTP 307;
2. `data.asf.alaska.edu/archive/datasets/uavsar/...` returned HTTP 302 to NASA
   Earthdata Login; and
3. the unauthenticated request ended with HTTP 401.

The follow-up official JPL product-page route for the same job was also
attempted and returned HTTP 401. That failure occurred before a JPL page or
payload-link inventory could be written. Credentials were not requested or
embedded in a reproducible recipe.

The official NASA data-policy evidence is otherwise favorable: NASA states
that it promotes full and open sharing of its data with research, industry,
academia, and the general public. The blocker is reproducible anonymous payload
access, not an identified restrictive license.

## Decision and retry condition

Do not repeat the ASF or JPL anonymous probes with the same URLs, and do not
promote this candidate while acquisition depends on personal Earthdata
credentials.

Retry only if NASA, JPL, or ASF exposes an exact official anonymous URL for a
bounded UAVSAR MLC archive or its constituent MLC and annotation files. A retry
must first confirm range access, then inspect only enough archive or annotation
metadata to establish native float32 complex storage, dimensions, polarization,
byte order, and natural sample sizes before downloading a payload.

Evidence remains under
`.data/discovery/nasa_uavsar_mlc_polarimetric_f32/` and
`.data/logs/nasa_uavsar_mlc_polarimetric_f32/`.
