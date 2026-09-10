# Rejected: The Well MHD-64 trajectories float32

- Date: 2026-09-10
- Candidate: `the_well_mhd64_trajectories_f32`
- Source: `polymathic-ai/MHD_64` on Hugging Face
- Pinned repository revision: `ede5ad0479ede939d5b0cc616e45fd9d3cbcb245`
- Intended representation: separate native-float32 magnetohydrodynamic physical fields
- Status: rejected

## Why it was considered

The Well MHD-64 dataset is a modern scientific-machine-learning benchmark for
compressible magnetohydrodynamic turbulence. Its documentation describes 100
timesteps of uniform `64 x 64 x 64` cubes with density, velocity, and magnetic
fields. Test and validation resources are individually bounded: 20 HDF5 files
are 734,041,296 bytes each, below the repository's one-gigabyte source cap.

The domain is attractive and AI-adjacent, and the separate scalar/vector
fields could provide substantial numerical volume.

## Metadata-only result

The user-run discovery fetched no HDF5 numerical payload. It established:

- one exact public repository, `polymathic-ai/MHD_64`;
- 31 HDF5 resources in total;
- 20 test/validation resources below one gigabyte;
- exact LFS SHA-256 identities for the bounded resources;
- a uniform Cartesian grid at `64^3` resolution;
- 100 timesteps per trajectory; and
- density, three velocity components, and three magnetic-field components.

Evidence is under:

- `.data/discovery/the_well_mhd64_trajectories_f32/summary.json`;
- `.data/discovery/the_well_mhd64_trajectories_f32/repositories.tsv`;
- `.data/discovery/the_well_mhd64_trajectories_f32/candidate_hdf5_files.tsv`;
- `.data/discovery/the_well_mhd64_trajectories_f32/documentation_hits.tsv`; and
- `.data/logs/the_well_mhd64_trajectories_f32/discover.latest.log`.

## Rejection reasons

### No explicit dataset license

The exact Hugging Face repository has no `cardData`, no license tag, and no
LICENSE/COPYING file in its complete repository tree. Its README provides a
paper citation but no reuse grant. Public accessibility and association with
The Well or Polymathic AI are not substitutes for an explicit license, and a
code-repository license must not be inferred to cover separately hosted data.

### Not a new homogeneous shape

The initial rank-4 trajectory idea would have mixed temporal and spatial
traversal regimes in one flattened payload. Under the collection's homogeneous
series rule, time and the three coordinate arrays must not be concatenated.
Separating by timestamp, physical field, and vector component leaves ordinary
dense `64 x 64 x 64` scalar volumes on a uniform Cartesian grid.

The accepted 32-bit corpus already contains dense 3D MRI, astronomical, dose,
weather-pressure, and other volumetric fields. MHD-64 contributes a new domain
but not a genuinely new per-sample numerical layout for the num32 model.

## Retry condition

Do not retry `polymathic-ai/MHD_64` merely because its files are reachable or
native float32. Reconsider only if both conditions change:

1. the exact dataset repository publishes an explicit training-compatible
   license; and
2. a separately stored homogeneous field exposes a genuinely new layout, such
   as sparse, unstructured, staggered/face-centered, adaptive, or
   multiresolution data without combining coordinate arrays or physical
   fields.
