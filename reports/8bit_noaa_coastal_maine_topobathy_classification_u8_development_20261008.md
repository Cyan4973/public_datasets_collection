# NOAA Coastal Maine topobathy lidar classification uint8 development

## Outcome

Accepted `noaa_coastal_maine_topobathy_classification_u8`. The family is the native per-point LAS 1.4 classification byte from 50 complete COPC tiles of the NOAA NGS 2022-23 Coastal Maine topobathymetric lidar project (Digital Coast / DAV ID 10423, InPort 77189).

The local corpus already holds a LAS classification family: `dc_lidar_2015_classification_u8`, urban topographic codes 1-17 in flight order. This recipe differs in three ways:
- It carries the ASPRS topobathy domain profile: bathymetric bottom 40, water surface 41, derived water surface 42, water column 45, submerged vegetation 64, plus 1 and 2.
- The data comes from a green-plus-NIR topobathy sensor.
- Points are in COPC octree order.

The byte gate measured it as distinct: zlsim verdict OK, nearest family downstream `fastq_phred_u8` at distance 0.0763. The DC classification family is not among the 10 nearest. The novelty kind is new content in a known modality.

## Source and rights

- Source: public anonymous NODD bucket `noaa-nos-coastal-lidar-pds`, `laz/geoid18/10423/<block>/<date>_<E>e_<N>n.copc.laz`. The project has 44,316 tiles (1.79 TB) in 10 blocks.
- Pinned download: 50 tiles, 2,076,786,177 bytes. Each tile has key, size, S3 multipart ETag, LAS header point count and SHA-256 pinned in `sources.tsv`. The metadata XML (99,264 bytes) is pinned by SHA-256 `6ffc7e3f…cd14906`.
- License: the AWS Open Data Registry entry for the bucket states "NOAA data disseminated through NODD are open to the public and can be used as desired". NOAA requests attribution, forbids implying endorsement, and forbids presenting modified data as unaltered. The metadata gives "Access Constraints: None". It is a US Government work.
- Citation: National Geodetic Survey, 2022-2023 NOAA NGS Topobathy Lidar: Coastal Maine, https://www.fisheries.noaa.gov/inport/item/77189.
- Lineage: NV5 acquired the data (2022-10-06 to 2023-12-16, 120 missions) with Leica Chiroptera HawkEye 4X and HawkEye 5 systems. NOAA OCM then reclassified it into the final scheme 1/2/7/22/40/41/42/43/45/64/65 and produced the COPC tiles with PDAL.

## Shape and conversion

Each natural record is one complete 500 m x 500 m COPC tile. Each sample is that tile's full classification array, byte 16 of every 30-byte PDRF-6 record, copied unchanged in stored COPC order. Flags, scanner channel and edge bits stay in byte 15 and are not mixed in. No point is dropped and there is no missing-value sentinel.

Decoding uses `tools/laz/laszip.py` (compressor 3, POINT14 v3, variable COPC chunks). The build checks each tile against its LAS header:
- decoded point count;
- all 15 extended points-by-return counts;
- XYZ bounds;
- exact layer-byte consumption.

Tile selection uses only NOAA's published listing and per-tile minmax CSV, never decoded classes:
1. Keep full-footprint tiles (x and y extents ≥ 499 m).
2. Keep tiles whose published z-extent spans −3 m to +3 m NAVD88: 8,711 of 44,316 qualify.
3. In each block, take the 5 tiles at ranks floor((2i+1)m/10) of the key-sorted list.

## Accepted output

- Primary samples: 50, 5 per block across all 10 blocks
- Primary values / bytes: 312,002,256 (uint8)
- Sample size: minimum 4,501,495, median 6,168,542.5 (gate), maximum 8,903,129 values
- Class shares (codes outside the documented scheme: 0):

  | Code | Class | Share |
  |---|---|---|
  | 1 | Unclassified | 33.35% |
  | 2 | Ground | 11.23% |
  | 40 | Bathymetric bottom | 4.52% |
  | 41 | Water surface | 2.07% |
  | 42 | Derived/synthetic water surface | 30.73% |
  | 45 | Water column | 18.05% |
  | 64 | Submerged vegetation | 0.06% |

- Tiles with 40 and 41/42: 46 of 50. The other four have no detected bottom.
- Per-tile top-code share: 29.9% to 92.3%
- Order-0 entropy: 0.44 to 2.31 bits per value
- Build time: about 4.7 minutes; verify time: about 4.5 minutes

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Verify:** I ran `verify.sh` myself (exit 0, 50/50 tiles, byte equality against a fresh whole-file decode).
- **Build is local-only:** build and verify scripts read only local downloads and the repository decoder. No credentials appear in any script.
- **Selection reproduced:** I fetched NOAA's 8.9 MB minmax CSV and re-derived the rule independently. It gives 8,711 qualifying tiles and exactly the same 50 keys as `sources.tsv`.
- **Sample bytes:** I read all 50 samples. Sizes match the index, all SHA-256 values are distinct, and only the 7 codes above occur. Entropy and run-length statistics vary naturally across tiles, and nothing is degenerate.
- **Decoder, three-layer consistency:** in every tile, class-42 count = scanner-channel-1 count = synthetic-flag count (95,877,645 in total). These come from three separately decoded LASzip layers. Together with the header cross-checks, this confirms the POINT14 v3 channel-switch path that `tools/laz/README.md` marks unverified. The code also matches my recollection of LASzip's reference reader.
- **Decoder, physical semantics:** I decoded about 400k points from each of 3 tiles. Median z puts class 40 0.7 to 4.9 m below the 41/42 surface, with class 45 between them. The channel-to-class mapping and the user-byte mapping match the metadata lineage.
- **Rights:** I opened the AWS ODR YAML and the metadata XML constraints myself.
- **Novelty:** `novelty.py` finds no other recipe on project 10423. The other NODD coastal-lidar staging recipes are different projects and fields.
- **Notes for the record:**
  - The README and builder summary describe the sensor as HawkEye 4X only, following NOAA's abstract. The lineage also names HawkEye 5, and user bytes for both appear within each tile, so this is not a per-sample regime split.
  - Class 42 points are contractor-generated synthetic water surface. They are a delivered class of the published files and are kept as published.
