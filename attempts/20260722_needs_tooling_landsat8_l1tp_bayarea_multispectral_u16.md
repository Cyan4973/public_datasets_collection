# Needs Tooling: landsat8_l1tp_bayarea_multispectral_u16 — tiled LZW + predictor

- Date: 2026-07-22
- Candidate: `staging/landsat8_l1tp_bayarea_multispectral_u16`
- Domain: multispectral satellite optical, Landsat-8 L1TP, 5 bands B1,B2,B3,B4,B8

## Attempt

Download succeeded:

```
B1.TIF 63M, B2 64M, B3 67M, B4 69M, B8 265M, total 551MB source
```

Build: `missing GDAL tools: install gdalinfo and gdal_translate`

Inspection:

```
w=7661 h=7801 bits=[16] comp=[5] spp=[1] predictor=[2] tile_width=[256] tile_length=[256] tiles=930
```

Tags: 256=width, 257=height, 258=16, 259=5 LZW, 277=1, 317=2 predictor, 322=256 tileWidth, 323=256 tileLength, 324=TileOffsets 930 entries, 325=TileByteCounts.

Current local parser `numeric16_extract --format tiff` only accepts:
- StripOffsets (273) not TileOffsets (324)
- Compression 1 (none), not 5 (LZW)
- No predictor handling

So it rejects all 5 bands.

## Reason

Landsat-8 on GCP is tiled LZW with horizontal differencing predictor 2. Requires:
- TileOffsets/TileByteCounts parsing
- LZW decompression (9-12 bit codes, clear 256 EOI 257)
- Predictor undo (add previous sample per row)

## Retry

- Extend `numeric16_extract.py` tiff parser to support tiled LZW + predictor 2, or
- Add GDAL as approved local feature, or
- Switch to Landsat on AWS `landsat-pds` which may have different compression (DEFLATE) or use COG with uncompressed option.

## Value

Landsat-8 multispectral distinct from Sentinel-2 (different sensor, 30m, different processing L1TP vs L2A), but remote-sensing rasters already well-represented per policy, so low priority vs truly new domains like sonar/lidar.

