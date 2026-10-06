# AhmedML CFD surface mean pressure float32 development

## Outcome

Accepted `ahmedml_cfd_surface_mean_pressure_f32`, which collects native float32 OpenFOAM `pMean` surface fields from the AhmedML hybrid RANS-LES dataset. Each sample is one complete time-averaged pressure field over the body surface of one simulated Ahmed-body geometry.

This is the first computational-fluid-dynamics solution field in the corpus at any width. The only earlier CFD attempt was `pdebench_sod6_shock_tube_f64`, which was rejected as degenerate.

## Source and rights

- Source: Hugging Face `neashton/ahmedml`, pinned at revision `02688c727cdb8dc8678e28abc6bbbb7e93c5fa15`. The authors are Ashton, Maddix, Gundry and Shabestari (NVIDIA / caemldatasets.org): arXiv:2407.20801, doi:10.57967/hf/5002.
- Files read: `run_<i>/boundary_<i>.vtp` for 50 runs. Per-file size, LFS sha256 and xet hash are pinned in `selection.tsv`.
- License: CC BY-SA 4.0. The README front matter declares `license: cc-by-sa-4.0`. The HF API reports `cardData.license = cc-by-sa-4.0` with `gated = false`. `LICENSE.txt` is the CC BY-SA 4.0 legal code (sha256 `28a9529c7d0bb4dc51f4bf5c116a3d16ef247a052f7591466768ddf563fd1cf5`). `download.sh` re-checks all three on every run.
- Attribution and ShareAlike obligations are recorded in the manifest and README. The same license class was accepted for `goose_vls128_lidar_scan_xyz_f32`, `exomol_state_energy_levels_f64` and `zenodo_crab_giant_pulse_sigmf_ci16`.

## Shape and conversion

- **File format:** each `boundary_<i>.vtp` is VTK XML PolyData (LittleEndian, header_type UInt64, uncompressed inline base64) containing the single surface patch `ahmed`. Its CellData holds, in a fixed order, `pMean`, `static(p)_coeffMean`, `yPlusMean` and `wallShearStressMean`(×3).
- **Locating the array:** `discover.sh` used ~7 KB of range probes per run to walk backwards from the end of the file and pin the byte span of the `pMean` base64 block.
- **Download:** `download.sh` fetches two ranges per run: the 2 KB header and the pMean window, which is the block plus 256 bytes before and 128 bytes after.
  - Each response must be a 206 with the exact Content-Range, a CDN ETag equal to the pinned xet hash, an X-Linked-Etag equal to the pinned LFS sha256, and X-Repo-Commit equal to the pinned revision.
  - Each window must be bracketed by the `</Polys><CellData>…pMean` opening tag and the `static(p)_coeffMean` tag.
  - Each window must decode to 8 + 4N bytes with a UInt64 prefix equal to 4N.
- **Build:** the 4N float32 bytes are emitted unchanged, one sample per run, in VTP polygon order.
- **Excluded arrays:**
  - `static(p)_coeffMean`: an exact 2× rescale.
  - `yPlusMean`: a mesh diagnostic.
  - `wallShearStressMean`: a different quantity.
  - Mesh points, connectivity and offsets.
  - Cell-area NPY files, volume VTUs, slices, images and force CSVs.
- **Missing-value policy:** the same in download, build and verify, and any failure is fatal. Values must be finite and within ±10; each field must contain both signs, be non-constant and have at least 5% distinct values; no two fields may be identical.

## Accepted output

| | |
|---|---|
| Series | `ahmedml_boundary_pmean_f32` (primary, native float32, little-endian) |
| Runs | 50: run_1, run_11, …, run_491 (`range(1, 501, 10)`) |
| Primary values | 53,282,167 |
| Primary bytes | 213,128,668 |
| Smallest sample | 724,668 values (run_351) |
| Median sample | 1,082,412 values (mean of 1,080,538 and 1,084,286) |
| Largest sample | 1,404,826 values |
| Value range | -1.8801849 (run_171) to 0.5230487 |
| Per-run max | 0.5164 – 0.5230 (front stagnation) |
| Per-run min | -0.652 (run_151) to -1.880 (run_171) |
| Download | 284,770,634 bytes on disk (ranges plus header dumps and metadata), 7.1% of the 4,001,636,664 bytes of full VTPs |
| Aggregate decoded SHA-256, samples in selection order | `d60349301c1973d4711bef84110c5dee9766a0e9301c300df1d1460177446497` |

All 500 runs would come to about 2.1 GB, over the cap, so the deterministic every-10th-run subset is the bounded scope.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/ahmedml_cfd_surface_mean_pressure_f32` gave PASS with no warnings and matched the totals above.
- **verify.sh:** I ran `bash staging/ahmedml_cfd_surface_mean_pressure_f32/verify.sh`. The synthetic self-test passed (5 files × 10 negative cases), and verify reported 50 samples, 213,128,668 bytes and 50 distinct payloads.
- **Local-only build:** `build.sh` and `verify.sh` contain no network calls, and the scripts contain no credentials.
- **Independent decode:** for runs 1, 251 and 491 I wrote a decoder separate from the helper (tag search, then base64). It reproduced the stored samples byte for byte; the prefix equals 4·NumberOfPolys, and the window brackets are correct.
- **Header and Cp check:** the header comment shows `patch='ahmed' time='79.9998'` in all 50 runs. The first `static(p)_coeffMean` value in each window equals 2× the first pMean value.
- **Byte statistics:** I computed these with standard-library Python (`struct`, `array`) on runs 1, 71, 141, 211, 281, 351, 421 and 491.
  - About 90–93% of values are negative (body suction); there are no zeros.
  - 95–99% of values are distinct.
  - All 256 low-byte bins are used, and there are 16–21 exponent bins.
  - Mantissa trailing zeros follow the ideal geometric distribution (0.50, 0.25, 0.125, …), so these are full 23-bit mantissas with no quantization.
  - Median lag-1 |Δ| is 3e-4 to 1e-3 m²/s², so the field is spatially smooth.
- **Duplicates:** all 50 value counts and all 50 leading 4 KB prefixes are distinct.
- **HTTP identity:** the stored headers for run_1 show 302 → 206, with `content-range: bytes 47474874-53350329/82725933`, ETag equal to the pinned xet hash, `x-linked-etag` equal to the pinned LFS sha256, and `x-repo-commit` equal to the pinned revision.
- **Rights:** I read the downloaded `LICENSE.txt` (its sha256 matches the pin), the README front matter and `api_info.json` (id, sha, gated=false, private=false, disabled=false, license cc-by-sa-4.0).
- **Novelty:** `novelty.py --url https://huggingface.co/datasets/neashton/ahmedml --terms ahmedml ahmed cfd openfoam "surface pressure" rans-les caemldatasets drivaerml windsorml vtp pMean` found:
  - no other recipe from the same source, only the same host;
  - for 'cfd', only the rejected PDEBench shock tube and a proposed PDEBench ledger row;
  - for 'surface pressure', only meteorological series;
  - no downstream match.

  No accepted 32-bit family in `pipeline/candidates.tsv` is a simulation surface field.
