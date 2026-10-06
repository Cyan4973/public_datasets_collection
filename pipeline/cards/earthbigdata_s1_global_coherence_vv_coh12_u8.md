# Global Seasonal Sentinel-1 Interferometric Coherence Tiles (VV, 12-day repeat) UInt8

- Candidate id: `earthbigdata_s1_global_coherence_vv_coh12_u8`
- Width: uint8
- Quantity: Median seasonal 12-day repeat-pass interferometric coherence for C-band VV polarization. The stored uint8 DN = coherence x 100 (0-100), with 0 as nodata. Each pixel is a 3-arcsec (~90 m) InSAR coherence estimate.
- Source: https://sentinel-1-global-coherence-earthbigdata.s3.us-west-2.amazonaws.com/index.html
- Resources: https://sentinel-1-global-coherence-earthbigdata.s3.us-west-2.amazonaws.com/?list-type=2&prefix=data/tiles/&delimiter=/, https://sentinel-1-global-coherence-earthbigdata.s3.us-west-2.amazonaws.com/data/tiles/N40W110/N40W110_summer_vv_COH12.tif, https://sentinel-1-global-coherence-earthbigdata.s3.us-west-2.amazonaws.com/data/tiles/N48W090/N48W090_fall_vv_COH12.tif
- License: CC-BY-4.0
- License evidence: https://sentinel-1-global-coherence-earthbigdata.s3.us-west-2.amazonaws.com/index.html
- License quote: License: The use of these data fall under the terms and conditions of the Creative Commons Attribution 4.0 International Public License Contains modified Copernicus Sentinel data.
- Natural record: One 1x1-degree tile GeoTIFF for a single metric, e.g. <TILE>_summer_vv_COH12.tif: 1200x1200 single-band uint8 pixels.
- Estimated samples: 300
- Estimated primary values: 432,000,000
- Estimated download bytes: 330,000,000
- Estimated primary bytes: 432,000,000
- Decode path: Classic little-endian TIFF read with stdlib struct. Probed IFD: W=H=1200, BitsPerSample=8, Compression=5 (LZW), Predictor=1, SampleFormat=1, RowsPerStrip=6, 200 strips, NoData='0', GeoKeys present. A pure-Python TIFF-LZW decoder (MSB-first, early change, clear 256 / EOI 257) decoded the first 6 real strips to exactly 1200*6 bytes each, with values 1..58 (coherence x100). Concatenate the 200 decoded strips into 1,440,000 uint8 values per tile. No predictor to undo.
- Novelty kind: new_modality
- Novelty evidence: novelty.py with --url .../data/tiles/ and --terms coherence interferometric sentinel-1 earthbigdata gave no URL matches and no local, ledger or downstream families. The only term hits are sentinel1_grd_measurement_u16 and downstream sentinel1_grd_hh_dn_u16 (GRD amplitude DN, a different product, quantity and width). No InSAR coherence or geodetic-interferometry material exists at any width locally or downstream.
- Homogeneity: Keep one metric (vv COH12) and one season (e.g. summer/JJA) across a pinned contiguous tile block, e.g. ~300 tiles over the western US/N. America. Don't mix COH06/18/24/36/48: different temporal baselines are different decorrelation regimes. Don't mix HH tiles or the AMP (uint16), rho/tau/rmse (uint16), inc or lsmap (uint8 categorical/aux) products. 24,858 tiles exist, so ~300 is a bounded subset well under the 1 GB cap.
- Risks: 1) It is a processed geophysical product (seasonal median coherence quantized to 0.01), but stored natively as uint8 DN by the producer. It is not a local remap. 2) The value range uses only ~0-100, about 7 bits. 3) Nodata 0 (ocean/no coverage) can dominate coastal tiles, so prefer land-interior tiles. 4) Attribution required: cite Kellndorfer et al. and 'Contains modified Copernicus Sentinel data'. 5) The tile list must be pinned, because listing gives 24,858 prefixes and some tiles lack VV or COH12 (the VRT 'COHno06' exists). download.sh should verify each TIFF header (8-bit, LZW, 1200x1200).
- Probe evidence: S3 listing of data/tiles/ with delimiter returned 24,858 tile prefixes. The N48W090 listing showed per-season vv_COH06..48, AMP, rho, tau, rmse, inc and lsmap files. HEAD on summer_vv_COH12 for N40W110, N45W120, N35W100, N50W115 and N31W105 all returned 200 with sizes 1.02-1.21 MB. A one-byte range GET returned 206. I range-fetched the first 64 KB of N48W090_fall_vv_COH12.tif: IFD parsed and 6 strips LZW-decoded. The bucket index.html documents the scaling ('Coherence (COH06,...,COH48.tif files): gamma = DN/100, No data value 0, DN stored as unsigned 8 bit integers') and the CC BY 4.0 license.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_174424.jsonl`).
