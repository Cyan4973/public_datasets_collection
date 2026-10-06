# ClimSim Low-Res E3SM-MMF Atmospheric Temperature Fields (float64)

Native full-mantissa float64 air-temperature fields from the E3SM-MMF climate
simulation that LEAP publishes as
[ClimSim low-res](https://huggingface.co/datasets/LEAP/ClimSim_low-res).
Each sample is the complete `state_t` variable of one model-timestep input
file: 60 vertical levels × 384 ne4pg2 physics columns = 23,040 doubles, in K.

| | |
|---|---|
| Source | `LEAP/ClimSim_low-res`, HF dataset revision `bab82a2ebdc750a0134ddcd0d5813867b92eed2a` |
| License | CC-BY-4.0: dataset-card front matter `license: cc-by-4.0` at the pinned revision; HF API `cardData.license = cc-by-4.0`, `gated = false` |
| Citation | Yu et al., *ClimSim: A large multi-scale dataset for hybrid physics-ML climate emulation*, NeurIPS 2023 D&B, arXiv:2306.08754 |
| Primary series | `climsim_e3sm_mmf_state_t_f64`: 825 samples × 184,320 bytes = 152,064,000 bytes, 19,008,000 values |
| Download | about 169 MB: 825 × (4 KB header range + 184,320-byte `state_t` range), plus 3 whole-file canaries, HTTP header dumps and API JSON |

## Material

ClimSim is a set of E3SM-MMF climate simulations. In E3SM-MMF the
Multiscale Modeling Framework embeds a cloud-resolving model in each
host-model column. The low-res set runs on the ne4pg2 grid (384 columns) with
60 hybrid levels and saves every 20-minute host timestep. The model is
calendar-agnostic (`NO_LEAP`), and the files cover model years 0001-02 to
0009-01. Each `E3SM-MMF.mli.<yyyy-mm-dd>-<sssss>.nc` file is the input state
to the MMF physics at that step. It is a NetCDF classic CDF-5 file of
1,897,632 bytes that holds 29 big-endian `NC_DOUBLE` variables plus the
`ymd`/`tod` scalars.

This recipe keeps one quantity, `state_t` (air temperature, K). Samples are
full-precision model doubles: in probes no value round-tripped through float32
and every field had 23,040 distinct values. Temperatures run from about 170 K
(upper stratosphere and polar tropopause) to about 315 K (surface), with the
stratosphere and tropopause structure intact.

Variables deliberately not taken:

- the humidity and condensates `state_q0001/2/3` (different regime; the
  condensates are mostly zeros)
- the winds `state_u/v` (other quantities)
- `state_pmid`, which is deterministic from `state_ps`
- the prescribed gas climatologies `pbuf_CH4/N2O/ozone`
- the 2D surface fields
- all `mlo` output files

## Selection (deterministic, bounded)

Model years 0002-0008 are taken complete: 7 × 365 days × 72 steps = 183,960
candidate timesteps. One `mli` file is kept every 223 steps (74 h 20 min),
starting at `0002-01-01-00000`, which gives 825 files.

- Because `223 mod 72 = 7` is coprime with 72, the time of day rotates through
  all 72 twenty-minute slots instead of aliasing the diurnal cycle.
- No two selected files are adjacent, which avoids near-duplicate 20-minute
  neighbours.
- Seasons and years are covered evenly.

`scripts/climsim.py planned_steps` implements the rule. `discover.sh`
resolved it once against the HF `paths-info` API, and all 825 planned paths
exist. `selection.tsv` pins path, expected in-file `ymd`/`tod`, size, LFS
sha256 and xet hash for every file. Every script re-checks `selection.tsv`
against the rule.

The full 7-year population is about 184k fields (about 34 GB of `state_t`
alone). The roughly 150 MB subset is sized for downstream family selection,
not to clear the floor.

## Download (`download.sh`)

The script uses anonymous curl only and resumes per file.

1. Revision API record: checks `id`, `sha`, not gated/private/disabled, and
   `cardData.license == cc-by-4.0`. Also checks `README.md` front matter at
   the pinned revision.
2. Batched `paths-info` POSTs: every selected path must exist with the pinned
   size, LFS sha256 and xet hash.
3. Per file, `Range: bytes=0-4095`. The response must be 206 with
   `Content-Range: bytes 0-4095/1897632`, the CDN `ETag` must equal the pinned
   xet hash, and the redirect `X-Linked-Etag` must equal the pinned LFS
   sha256. The CDF-5 header is then parsed and checked:
   - magic `CDF\x05`, `ncol=384`, `lev=60`, `calendar=NO_LEAP`
   - `state_t` is non-record `NC_DOUBLE (lev, ncol)` with vsize 184,320,
     and its begin lies inside the file
   - the in-file `ymd`/`tod` scalars equal the file name
4. Per file, the `state_t` range is taken from that file's own parsed header,
   never hard-coded; it is 791,712-976,031 in every probed file. The same
   HTTP checks apply. Values must be finite, within 50-1000 K, non-constant,
   vertically plausible (lowest level more than 20 K warmer than levels
   15-25) and not duplicated across files.
5. Three whole-file canaries (ordinals 0, 759 and 824) are fetched. Each must match
   its pinned LFS sha256, and the range-fetched header and `state_t` bytes
   must equal the same slices of the verified whole file. This proves the CDN
   honours the ranges exactly.

Pacing: one request at a time with a short sleep. HF limits anonymous
resolves to 3,000 per 5 minutes, and the recipe makes about 1,650. Each
request uses curl `--retry` with exponential backoff, `--speed-limit`/
`--speed-time` stall detection (no `--max-time` on data), and an outer retry
loop.

## Build and verify

- `build.sh`: runs the CDF-5 self-test, re-parses every header, unpacks
  `>23040d`, and writes `<23040d` unchanged in source order (lev-major, ncol
  fastest). Output:
  - samples: `samples/<id>/climsim_e3sm_mmf_state_t_f64/E3SM-MMF.mli.<date>-<sssss>.state_t.f64le.bin`
  - index: `index/<id>/samples.jsonl`, with shape, axes, source path, LFS
    sha256, byte range, model date/time, min/max from the stored float64, and
    sha256
  - summary: `filtered/<id>/ingest_stats.json`
- `verify.sh`:
  - re-derives every sample from the downloaded ranges and compares bytes and
    every index field
  - cross-checks the conversion with a second, struct-free path that reverses
    each 8-byte group of the source slab
  - rejects non-finite, out-of-range, constant, degenerate (fewer than 25%
    distinct values) or duplicated fields, and stray files
  - checks manifest `sample_count`/`total_size_bytes` against the realized
    output
- Missing values: the variable has no `_FillValue`, so nothing is dropped or
  imputed. Any violation is fatal in all three scripts.

The parser (`scripts/cdf5.py`) is pure standard library. Its self-test
(`scripts/selftest_cdf5.py`) builds synthetic CDF-1, CDF-2 and CDF-5 files
with unpadded names and odd-length attributes, CDF-5 64-bit counts, and a
`begin`/`vsize` above 2^32. It checks every field and the payload decode, and
checks that truncated prefixes and bad magic are rejected.

## Caveats

- This is model output, not observations: one model on one coarse grid, and
  the material is the model's state trajectory.
- Fields from different timesteps share the fixed vertical structure, so
  samples are correlated in their level means. The 74-hour spacing keeps
  synoptic weather decorrelated between consecutive samples.
- One field keeps a genuine model-top transient. In
  `E3SM-MMF.mli.0008-06-10-68400` (ordinal 759), lev 0 columns 302-303 read
  414.2 K and 663.6 K, with strong top-level winds nearby. The whole file is
  fetched as a canary: its sha256 matches the pinned LFS object and its slice
  equals the range bytes. The values are therefore kept as source content,
  not filtered. Every other field spans 146.2-331.5 K. The 50-1000 K bound
  only guards against decode garbage.
- Only `state_t` is collected. Other state variables would be separate
  families, not extra series here.
