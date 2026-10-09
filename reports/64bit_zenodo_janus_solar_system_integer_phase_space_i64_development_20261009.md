# JANUS Solar System integer phase-space int64 development

## Outcome

Accepted `zenodo_janus_solar_system_integer_phase_space_i64` after one repair
cycle.

The recipe collects the authoritative integer state of 24 long-term Solar
System integrations. They were run with JANUS, Rein & Tamayo's bit-wise
reversible N-body integrator, which advances 64-bit integers on a fixed-point
lattice with exact integer arithmetic. The recipe keeps this state as two
primary int64 series, positions and velocities, one sample per integration.

The round-1 recipe emitted positions and velocities interleaved as
`x, y, z, vx, vy, vz` in one stream. The judge asked for a split into one
quantity per series, following the TrackML rejection precedent and the
accepted rMD17 and TUM splits. The builder made the split exactly as
specified.

Novelty: `new_source`. Planetary-motion material exists at 64 bits only as
float64 Chebyshev ephemeris coefficients (`nasa_naif_de440s_spk_coefficients_f64`,
plus a downstream mirror). No local or downstream family holds integer
fixed-point N-body integrator states. zlsim verdict OK: position nearest
0.0811 (`ozflux_l3_fe_f64`), velocity nearest 0.0959 (`vm_cpu_avg_pct_f64`),
DE440s at 0.0865.

## Source and rights

- Source: Zenodo record 546258, "Bit-wise reversible integrations of the
  Solar System with JANUS" (Rein, H. and Tamayo, D., 2017),
  DOI 10.5281/zenodo.546258. Method paper: MNRAS 473, 3351 (2018).
- Files: `restart_0000.bin` .. `restart_0023.bin`, 634,748,768 bytes in
  total, each pinned by size and md5 in `scripts/files.tsv` and the manifest.
- License: CC-BY-4.0. The Zenodo record metadata `license.id = "cc-by-4.0"`
  applies to the record's files. `download.sh` re-checks the license on every
  run, together with the record id, the title and the exact 24-file list.
- No credentials; anonymous direct download. Simulation output, no personal
  data.

## Shape and conversion

Each file is a REBOUND 3.2.2-dev (git `b0f792d`) binary SimulationArchive:

- a 64-byte banner;
- tagged header fields `{u32 type, u32 pad, u64 size, payload}` up to tag
  9999. The header length comes from field 45 (3340 in every file). The
  parser also requires N = 9, integrator = JANUS (8), safe_mode = 0,
  SASIZESNAPSHOT = 448, a single JANUS_SCALE = 1e16 (field 108) and
  plausible masses;
- fixed 448-byte snapshots: `double t, double walltime, int64[9][6]`.

Validation requires `(size - header) % 448 == 0`, strictly increasing t, and
gaps within 2*dt of the archive interval (32317.29 time units, about 5,143 yr).

For each snapshot and each body b, bytes `[48b, 48b+24)` (x, y, z) go to the
position sample and `[48b+24, 48b+48)` (vx, vy, vz) go to the velocity sample.
The bytes are copied verbatim, with no rescale or reorder. Each sample has
shape `[snapshots, 9, 3]` in C order. Units are 1e-16 AU, or 1e-16 AU per
yr/2pi (G = 1, solar masses). t is kept as the auxiliary float64 series
`janus_snapshot_time_f64`; walltime is dropped. The simulation frame is never
re-centred, so the Sun drifts with the barycentre (up to about 0.7 AU over
3e8 yr). The README documents this.

## Accepted output

- Primary series: `janus_solar_system_position_i64`,
  `janus_solar_system_velocity_i64` (int64 LE, role primary)
- Primary samples: 48 (24 per series, one per integration)
- Primary values: 76,500,234 (38,250,117 per series)
- Primary bytes: 612,001,872 (306,000,936 per series)
- Sample size: 1,590,354 to 1,638,684 values (58,902 to 60,692 snapshots x 27);
  gate median 1,591,960.5
- Position range: -309,726,158,593,589,713 .. 312,322,978,770,778,310
  (about ±31 AU)
- Velocity range: -22,128,775,791,726,807 .. 22,038,040,890,188,133
  (about ±2.2 AU per yr/2pi)
- Auxiliary: `janus_snapshot_time_f64`, 24 samples, 1,416,671 values,
  11,333,368 bytes; t from 32,317.30 to 1.96e9 (about 303-312 Myr per run)
- Download retained: 96.4%

Known characteristics, documented in the README:

- The 24 runs start from slightly perturbed copies of one set of initial
  conditions. The largest spread at snapshot 0 is 7.9e-5 AU, for Mercury; the
  README's "about 2e-5 AU" understates it slightly. All other bodies are
  within 1e-7 AU.
- No values are equal across runs. The runs share leading bytes for about the
  first 5,000 snapshots (about 8% of each sample) and decorrelate by
  snapshot 20,000.

## Judge checks

- `gate.py staging/<id>`: PASS, no warnings (48 samples, 76,500,234 values,
  612,001,872 bytes, width 64).
- Ran `verify.sh`: success. It confirmed the md5 of all 24 sources, the
  stride re-derivation and sha256 match of every position, velocity and time
  sample, the re-interleave check reproducing each native int block, the
  duplicate and constant-column checks, and the manifest totals. `build.sh`
  reads only `.data/downloads`.
- Ran the current `janus_sa.py validate` on all 24 local files, because the
  download log predates the repair: all ok.
- Byte inspection with stdlib `array`/`struct` on restart_0000, 0011 and 0023:
  - 2,000 random (snapshot, body) records per file matched an independent
    source unpack.
  - Vis-viva semi-major axes are 0.3871 / 0.7233 / 1.0000 / 1.5237 / 5.2076 /
    9.560 / 19.22 / 30.11 AU, which confirms pairing, component order and
    scale.
  - Low 3 bits are uniform and trailing zeros fall off geometrically: native
    integer state.
  - Positions use 44-59 bits and velocities 36-54: int64 is honest.
  - All of the first 200k values are distinct; zlib-6 ratio 0.93-0.96.
- Cross-run comparison (runs 0/1/7/23): no equal values; leading-byte
  sharing only early in each run; maximum spread at snapshot 0 measured
  across all 24 runs.
- Rights: saved `record.json` and a live Zenodo API probe both show
  `cc-by-4.0`, open access, 24 files, 634,748,768 bytes. No secrets in the
  scripts.
- Novelty: `novelty.py` URL, terms, `--vocabulary`, and `--type/--instrument/
  --archive`. No match beyond the staging recipe itself; the nearest
  semantic family is DE440s Chebyshev coefficients (float64).
- Minor non-blocking notes:
  - `verify.sh` does not re-apply the 100 AU / 10-unit magnitude bounds or
    the cadence check. Build and validate enforce both, and verify proves the
    samples are byte-identical to the source.
  - The velocity `semantic_meaning` has a typo ("velocitys").
