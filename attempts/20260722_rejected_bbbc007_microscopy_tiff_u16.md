# Rejected: bbbc007_microscopy_tiff_u16 — 8-bit RGB not 16-bit

- Date: 2026-07-22
- Candidate: `staging/bbbc007_microscopy_tiff_u16`
- Domain: Drosophila Kc167 fluorescence, 3-channel

## Attempt

Download succeeded: `BBBC007_v1_images.zip` 6.2 MB, `outlines.zip` 638 KB.

Build: `no native 16-bit samples accepted`

Inspection:

```
BBBC007_v1_images/f96 (17)/17P1_POS0014_D_1UL.tif w=[400] h=[400] bits=[8,8,8] comp=[1] spp=[3]
```

BitsPerSample = [8,8,8] RGB 8-bit, not 16-bit.

## Reason

Images are 8-bit RGB TIFF, not uint16.

## Retry

Not for 16-bit hunt; could be u8 RGB candidate.

