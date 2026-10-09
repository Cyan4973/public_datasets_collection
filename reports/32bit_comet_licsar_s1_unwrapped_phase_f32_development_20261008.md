# COMET LiCSAR Sentinel-1 unwrapped interferometric phase float32 development

## Outcome

Accepted `comet_licsar_s1_unwrapped_phase_f32`: complete geocoded unwrapped differential interferometric phase rasters (`<date1>_<date2>.geo.unw.tif`) from the COMET LiCSAR Sentinel-1 processing system, emitted as native IEEE-754 float32 in radians.

This is the corpus's first unwrapped-phase material at any width. The InSAR material already in the corpus is the u8 interferometric coherence family `earthbigdata_s1_global_coherence_vv_coh12_u8`. Related SAR families are `sentinel1_grd_measurement_u16` (backscatter amplitude) and the complex SLC candidate in the pipeline. All of those are different quantities. Novelty kind: new quantity, from a new source host.

## Source and rights

- Source: official COMET LiCSAR products in the public NCEO geohazards JASMIN group workspace (`https://gws-access.jasmin.ac.uk/public/nceo_geohazards/LiCSAR_products.public/`). The COMET LiCSAR portal (`comet.nerc.ac.uk/licsar/LiCSAR_portal.html`) links each of the four frames used to this workspace.
- Selection: 24 files pinned in `sources.tsv` by size, Last-Modified and SHA-256, 776,518,900 bytes in total.
- Rights:
  - The COMET-LiCS portal states that downloadable Sentinel-1 results are "Derived Works of Copernicus data", subject to the Sentinel data terms, and requires an acknowledgement.
  - The EU Legal notice on the use of Copernicus Sentinel Data and Service Information grants free reproduction, distribution, communication to the public and adaptation/modification. Modified data must carry the notice "Contains modified Copernicus Sentinel data [Year]".
  - CEDA catalogue record `52cda2e0e6c04272ae15ac836c1e8493` ("LiCSAR interferometry products") states the Open Government Licence v3.0 for the product line.
  - Corpus precedent: `sentinel1_grd_measurement_u16` is accepted under the Copernicus terms.
- Required acknowledgement, kept in the manifest: "LiCSAR contains modified Copernicus Sentinel data 2023 analysed by COMET. LiCSAR uses JASMIN." Cite Lazecký et al. 2020.

## Shape and conversion

- Natural record: one interferogram's unwrapped-phase raster. Each record becomes one sample, row-major from north to south and west to east, with no tiling.
- Frames (four inland frames, six consecutive 12-day Sentinel-1A IW pairs each, June–September 2023):

  | Frame | Area | Pass | Raster (w × h) |
  |---|---|---|---|
  | 001A_05031_131313 | central Spain | ascending | 3498 × 2689 |
  | 043A_05221_121313 | eastern Anatolia | ascending | 3364 × 2639 |
  | 050D_05246_131313 | south-eastern Anatolia | descending | 3464 × 2870 |
  | 094D_05100_131313 | central Anatolia | descending | 3414 × 2685 |

- Container: classic little-endian GeoTIFF, a single float32 band (SampleFormat 3), RowsPerStrip 1.
  - Frame 001A comes from a November 2025 batch encoded with zlib + floating-point predictor 3.
  - The other three frames come from May/June 2025 batches and are uncompressed.
- Decoding (pure stdlib): zlib inflate, then a per-row running byte sum mod 256, then the four MSB-first byte planes are reassembled into big-endian float32 and re-serialised little-endian. Uncompressed strips are copied as they are. Values stay bit-exact.
- No-data: 0.0 is kept, never converted to NaN. Most zeros are bounding-box corners outside the tilted swath; the rest are low-coherence masking, which CEDA documents. download, build and verify all reject a raster with zero fraction above 0.5, any non-finite value, or constant values.
- Excluded products: wrapped `diff_pha`, `cc`, `mag_cc`, `bovl`/`sbovl` and PNG previews.

## Accepted output

- Primary samples: 24
- Primary values: 224,351,928
- Primary bytes: 897,407,712
- Minimum sample: 8,877,596 values; median 9,286,356; maximum 9,941,680
- Value range: -34.397 to +35.005 rad
- Zero (no-data) values: 75,435,899, or 0.336 overall (per raster 0.309–0.389)
- Aggregate decoded SHA-256 (samples in index order): `6e73fe718b92ad20d0e6e2eb0c87d085d443105ecf619b322ff30114c9ceb321`
- Breadth (zlsim): verdict OK. Nearest is `downstream:h1__collection2._0.prbz` at distance 0.096 with compression loss 0.065. Own compression ratio is 1.94.

Limitations: the coverage is narrow (four frames, one summer). Sample count is bounded by the 1 GB cap at about 37 MB per natural raster, not by the source.

## Judge checks

- `gate.py staging/comet_licsar_s1_unwrapped_phase_f32`: PASS with no warnings.
- `verify.sh` run by the judge: pass (24/24 samples re-derived by the separate reference decoder; hashes, duplicates, zero policy and totals checked). build.sh and licsar_unw.py contain no network calls. The driver's download log shows all 24 files fetched and every strip decoded and checked.
- Independent judge decoder (own TIFF tag parser and an explicit predictor-3 loop):
  - It matched `001A…20230714_20230726` (predictor 3) and `050D…20230730_20230811` (uncompressed) byte for byte.
  - The tag dump shows one IFD with no GDAL scale/offset or nodata tags and no overviews.
- Bytes, on 7 samples across all frames:
  - Medians are about 0, and the 1–99% quantiles sit within ±6 to ±26 rad.
  - Each raster has about 830k–910k sampled distinct bit patterns, and there is no -0.0.
  - The low mantissa byte is zero for about 1–2% of values. In one 094D raster the figure is 11.7%: those values are multiples of 2^-17, the float32 ulp of [64,128) rad, which points to upstream re-referencing rather than a local remap.
  - The rasters are spatially smooth: mean |dx| is 0.03–0.11 rad and mean |dy| 0.06–0.15 rad.
  - Strips do not overlap. The single non-monotonic strip-offset jump falls in the all-zero top rows.
- Duplicates: consecutive pairs from the same frame share 0 identical valid values and correlate at -0.14 to -0.71, as expected when adjacent pairs share an epoch with opposite sign.
- Zero structure: 30.3–37.0% of each raster is swath-exterior row margins, and only 0.6–2.9% is interior masking.
- Rights:
  - The COMET portal page, the CEDA record and the EU legal notice PDF were fetched; the judge extracted the PDF text with zlib.
  - LiCSAR_portal.html links all four frames to the gws-access directories that download.sh uses.
  - No credentials appear in any script.
- Novelty: `novelty.py` was run with the JASMIN, COMET and CEDA URLs and the LiCSAR/unwrapped/interferogram/SNAPHU/InSAR terms. It also ran with `--type insar_unwrapped_phase --instrument sentinel1_iw_licsar --archive …` and with `--vocabulary`. Nothing matched beyond this candidate, apart from the different-quantity coherence and SAR families.
