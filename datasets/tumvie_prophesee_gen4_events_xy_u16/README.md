# TUM-VIE Prophesee Gen4 HD event-camera pixel addresses (x, y) uint16, left camera

This recipe collects per-event pixel coordinates from an event camera (DVS/CD
sensor). The source is the left Prophesee Gen4 HD camera (1280 × 720) of the
TUM-VIE stereo visual-inertial event dataset (Klenk, Chui, Demmel, Cremers,
IROS 2021). An event camera does not output frames. It emits one event
`(x, y, t, p)` whenever a pixel's log-brightness changes by more than a
threshold. TUM-VIE stores each camera stream as HDF5 datasets
`events/{x,y,t,p}` (DSEC layout). `x` and `y` are native `uint16`.

There are two primary series:

- `tumvie_left_event_x_u16`: the pixel column of each event, 0–1279.
- `tumvie_left_event_y_u16`: the pixel row of each event, 0–719. It covers the
  same events as the x series, element for element.

Each sample is a window of **4,194,304 consecutive events** (128 whole HDF5
chunks of 32,768) from one sequence's left-camera stream. The recipe takes
one window per sequence from each of the 21 non-calibration sequences. That
gives 42 samples of 8,388,608 bytes, or 352,321,536 bytes of primary output.

## Source and rights

- Dataset page: <https://cvg.cit.tum.de/data/datasets/visual-inertial-event-dataset>
- Files: `https://tumevent-vi.vision.in.tum.de/<seq>/<seq>-events_left.h5`
  (Apache, `Accept-Ranges: bytes`, strong ETags, `If-Match` honoured; all
  files last modified 2021-07-30).
- License: the page states *"All data in the TUM-VIE Dataset is licensed
  under a Creative Commons 4.0 Attribution License (CC BY 4.0) and the
  accompanying source code is licensed under a BSD-2-Clause License."*
  `download.sh` re-fetches the page and fails if that sentence, or a link to
  any pinned file, is missing.
- Cite: S. Klenk, J. Chui, N. Demmel, D. Cremers, *TUM-VIE: The TUM Stereo
  Visual-Inertial Event Dataset*, IROS 2021 (arXiv:2108.07329).

## Why a bounded window (rule 7)

The 21 left-camera streams hold 0.57–8.4 billion events each, 168.7 GB of
compressed HDF5 in total. Whole streams cannot be collected under the 1 GB
cap. The recipe takes one contiguous window per stream at a fixed position
(the middle of the stream):

```
n_chunks    = ceil(n_events / 32768)
start_chunk = n_chunks // 2 - 64
window      = chunks [start_chunk, start_chunk + 128)
            = events [32768 * start_chunk, 32768 * (start_chunk + 128))
```

This is one window per stream, not a tiling: no stream is cut into several
samples. The middle avoids the start and end of each recording, where the rig
is often static near the motion-capture area. x and y always use the same
chunk indices, so every x sample lines up event-for-event with its y sample.
At 15–27 M events/s a window covers roughly 0.15–0.3 s of motion. The
per-sequence values (event count, start chunk, stored bytes, SHA-256 of the
chunk address/size table) are pinned in `sequences.tsv`, which `discover.sh`
re-derives from the live server.

Excluded:

- the right camera, to keep one sensor instance; the right camera could be a
  later extension;
- the calibration, IMU-calibration and vignette sequences;
- timestamps (`events/t`, int64, another width);
- polarity (`events/p`, uint8);
- `ms_to_idx`.

## Sequences

mocap-1d-trans, mocap-3d-trans, mocap-6dof, mocap-desk, mocap-desk2,
mocap-shake, mocap-shake2, office-maze, running-easy, running-hard,
skate-easy, skate-hard, loop-floor0, loop-floor1, loop-floor2, loop-floor3,
floor2-dark, bike-easy, bike-hard, bike-night, slide.

The scenes vary: a motion-capture room, desks, offices and corridors,
handheld and head-mounted running, skating, biking (including at night), a
dark floor and a slide. The sensor model, resolution, HDF5 layout and Blosc
settings are identical in every file. download, build and verify check this
per file.

## Acquisition and decode (pure Python stdlib + `zstd` CLI)

