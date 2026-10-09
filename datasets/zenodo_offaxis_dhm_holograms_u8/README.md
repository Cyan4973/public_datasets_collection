# zenodo_offaxis_dhm_holograms_u8

Raw 8-bit off-axis digital holograms (2048x2048 camera frames carrying an
off-axis carrier-fringe pattern) from one custom off-axis common-path digital
holographic microscope at 405 nm illumination, imaging unresolved
nanoparticles, beads and lipid vesicles.

## Instrument (sourced statements)

- Associated article (the record's `isCitedBy`): Johnston, Dubay, Serabyn and
  Nadeau 2024, *Applied Optics* 63(7):B114, doi:10.1364/AO.507375. Its
  Methods 2.A describes:
  - a custom off-axis common-path DHM (design of Wallace et al. 2015,
    *Opt. Express* 23:17367);
  - a Thorlabs MCLS-1 fibre-coupled diode laser at 405 or 520 nm;
  - an Allied Vision Prosilica GT2450 camera (3.45 um pixels, well depth 6500);
  - all frames 2048x2048;
  - acquisition software DHMx.
- The deposit README instead says the data were acquired with the software
  KOALA (LynceeTec). Both statements are recorded here as they appear in their
  sources. The microscope itself is not a Lyncee Tec instrument.
- The "same camera" claim below rests on the article.

## Carrier geometry by session

The off-axis carrier is not the same in every video. The instrument and camera
are the same, but the optics were realigned between sessions:

| Session | Videos / samples | Fringes | Neighbour stats |
|---|---|---|---|
| 2022.06.09 | 4 / 24 | near-vertical, horizontal period about 2.8 px | rho(dy=1,dx=0)=0.98; mean abs diff about 8-10 DN vertically vs 83-101 DN horizontally |
| 2022.07.27, 2022.08.02 | 10 / 60 | diagonal, about 4 px period on both axes | rho(1,1)=0.98-0.99; mean abs diff 55-66 DN on both axes |
| 2022.10.05, 2022.10.17 | 3 / 18 | a different diagonal carrier | rho(3,-1)=0.95-0.98; mean abs diff about 60-67 DN (about 26-29 for PolystyreneFlat) |

- Source: Zenodo record [10632465](https://zenodo.org/records/10632465)
  ("Detectability of unresolved particles in off-axis digital holographic
  microscopy", Dryad mirror doi:10.5061/dryad.9cnp5hqr7)
- License: CC0-1.0 (Zenodo metadata `license.id = cc-zero`, re-checked by
  `download.sh`)
- Output: 102 samples x 4,194,304 uint8 = 427,819,008 bytes, one sample per
  hologram frame, series `dhm_offaxis_hologram_u8`

## Scope and selection

The record has 18 zips, one DHM video each (~7 fps, 106-315 frames). The README
says illumination is 405 nm unless specified to be 520 nm; the only 520 nm video
(`2022.08.02_14-37_AuFlat520.zip`) is excluded because it uses a different
laser line: the 520 nm channel of the Thorlabs MCLS-1 (the paper reports a
different coherence envelope at 520 nm). The family is restricted to 405 nm
illumination. The 405 nm videos do not share a single fringe period (see the
table above). All other 17 videos are used: alumina 30/100/300 nm, 50 nm
gold, 1 um polystyrene beads (water, immersion oil), and 100 nm, 200 nm and
unextruded lipid vesicles, with and without corrole dye, in flat slides and 0.8 mm chambers.
All of them come from the same microscope and camera (per the article), with
the same 2048x2048 8-bit TIFF format. The acquisition software is KOALA per the
deposit README and DHMx per the article.

From each video of N frames, frames `floor((2k+1)*N/12)`, k = 0..5, are kept:
evenly spaced, never contiguous (17-52 frames apart), because consecutive
frames of the mostly static scenes are near-duplicates.

## Pipeline

- `discover.sh` (metadata only, ~2 MB) lists the record, reads every zip's
  central directory from its tail, and writes `videos.tsv` (zip size, MD5,
  central-directory offset/size, frame count) and `selected_frames.tsv` (per
  member: name, CRC32, sizes, local-header offset, next-entry offset). Both
  are committed pins.
- `download.sh` re-validates the record (CC0, sizes, MD5s) and README (MD5,
  wavelength statement), re-reads each central directory by exact range and
  checks the pins, then fetches each selected member as exactly
  `[local header offset, next entry offset)` (~5.2 MB each, ~532 MB total). It
  rejects ZIP64, multi-disk archives, and non deflate/stored or encrypted members,
  requires HTTP 206 with the exact Content-Range, inflates and checks CRC32 and
  size, and checks the TIFF IFD (2048x2048, 8 bps, spp 1, LZW, predictor 2,
  BlackIsZero, single IFD). It keeps only the validated TIFFs (571,309,612 bytes).
- `build.sh` runs `scripts/selftest_tiff.py` (synthetic 2048x2048 LZW/predictor
  TIFF round trip, table overflow and clear codes, KwKwK, legacy EOI width,
  layout rejections, corruption), then `scripts/dhm_build.py` decodes each
  TIFF with `scripts/dhm_tiff.py` and writes raw samples plus
  `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
- `verify.sh` (`scripts/dhm_verify.py`) re-decodes every TIFF with an
  independently written decoder and byte-compares each sample. It also checks
  the selection rule, index fields, sha256s, per-frame stats, duplicates,
  degeneracy and manifest totals.

## Decoder note

A few strips in some frames end with the EOI code written at the code width
in effect *before* the final table-size increment (the old libtiff
LZWPostEncode behaviour). The decoder accepts that EOI only in exactly this
situation: the output strip is complete and the width was bumped on the last
data code. Each strip must also produce exactly `rows*2048` bytes and leave at
most one padding byte. The count of such strips is recorded per sample
(`legacy_eoi_strips`). They occur only in the June and October 2022 sessions,
which fits a different TIFF writer version there. They do not affect pixel
values.

## Realized output (2026-10-08)

102 samples, 427,819,008 bytes. verify.sh independently re-decoded all 102.
155 of the 52,224 strips use the legacy EOI width; they occur only in the
2022.06.09 and 2022.10 videos.
Per-video frame means are about 88-117 DN; see the carrier-geometry table
for neighbour statistics. One video, 2022.10.05_16-02_PolystyreneFlat, was
recorded at lower exposure: frame mean 42.7 DN, max 148-163, order-0 entropy
6.32 bits, against 7.33-7.77 bits for the other videos. It is kept as the
same quantity on the same instrument. The 2022.06.09 vesicle videos saturate
up to 0.9% of pixels at 255; all others stay below 0.01%.

## Not emitted

timestamps.txt (auxiliary, left out), phase/amplitude reconstructions (none
in the deposit), `__MACOSX`/`.DS_Store` entries.

## Run

```bash
bash staging/zenodo_offaxis_dhm_holograms_u8/download.sh   # ~572 MB, range requests
bash staging/zenodo_offaxis_dhm_holograms_u8/build.sh      # ~4-5 min pure Python
bash staging/zenodo_offaxis_dhm_holograms_u8/verify.sh     # ~7 min pure Python
```
