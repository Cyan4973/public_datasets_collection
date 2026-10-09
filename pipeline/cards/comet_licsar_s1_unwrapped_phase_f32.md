# COMET LiCSAR Sentinel-1 Frame Interferograms: Geocoded Unwrapped Interferometric Phase (geo.unw.tif, radians), Native Float32 GeoTIFF

- Candidate id: `comet_licsar_s1_unwrapped_phase_f32`
- Width: float32
- Quantity: Unwrapped differential interferometric phase (radians) of Sentinel-1 IW short-baseline (6/12-day) pairs, geocoded on a ~0.001 deg grid; 0 = no-data
- Source: https://comet.nerc.ac.uk/comet-lics-portal/
- Resources: https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products/, https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products.public/1/001A_05031_131313/interferograms/20240602_20240614/20240602_20240614.geo.unw.tif
- License: Derived works of Copernicus Sentinel data under the Copernicus Sentinel data terms (free, full and open; attribution required), as stated by the COMET-LiCS portal
- License evidence: https://comet.nerc.ac.uk/comet-lics-portal/
- License quote: All Sentinel-1 results that are available for download are Derived Works of Copernicus data (2015-2016), subject to the following use conditions: 'Terms and conditions for the use and distribution of sentinel data and service information'. ... Please include the following acknowledgement ... 'LiCSAR contains modified Copernicus Sentinel data [Year of data used] analysed by the Centre for the Observation and Modelling of Earthquakes, Volcanoes and Tectonics (COMET).'
- Natural record: One interferogram unwrapped-phase raster (<date1>_<date2>.geo.unw.tif), e.g. 3498 x 2689 = 9.4M float32 pixels
- Estimated samples: 20
- Estimated primary values: 188,000,000
- Estimated download bytes: 340,000,000
- Estimated primary bytes: 752,000,000
- Decode path: Pure-stdlib TIFF: LE classic TIFF, SampleFormat=3, BitsPerSample=32, Compression=8 (zlib), Predictor=3 (floating-point), RowsPerStrip=1. Per strip: zlib.decompress, undo the horizontal byte difference, then de-interleave the 4 byte planes (MSB-first) to big-endian float32 and re-emit LE. Validated in the probe on a mid-raster strip: 2938 valid values in [-12.02, 13.15] rad, 560 zero no-data, 0 NaN.
- Novelty kind: new_quantity
- Measurement type: insar_unwrapped_phase
- Instrument line: sentinel1_iw_licsar
- Archive collection: gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products
- Novelty evidence: novelty.py --url/--terms LiCSAR/unwrapped/interferogram: no recipe, registry, ledger or downstream matches; host gws-access.jasmin.ac.uk unused. InSAR is present only as earthbigdata coherence u8 (insar_coherence) and the umbra SICD complex SLC in the pipeline. --type insar_unwrapped_phase shows 0 families.
- Homogeneity: One processor (LiCSAR/GAMMA), one product (geo.unw), one unit (radians), Sentinel-1 IW. Restrict to short temporal baselines (consecutive 6/12-day pairs) from a handful of frames so the phase statistics are one regime. Do not mix in wrapped diff_pha, coherence or bovl products.
- Risks: License is the Copernicus Sentinel terms via the portal rather than an explicit CC licence; the judge may want the Copernicus terms text quoted (the corpus already accepts Sentinel-derived recipes). No-data zeros fill off-swath and water areas, so the zero fraction per raster should be measured; prefer land frames. Smooth float rasters have collided with existing families before (HMI synoptic vs WMAP), so breadth is uncertain. Each raster is ~37 MB, so ~20 samples come to ~750 MB.
- Probe evidence: Listing LiCSAR_products/1/ -> frames; interferograms/20240602_20240614 lists geo.unw.tif (links resolve under LiCSAR_products.public/). HEAD: HTTP 200, content-length 17018630. 64 KB range GET: TIFF tags 256=3498, 257=2689, 258=32, 259=8, 317=3, 339=3, GeoKeys WGS 84. Strip 1340 decoded as above.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_183620.jsonl`).
