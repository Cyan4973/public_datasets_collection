# NORDIF EBSD Kikuchi pattern uint8 development

## Outcome

Accepted `zenodo_nordif_ebsd_kikuchi_patterns_u8`. It holds raw 8-bit electron backscatter diffraction (Kikuchi) patterns from a NORDIF UF-1100 detector, one 240x240 frame per SEM scan point. They come from the two complete EBSD maps (II and III) of the Bergh, Ånes and Wenner (2022) cold-metal-transfer Al-steel weld deposit.

Novelty is labelled `new_source`. EBSD already exists locally only as `zenodo_silicon_diffraction_tiff_u16`: a single 16-bit 1152x1600 silicon pattern from a different Zenodo deposit (record 1450892). The downstream mirror of that recipe is `silicon_ebsd_detector_u16`. This recipe is a different deposit, instrument and width, and it carries thousands of natural frames. No 8-bit diffraction family exists locally, downstream, or among this effort's accepted 8-bit rows.

## Source and rights

- Source: Zenodo record 6634354, DOI 10.5281/zenodo.6634354 (published 2022-08-12, revision 7)
- Files used:
  - `II_EBSD.dat`: 706,867,200 B, md5 `bf5446ab3566b5d47fa9c1205c399e60`
  - `III_EBSD.dat`: 1,190,707,200 B, md5 `bc44c9a44ffd04185300783fd986cf64`
  - `II_Setting.txt` and `III_Setting.txt`: MD5 and SHA-256 pinned
- License: CC BY 4.0, declared record-wide in the Zenodo metadata (`license.id = cc-by-4.0`, `access_right = open`). download.sh re-checks it on every run, together with the title and each used file's size and MD5.
- Excluded:
  - `I_EBSD.dat`: 1,292,668,928 B, short of the 1,299,628,800 B its 109x207 grid needs, so truncated
  - calibration and background BMPs (gain 15)
  - SEM area images
  - other NORDIF deposits with 60x60 or 480x480 geometry

## Shape and conversion

`EBSD.dat` is NORDIF's headerless `Pattern.dat`. It is a stack of row-major 240x240 uint8 patterns in scan-raster order, x fastest. The geometry comes from `Setting.txt` ([Acquisition settings] Resolution 240x240; [Area] Number of samples 59x208 / 64x323, cross-checked with Height/Step and Width/Step). Rows x cols x 57,600 equals each file size exactly.

download.sh range-fetches scan rows 0, 8, …, 56 of each map, one HTTP Range request per row. Each row must return 206, the exact Content-Range, the exact length, and the pinned per-row SHA-256 (`row_sha256.tsv`). build.sh splits each row into its C patterns and writes each one unchanged as `<map>_r<row>_c<col>.bin`. Nothing is rescaled, background-corrected or binned. Hot-pixel 255 values are kept as stored.

Both maps share identical acquisition settings: 240x240, gain 10, 20 fps, 49,950 µs exposure, SU-6600 at 20 kV, 70° tilt, magnification 1800. They differ only in working distance (23.8 vs 24.5 mm) and step size (0.1 vs 0.05 µm).

## Accepted output

- Primary samples: 4,248 (II 8 rows x 208 = 1,664; III 8 rows x 323 = 2,584)
- Primary values and bytes: 244,684,800 (57,600 per sample; median 57,600)
- Population: 32,944 patterns (1.9 GB); the stride-8 rows subset keeps about 13%
- Downloaded range bytes: 244,684,800 payload (244,736,926 transferred in 105 s)
- Value range: 5..255; 251 distinct overall; 166–241 distinct per pattern (median 212); mean 128.708; no zeros
- 255 fraction: 2.353e-5, all of it fixed hot pixels. (117,217) is 255 in every pattern; 1–4 such pixels per pattern.
- Byte-identical duplicates: 0
- zlib -9 ratio per pattern: about 0.75–0.81
- Aggregate SHA-256 in index order: `e66e79ec7451768f4747d37ca61a13cad123b005f575bc81985ee27f13d4ec67`

## Judge checks

- `gate.py`: PASS, no warnings. I re-ran `verify.sh` myself: exit 0, with the aggregate hash above.
- **Provenance:** download.sh was last edited (01:59) before the driver's download (02:02). The log shows 16/16 rows returned 206 with the exact Content-Range on the first attempt. The recipe pins match the realized row hashes, and build.sh and verify.sh enforce them. verify does not import the build code and byte-compares every sample with its source row slice.
- **Rights:** I read `record.json` (cc-by-4.0, open, MD5s match the pins) and fetched the live landing page (CC BY 4.0, Open, no embargoed files). A grep found no credentials in the scripts.
- **Bytes** (stdlib inspection of 12 samples plus index stats):
  - Width and alignment: neighbour differences are about 3 DN, and stride 239 gives a larger difference than stride 240, which confirms width 240. The hot pixel constant across all 4,248 patterns confirms alignment.
  - Detector geometry: a coarse block map of the mean pattern shows a smooth backscatter blob with dark right-hand detector corners, which explains the small 10–16 DN histogram bump.
  - Raster order: per-pattern means along a row have no period-59 jumps (map II), so the order is x-fastest.
  - Quantization: the global histogram has an even/odd comb (odd codes run at about 0.33 of their even neighbours). This is native camera digital-gain quantization, not widening.
  - Diffraction signal: after removing the static and dynamic background, residual RMS is about 2%; adjacent scan points correlate at 0.12–0.57 and random same-map pairs at about 0. That shows genuine position-dependent Kikuchi structure. The builder's higher 0.65–0.95 likely used smoothed residuals; my raw-pixel figures support the same conclusion. The material is noise-dominated, as raw 50 ms frames are.
  - The outlier jump at III r032 c322 is an intact pattern, not a torn frame.
- **Homogeneity:** a diff of II and III `Setting.txt` confirms identical acquisition settings; only working distance, step, area and the unused calibration exposure differ.
- **Novelty:** `novelty.py --url https://zenodo.org/records/6634354 --terms kikuchi nordif ebsd backscatter 6634354` matched no other recipe on this record. The only EBSD hit is the single-pattern 16-bit silicon recipe, so the label is `new_source`, downgraded from the claimed `new_modality`.
