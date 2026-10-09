# TUM-VIE Prophesee Gen4 event-camera pixel addresses uint16 development

## Outcome

Accepted `tumvie_prophesee_gen4_events_xy_u16`. It holds native uint16 per-event pixel addresses from the left Prophesee Gen4 HD (1280 × 720) event camera of the TUM-VIE stereo visual-inertial event dataset (Klenk, Chui, Demmel, Cremers, IROS 2021).

This is the first event-camera (DVS/CD sensor) material in the corpus at any width, locally or downstream. An event camera emits one `(x, y, t, p)` record whenever a pixel's log-brightness changes. The recipe keeps the two address fields as separate primary series:

- `tumvie_left_event_x_u16`: pixel column, 0–1279
- `tumvie_left_event_y_u16`: pixel row, 0–719, aligned event for event with x

The material differs from the other TUM CVG families in sensor and quantity:

- `tum_rgbd_depth_u16`: Kinect depth
- `tum_rgbd_groundtruth_pose_f64`: mocap poses
- `tumvi_euroc_1024_cam_frames_u16`: uEye grayscale frames

With this recipe there are four TUM CVG families, not the three the builder counted. The event files come from a separate host, `tumevent-vi.vision.in.tum.de`. The driver's archive-cap check applies to the declared hosts.

## Source and rights

- Dataset page: https://cvg.cit.tum.de/data/datasets/visual-inertial-event-dataset
- Files: `https://tumevent-vi.vision.in.tum.de/<seq>/<seq>-events_left.h5`
  - 21 non-calibration sequences
  - 1,215,913,150 to 17,868,884,571 bytes each, 168.7 GB in total
  - all Last-Modified 2021-07-30
  - pinned by size, strong ETag (sent as `If-Match`) and a per-window SHA-256 of the chunk address/size table in `sequences.tsv`
- License: the page states "All data in the TUM-VIE Dataset is licensed under a Creative Commons 4.0 Attribution License (CC BY 4.0) and the accompanying source code is licensed under a BSD-2-Clause License." `download.sh` re-fetches the page and requires that sentence plus links to all 21 pinned files.
- Access is anonymous HTTPS range requests. No credentials are used, and pixel addresses carry no personal data.

## Shape and conversion

- **Natural record.** Each natural record is one sequence's left-camera event stream, between 568,074,201 (mocap-6dof) and 8,437,678,295 (loop-floor0) events. That is far too large to collect whole.
- **Bounded subset (rule 7).** The recipe takes one fixed window per stream at the middle of the recording:
  - `start_chunk = ceil(n/32768)//2 − 64`
  - 128 whole HDF5 chunks = 4,194,304 consecutive events
  - x and y use identical event indices
  - no stream is tiled into several samples
- **Acquisition.** A pure-Python planner walks the file metadata with about 12 × 4 KiB byte ranges per file:
  - v0 superblock
  - symbol-table groups
  - v1 object headers (layout v3 chunked, Blosc filter 32001 with cd_values typesize 2, 65,536 bytes, byte shuffle, zstd)
  - only the type-1 chunk B-tree nodes covering the window

  Then 2–4 coalesced chunk spans are fetched per file.
- **Decode.**
  - Blosc1 header check: flags 0x91, typesize 2, nbytes 65,536, cbytes equal to the stored size.
  - Parse the bstarts table.
  - Per block: int32 csize plus one zstd frame, with the frame content size checked, decompressed by the `zstd` CLI (MPC precedent).
  - Byte unshuffle with typesize 2, then raw little-endian uint16 out.
  - No remapping, sorting or filtering.
- **Excluded:** right camera, calibration/IMU/vignette sequences, `events/t` (int64), `events/p` (uint8) and `ms_to_idx`.

## Accepted output

| Item | Value |
|---|---|
| Sequences | 21 |
| Primary samples | 42 (21 x, 21 y) |
| Values per sample | 4,194,304 (8,388,608 bytes) |
| Primary values | 176,160,768 |
| Primary bytes | 352,321,536 |
| Download | 167,310,129 bytes (dataset page + 1,060,864 metadata bytes + 165,705,694 chunk-span bytes) |
| Aggregate SHA-256 of sample SHA-256s | `f64e5f6fe31893d3c1aa19a273ac243029f9368c0a99a0a9ee814e5e1034ce75` |
| x range and distinct values | 0–1279, all 1280 present in 21/21 samples |
| y range and distinct values | 0–719, all 720 present in 21/21 samples |
| Top-value fraction | x 0.10–0.54%, y 0.17–0.50% (no fill) |
| zlsim, x series | own ratio 1.60; nearest `local:nasa_heasarc_batse_cont_counts_i16` at feature distance 0.0746 (loss 0.0265), not redundant; verdict OK |
| zlsim, y series | not measured: `zli train` timed out after 1800 s |

The y series is strongly structured: run-length structure with ratios several times higher than x, by zstd. Per policy, the recipe verdict needs only one non-redundant primary series.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **verify.sh:** I ran it myself and it passed in 37 s. It ran the self-test, re-derived the plans against `sequences.tsv`, re-decoded every window byte for byte, and matched the manifest counts. `build.sh` reads only cached range files; network I/O is curl-only in `download.sh`.
- **Independent decode:** a separate stdlib Blosc/zstd/unshuffle implementation (not the recipe's code) decoded the first, middle and last window chunk of x and y for mocap-shake, loop-floor3 and bike-night. All 18 matched the emitted samples. Chunk indices were contiguous and addresses monotonic.
- **Byte structure, all 42 samples:**
  - y moves in row-readout runs (mean run 2.6–4.8 events).
  - Within y-runs x ascends 80–89% of the time, versus 64–81% with y shifted by one chunk.
  - Hot pixels (527,36), (1080,319) and (1014,512) recur as the top pixel across many sequences, which confirms x/y alignment and one physical sensor.
  - Chunk-boundary |dy| is in line with |dy| inside chunks, so chunk ordering is correct.
  - All sample SHAs are distinct.
- **License:** I fetched the live dataset page. It shows the CC BY 4.0 sentence for all TUM-VIE data next to the event-file links, and 28 left-event links (21 pinned plus calibration).
- **Novelty:** `novelty.py` (URL and terms prophesee, tumvie, event camera, dvs, neuromorphic, event-based, dsec, mvsec) found no recipe, registry or downstream match. `--type/--instrument/--archive` found 0 matches. `--vocabulary` lists no event-camera type. The nearest conceptual analog is NICER X-ray per-photon detector addresses (u8).
- **Credentials:** a grep of all scripts for credentials and Python network libraries found nothing.
