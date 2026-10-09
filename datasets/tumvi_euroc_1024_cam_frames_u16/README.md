# tumvi_euroc_1024_cam_frames_u16

Native 16-bit grayscale camera frames from the
[TUM VI visual-inertial benchmark](https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset)
(Schubert et al., IROS 2018), EuRoC export at 1024x1024
(`https://vision.in.tum.de/tumvi/exported/euroc/1024_16/`).

- **Content:** right camera (`mav0/cam1`) of the stereo IDS uEye global-shutter
  fisheye rig, 20 Hz, linear response. 8 frames from each of the 28 sequences
  (room1-6, corridor1-5, slides1-3, magistrale1-6, outdoors1-8), so 224 frames
  of 1024x1024 uint16 each (469,762,048 bytes).
- **Representation:** the PNGs carry 12-bit sensor codes MSB-aligned in 16
  bits, so every value is a multiple of 16 (realized range 0..65520). Values
  are kept exactly as published.
- **License:** CC BY 4.0. The dataset page says: "All data in the Visual
  Inertial Dataset is licensed under a Creative Commons 4.0 Attribution License
  (CC BY 4.0)". `download.sh` re-checks this sentence.

## How the subset is chosen

The sequence tars are 3.4-61 GB each and uncompressed. Their member order is
not chronological, so the first cam1 members of each tar are spread across the
whole recording: 53-1126 s spans between the earliest and latest pinned
timestamps. Two pairs, in room2 and room4, are only 0.1 s apart.
`discover.py` walked each tar's headers with small range reads and pinned the
first 8 cam1 PNG members (name, offset, size, last IDAT CRC) into
`scripts/members.tsv`. The prefix of each tar up to the end of its 8th member
holds only 4 directory headers and those 8 PNGs.

## Scripts

- `download.sh`: checks the license, then fetches the 28 prefixes (about
  206 MB, using range GETs that resume by requesting only the missing bytes),
  validates the members against the pin, and checks each prefix against
  the SHA-256 pinned in `scripts/prefix_sha256.tsv`.
- `build.sh`: walks each tar and decodes the 16-bit PNG (pure stdlib: zlib plus
  all 5 filters, big-endian to little-endian). It asserts the IHDR
  (1024x1024, 16-bit, gray, non-interlaced) and the zero low nibble. It skips
  constant frames and frames where one value covers more than 50% of pixels,
  then writes `samples/<id>/tumvi_cam1_intensity_u16/<seq>_cam1_<ns>.bin`.
- `verify.sh`: re-decodes every pinned member, then byte-compares it with the
  sample and checks the index fields, the skip list and the manifest scope.
- `scripts/selftest.py`: synthetic PNGs that cycle filter types 0-4,
  rejection paths, and the tar prefix walk.

## Realized build (2026-10-08)

224 frames from 28 sequences, 469,762,048 bytes, none skipped. In 202
frames the most frequent value is saturation (65520), covering at most 18.3%
of a frame (outdoors7). Per-frame minima run from 0 to 1152.
