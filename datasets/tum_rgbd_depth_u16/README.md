# TUM RGB-D Depth Frames (uint16)

Collects native 16-bit **depth-sensor frames** from the
[TUM RGB-D benchmark](https://cvg.cit.tum.de/data/datasets/rgbd-dataset). Each
depth frame is a 640×480 `uint16` raster where the pixel value is the depth
camera's raw range reading (TUM scale factor 5000: `metres = pixel / 5000`);
`0` marks pixels with no valid return.

This is a genuinely new modality for the corpus — **range sensing** — distinct
from reflectance, radiodensity, or elevation rasters. The natural record is one
depth frame → **one sample per frame**, so a sequence yields a real multi-sample
family (hundreds of frames).

## Usage

```bash
datasets/tum_rgbd_depth_u16/download.sh
datasets/tum_rgbd_depth_u16/build.sh
datasets/tum_rgbd_depth_u16/verify.sh
```

The downloader fetches a bounded set of per-sequence `.tgz` archives (default
`freiburg1_xyz`) from the TUM host (falls back across `cvg.cit.tum.de` /
`vision.in.tum.de`). Archives contain both `rgb/` and `depth/`; only the 16-bit
`depth/*.png` frames are used. The build extracts a capped number of frames.

Tunables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `TUM_SEQUENCES` | `freiburg1_xyz` | Space list of sequence names (e.g. `freiburg1_xyz freiburg2_desk`) |
| `TUM_TGZ_URLS` | — | Explicit `.tgz` URL list (overrides sequence resolution) |
| `TUM_MAX_FRAMES` | `400` | Cap on depth frames collected (keeps primary output bounded) |
| `TUM_MIN_FRAMES` | `50` | Minimum frames for the build to succeed |

## Decoding (no external tools)

Pure-python, stdlib only: depth PNGs are 16-bit grayscale, decoded with `zlib`
plus PNG scanline unfiltering (None/Sub/Up/Average/Paeth), then written as raw
little-endian `uint16` (PNG stores samples big-endian). No RGB, poses, or
timestamps are extracted.
