# ESRF ID15 MXene aerogel micro-CT axial slices uint8 development

## Outcome

Accepted `zenodo_esrf_mxene_aerogel_microct_slices_u8`: reconstructed
synchrotron X-ray micro-tomography axial slices of one freeze-cast lamellar
Ti3C2Tx MXene aerogel, imaged at ESRF beamline ID15 at 11 compressive-strain
states (0, 5, ..., 50%).

This is the first 8-bit reconstructed tomography family in the collection.
Reconstructed X-ray CT exists locally only at 16 bits, as clinical TCIA
DICOM in Hounsfield or detector units. Other tomography-related families sit
at other widths and process stages:
- IMAT neutron projections (f32)
- TEM tilt series (i16)
- LoDoPaB sinograms (f32)

The nearest 8-bit volumetric family, `empiar_13192_sbfsem_vessel_slices_u8`,
is serial block-face SEM of tissue: a different physics and material.

## Source and rights

- Source: Zenodo records 4761663, 4764282 and 4766087, "CT data; freeze cast
  aerogel as-cast and following compressive strain; upload 1/2/3 of 3".
  Authors: Rawson, Bayram, McDonald, Yang, Courtois, Guo, Xu, Burnett, Barg
  and Withers (2021). The deposit accompanies "Tailoring lamellar MXene
  aerogel microstructure by compressive straining".
- License: CC BY 4.0. The live record metadata of all three records shows
  `"license": {"id": "cc-by-4.0"}` and `access_right: open`, and lists the
  exact `.raw` and `.txt` files used.
- 11 headerless 8-bit `.raw` volumes of 1381 x 1381 x Z voxels:
  - Z = 3155, 3007, 2841, 2667, 2520, 2400, 2239, 2081, 1909, 1768, 1769
  - 50,265,135,316 bytes and 26,356 slices in total
  - each volume pinned by exact size (= 1381²·Z) and Zenodo MD5
- 11 `.txt` descriptors, pinned by MD5 and SHA-256, each declaring the
  lattice, 8 bit, little endian and 3.1 µm voxels.
- `download.sh` re-validates the titles, license, access, the ESRF ID15
  description and every used file's size and MD5 on each run.

## Shape and conversion

Each natural record is one reconstructed axial slice: 1381 x 1381 uint8
voxels, 1,907,161 bytes. Synchrotron parallel-beam reconstruction produces
each slice from its own sinogram. Whole volumes are 3.37-6.02 GB, above the
1 GB cap. Slices are taken whole and are not tiled, cropped or grouped into
slabs.

Slice plan per volume: m = ceil(0.05·Z) and
z_k = m + round_half_up(k·(Z−1−2m)/19) for k = 0..19. Kept slices are 83-150
slices (0.26-0.47 mm) apart.

The 5% end margin excludes end zones whose slice mean rises to 101-113. The
last 50% slice is a featureless disc with ring artefacts.

Each kept slice is fetched with one HTTP Range request
`[z·1907161, (z+1)·1907161)`. The response must be a final 206 with
`Content-Range` total equal to the pinned `.raw` size and exactly 1,907,161
bytes. The bytes are written unchanged as row-major [y][x] uint8.

Grey levels are the authors' published per-volume 8-bit windowing. Nothing
is rescaled or masked, and 0 and 255 are kept as clipped extremes.
Degeneracy rules are the same in download, build and verify:
- at least 64 distinct values
- modal value at most 10%
- no constant row or column
- mean in [72, 104]
- no duplicates

## Accepted output

- Volumes: 11 (all published strain states)
- Primary samples: 220 (20 per volume)
- Primary values = bytes: 419,575,420
- Sample size: 1,907,161 values each (min = median = max)
- Download: 420,102,892 bytes (driver run 2026-10-06, all 220 slices 206 on
  the first attempt)
- Value range 0..255, mean 86.9914, zero fraction 1.269e-5, 255 fraction
  7.181e-5
- Per-slice distinct values 245-256, entropy 6.14-6.71 bits/value
- Per-volume slice-mean ranges between 85.84 and 88.57
- Listing SHA-256 (name\tsha256 lines in index order):
  `eff23b6f7a8b4102e9ccea6c767e81e1273477d89bc17080c641acb20bbbe0d3`

Known limitations:
- All samples show one specimen, so content is correlated across samples.
- The per-volume 8-bit windowing is not calibrated to attenuation.
- Every slice shows a faint field-of-view circle, a source artefact that is
  kept.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/<id>` gave PASS with
  no warnings. Primary values are 419,575,420, there are 220 samples, the
  median is 1,907,161 and the width is 8.
- **Verify:** I ran `bash staging/<id>/verify.sh` myself. It printed
  `verify ok samples=220 bytes=419575420 distinct_payloads=220`.
  `verify_slices.py` shares no code with build or download.
- **Pins:** the recipe's `slice_sha256.tsv` is identical to the realized
  `downloads/<id>/slice_sha256.tsv`.
- **Download log:** 220 `slice_validation=ok` lines and 3
  `record_validation=ok` lines. A sample header file shows a final
  `206 PARTIAL_CONTENT` with
  `content-range: bytes 301331438-303238598/6017092955`.
- **Bytes**, using stdlib Python under `/tmp/autocollect/<id>/` on 8 samples
  spanning 0-50% strain and both margins:
  - Neighbour differences are smallest at a 1381 offset, compared with 1380
    and 1382, which confirms the lattice width.
  - Horizontal neighbours differ by 13-20 grey levels against 23-29 for
    random pairs, so there is real spatial structure.
  - Percentiles are consistent across volumes.
  - Rendered PNGs show lamellar aerogel interior. The 50% slices are buckled
    and denser.
  - The builder's probe of the 50% end slice (z=1768) is a ring-artefact
    disc, confirming the margin rule.
- **Duplicates:** comparing every pair of the 220 samples, the closest pair
  differs by a mean of 20.5 grey levels, with only 1.9% of values equal. lzma
  on two neighbouring kept slices concatenated saves nothing.
- **Rights:** a live fetch of all three Zenodo record JSONs confirmed
  cc-by-4.0 and open access, the file keys and sizes, and the ESRF ID15
  description. Grep found no credentials in the recipe.
- **Novelty:** `novelty.py` matched none of the three record URLs; the only
  URL hits were the generic Zenodo API path. The specific terms matched no
  other recipe, registry, ledger or downstream entry. A grep of `datasets/`
  found reconstructed CT only at 16 bits (TCIA).
