# ClimSim low-res E3SM-MMF air-temperature float64 development

## Outcome

Accepted `leap_climsim_lowres_e3sm_mmf_state_fields_f64`. It holds native full-precision float64 air-temperature fields from the E3SM-MMF climate simulation that LEAP publishes as ClimSim low-res.

This is the first climate-model 3D atmospheric state family at 64-bit, in both the local and the downstream corpus. Existing 64-bit temperature families are decimal-quantized station or point series: NOAA CO-OPS, NDBC, the Beijing air-quality set and NASA POWER. The nearest gridded atmosphere family, `weatherbench2_era5_pressure_level_fields_f32`, is reanalysis at 32-bit.

The scout card proposed four variables (`state_t`, `state_u`, `state_v`, `state_q0001`). The builder shipped `state_t` only, as one homogeneous quantity. The other variables would be separate families. The dataset id keeps the card's plural "state_fields", but the manifest name, description and README all say temperature only.

## Source and rights

- Source: Hugging Face dataset `LEAP/ClimSim_low-res`, pinned revision `bab82a2ebdc750a0134ddcd0d5813867b92eed2a`; it is still the current `main` sha.
- Files: `train/<yyyy-mm>/E3SM-MMF.mli.<yyyy-mm-dd>-<sssss>.nc`, NetCDF classic CDF-5, 1,897,632 bytes each.
- Pinning: per-file LFS sha256 and xet hash are pinned in `selection.tsv` and re-checked through `paths-info` on every download.
- License: CC BY 4.0. Three sources agree:
  - the dataset-card front matter at the pinned revision (`license: cc-by-4.0`)
  - the HF API (`cardData.license = cc-by-4.0`, tag `license:cc-by-4.0`, `gated = false`)
  - the ClimSim GitHub README, which uses "the Creative Commons Attribution 4.0 license for data hosted on HuggingFace" (Apache 2.0 for code)
- Citation: Yu et al., *ClimSim*, NeurIPS 2023 Datasets and Benchmarks, arXiv:2306.08754.

## Shape and conversion

Each natural record is one model-timestep input-state file. A sample is that file's complete `state_t` variable, the full global field at one timestep:

- type and shape: NC_DOUBLE, dims (lev=60, ncol=384), no attributes, no fill
- size: 23,040 values, written level-major with columns fastest

`download.sh` uses HTTP Range requests: a 4 KB header and the 184,320-byte `state_t` slab per file. The slab's range comes from each file's own parsed header (begin 791,712 in all 825). Each response must meet four checks:

- status 206 with the exact Content-Range
- CDN ETag equal to the pinned xet hash
- X-Linked-Etag equal to the pinned LFS sha256
- in-file `ymd`/`tod` equal to the filename

Three whole-file canaries (ordinals 0, 759 and 824) are sha256-checked, and their slices equal the range bytes.

Conversion: the big-endian doubles are byte-swapped to little-endian with every bit pattern preserved. Nothing is filtered or imputed.

Selection is deterministic: one mli file every 223 twenty-minute steps (74 h 20 min) from `0002-01-01-00000` across complete no-leap model years 0002–0008. Because 223 mod 72 = 7, the time of day rotates through all 72 slots, and no two selected files are adjacent.

Excluded:
- winds, humidity and condensates
- `state_pmid`
- prescribed gases
- 2D surface fields
- all mlo files

Missing-value policy:
- Every value must be finite and within a 50–1000 K guard against decode garbage.
- The lowest level must average more than 20 K warmer than levels 15–25.
- Every field must be non-constant and distinct from every other field.
- Any violation is fatal.

One upstream model-top transient is kept: lev 0 columns 302–303 of `0008-06-10-68400` read 414.2 K and 663.6 K. That file's whole-file sha256 is verified.

## Accepted output

| | |
|---|---|
| Source files used | 825 (range-fetched), plus 3 whole-file canaries |
| Download | 169,135,196 bytes |
| Primary samples | 825 |
| Primary values | 19,008,000 |
| Primary bytes | 152,064,000 |
| Values per sample (min = median = max) | 23,040 (184,320 bytes) |
| Distinct values per sample | 23,040 in every sample |
| Coverage | model years 0002–0008 (118 samples per year for 0002–0007, 117 for 0008), all 12 months, all 72 times of day |
| Per-sample minimum | 146.23–184.49 K |
| Per-sample maximum | 303.80–331.54 K, plus one 663.62 K transient |
| Series range | 146.2327418170901 – 663.6245325112556 K |
| Aggregate decoded SHA-256 | `35ed9dc20bc14a06dbb68e87d16c24f9f45e6f30b0c5cb974d74bf56c3fb504c` |

## Judge checks

- **Gate:** `tools/autocollect/gate.py` passed with no warnings (values=19008000, bytes=152064000, samples=825, median=23040, widths=[64]). `tools/check_repo_hygiene.py` passed.
- **verify.sh:** my own run succeeded in about 9 s. It covers:
  - the CDF-1/2/5 self-test
  - re-derivation of all 825 samples from the downloaded ranges
  - a struct-free byte-swap cross-check
  - index and manifest comparisons
- **Local-only build:** build.sh reads only local files. The Python scripts contain no network code, and the self-test builds its synthetic files in memory. No credentials appear anywhere; grep hits were only `hf_` resource ids.
- **Download history:** the first download log confirms the builder's account. The run failed at the original 120–380 K bound on ordinal 759. The rerun passed the meta, paths, heads, data and canary stages.
- **Independent decode:** I parsed the three canary files without the recipe's parser. I located the `state_t` header entry by name scan (rank 2, ABSENT attrs, type 6, vsize 184320, begin 791712). Repacking `>23040d` as `<23040d` equals the stored samples byte-for-byte, and each canary's sha256 equals the pinned LFS oid. One HTTP dump I inspected shows 302 then 206, `content-range: bytes 791712-976031/1897632`, the xet ETag and the LFS X-Linked-Etag.
- **Precision:** across 33 samples (760,320 values), 0 values round-trip through float32 and 0 have their low 29 mantissa bits zero. These are genuine model doubles, not widened data.
- **Physical plausibility:** level means over all samples follow a real temperature profile:

  | Level | Mean (K) |
  |---|---|
  | lev 0 | 215.5 |
  | lev 5 (stratopause) | 259.3 |
  | lev 15–20 (tropopause) | 204–207 |
  | lev 40 | 267.2 |
  | lev 59 (surface) | 288.4 |

  The surface-level minimum of 206.5 K is consistent with polar winter. Values above 295 K at lev 0–2 occur 13 times in 6 samples, all within columns 275–330: a recurring model-top behaviour, not decode garbage.
- **Diversity:** consecutive samples differ by a mean absolute 1.75–2.83 K. Anomaly std against the 825-sample mean field is 3.4–7.7 K. There are no duplicates or near-duplicates.
- **License:** I read the pinned README and the live HF API record myself, and fetched the ClimSim GitHub README, which states the CC BY 4.0 data license for HF-hosted data.
- **Novelty:** `tools/autocollect/novelty.py` with the ClimSim URL and the terms climsim, e3sm, E3SM-MMF, state_t, climate model and superparameterization matched only this candidate. The registry and downstream returned none. A filtered scan of the downstream 64-bit family list for climate and temperature terms found only station or point decimal series.
