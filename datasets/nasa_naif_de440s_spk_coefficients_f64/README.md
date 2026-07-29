# NASA/JPL DE440s SPK Coefficients (float64)

Accepted recipe for native double-precision Chebyshev position coefficients from
the NASA/JPL DE440s planetary ephemeris.

The source `.bsp` file is a NAIF Double Precision Array File containing SPK
segments. The build parses the DAF file record and summary chain, follows each
segment's word addresses, and decodes SPK type-2 records. It emits coefficient
values—not `.bsp` container bytes—using one ephemeris segment as the natural
sample.

Per-record `MID` and `RADIUS` values and the segment's `INIT`, `INTLEN`,
`RSIZE`, and `N` directory words are structural bookkeeping and are not emitted.

## Run

The user must run the network acquisition step:

```bash
bash staging/nasa_naif_de440s_spk_coefficients_f64/download.sh
```

After the kernel is present locally:

```bash
bash staging/nasa_naif_de440s_spk_coefficients_f64/build.sh
bash staging/nasa_naif_de440s_spk_coefficients_f64/verify.sh
```

Set `DATA_DIR` to use scratch storage outside the repository default `.data/`.
Set `FORCE=1` to replace an existing valid local kernel during download.

## Realized local validation

The first user download produced the expected 32,726,016-byte DE440s kernel.
After decoding, 12 full ephemeris segments produced 3,863,400 float64 values
(30,907,200 bytes), with median sample length 159,262.5 values. Two special
six-coefficient segments were reported and excluded as sub-floor natural
samples. Build and independent verification passed.
