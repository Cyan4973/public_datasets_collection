# Rejected: bbbc004_microscopy_tiff_u16 — 8-bit not 16-bit

- Date: 2026-07-22
- Candidate: `staging/bbbc004_microscopy_tiff_u16`
- Intended: synthetic fluorescence microscopy uint16

## Attempt

User ran download, got 5 zips 13MB each, 20 TIFFs each (BBBC004_v1_000_images.zip etc).

Build: `no native 16-bit samples accepted`

Inspection:

```
synthetic_000_images/10GRAY.tif {256: (3,1,950), 257: (3,1,950), 258: (3,1,8), 259: (3,1,32773)}  # bits 8, comp PackBits
```

Tags: 258=BitsPerSample=8, 259=Compression=32773 (PackBits), not 16-bit uncompressed.

## Reason

BBBC004 synthetic images are 8-bit PackBits TIFF, not native 16-bit. Fails 16-bit hunt criteria.

## Retry

Not for 16-bit; could be reclassified as u8 8-bit dataset (synthetic microscopy) if needed.

