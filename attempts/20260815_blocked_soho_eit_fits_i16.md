# Blocked: SOHO/EIT Solar EUV FITS Int16

- Date: 2026-08-15
- Candidate: `soho_eit_fits_i16`
- Intended domain: solar-corona extreme-ultraviolet image planes
- Intended representation: native FITS signed int16, or conventional
  `BZERO=32768` uint16, serialized little-endian

## Why it was considered

SOHO's Extreme ultraviolet Imaging Telescope observes coronal plasma at 171,
195, 284, and 304 angstroms. Complete native-16-bit frames would add a solar
physics imaging process absent from the accepted corpus. The target was one
complete 2D detector/image plane per sample, not FITS container bytes.

This was deliberately separate from the rejected SDO/AIA synoptic route. The
SDO products exposed tile-compressed, scaled logical int32 images. The SOHO
probe required a simple primary image with `BITPIX=16`, rank two,
`BSCALE=1`, and `BZERO` of either zero or the lossless unsigned convention
32768.

## Bounded discovery performed

A user-run metadata-only script queried official SOHO/NASA paths and never
downloaded a complete observation. It:

- fetched official mission and data-access pages;
- crawled bounded paths under `umbra.nascom.nasa.gov/eit/` and
  `soho.nascom.nasa.gov/data/REPROCESSING/Completed/`;
- reached exact yearly `eit171`, `eit195`, `eit284`, and `eit304`
  directories;
- tried ordinary FITS suffixes, known legacy EIT `ef*` names, and finally all
  non-document/non-preview file links within those exact wavelength
  directories; and
- was prepared to range-read at most 256 KiB, recognize FITS or a gzip
  wrapper, and reject every non-native/scaled/non-image header.

Across three bounded discovery revisions, no machine-discoverable observation
payload URL was emitted. The general EIT host also returned HTTP 503 during
the final run, although the SOHO reprocessing tree remained reachable. No
FITS header qualified because no candidate object URL reached the header
probe.

## Rights result

The official SOHO mission and general data pages were reachable, but contained
no explicit license or reuse statement detected by the rights probe. The
expected SOHO data-use-policy URL returned HTTP 404. NASA and ESA mission
participation alone is not treated as evidence that every jointly produced
payload is unrestricted training material.

## Decision

Block this route. No dataset payload or training sample was produced. Do not
repeat broad directory crawling.

Retry only if both are available:

1. exact official SOHO/EIT observation URLs already known to contain direct,
   simple native `BITPIX=16` image payloads; and
2. an official SOHO/EIT-specific rights statement clearly permitting the
   intended training reuse.

Evidence remains in:

- `.data/logs/soho_eit_fits_i16/discover.latest.log`;
- `.data/discovery/soho_eit_fits_i16/pages.json`;
- `.data/discovery/soho_eit_fits_i16/rights_evidence.json`; and
- `.data/discovery/soho_eit_fits_i16/candidate_urls.txt`.
