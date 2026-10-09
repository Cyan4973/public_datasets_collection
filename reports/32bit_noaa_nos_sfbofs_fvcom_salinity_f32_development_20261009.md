# SFBOFS (FVCOM) nowcast salinity float32 development

## Outcome

Accepted `noaa_nos_sfbofs_fvcom_salinity_f32`: native float32 sea-water salinity fields from NOAA's operational San Francisco Bay Operational Forecast System (SFBOFS, FVCOM 4.4.7).

This is the first ocean-model output in the corpus at any width. The nearest existing material is different in kind:
- Argo in-situ CTD salinity profiles (`argo_gdac_ctd_profiles_f32`, downstream `argo_salinity_f32`) are measured, not modelled.
- STOFS-2D ADCIRC station water level (`noaa_stofs2d_glo_adcirc_station_water_level_f64`) is a different quantity from a different bucket.
- ERA5, CMIP6 and ClimSim are atmospheric model fields.

The novelty kind is new source and quantity within simulated geophysical fields, not a new modality. The measured breadth verdict is OK: the nearest family is downstream `h1__collection2._0.pt` at feature distance 0.0831, and its compressor does 12.6% worse on this data.

## Source and rights

- Source: NOAA NODD bucket `noaa-nos-ofs-pds` (us-east-1, anonymous HTTPS, not requester-pays).
- Objects: `sfbofs/netcdf/YYYY/MM/DD/sfbofs.t03z.YYYYMMDD.fields.n003.nc`, on 52 dates every 7 days from 2025-01-01 to 2025-12-24.
- Each object is 56,605,561 bytes, with its S3 ETag pinned in `sources.tsv`. The `sources.tsv` SHA-256 `dcc50d8a…` is pinned in the script.
- License: the AWS Open Data Registry entry `noaa-ofs.yaml` lists `arn:aws:s3:::noaa-nos-ofs-pds` ("CO-OPS Operational OFS Data (Historical Retention)") under the NODD terms. NODD data "are open to the public and can be used as desired"; attribution is requested, and implying NOAA endorsement is not allowed.
- The data are a U.S. Government work: simulated environmental model output with no personal data.

## Shape and conversion

Each natural record is one model output time step: the complete `salinity(time=1, siglay=20, node=54120)` field of one hourly fields file, valid at 00:00 UTC.

Storage is HDF5 with a v0 superblock, v2 object headers and dense root links. The variable is IEEE float32 LE in four raw chunks of shape (1, 10, 27060), with no filter pipeline (filter mask 0), no `_FillValue`, and no scale or offset.

`download.sh` fetches only nine byte ranges per object, 5,036,992 bytes in total:
- the 256 KiB head
- two 4 KiB B-tree windows
- the x/y mesh coordinates
- the four salinity chunks
- the time chunk

Every response must be HTTP 206 with the exact Content-Range, Content-Length and ETag, and every request sends If-Match.

The pure-stdlib reader is the accepted STOFS `h5lite.py` over a bounds-checked sparse range view, and it verifies lookup3 checksums. Stored floats are copied unchanged. The only reordering undoes the chunk tiling into row-major (siglay, node), with layer 0 at the surface and layer 19 at the bottom.

Per-file checks:
- the pinned 56-link root set
- globals title SFBOFS and source FVCOM_4.4.7
- a forcing attribute naming that date's t03z cycle
- an identical mesh (x/y SHA-256 pinned)
- time equal to the date at 00:00 UTC

The value policy is fatal on any fill (9.96921e36), NaN/Inf, or value outside (−1, 45). A sample is also rejected if it has fewer than 100k distinct values, a modal value covering more than half of it, or all layers identical.

## Accepted output

- Primary samples: 52, each 1,082,400 values and 4,329,600 bytes
- Primary values: 56,284,800
- Primary bytes: 225,139,200
- Fetched bytes: 261,923,584, which is 8.9% of the 2,943,489,172 bytes of whole objects; 86% of fetched bytes are kept
- Global range: 0.004995 to 34.0143 PSU
- Per-sample minimum: 0.005 to 8.557
- Per-sample maximum: the ocean boundary value, 33.9933 until 2025-05-14 and 34.0143 afterwards
- Per-sample distinct values: 611,934 to 1,023,006
- Maximum modal fraction: 1.364% (freshwater floors 0.005, 0.05 or 0.1)
- Zero values: 0; fill values: 0; identical adjacent layers: 0
- Domain mean: about 15 PSU in the January wet season, about 31 PSU in December; bottom-layer mean above surface-layer mean in all samples

## Judge checks

- `gate.py` passed with no warnings, and I re-ran `verify.sh` myself: the self-test, the layer-walk re-decode of all 52 samples, the statistics and the manifest totals all passed.
- I parsed every `sal_btree.bin` with my own `struct` code: TREE v1, leaf, 4 entries, each 1,082,400 bytes with mask 0, at chunk offsets (0,0), (0,27060), (10,0), (10,27060). My independent reassembly reproduces all 52 sample files byte for byte.
- Value inspection:
  - Freshwater floors and the ocean boundary cap are physically plausible; the cap covers 14 to 75 nodes per sample and is not a fill.
  - Bottom-layer salinity exceeds the surface in every sample, and the seasonal salinification is coherent.
  - Consecutive weeks share only 0.004% to 1.1% of values exactly, with mean absolute difference 0.35 to 3.9 PSU, so there are no near-duplicates.
  - Mantissas are fully used; this is native float32, not widened codes.
- Rights: I opened `noaa-ofs.yaml` myself. The bucket ARN is listed and the license text matches the manifest quote. No credentials appear in any script.
- Novelty:
  - `novelty.py --url` found no match outside this staging recipe, and `--type/--instrument/--archive` found 0 families.
  - The downstream 32-bit corpus (637 families) has no ocean-model fields.
  - The card's `new_modality` label is downgraded to `new_source`.
- Homogeneity: one model, mesh, variable, unit, cycle and output hour. The boundary-cap shift in mid-May is a forcing value within the same regime, not a mixed regime.
