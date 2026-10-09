# Bit-wise Reversible JANUS Integrations of the Solar System (Rein & Tamayo, REBOUND SimulationArchive): Native Int64 Fixed-Point Planetary Phase-Space States

- Candidate id: `zenodo_janus_solar_system_integer_phase_space_i64`
- Width: int64
- Quantity: JANUS integer (fixed-point) heliocentric phase-space coordinates x,y,z,vx,vy,vz of the Sun and 8 planets (reb_particle_int, int64) at each archived snapshot of long-term Solar System integrations
- Source: https://zenodo.org/records/546258
- Resources: https://zenodo.org/api/records/546258/files/restart_0000.bin/content, https://zenodo.org/api/records/546258/files/restart_0023.bin/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/546258
- License quote: Zenodo record 'Bit-wise reversible integrations of the Solar System with JANUS': license id 'cc-by-4.0' (Creative Commons Attribution 4.0 International). Description: 'This dataset contains 24 integrations of the Solar System. The integrator is JANUS, a bit-wise reversible algorithm that uses a mix of integer and floating-point arithmetic. The files are Simulation Archives...'
- Natural record: One integration = one restart_NNNN.bin SimulationArchive: about 58,961 snapshots x 9 bodies x 6 int64 = about 3.18M int64 values (about 25.5 MB)
- Estimated samples: 24
- Estimated primary values: 76,420,000
- Estimated download bytes: 634,748,768
- Estimated primary bytes: 611,400,000
- Decode path: Pure struct. The file starts with a 64-byte ASCII banner 'REBOUND Binary File. Version: 3.2.2', then tagged fields {uint32 type, uint32 pad, uint64 size, payload}. The tags include field 85 = 9 reb_particle (1152 bytes) and field 45 = simulationarchive_size_first = 3340; the header ends at tag 9999. After byte 3340 come fixed 448-byte blobs: f64 t, f64 walltime, then 9x6 little-endian int64 (x,y,z,vx,vy,vz per body). Primary: the int64 block per blob (optionally split into position and velocity series). t and walltime are auxiliary. Check (size-3340) % 448 == 0 and the md5s from the Zenodo API.
- Novelty kind: new_modality
- Measurement type: nbody_integration_state
- Instrument line: rebound_janus_bitwise_reversible_integrator
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/546258 --terms JANUS REBOUND reversible SimulationArchive: no URL match. Only term hit is an unrelated 'reversible' in luh_lumo_tower_acceleration_f32; registry, ledger and downstream show none. The nearest existing material (DE440s Chebyshev coefficients f64, trajectory_positions f64) is floating point. No corpus family holds integer fixed-point N-body/orbital states; --type nbody_integration_state returns 0.
- Homogeneity: All 24 files come from one integrator (JANUS, REBOUND 3.2.2), one system (Sun + 8 planets), one fixed-point lattice and one archive cadence; the files differ only by initial-condition perturbation. Positions and velocities use different JANUS scales. If the judge wants strict unit coherence, emit them as two primary series (int64 positions, int64 velocities) within the family.
- Risks: (1) Positions and velocities are interleaved in the native record, so the builder may need to split them into two series. (2) The header size is assumed to be 3340 for every file; all 24 sizes satisfy (size-3340)%448==0, but the builder should read field 45 per file. (3) Planetary orbits are smooth and quasi-periodic, but in int64 with high upper-byte usage (values ~1e15-1e17), so byte statistics differ from the smooth-f64 families zlsim has rejected against. Still a risk. (4) The archive is from 2017 (REBOUND 3.2.2); the format is frozen, so this is not a liveness problem.
- Probe evidence: Range GET 0-8191 of restart_0000.bin: banner 'REBOUND Binary File. Version: 3.2.2'; tagged fields parsed with 16-byte headers through tag 9999 at offset 3324; field 4 (N) = 9, field 85 size 1152, field 45 = 0xd0c = 3340. The bytes at 3340 decode as f64 t=32317.299..., walltime 55.77, then int64s such as 1391526289809385. The next blob at +448 has t=64634.588 (an exact 2x cadence). The API lists 24 files totalling 634,748,768 bytes, each with (size-3340)%448==0 (58,902-60,692 snapshots) and published md5s.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_102323.jsonl`).
