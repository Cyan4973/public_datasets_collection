# Hyperspectral Hunt Failure Triage - 2026-06-17

This report documents failed hyperspectral source-discovery attempts so future
runs do not repeat the same URL guesses.

## `nasa_aviris_classic_hyperspectral_i16`

- Target shape: native ENVI hyperspectral cubes, one scene per sample.
- Qualitative status: still desirable.
- Failure status: blocked on exact HTTPS product URLs.
- Prior repository trace: `reports/16bit_hunt_20260614_round3_dataset_state.md`
  records that the AVIRIS discovery path selected FTP payload links. FTP was not
  usable through the available environment/proxy path.
- Current decision: do not rerun the scraper-only AVIRIS recipe. Revisit only
  when exact HTTP(S) `.hdr` plus raw ENVI payload URLs, or a coherent archive URL
  containing both, are known.

## `nasa_pds_crism_trdr_i16`

- Target shape: native NASA PDS CRISM targeted hyperspectral `QUBE` products.
- Qualitative status: still desirable.
- Parser status: local synthetic PDS3 `QUBE` smoke test passed after repairing
  `tools/numeric16_extract.py`.
- Failure status: blocked on source discovery, not parser validation.
- Failed route 1: recursive HTML traversal of
  `https://pds-geosciences.wustl.edu/mro/mro-m-crism-3-rdr-targeted-v1/`.
  Result: no `.lbl` labels discovered.
- Failed route 2: guessed volume indexes
  `mrocr_2001` through `mrocr_2005` and `mrocr_2101` through `mrocr_2103`.
  Result: all `index/index.tab` URLs returned HTTP 404.
- Failed route 3: guessed volume indexes `mrocr_0001` through `mrocr_0008`.
  Result: all index candidates failed; download log summarized this as
  `skipped_index_count=8` followed by `no PDS labels discovered`.
- Current decision: do not add more guessed CRISM volume IDs. Revisit only with
  exact PDS label URLs from ODE/PDS, or a confirmed machine-readable catalog URL
  that yields labels and detached payload paths.

## `zenodo_forest_hyperspectral_envi_i16`

- Target shape: native ENVI hyperspectral forest/drone cubes.
- Qualitative status: plausible, but not yet validated.
- Failure status after rerun with repaired diagnostics: rejected.
- `download.sh` inspected four Zenodo records and downloaded no payload files.
- Problem in the initial recipe: the script specified Zenodo record IDs, but it
  did not pin file-level payload names or emit a durable failure inventory when
  no files matched the ENVI-like suffix filter. This made the failure hard to
  diagnose and resembled prior low-quality "empty candidate" scripts.
- Repair made: `tools/zenodo_envi_download.py` now always writes
  `download_inventory.json` with inspected record metadata and failure reasons,
  even when zero payloads are downloaded.
- Observed record metadata:
  - `13846686`, CC-BY-4.0, file `HYPER 1.txt`, 884 bytes.
  - `13846724`, CC-BY-4.0, file `HYPER 2.txt`, 275 bytes.
  - `13846747`, CC-BY-4.0, file `HYPER 3.txt`, 322 bytes.
  - `14535368`, CC-BY-4.0, file `hyper_4.txt`, 902 bytes.
- Rejection reason: these records expose only tiny `.txt` files through the
  Zenodo API, not native ENVI headers, binary payloads, or archives.
- Current decision: abandon this source. Do not retry these record IDs unless a
  new file-level payload URL is discovered outside the current Zenodo record
  file list.
