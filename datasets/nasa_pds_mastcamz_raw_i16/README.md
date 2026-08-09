# NASA PDS Mars 2020 Mastcam-Z raw int16

This candidate targets complete raw signed-16-bit Mastcam-Z rover-camera
detector frames from the official NASA Planetary Data System. One complete
PDS4 image array would be one natural two-dimensional sample.

Run the label-only preflight:

    bash datasets/nasa_pds_mastcamz_raw_i16/discover.sh

The preflight fetches NASA's science-information policy, official PDS HTML
directory listings, bounded PDS4 XML labels, and HTTP HEAD metadata. It does
not download image payloads. A product qualifies only when its label proves:

- Mars 2020 Mastcam-Z observational provenance;
- a complete `Array_2D_Image` with `SignedMSB2` elements;
- a directly addressable, unpacked 16-bit PDS array representation;
- explicit positive line/sample geometry and a bounded payload;
- an array byte extent consistent with the official file size.

If qualified products exist, a later recipe will select a deterministic
bounded set of complete EDR frames and convert the big-endian source words to
canonical little-endian int16.

The qualified plan contains all 52 complete 1200×1648 EDR frames found in the
bounded sol-1/sol-2 label prefix, totaling 205,670,400 primary bytes. Run:

    bash datasets/nasa_pds_mastcamz_raw_i16/download.sh
    bash datasets/nasa_pds_mastcamz_raw_i16/build.sh
    bash datasets/nasa_pds_mastcamz_raw_i16/verify.sh

The builder validates each pinned PDS4 XML label and complete IMG file,
extracts the one `Array_2D_Image` at its declared byte offset, and changes only
byte order from source big-endian `SignedMSB2` to canonical little-endian
int16. PDS/VICAR headers and all mission metadata are excluded.

The detector samples use 12 significant bits inside the signed 16-bit
container. PDS metadata identifies `MCZ_LUT0`/`MCZ_LUT1` hardware companding
in expanded form, so some valid frames intentionally occupy a sparse set of
DN codes.
