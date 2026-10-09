# Off-axis DHM raw hologram uint8 development

## Outcome

Accepted `zenodo_offaxis_dhm_holograms_u8`. It contains raw 8-bit camera frames of off-axis digital holograms. Each frame is an interference pattern between a tilted reference wave and the object wave scattered by unresolved nanoparticles, beads and lipid vesicles, so carrier fringes modulate the pixel intensities. It is the first hologram or interferogram family in the corpus at any width. zlsim rates it `OK`: the nearest family is `empiar_13192_sbfsem_vessel_slices_u8` at feature distance 0.030, but the compression loss is 9.6%, so the two are not compression-equivalent.

The recipe passed on the second judge review. The first review found correct bytes but wrong documentation, and asked for a documentation-only repair:
- **Instrument:** the microscope was misattributed to Lyncée Tec.
- **Fringes:** a false "3–4 px in both directions" carrier claim.
- **520 nm exclusion:** an incorrect rationale for dropping the 520 nm video.

The repair left the output byte-identical (aggregate SHA-256 unchanged).

## Source and rights

- **Source:** Zenodo record 10632465, "Detectability of unresolved particles in off-axis digital holographic microscopy", published 2024-02-07, also Dryad doi:10.5061/dryad.9cnp5hqr7. Depositor: Jay Nadeau, Portland State University.
- **Contents:** 18 zips, one DHM video each (106–315 frames, ~7 fps per the deposit README), plus README.md.
- **License:** CC0-1.0. Zenodo metadata gives `license.id = cc-zero` and `access_right = open`. `download.sh` re-checks the record id, title, license, and the size and MD5 of every zip it uses.
- **Instrument evidence:** Johnston, Dubay, Serabyn and Nadeau 2024, *Appl. Opt.* 63(7):B114, doi:10.1364/AO.507375 (the record's `isCitedBy`), Methods 2.A:
  - a custom off-axis common-path DHM (Wallace et al. 2015, *Opt. Express* 23:17367);
  - a Thorlabs MCLS-1 laser at 405 or 520 nm;
  - an Allied Vision Prosilica GT2450 camera (3.45 µm pixels, well depth 6500);
  - 2048×2048 frames;
  - DHMx acquisition software.
- **Software discrepancy:** the deposit README names KOALA (LynceeTec) instead. Both statements are recorded as sourced.
- **Safety:** synthetic particles and lipid vesicles only, with no personal data.

## Shape and conversion

- **Natural record and sample:** one natural record is one hologram TIFF frame, and one sample is one frame: 2048×2048 = 4,194,304 uint8 values, row-major.
- **Selection:** from each of the 17 videos recorded at 405 nm, with N frames, the recipe keeps frames floor((2k+1)·N/12) for k = 0..5. These are evenly spaced, 17–52 frames apart, so they are never contiguous.
- **Exclusion:** the single 520 nm video (`2022.08.02_14-37_AuFlat520.zip`) uses a different laser line and is excluded.
- **Download:**
  - `download.sh` reads each zip's central directory by exact HTTP range.
  - It fetches each selected member as exactly [local header, next entry), requiring 206 and the exact Content-Range.
  - It inflates raw deflate, checks CRC32 and size, and validates the TIFF layout: little-endian, single IFD, 2048×2048, 8 bps, spp 1, LZW, predictor 2, BlackIsZero.
  - It rejects ZIP64, multi-disk and encrypted archives.
- **Decode:** `build.sh` first self-tests the pure-Python LZW and predictor-2 decoder on synthetic TIFFs, then decodes each frame and writes the pixels unchanged.
  - A legacy end-of-strip EOI code width (old libtiff behaviour) appears in 155 of 52,224 strips, all in the June and October 2022 sessions.
  - It is accepted only when the strip is already complete and the code width was just bumped.
- **Verify:** `verify.sh` re-decodes every frame with a separately written decoder and byte-compares it with the sample.
- **Carrier geometry by session:** one instrument, realigned between sessions, documented in the manifest and README:
  - 2022.06.09 (24 samples): near-vertical fringes, horizontal period ~2.8 px.
  - 2022.07.27 and 2022.08.02 (60 samples): diagonal fringes, ~4 px period.
  - October 2022 (18 samples): a different diagonal carrier.
- **Exposure outlier:** 2022.10.05_16-02_PolystyreneFlat was recorded at lower exposure (mean 42.7 DN, max 148–163, H0 6.32 bits) and is kept as the same quantity.

## Accepted output

| Item | Value |
|---|---|
| Series | `dhm_offaxis_hologram_u8` (primary, native_numeric, uint8) |
| Videos | 17 at 405 nm (of 18 in the record) |
| Source frames | 4,121 |
| Samples | 102 (6 per video) |
| Values per sample | 4,194,304 (2048×2048) |
| Primary values and bytes | 427,819,008 |
| Range-fetched TIFF bytes kept | 571,313,482 |
| Whole-archive size avoided | ~22 GB |
| Legacy-EOI strips | 155 of 52,224 |
| Aggregate SHA-256 of per-sample SHA-256s | `ec62329ea22c922568a991f9ca9beaa50bae016fe84f3fef303988d90abb4dc7` |

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/zenodo_offaxis_dhm_holograms_u8` gave PASS with no warnings (median 4,194,304 values, widths [8]).
- **Verify:** I ran `bash staging/zenodo_offaxis_dhm_holograms_u8/verify.sh` myself (exit 0). Output: `verify=ok samples=102 bytes=427819008 independently_decoded=102`.
- **Local-only build:** build and verify, and the modules they use, make no network calls. The repair-cycle edits to `dhm_tiff.py`, `dhm_build.py` and `selftest_tiff.py` were sed substitutions on docstrings and comments only (builder transcript).
- **Rights:** I fetched the Zenodo API record myself: cc-zero, open, DOI 10.5061/dryad.9cnp5hqr7. No credentials appear in any script.
- **Instrument claims:** I checked them against the accepted-manuscript text (NSF PAR 10519442).
  - Confirmed: MCLS-1 405/520 nm, Prosilica GT2450 at 3.45 µm/pixel, 2048×2048, DHMx, well depth 6500, reference [28] = Wallace 2015, and the Fig. 1 caption "off-axis common-path DHM".
  - The paper does report a larger coherence envelope at 520 nm, though only with polymer coverslips.
  - The paper gives 15 fps acquisition while the manifest uses the deposit README's ~7 fps. This is a minor descriptive difference.
- **Bytes:** I used stdlib Python on the first frame of each of the 17 videos.
  - The carrier autocorrelations match the documented session table.
    - June: ρ(1,0)=0.98, |Δ| 84–98 horizontally vs 8.6–9.7 vertically.
    - July/August: ρ(1,1)=0.98–0.99.
    - October: ρ(3,-1)=0.95–0.98.
  - My full-frame |Δ| for July/August is 52–60 DN, a little below the manifest's crop-based 55–66. This is immaterial.
  - Strip-boundary vs within-strip |Δ| ratio is 0.999–1.004.
  - There are no constant borders.
  - Mode share is at most 1.9%, with saturation only in the June vesicle videos (at most 0.7%).
  - All 17 videos share one identical 18-tag TIFF signature.
- **Near-duplicates:** for all 15 frame pairs within each video, at most 9.6% of pixels are equal and the minimum mean absolute difference is 3.9 DN (the most static video is 300nmAluminaThick, MAD 4.4–5.2 DN).
- **Novelty:**
  - `novelty.py --url` on the record and the Dryad DOI, with terms hologram, holographic, DHM, interferogram, off-axis, fringe, koala, lyncee and prosilica: no recipe, registry or downstream match beyond this staging recipe and unrelated InSAR and Fermi term hits.
  - `--type digital_hologram`, `--instrument` and `--archive` each returned 0.
  - The vocabulary has no hologram type.
  - Labelled `new_quantity`, because 8-bit microscope camera and detector images exist and are feature-close.
- **Breadth key:** the screener's `instrument_line` (`lyncee_tec_common_mode_offaxis_dhm`) is wrong and is replaced with `custom_offaxis_common_path_dhm_prosilica_gt2450`. The ledger title in `pipeline/candidates.tsv` still says "Lyncée" and should follow the manifest name.
