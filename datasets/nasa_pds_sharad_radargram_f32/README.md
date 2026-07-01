# NASA PDS SHARAD Radargram Float32

This recipe collects Mars Reconnaissance Orbiter SHARAD radargram PDS3
products and emits one native `float32` radargram sample per product.

The source labels declare:
- `SAMPLE_TYPE = PC_REAL`
- `SAMPLE_BITS = 32`

The build accepts only detached PDS3 image products whose label geometry
matches the `.img` payload exactly. Payload bytes are copied unchanged as
little-endian IEEE float32 radar backscatter power values.

Run:

```sh
datasets/nasa_pds_sharad_radargram_f32/download.sh
datasets/nasa_pds_sharad_radargram_f32/build.sh
datasets/nasa_pds_sharad_radargram_f32/verify.sh
```

For the historical staging repair, `build.sh` can also read the already-local
legacy download directory
`${DATA_DIR:-.data}/downloads/nasa_pds_sharad_radargram_i16/`; that fallback
exists because the source was originally misclassified as 16-bit.
