# Blocked: DeepMind Learning to Simulate Particle Trajectories Float32

- Date: 2026-08-27
- Candidate: `deepmind_learning_to_simulate_particles_f32`
- Intended domain: graph-network particle simulations of fluids, granular
  materials, viscoelastic materials, ramps, shaking containers, and mixed
  materials
- Intended representation: one complete little-endian float32
  `time_step x particle` sample per trajectory and spatial coordinate
- Decision: blocked for training because the separately hosted datasets have no
  explicit reuse license

## Expected value

This source would provide a genuinely new num32 structure.  Its natural records
are Lagrangian particle rollouts: the same particles evolve through time under
simulated physical interactions.  Coordinate components would be kept in
separate homogeneous streams rather than interleaved.

This differs from regular image/voxel grids, static point clouds, sensor
timelines, molecular trajectories, and neural-network parameter tensors.  The
official project publishes fluid, sand, goop, mixed-material, ramp, shake-box,
continuous, extra-large, and 3D variants.

## Metadata result

Discovery pinned the official `google-deepmind/deepmind-research` revision:

```text
f5de0ede8430809180254ee957abf36ed62579ef
```

The repository README documents exact public objects under:

```text
https://storage.googleapis.com/learning-to-simulate-complex-physics/Datasets/{DATASET_NAME}/
```

The GCS bucket does not permit unauthenticated enumeration, returning HTTP 401,
but every exact WaterDrop and WaterDropSample URL documented by DeepMind is
publicly reachable.  No trajectory TFRecord payload was downloaded.

The two small metadata files establish:

- spatial dimensions: 2;
- sequence length: 1,000 time steps;
- simulation timestep: 0.0025;
- normalized box bounds: 0.1 through 0.9 on each axis; and
- published velocity and acceleration normalization statistics.

Exact object headers reported:

| Dataset/split | Bytes | GCS generation | ETag/MD5 |
|---|---:|---:|---|
| WaterDropSample train | 8,312,756 | 1599153802497211 | `54b78cacf8b00d146ac314b094fc00f4` |
| WaterDropSample valid | 6,797,732 | 1599153810263443 | `ce034d83d7d0c98104d9e22d0457dfe6` |
| WaterDropSample test | 8,833,796 | 1599153796695198 | `ae6789c477a35aeb6b2a3568aab8c115` |
| WaterDrop train | 4,541,246,980 | 1599155601295039 | `80ce396abd6628336246b525577ec8b2` |
| WaterDrop valid | 137,190,408 | 1599154542560372 | `b387c27a4848ba7bddc4d0e31c5431eb` |
| WaterDrop test | 136,885,800 | 1599154512887229 | `f3adcb63381dfa08e4b61f1eafdab43e` |

The WaterDrop validation and test splits would likely provide a useful bounded
selection without acquiring the 4.54 GB training split.  The tiny
WaterDropSample could also support a future schema/decoder probe if licensing
is resolved.

## License investigation

The repository root contains Apache License 2.0, but the repository README
describes the code and externally hosted datasets without stating that the code
license covers the data objects.

The investigation found:

- no dataset-license wording in the project README;
- no license metadata in either WaterDrop metadata JSON file;
- no discoverable license object through the bucket API because enumeration is
  not public; and
- HTTP 403 for exact `LICENSE` and `LICENSE.txt` paths at the bucket root,
  `Datasets/`, `Datasets/WaterDropSample/`, and `Datasets/WaterDrop/`.

Public readability of known TFRecord URLs is not a reuse grant.  The
Apache-2.0 repository license cannot safely be extended to separately hosted
trajectory data by inference.

## Decision and retry condition

Do not download trajectory payloads or promote this source for training under
the current evidence.  Retry only if Google DeepMind publishes an explicit
license covering the `learning-to-simulate-complex-physics/Datasets/` objects,
or adds an applicable license file to the relevant dataset directories.

Do not repeat bucket-list discovery or infer permission from the repository
code license.  If licensing is clarified, start with a bounded TFRecord-schema
probe of WaterDropSample, implemented without TensorFlow, before selecting the
real WaterDrop validation/test trajectories.

Evidence remains under
`.data/discovery/deepmind_learning_to_simulate_particles_f32/` and
`.data/logs/deepmind_learning_to_simulate_particles_f32/`.
