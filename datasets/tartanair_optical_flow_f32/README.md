# TartanAir V1 Dense Optical-Flow Fields (float32)

Dense forward optical flow from the CMU AirLab **TartanAir V1** visual-SLAM
simulation dataset. Each sample is one complete flow frame: the left-camera
image-plane displacement from frame N to frame N+1 of a trajectory, a
480 x 640 x 2 little-endian float32 tensor (614,400 values, 2,457,600 bytes)
in pixels.

- Source: <https://huggingface.co/datasets/theairlabcmu/tartanair>, pinned to
  revision `65e00180ea952475878a748543e11e9ec20beaac`. This is the repository
  the official `castacks/tartanair_tools` downloader uses
  (`repo_id = "theairlabcmu/tartanair"`).
- Project page: <https://theairlab.org/tartanair-dataset/>
- Data-type documentation:
  <https://github.com/castacks/tartanair_tools/blob/master/data_type.md>
  ("The optical flow maps are saved as a float32 numpy array, which is
  calculated based on the ground truth depth and ground truth camera motion").

## License

- Project page, "Term of use": "This work is licensed under a Creative Commons
  Attribution 4.0 International License." (links to CC BY 4.0).
- Hugging Face dataset card front matter at the pinned revision:
  `license: bsd-3-clause`.

Both licenses are permissive. The recipe follows CC BY 4.0 attribution: cite
Wang et al., "TartanAir: A Dataset to Push the Limits of Visual SLAM",
IROS 2020 (arXiv:2003.14338). `download.sh` fails if the HF card license
changes, and logs whether the CC BY 4.0 notice is still on the project page.

## What is collected

The release ships flow as 36 ZIP64 archives `<env>/<Easy|Hard>/flow_flow.zip`
(18 environments x 2 motion-difficulty levels, 4.4-63.4 GB each, 676.8 GB
total). Each archive holds `Pxxx/flow/NNNNNN_MMMMMM_flow.npy` members, one per
consecutive frame pair. `sources.tsv` pins all 36 archives with their size,
LFS sha256 and xet hash (regenerate with `discover.sh`).

Selection is deterministic (`select_members` in `scripts/tartanair_flow.py`).
In each archive the trajectories are sorted, three evenly spread ones are
chosen (index `floor((2k+1) n / 6)`, k = 0..2), and the temporal middle frame
of each is taken. That gives **108 frames from 108 different trajectories**,
covering every environment and both difficulty levels, with no temporally
adjacent near-duplicates. Upstream holds 369 trajectories (4-37 per archive)
and 306,268 flow frames, so the subset is one frame from each of 29% of all
trajectories. If an archive had fewer than three trajectories, its slots would
be spread over evenly spaced frames within them; none does. The realized
member list is pinned in `selection.lock.tsv`.

Realized output: 108 samples, 66,355,200 float32 values, 265,420,800 bytes;
median per-frame mean |flow| is 7.6 px (Easy) and 10.4 px (Hard). Per-frame
means range from 1.67 to 54.75 px, and all values lie between -326.0 and
255.8 px. No non-finite values were found.

## How the download stays bounded

No archive is fetched whole. `download.sh` uses curl byte ranges only:

1. HF API: revision metadata (identity, public/ungated, card license) and the
   pinned tree listing (every `sources.tsv` row must match).
2. For each archive, the last 65,536 bytes, parsed for the classic EOCD,
   ZIP64 locator and ZIP64 EOCD record.
3. The exact central-directory range (0.24-3.8 MB per archive), parsed with
   ZIP64 `0x0001` extras. Sizes and offsets are present there only when the
   32-bit field is `0xFFFFFFFF`.
4. For each selected member, the exact span from its local header to the next
   entry's local header. The local extra field differs from the central one,
   so it is never guessed. The span is raw-inflated (wbits -15) and checked
   against the CD CRC32 and the `.npy` header. Non-finite or constant frames
   are rejected.

Each range request goes through the HF resolver (302 to a signed xet CDN
URL). The redirect must carry `x-repo-commit` equal to the pinned revision and
`x-linked-etag` equal to the archive's pinned LFS sha256. The final response
must be `206` with the exact `Content-Range` (including the archive size).
Pieces are cached and validated, so re-runs fetch only missing or invalid
pieces. There are about 180 range requests in total, well below the
anonymous resolver limit of 3000 per 5 minutes. Expected traffic is about
282 MB: 39,552,939 bytes of central directories (307,816 entries; all 36
tails were probed and parsed while authoring), 2,359,296 bytes of tails, and
roughly 240 MB of member spans.

After a successful run, `downloads/<id>/selection.tsv` records the realized
members (offset, span, sizes, CRC32). It must match the committed
`selection.lock.tsv` exactly; both `download.sh` and `verify.sh` check this.
The driver run on 2026-10-06 made 180 range requests and stored 281,125,039
bytes under `downloads/` in 315 s.

## Conversion

`build.sh` re-derives the selection from the cached tails and central
directories, checks that it matches `selection.tsv`, and inflates each span.
It checks CRC32 and the npy v1.0 header, which must be exactly
`{'descr': '<f4', 'fortran_order': False, 'shape': (480, 640, 2)}` with a
128-byte prefix. It then writes the remaining 2,457,600 bytes unchanged to
`samples/tartanair_optical_flow_f32/tartanair_left_optical_flow_uv_f32/<env>__<Easy|Hard>__<Pxxx>__<NNNNNN>_<MMMMMM>.f32`.
Axes are (image_row, image_column, flow_component), in C order.

`verify.sh` independently repeats the selection from the central directories
and re-inflates every member with a one-shot decoder. It byte-compares every
sample, recomputes the index min/max from the stored float32 values, and
re-checks finiteness through the float32 exponent bits. It rejects constant
components, low-diversity frames and duplicate payloads, and checks
`sample_count` / `total_size_bytes` against this manifest.

Missing values: TartanAir flow has no sentinel. Any NaN or infinity is fatal.
Occluded and dynamic-object pixels keep their upstream geometric flow, and the
uint8 `*_mask.npy` members are neither applied nor emitted.

## Caveats

- **Synthetic material.** The flow is simulator ground truth (Unreal Engine +
  AirSim), computed by the dataset authors from rendered depth and camera pose
  and published as float32 arrays. It is an upstream artifact, not a local
  numericization, but it is not measured optical flow.
- **One regime, varying magnitude.** Every frame comes from the same camera
  model (640 x 480, fx = fy = 320), the same flow pipeline and the same unit
  (pixels). Environments change scene content, and the Hard level has more
  aggressive motion, so displacement magnitudes vary between frames.
- Only the left-camera flow exists upstream. Depth, RGB, segmentation, poses
  and masks are not collected.

## Running

```bash
bash staging/tartanair_optical_flow_f32/download.sh   # ~282 MB of range requests
bash staging/tartanair_optical_flow_f32/build.sh
bash staging/tartanair_optical_flow_f32/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/tartanair_optical_flow_f32/`.
