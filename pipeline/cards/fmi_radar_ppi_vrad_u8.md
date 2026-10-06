# FMI Weather Radar 0.5-degree PPI Doppler Radial Velocity (VRAD, QC) GeoTIFFs UInt8

- Candidate id: `fmi_radar_ppi_vrad_u8`
- Width: uint8
- Quantity: Single-site Doppler radial velocity of hydrometeors from the lowest (0.5 deg) PPI after FMI quality control. uint8 code with v = 0.5*code - 64 m/s per embedded GDAL metadata; NoData 255. Gridded to 2003x2003 Cartesian pixels around the radar.
- Source: https://registry.opendata.aws/fmi-radar/
- Resources: https://fmi-opendata-radar-geotiff.s3.amazonaws.com/?list-type=2&prefix=2025/06/15/fikor/, https://fmi-opendata-radar-geotiff.s3.amazonaws.com/2025/06/15/fikor/202506150000_fikor_ppi_0.5_vrad_qc.tif, https://fmi-opendata-radar-geotiff.s3.amazonaws.com/2026/03/10/fikor/202603100000_fikor_ppi_0.5_vrad_qc.tif
- License: CC BY 4.0 (Finnish Meteorological Institute open data)
- License evidence: https://registry.opendata.aws/fmi-radar/ (read via https://s3.amazonaws.com/registry.opendata.aws/fmi-radar/index.html); FMI doc page http://en.ilmatieteenlaitos.fi/radar-data-on-aws-s3
- License quote: License Creative Commons Attribution 4.0 International (CC BY 4.0)
- Natural record: One PPI scan product file: one site, one 5-minute scan time, product ppi_0.5_vrad_qc, decoded to a 2003x2003 uint8 raster (4,012,009 values).
- Estimated samples: 48
- Estimated primary values: 192,576,432
- Estimated download bytes: 18,000,000
- Estimated primary bytes: 192,576,432
- Decode path: Pure-stdlib TIFF reader: little-endian classic TIFF, BitsPerSample 8, SampleFormat 1, SamplesPerPixel 1, Compression 5 (LZW), Predictor 1, 512x512 tiles (16 tiles, TileOffsets/TileByteCounts). Uses a TIFF-variant LZW decoder (MSB-first codes, 9-12 bit, early change, Clear 256 / EOI 257), validated on synthetic input. Tiles are assembled and cropped to ImageWidth x ImageLength (2003x2003). GDAL_METADATA tag 42112 (SCALE 0.5, OFFSET -64, UNITS VRADH) and GDAL_NODATA tag 42113 ('255') are read and checked as auxiliary metadata.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://fmi-opendata-radar-geotiff.s3.amazonaws.com/ with terms FMI / 'radial velocity' / vrad / radar: no FMI or radial-velocity recipe, registry row, ledger row or downstream family. The only 'fmi' hit is a substring of the Magellan 'fmidr' id. Local radar families are NEXRAD Level-III N0Q reflectivity (u8) and DWD RADOLAN precipitation (i16). Doppler radial velocity is a new quantity from a new national network.
- Homogeneity: One product (ppi_0.5_vrad_qc), one site (e.g. fikor; a few sites would still share scale/offset/grid), new naming era only (2025-01 onward). Files before mid-2024 use different names (VRAD-1.tif) and should not be mixed. SCALE 0.5 / OFFSET -64 / NoData 255 verified identical on 2025-06-15 and 2026-03-10 files.
- Risks: Large NoData/no-echo fractions on dry days reduce entropy, so choose widespread-precipitation days. Space scans at least 1 h apart (e.g. 4 per day x 12 days) to avoid near-duplicate consecutive 5-min scans. Data are Cartesian resamplings of polar scans (operational product, not raw gates). Extraction ratio is high (about 0.37 MB LZW file to 4 MB raster), which is fine since source-side compression explains it. Each site has about 285 files per day, but there is a coverage gap mid-2024. Together with SEVIR VIL this is a second weather-radar candidate this round, though a different quantity and source.
- Probe evidence: Bucket fmi-opendata-radar-geotiff lists anonymously with years 2020-2026. 2025-06-15/fikor has 4,267 files including 285 ppi_0.5_vrad_qc.tif (mean 367 KB, max 513 KB). Product list: cappi_600_dbzh, etop_{-10,20,45,50}_dbzh, ppi_{0.5..9.0}_dbzh, ppi_0.5_hclass, ppi_{0.5,0.7,1.5}_vrad. A 16 KB header range read gave W=H=2003, BPS 8, Compression 5, Predictor 1, Tile 512x512, 16 tile offsets, SampleFormat 1, GDAL metadata UNITS VRADH / OFFSET -64 / SCALE 0.5, NoData '255'. One-byte range GET returned 206. License read from the S3-hosted registry page.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_194855.jsonl`).
