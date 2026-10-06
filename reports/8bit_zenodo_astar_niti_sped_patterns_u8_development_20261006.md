# NanoMegas ASTAR SPED diffraction pattern uint8 development

## Outcome

`zenodo_astar_niti_sped_patterns_u8` is accepted. It holds raw 8-bit scanning precession electron diffraction (SPED) patterns. Each one is a 144x144 image of the TEM fluorescent screen, taken by the ASTAR external camera at one probe position of a 3–4 nm-step orientation map over NiTi shape-memory wire lamellae.

This family is distinct from the accepted `zenodo_nordif_ebsd_kikuchi_patterns_u8`:
- That recipe holds SEM backscatter Kikuchi band patterns.
- This one holds TEM transmission spot patterns: sparse Bragg reflections around a saturated direct beam on a dark background.

The two are the first and second 8-bit electron-diffraction families in this collection effort. Further 8-bit electron-diffraction candidates fall under the breadth rule.

## Source and rights

- Zenodo record 15183487 (Molnárová, Tyc, Klinger, Šittner 2024; DOI 10.5281/zenodo.15183487; article 10.1016/j.matchar.2024.114084). Blockfiles: Fig5, Fig6, Fig7, Fig8 and Fig S5.
- Zenodo record 15183021 (Tyc, Šittner 2024; article 10.1016/j.apmt.2024.102448). Blockfiles: Fig9, Fig10 and Fig11.
- License: both records declare `cc-by-4.0` with `access_right: open`, and both are the latest version. `download.sh` re-checks the title, licence, access, and the size and MD5 of every used `.blo` on each run.
- The 15183487 readme states "The .blo files are raw data from Astar mapping". The 15183021 readme lists them as "ASTAR data" for Figs 9–11.
- Pinned whole-file MD5s (sizes 430,836,206 to 963,309,016 bytes), header SHA-256s and 92 per-row SHA-256s.

## Shape and conversion

Each natural record is one diffraction pattern at one scan point.

NanoMegas blockfile layout, following the RosettaSciIO reader:
- a 4096-byte `IMGBLO` header (magic 258)
- an NX*NY uint8 virtual bright-field image
- NX*NY frames in (NY, NX) raster order, each a 6-byte prefix (u16 0x55AA, u32 frame index) followed by 20,736 uint8 pixels

For every scan, `DP_offset + NX*NY*20742` equals the Zenodo file size exactly.

How the recipe builds the output:
- `download.sh` range-fetches each header and every 16th scan row, with exact 206 and Content-Range checks.
- `build.sh` validates every frame marker and index, strips the prefix, and writes the pixels unchanged.
- There is no rescaling, background subtraction, centring or binning.
- The virtual bright-field image, the `.res` ACOM results and the PNG figures are not emitted.

The scans share one lab, setup (200 kV), material and detector geometry. Per-session camera settings vary and are documented rather than equalised:
- camera length: 77 mm on five scans, and 100, 145 and 265 mm on the others
- background level: median DN 2 (Fig9) to 51 (Fig8)
- precession angle: 0.5–0.7°

## Accepted output

- Scans: 8. Kept rows: 92 (stride 16). Upstream population: 226,341 patterns (4.69 GB).
- Samples by scan: Fig5 1,485, Fig6 1,896, Fig7 1,925, Fig8 1,911, FigS5 1,694, Fig9 1,520, Fig10 3,010, Fig11 1,340.
- Primary samples: 14,781.
- Values per sample: 20,736 (144x144 uint8).
- Primary values and bytes: 306,498,816.
- Range-fetched row bytes: 306,587,502, plus 8 × 4,096 header bytes.
- Value range 0..255 with all 256 codes used. Overall mean 23.75. 255 fraction 4.6e-4. Zero fraction 0.77%, nearly all in Fig9.
- Distinct values per pattern: 74 to 224. Constant patterns: 0. Byte-identical duplicates: 0.
- Aggregate SHA-256: `f6792033f01fb98b996caae1137f399c95f7996768066db827c102c35d95b974`

## Judge checks

- **Gate:** `gate.py` passed with no warnings (306,498,816 primary values, median 20,736, width 8).
- **Verify:** I re-ran `verify.sh` and it passed (11.4 s, same aggregate SHA-256).
- **Pins:** the recipe's `row_sha256.tsv` is identical to the driver-realized `.data/downloads/<id>/row_sha256.tsv`.
- **Local build:** `build.sh` reads only local downloads.
- **Licence:** I fetched both Zenodo API records and both readme files live. The licence is CC BY 4.0, access is open, the records are the last version, and file sizes and MD5s match the pins.
- **Header parse:** an independent struct parse of all 8 headers gives 200 kV, 3–4 nm steps, CL 77.0–264.8 mm, and acquisition dates 2023-10-19..2024-04-30, inside the readme's collection window.
- **Offset spot-check:** I recomputed 12 random frames from raw row bytes with my own offset arithmetic. Marker, index and pixel bytes all match the emitted samples.
- **Row width:** lag-144 autocorrelation exceeds lags 143 and 145 in all 24 sampled patterns, which confirms the 144-pixel row width.
- **Saturation:** the 255 pixels cluster at the detector centre (~72, 71), i.e. the direct beam.
- **Renders:** ASCII renders show genuine spot lattices.
- **Vacuum check:** a full pass over all 14,781 patterns found negligible vacuum-like frames (0.5% of Fig9, none elsewhere). Median off-centre bright-pixel counts are 271–3,953 per scan.
- **Near-duplicates:** adjacent patterns share a median of 13–35% identical pixels (70% in Fig9). Neighbour-conditioned zlib saves 4–7%, so these are not near-duplicates.
- **Histogram:** Fig6, Fig8 and FigS5 lack a few codes below their p01, which is consistent with an instrument-side brightness/contrast transfer. Above p01 every code is used, so the 8-bit width is honest.
- **Novelty:** `novelty.py` found no local, registry, ledger or downstream match. The ledger breadth check shows one prior 8-bit electron-diffraction acceptance (NORDIF).

## Documentation notes (non-blocking)

- The README and the manifest licence notes say both readmes call the `.blo` files "raw data from Astar mapping". Only the record 15183487 readme does.
- The README describes the values as "stored unprocessed". The low-tail code gaps above suggest instrument-side transfer settings. The recipe itself applies no processing.
