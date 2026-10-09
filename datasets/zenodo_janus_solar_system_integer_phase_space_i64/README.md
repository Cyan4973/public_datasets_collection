# JANUS Solar System integrations: native int64 fixed-point positions and velocities

Source: Rein & Tamayo, "Bit-wise reversible integrations of the Solar System
with JANUS", Zenodo record 546258 (DOI 10.5281/zenodo.546258), CC-BY-4.0
(Zenodo API `metadata.license.id = "cc-by-4.0"`, re-checked by `download.sh`).
Method paper: Rein & Tamayo (2018), MNRAS 473, 3351.

## Material

24 independent long-term integrations of the Sun plus 8 planets with JANUS,
a bit-wise reversible integrator. Its authoritative state is a set of 64-bit
integers on a fixed-point lattice, advanced with exact integer arithmetic.
Each file `restart_NNNN.bin` is a REBOUND SimulationArchive with these parts:

- a 64-byte banner `REBOUND Binary File. Version: 3.2.2`, written by
  development build git `b0f792d...`;
- tagged header fields `{uint32 type, uint32 pad, uint64 size, payload}`
  ending at tag 9999. Field 45 (SASIZEFIRST) gives the header length, 3340
  in every file; the recipe reads it per file. Field 46 gives the 448-byte
  snapshot size. Field 108 (JANUS_SCALE) is `1e16`;
- 58,902 to 60,692 fixed snapshots per file. Each holds `double t`,
  `double walltime`, then `int64[9][6]` (x, y, z, vx, vy, vz per body).

In this pre-3.4.0 build one scale multiplies both positions and velocities
(`int = (int64)(double * 1e16)`, see `integrator_janus.c` at `b0f792d`).
Simulation units are G = 1, AU, solar masses and yr/2π. One integer unit is
therefore 1e-16 AU, or 1e-16 AU per yr/2π. REBOUND 3.4.0 later split the
scale into `scale_pos`/`scale_vel` (fields 113/114). Those fields are absent
here, and the manifest's `[source_format_notes]` documents the actual field.
The archive cadence is 32317.29 time units (about 5,143 yr), so each file
spans about 3.0e8 yr.

The 24 integrations start from slightly perturbed copies of the same initial
conditions. Their first snapshots are all distinct, but differ by only about
2e-5 AU at most, and the runs then diverge chaotically. At snapshot 1,000
(about 5 Myr) the largest per-value difference between runs is about 1e13 to
2e14 units. By snapshot 10,000 it is about 1e15 to 1e16, and by snapshot
50,000 it is about 3e17 to 6e17. As a result, the first part of each sample
is close to the matching part of every other sample, while the rest is
independent.

## Output

| series | role | kind | samples | bytes |
|---|---|---|---|---|
| `janus_solar_system_position_i64` | primary | int64 LE | 24 (one per integration) | 306,000,936 |
| `janus_solar_system_velocity_i64` | primary | int64 LE | 24 (one per integration) | 306,000,936 |
| `janus_snapshot_time_f64` | auxiliary | float64 LE | 24 | 11,333,368 |

Each body record in a snapshot is 48 bytes: `int64 x, y, z, vx, vy, vz`.
The position series takes bytes `[0, 24)` of every record and the velocity
series takes bytes `[24, 48)`, both copied verbatim with no rescaling or
reordering. Each primary sample has shape `[snapshots, 9, 3]` (snapshot,
body, component) in C order: about 1.6M values (about 12.7 MB) per sample
and 38,250,117 values per series. Positions are in units of 1e-16 AU and
velocities in units of 1e-16 AU per yr/2π. The 16-byte per-snapshot
(t, walltime) prefix is stripped: t goes to the auxiliary series and
walltime is dropped.

## Scripts

- `download.sh`: validates the Zenodo record (id, title, license, and the
  exact 24-file list with sizes and md5s from `scripts/files.tsv`). It then
  fetches each file resumably with `curl -C -`, checks size and md5, and
  runs `janus_sa.py validate`, which checks the header, the alignment,
  strictly increasing times with interval spacing, non-constant columns and
  plausible magnitudes (every body within 100 AU, speeds below 10; the Sun
  is not bounded more tightly because the frame is not re-centred and it
  drifts with the barycentre, about 0.7 AU over 3e8 yr in restart_0000).
  Download size: 634,748,768 bytes.
- `build.sh`: `janus_sa.py selftest` (synthetic archive, per-record
  position/velocity spot checks, corruption cases), then `build`. It writes samples, `index/<id>/samples.jsonl` and
  `filtered/<id>/ingest_stats.json`, which holds the per-file header fields,
  masses and time span.
- `verify.sh`: re-hashes the sources, re-walks the snapshots and body
  records by stride and byte-compares every position, velocity and time
  sample. It also checks that re-interleaving each position/velocity pair
  reproduces the file's native int block, rejects constant samples or
  columns and duplicate integrations per series, and checks the manifest
  totals for all three series.

Pure standard-library Python on a little-endian host.
