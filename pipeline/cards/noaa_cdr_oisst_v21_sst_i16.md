# NOAA CDR Daily Optimum Interpolation SST v2.1 (AVHRR-only, 0.25° Global): Sea-Surface Temperature Analysis Grids, Native Scaled Int16 (0.01 °C)

- Candidate id: `noaa_cdr_oisst_v21_sst_i16`
- Width: int16
- Quantity: Daily optimum-interpolation sea-surface temperature analysis stored natively as int16 with scale_factor 0.01 °C, add_offset 0 and _FillValue -999 over land. The NetCDF4 variable 'sst' has shape 1x1x720x1440.
- Source: https://registry.opendata.aws/noaa-cdr-oceanic/
- Resources: https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com/data/v2.1/avhrr/202001/oisst-avhrr-v02r01.20200101.nc, https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com/?list-type=2&prefix=data/v2.1/avhrr/202001/
- License: NOAA NODD open data (US Government work, no use restrictions; attribution requested)
- License evidence: https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/noaa-cdr-oceanic.yaml
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired. ... NOAA requests attribution for the use or dissemination of unaltered NOAA data.
- Natural record: One daily NetCDF file = one complete global 720x1440 SST analysis grid (1,036,800 values). Bounded scope is the 1st of each month 2015-01 to 2024-12 (120 files), all final (non-preliminary) v02r01 files.
- Estimated samples: 120
- Estimated primary values: 124,416,000
- Estimated download bytes: 205,000,000
- Estimated primary bytes: 248,832,000
- Decode path: curl each pinned .nc (about 1.7 MB) from the anonymous NODD bucket and pin size and ETag/MD5. Decode with the pure-stdlib HDF5 approach already accepted in datasets/noaa_cdr_seaice_conc_nh_daily_u8/scripts/h5lite.py: superblock, links, then dataset 'sst'. It is datatype fixed-point signed 2-byte with a v1 B-tree chunk index, a single 720x1440 chunk, and filters shuffle(2 bytes)+deflate. Inflate, unshuffle 2-byte lanes, and emit little-endian int16 unchanged (keep -999 land fill as native, documented).
- Novelty kind: new_quantity
- Measurement type: geo_product_raster
- Instrument line: NOAA OISST v2.1 AVHRR-only daily analysis (NCEI CDR)
- Archive collection: aws_opendata_noaa_cdr
- Novelty evidence: novelty.py --url OISST bucket --terms OISST 'sea surface temperature': no matches in recipes, registry, ledger, downstream or downstream_registry. No SST grid exists at any width; the only NOAA CDR recipe is sea-ice concentration u8, which comes from a different bucket and file.
- Homogeneity: One product and version (OISST v2.1 AVHRR-only, final), one grid, one variable, one unit and scale (0.01 °C int16), one fill convention. The anom, err and ice variables in the same file are excluded and not to be proposed separately.
- Risks: (1) Land fill -999 is about 33% of each grid: native and documented, below dominance. (2) It is a smooth analysis field and could sit near another smooth geophysical i16 raster in zlsim (for example SoilGrids clay or SRTM); the byte gate decides. (3) The last ~2 weeks of files are 'preliminary'; the selected 2015-2024 dates are final. (4) Ocean/climate domain rather than strictly atmosphere.
- Probe evidence: Bucket listing for data/v2.1/avhrr/202001/: daily files of about 1.69 MB. Fetched one 1.7 MB file and parsed it with the repo's h5lite. Variables: time, anom, err, ice, lat, lon, sst, zlev. sst shape (1,1,720,1440), datatype class fixed-point signed size 2, filters [(shuffle,2),(deflate,4)], chunk (1,1,720,1440), attributes scale_factor 0.01, add_offset 0, _FillValue -999, units Celsius. Decoded 1,036,800 values: fill 33.3%, 3,401 distinct, range -180 to 3,223, next most common value 1.9% (sea-ice -1.80 °C).

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_132438.jsonl`).
