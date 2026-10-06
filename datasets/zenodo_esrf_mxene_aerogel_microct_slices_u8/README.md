# ESRF ID15 MXene aerogel micro-CT axial slices uint8

This recipe collects reconstructed synchrotron X-ray micro-tomography slices of
a freeze-cast lamellar Ti3C2Tx MXene aerogel. The data come from three Zenodo
uploads by Rawson, Bayram, McDonald, Yang, Courtois, Guo, Xu, Burnett, Barg
and Withers (2021): [4761663](https://doi.org/10.5281/zenodo.4761663),
[4764282](https://doi.org/10.5281/zenodo.4764282) and
[4766087](https://doi.org/10.5281/zenodo.4766087). They accompany the paper
"Tailoring lamellar MXene aerogel microstructure by compressive straining".
All three records are CC BY 4.0 with open access.

The deposit holds 11 volumes of **one aerogel specimen**, imaged at ESRF
beamline ID15 before compression and then after each 5% step of compressive
strain, up to 50%. Each volume is a headerless 8-bit raw stack with
1381 x 1381 x Z voxels of 3.1 µm. Each sample in this recipe is one complete
reconstructed axial slice: 1381 x 1381 uint8 values, 1,907,161 bytes.

## Natural record

The natural record here is the reconstructed axial slice
(`natural_record_kind = "reconstructed_axial_slice"`). It is not the whole
volume, for three reasons:

- ID15 is a synchrotron beamline with a (quasi-)parallel beam. Parallel-beam
  tomography reconstructs each axial slice independently, from its own
  sinogram (one detector row across all projection angles). The slice is the
  unit the reconstruction produces. The volume is a stack of such slices.
- In the published `.raw` layout (Fiji "Import > Raw": width 1381,
  height 1381, Z images, x fastest) every slice is one contiguous
  1,907,161-byte block. A slice is therefore a clean, typed 2-D image, not a
  cut through a serialized structure.
- The whole volumes are 3.37-6.02 GB each, so even one breaks the 1 GB cap.
  The recipe takes whole slices and never tiles or crops them. It does not
  use contiguous slabs either: slices are evenly spaced through each volume.

## Scope

Per volume of Z slices, the margin is m = ceil(0.05·Z). The recipe keeps 20
slices z_k = m + round_half_up(k·(Z−1−2m)/19), for k = 0..19.

| strain | record | file | Z | kept z | spacing |
|-------:|--------|------|--:|--------|--------:|
| 0%  | 4761663 | `00percent.raw` | 3155 | 158 … 2996 | 149-150 |
| 5%  | 4761663 | `05 percent.raw` (space; `%20` in the URL) | 3007 | 151 … 2855 | 142-143 |
| 10% | 4761663 | `10percent.raw` | 2841 | 143 … 2697 | 134-135 |
| 15% | 4761663 | `15percent.raw` | 2667 | 134 … 2532 | 126-127 |
| 20% | 4764282 | `20percent.raw` | 2520 | 126 … 2393 | 119-120 |
| 25% | 4764282 | `25percent.raw` | 2400 | 120 … 2279 | 113-114 |
| 30% | 4764282 | `30percent.raw` | 2239 | 112 … 2126 | 106 |
| 35% | 4764282 | `35percent.raw` | 2081 | 105 … 1975 | 98-99 |
| 40% | 4766087 | `40percent.raw` | 1909 | 96 … 1812 | 90-91 |
| 45% | 4766087 | `45percent.raw` | 1768 | 89 … 1678 | 83-84 |
| 50% | 4766087 | `50percent.raw` | 1769 | 89 … 1679 | 83-84 |

That gives 220 samples and 419,575,420 bytes of primary output, with a
download of about 420 MB. The full lists of kept z are printed by
`download.sh` and recorded in `filtered/<id>/ingest_stats.json`. Neighbouring
kept slices are 0.26-0.47 mm apart, so no two samples are near-duplicates.
They still sample the lamellar microstructure through the full height of
each strain state.

**Why the 5% end margin.** Cheap multi-range probes took three rows per
slice, every 1-2% of Z, in all 11 volumes. Interior slices have a mean grey
level of about 85-90 everywhere. Within the last 1-3% of every volume the
mean rises to 101-113, and z = 0 reads 92-106 in 10 of the 11 volumes. The
final slice of the 50% volume (z = 1768) is a uniform disc with concentric
ring artefacts and no aerogel texture, most likely the compression platen or
the edge of the reconstructed region. A 5% margin excludes all of these
zones with room to spare. The slice-mean rule below ([72, 104]) is a coarse
second guard that catches only the strongest of them.

**What the scope is, honestly.** This is one physical specimen, at 11 strain
states, from one beamline and one protocol. The microstructure evolves with
strain: lamellae buckle and densify, and Z shrinks from 3155 to about 1769
slices. Slices also come from different heights. Even so, all samples share
one material and one specimen, so the content is correlated. The 45% and
50% volumes have almost the same Z (1768 vs 1769) but are independent scans.
A probe of the same row at the same z differed by a mean absolute 30 grey
levels, and only about 1% of values matched.

## Format and conversion

Each `.txt` descriptor is a free-form ASCII note, for example
`lattice info: 1381 x 1381 x 3155 voxels / 8 bit / little endian /
voxel size: 3.1 x 3.1 x 3.1 microns`. The wording varies between files.
`05percent.txt` belongs to `05 percent.raw`. All 11 declare 1381 x 1381 x Z,
8 bit, little endian and 3.1 µm. Every pinned `.raw` size equals 1381²·Z
exactly. The recipe pins the record/file map, sizes, MD5s and descriptor
SHA-256s in `volumes.tsv`.

Slice z is the byte range `[z·1907161, (z+1)·1907161)`. `download.sh` fetches
each kept slice with one HTTP Range request. `build.sh` writes the bytes
unchanged to
`samples/<id>/mxene_aerogel_microct_slice_u8/strainNNpct_zZZZZ.bin`, as row
major [y][x] with x fastest. 8-bit values need no byte-order handling.

**Grey levels are source-native.** The authors chose the 8-bit windowing of
each reconstruction themselves and did not publish the mapping to
attenuation coefficient. The windowing may differ slightly between strain
states. Interior slice means are about 86 at 0% and about 88 at 50%. The
recipe does **not** rescale, re-window, crop, mask or filter. Values 0 and
255 are the clipped extremes of the authors' windowing and are kept.

Every slice shows a faint circle. It marks the edge of the reconstructed
field of view (the specimen is wider than the detector field). Lamellar
texture continues outside the circle to the square edges, with no zero
padding. The full published 1381 x 1381 square is emitted.

## Integrity

- `download.sh` re-fetches the three record JSONs. It checks the exact
  titles, `cc-by-4.0`, open access, the ESRF ID15 description, and the size
  and MD5 of every used `.raw` and `.txt` file. It pins the descriptors by
  size, MD5 and SHA-256 and re-parses their lattice, bit depth, byte order
  and voxel size.
- Each slice request must end in HTTP 206 with the exact
  `Content-Range: bytes start-end/<pinned .raw size>` and exactly 1,907,161
  bytes. A failed slice is discarded and re-requested, because `curl -C -`
  does not compose with `--range`. curl uses `--retry` and stall-based
  `--speed-limit/--speed-time`, and download.sh pauses 0.6 s between
  requests. Zenodo's guest limit is about 133 requests per minute, and curl
  honours `Retry-After` on 429.
- Degeneracy rules, identical in download, build and verify:
  - at least 64 distinct values
  - modal value at most 10% of voxels
  - no constant voxel row or column
  - slice mean within [72, 104]
  - no duplicate payloads
- The whole-file MD5s cannot check byte ranges. Per-slice SHA-256 values are
  therefore pinned in `slice_sha256.tsv` in this recipe. They were taken from
  the first driver-run download on 2026-10-06: 420,102,892 bytes in 510 s,
  and every slice answered 206 with the exact Content-Range on its first
  attempt. `download.sh` enforces the pins when the file exists and always
  writes realized values to `downloads/<id>/slice_sha256.tsv`. `build.sh` and
  `verify.sh` check every slice against the pins, and `verify.sh` fails if
  they are missing. `verify.sh` also pins the SHA-256 of the
  `<sample name>\t<sha256>` listing in index order:
  `eff23b6f7a8b4102e9ccea6c767e81e1273477d89bc17080c641acb20bbbe0d3`.
- `verify.sh` shares no code with build or download. It:
  - re-parses the descriptors
  - re-derives the slice plan with exact fractions
  - byte-compares every sample with its downloaded slice
  - recomputes every index field and statistic
  - checks that the sample directory holds exactly the planned files
  - checks the manifest totals

Self-tests run under `/tmp` before the first real download:
- `check_slice.py` accepted a real probe slice (00% z = 1577). It rejected
  the 50% end slice (mean 109.9), a wrong Content-Range total, a 200
  response, a short payload, a synthetic constant row and column, and a
  wrong pin.
- `download.sh` ran end-to-end against an offline curl stub. It produced the
  same 220-slice plan as the Python code and recovered from an injected
  truncated response.
- build and verify passed on that synthetic tree. verify rejected a tampered
  sample, an extra file, a wrong manifest count, and missing or incomplete
  pins.

## Novelty

`tools/autocollect/novelty.py` found no match for the source URLs or for
MXene, aerogel, ESRF or synchrotron in local recipes, the registry, the
ledger or the downstream corpus. No family of reconstructed X-ray CT or
tomography exists at 8 bits.
- The nearest 8-bit volumetric family is `empiar_13192_sbfsem_vessel_slices_u8`.
  It is serial block-face SEM backscatter imaging of resin-embedded tissue: a
  different physics, contrast mechanism and material.
- Tomography elsewhere in the corpus sits at other widths and stages:
  - LoDoPaB simulated sinograms (f32)
  - IMAT neutron projections (f32)
  - TEM tilt series (i16)
  - TCIA clinical CT in Hounsfield units (i16)

## Realized output

Built and verified on 2026-10-06 from the driver-run download.

- Output: 220 samples in one primary series, `mxene_aerogel_microct_slice_u8`.
  Each is a 1381 x 1381 uint8 slice of 1,907,161 values. The total is
  419,575,420 bytes, and the median sample is 1,907,161 values.
- Values span the full range 0..255. The overall mean is 86.99. About
  1.27e-5 of values are 0 and 7.18e-5 are 255.
- Every slice has 245-256 distinct values. Shannon entropy is 6.14-6.71
  bits per value (median 6.46). zlib level 6 compresses a slice to 0.78-0.84
  of its size, measured on every 4th sample.
- All 220 payloads are distinct.

Slice-mean ranges per strain state:

| strain | slice-mean range |
|-------:|------------------|
| 0%  | 85.84-86.34 |
| 5%  | 85.91-86.45 |
| 10% | 85.99-86.58 |
| 15% | 86.10-87.33 |
| 20% | 86.18-87.24 |
| 25% | 86.28-87.96 |
| 30% | 86.45-87.93 |
| 35% | 86.73-87.99 |
| 40% | 87.07-88.41 |
| 45% | 87.67-88.57 |
| 50% | 87.14-88.44 |

The mean drifts up slightly as the aerogel densifies under strain, and no
kept slice comes near the [72, 104] guard. Visual checks found lamellar
aerogel interior with no platen or end-zone content. The checked slices were
the outermost kept ones (0% z = 158, 50% z = 89 and z = 1679) and a middle
one (25% z = 1143). The 50% slices show buckled, denser lamellae than the
0% ones.
