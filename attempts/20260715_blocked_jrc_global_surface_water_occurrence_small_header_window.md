# Blocked Attempt: `jrc_global_surface_water_occurrence_u8`

Date: 2026-07-15

## Outcome

The first staged download run fetched six 4 MiB TIFF header windows, then failed
before selecting or downloading internal tile chunks.

## Failure

The JRC Global Surface Water occurrence GeoTIFFs can place the first image file
directory well beyond the first 4 MiB. The observed failure was:

```text
struct.error: unpack_from requires a buffer of at least 36592012 bytes for
unpacking 2 bytes at offset 36592010 (actual buffer size is 4194304)
```

No chunks were downloaded.

## Fix Applied

The staging downloader now defaults `GSW_HEADER_BYTES` to 64 MiB and treats
smaller cached header files as incomplete, so a rerun will refetch the headers
and continue to chunk selection.

## Follow-up

The 64 MiB rerun reached header parsing and showed the occurrence GeoTIFFs use
TIFF compression code `5` (LZW). The staging recipe was updated again to allow
LZW, extract selected chunks from cached full TIFF files when available, and
decode LZW locally during build.
