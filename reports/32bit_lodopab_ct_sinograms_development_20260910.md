# LoDoPaB-CT sinogram float32 development

## Outcome

Accepted `zenodo_lodopab_ct_sinograms_f32` from the CC BY 4.0 LoDoPaB-CT
version 1.0.0 Zenodo deposit.

The new numerical geometry is a complete CT Radon-domain sinogram: one
`1000 projection angles × 513 detector bins` matrix per de-identified thoracic
CT slice. This differs from the existing IMAT tomography family, whose natural
record is one spatial detector image at a single acquisition angle.

## Bounded acquisition

Zenodo packages validation observations in a 2,944,573,582-byte ZIP, too large
to acquire as a whole for one recipe. The server supports exact byte ranges.
The recipe therefore:

1. validates record 3384092, CC BY 4.0, the outer size, and its published MD5;
2. fetches only bytes `0-106629167` containing the complete first ZIP member;
3. validates the pinned range SHA-256, ZIP local header, raw-DEFLATE boundary,
   uncompressed size, and CRC32; and
4. obtains `observation_validation_000.hdf5` without downloading the oversized
   outer ZIP.

The selected HDF5 source is 272,735,288 bytes with SHA-256
`04f0399b1d1d4ff8d012d54312b1b67f84a412d94bf935865963172e996fb977`.

## Schema and conversion

The dependency-free local parser validated:

- one root HDF5 dataset named `/data`;
- native little-endian IEEE float32;
- logical shape `128 × 1000 × 513`;
- unfiltered chunk shape `8 × 63 × 33`;
- a complete 4,096-entry chunk grid;
- finite values and no constant natural records.

Build dechunking copies source float32 words unchanged, removes only padding
outside the declared dataspace, and emits each leading-axis record as its own
row-major sinogram sample.

## Accepted output

- Samples: 128
- Values per sample: 513,000
- Bytes per sample: 2,052,000
- Total values: 65,664,000
- Total bytes: 262,656,000
- Value range: -0.000991210574284196 to 0.13053756952285767
- Zero fraction: 0.0009118999756335283
- Aggregate decoded SHA-256:
  `22f4ccaf7abb43e8b657429a25f5ab6e5dc61144e3f695af07caba0a6fbb893e`

The production build and independent source-to-output byte comparison both
completed successfully.
