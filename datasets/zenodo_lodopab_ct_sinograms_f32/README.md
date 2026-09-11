# LoDoPaB-CT sinograms float32

This recipe collects low-dose CT observation sinograms from the LoDoPaB-CT
machine-learning benchmark. A natural record is one patient slice represented
in projection space: approximately 1,000 acquisition angles by 513 detector
bins, rather than a reconstructed spatial image.

This geometry is distinct from the accepted tomography material:

- `zenodo_imat_neutron_projections_f32` stores one two-dimensional detector
  image for each individual acquisition angle;
- this recipe stores the complete angle-by-detector Radon sinogram for
  one CT slice.

Only observation sinograms are retained. Reconstructed ground-truth CT images,
patient identifiers, split indices, acquisition geometry, and other fields
must not be interleaved with the observation matrix. Each source HDF5 record
must remain one sample and must be serialized as canonical little-endian
float32.

The first step is metadata-only. It queries the official Zenodo record, checks
that its license permits training use, inventories exact files and checksums,
and identifies bounded observation-shard candidates without downloading them.

Run from the repository root:

```bash
bash datasets/zenodo_lodopab_ct_sinograms_f32/download.sh
bash datasets/zenodo_lodopab_ct_sinograms_f32/build.sh
bash datasets/zenodo_lodopab_ct_sinograms_f32/verify.sh
```

Discovery results are written below
`.data/discovery/zenodo_lodopab_ct_sinograms_f32/`, with logs below
`.data/logs/zenodo_lodopab_ct_sinograms_f32/`.

The local schema probe established the HDF5 dataset path, native dtype, exact
per-record shape, missing/non-finite behavior, shard record count, and decoded
output volume.

Zenodo exposes the observations as three oversized ZIP objects: validation is
2.94 GB, test is 3.00 GB, and training is 29.94 GB. `discover_zip.sh` therefore
requests only the final 4 MiB of the validation ZIP, validates HTTP byte-range
behavior, and parses its ZIP central directory. This determines whether exact
member-level acquisition can remain bounded without first downloading the
oversized outer archive.

`download_probe.sh` transfers only the exact ZIP byte range containing
`observation_validation_000.hdf5` (about 106.6 MB compressed), validates the
local ZIP header and central-directory metadata, inflates raw DEFLATE locally,
and checks the member's declared size and CRC32. It does not download the
2.94 GB outer archive.

`probe_hdf5.py` is local-only and dependency-free. It validates the HDF5
superblock, single `data` dataset, native little-endian float32 datatype,
`128 × 1000 × 513` shape, chunk B-tree and complete chunk grid, then scans all
valid values for finiteness and per-sinogram nondegeneracy.

The validated probe contains 128 complete `1000 × 513` sinograms: 65,664,000
native float32 values and 262,656,000 decoded bytes. One shard therefore
provides sufficient volume without acquiring additional highly correlated
validation shards. `download.sh` is the pinned acceptance downloader; it
validates the live Zenodo record and reuses the already verified local HDF5
when present.

The complete build emits 128 natural-record samples, each containing 513,000
values (2,052,000 bytes), for 65,664,000 values and 262,656,000 bytes total.
The aggregate decoded-byte SHA-256 is
`22f4ccaf7abb43e8b657429a25f5ab6e5dc61144e3f695af07caba0a6fbb893e`.