Whole files are never downloaded. For each sequence:

1. **Metadata walk.** `scripts/tumvie_events.py plan` parses whatever 4 KiB
   ranges are cached and reports the next range it needs as
   `NEED <offset> <length>`. `download.sh` fetches that range with curl, and
   the loop repeats about 12 times per file. The walk covers:
   - the superblock (v0);
   - the root and `events` symbol-table groups (TREE type 0 / HEAP / SNOD);
   - the `events/x` and `events/y` object headers (v1): dataspace, datatype,
     layout v3 chunked with dims (32768, 2), and filter pipeline = Blosc 32001
     with cd_values (2, 2, 2, 65536, 1, 1, 5), i.e. typesize 2, 64 KiB chunks,
     byte shuffle, zstd;
   - the v1 type-1 chunk B-trees, of which only the nodes covering the window
     are visited.

   Python never opens a network connection.
2. **Pin check.** The re-derived window must match `sequences.tsv`: event
   count, start chunk, and stored bytes plus the SHA-256 of the
   `(chunk index, address, size)` table for both x and y.
3. **Chunk spans.** The window's chunks for each dataset are nearly
   contiguous in the file (B-tree nodes sit between them), so they are
   fetched as 2–4 coalesced spans per file (gap ≤ 64 KiB).
4. **Blosc1 decode.**
   - Parse the 16-byte header (flags 0x91 = byte shuffle + DONT_SPLIT + ZSTD,
     typesize 2, nbytes 65,536, blocksize 32,768) and the `bstarts` table.
   - Each block is an int32 csize followed by one zstd frame (content size
     checked), decompressed with the `zstd` CLI. A block whose csize equals
     its block size is copied as stored. Memcpyed buffers are handled.
   - Byte-unshuffle with typesize 2 and check `nbytes`.
5. **Value checks.** Every chunk must have x ≤ 1279 and y ≤ 719. Each window
   needs at least 256 distinct x values (128 for y), and no single value may
   hold more than 25% of the window.

Every range request carries `If-Match: "<pinned ETag>"` and must answer 206
with the exact `Content-Range`. `scripts/selftest.py` runs before any decode.
It checks five synthetic Blosc variants and a synthetic two-level type-1
B-tree.

Expected transfer is about 167 MB:

- 1,060,864 bytes of metadata ranges;
- 165,705,694 bytes of chunk spans;
- the 0.23 MB dataset page.

## Outputs

- `samples/tumvie_prophesee_gen4_events_xy_u16/tumvie_left_event_x_u16/<seq>.u16`
- `samples/tumvie_prophesee_gen4_events_xy_u16/tumvie_left_event_y_u16/<seq>.u16`
- `index/tumvie_prophesee_gen4_events_xy_u16/samples.jsonl`: the required
  fields plus sequence, source URL, event index range, start chunk, stream
  length, min/max, distinct count, top-value fraction and SHA-256.
- `filtered/tumvie_prophesee_gen4_events_xy_u16/ingest_stats.json`

`verify.sh` re-resolves every window from the cached metadata, re-decodes
it, and compares it byte-for-byte with the samples. It then recomputes
ranges, distinct counts and SHA-256, rejects constant or duplicate samples,
checks that x and y cover the same event range, and matches the manifest
sample counts and sizes against the realized output.

## Character of the material

In the authoring probe (mocap-shake window), y holds near-constant runs that
drift slowly, because the sensor reads out rows. x jumps within each row
group, often in ascending runs. Raw 8 MiB windows compress to about 5.0 MB
(x) and 0.55 MB (y) with `zstd -19`. These are genuine sensor addresses with
a distinctive structure: no existing corpus family holds event-camera data.

## Commands

```bash
bash staging/tumvie_prophesee_gen4_events_xy_u16/download.sh
bash staging/tumvie_prophesee_gen4_events_xy_u16/build.sh
bash staging/tumvie_prophesee_gen4_events_xy_u16/verify.sh
# optional: re-derive sequences.tsv (metadata ranges only)
DATA_DIR=/tmp/tumvie_discover bash staging/tumvie_prophesee_gen4_events_xy_u16/discover.sh
```
