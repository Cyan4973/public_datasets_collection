# TartanAir V1 dense optical-flow float32 development

## Outcome

Accepted `tartanair_optical_flow_f32`: dense forward optical flow from the CMU
AirLab TartanAir V1 visual-SLAM simulation dataset, kept in its native
little-endian float32 form.

This is the first optical-flow family in the local corpus at any width, and
the downstream corpus has none either. The earlier Kubric MOVi flow attempts
(`kubric_movi_optical_flow_f32`, rejected; `kubric_movi_optical_flow_u16`,
blocked) came from a different source. They failed because the data was stored
as uint16 and the data objects had no license. Neither problem applies here.
The nearest accepted relative is `zenodo_morphodunes_piv_f64`, which holds
laboratory fluid PIV velocity at 64-bit: a different material, generation
process and width.

## Source and rights

- Source: Hugging Face dataset `theairlabcmu/tartanair`, pinned to revision
  `65e00180ea952475878a748543e11e9ec20beaac` (public, not gated). The official
  `castacks/tartanair_tools` `download_training.py` hard-codes
  `repo_id = "theairlabcmu/tartanair"`.
- Archives: 36 ZIP64 `<env>/<Easy|Hard>/flow_flow.zip` files, 676,775,615,642
  bytes in total (4.4–63.4 GB each). Each is pinned in `sources.tsv` with size,
  LFS sha256 and xet hash.
- Data type: per `tartanair_tools/data_type.md`, "The optical flow maps are
  saved as a float32 numpy array, which is calculated based on the ground truth
  depth and ground truth camera motion" (ImageFlow code).
- Rights:
  - Project page <https://theairlab.org/tartanair-dataset/>, "Term of use":
    "This work is licensed under a Creative Commons Attribution 4.0
    International License."
  - HF dataset card at the pinned revision: `license: bsd-3-clause`.

  Both are permissive, and the recipe follows the CC BY 4.0 attribution terms.
- Citation: Wang et al., *TartanAir: A Dataset to Push the Limits of Visual
  SLAM*, IROS 2020 (arXiv:2003.14338).
- Caveat: this is synthetic simulator ground truth (AirSim/Unreal) published
  upstream as float32, not measured flow and not a local numericization.

## Shape and conversion

Each natural record is one `Pxxx/flow/NNNNNN_MMMMMM_flow.npy` member: the flow
from frame N to frame N+1 of one trajectory. It is a (480, 640, 2) C-order
float32 tensor of 614,400 values (2,457,600 bytes) in pixels.

**Download.** The download uses byte ranges only:

1. the 64 KiB tail of each archive;
2. the exact ZIP64 central directory (39,552,939 bytes across 307,816 entries);
3. the exact local-header-plus-DEFLATE span of each selected member.

Every response must meet three conditions:

- it is a 206 with the exact `Content-Range`, including the archive size;
- `x-repo-commit` equals the pinned revision;
- `x-linked-etag` equals the archive's LFS sha256.

**Decode.** Each member is raw-inflated (wbits -15) and checked against the
central-directory CRC32 and sizes. The npy v1.0 header must be exactly
`{'descr': '<f4', 'fortran_order': False, 'shape': (480, 640, 2)}` with a
128-byte prefix. The payload is then written unchanged.

**Exclusions and missing values.** Masks, depth, RGB, segmentation and poses
are excluded. Any NaN or Inf would be fatal; none occur.

**Selection.** Selection is deterministic. In each archive the trajectories
are sorted, and slot k goes to trajectory index floor((2k+1)n/6). The temporal
middle frame of each chosen trajectory is taken. The realized list is pinned
in `selection.lock.tsv`, and both download and verify require an exact match.

## Accepted output

- Upstream population: 369 trajectories, 306,268 flow frames
  (4–37 trajectories per archive)
- Primary samples: 108, from 108 distinct trajectories
- Coverage: all 18 environments, 54 Easy and 54 Hard
- Primary values: 66,355,200
- Primary bytes: 265,420,800
- Sample size: 614,400 values (2,457,600 bytes) each
- Global value range: -326.0202 to 255.8156 px
- Per-frame mean |flow|: 1.67–54.75 px (median 7.56 Easy, 10.38 Hard)
- Download: 180 range requests, 281,125,039 bytes stored, 315 s

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Verify:** I reran `verify.sh` and it passed: 108 samples, 36 archives, 108
  trajectories, byte-exact against a one-shot re-inflate, and the selection
  matches the lock.
- **Bytes:** I inspected all 108 samples with `array`/`struct`.
  - Every file is 2,457,600 bytes.
  - Each frame has 596,849–612,580 distinct bit patterns out of 614,400 values.
  - The low 13 mantissa bits are zero in 0.0122% of values (about 1/8192), so
    this is genuine float32, not widened float16. The low-byte histogram is
    uniform over 256 values.
  - There are no zeros, NaN or Inf; the fields are spatially smooth; all 108
    sha256 hashes are unique.
- **Duplicates:** I parsed all 36 cached central directories.
  - The day/night (`abandonedfactory_night`), season (`seasonsforest_winter`)
    and `office2` variants have independent trajectories, with different frame
    counts and zero shared CRC32s.
  - The 10 CRC collisions among 306,268 members match the birthday expectation
    of about 10.9.
- **Index claims:** I confirmed the 54/54 Easy/Hard split, 18 environments,
  the Easy/Hard medians and the global range from the index and the stored
  bytes.
- **Rights:**
  - I read the CC BY 4.0 "Term of use" in the body of the saved project page.
  - I read `cardData.license = bsd-3-clause` with `gated = False` in the saved
    HF revision JSON.
  - I confirmed the official downloader's repo id with a small probe of
    `download_training.py`.
  - No credentials appear in any script.
- **Novelty:** `novelty.py` with the HF and project URLs and flow terms found
  no URL or downstream matches. The only registry hits are the Kubric attempts
  (different source, different failure grounds). No 32-bit flow or PIV family
  exists.
