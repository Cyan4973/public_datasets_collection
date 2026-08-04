# SARS-CoV-2 TEM Tilt-Series Int16

This recipe extracts a coherent half-rate angular sequence from a raw
transmission-electron-tomography tilt stack in Zenodo record `3985424`, released
under CC BY 4.0.

The immutable source MRC contains 125 uncompressed 2048x2048 mode-1 projections
from approximately -62 to +62 degrees. Its complete 1,048,576,000-byte numeric
field exceeds the repository's decimal 1 GB limit. Because each projection is
an independently addressable uncompressed natural record, the downloader uses
HTTP ranges to acquire even indices `0,2,...,124` directly. This yields 63
complete frames spanning the full tilt range without downloading the oversized
source object.

Run:

```bash
bash datasets/zenodo_tem_tilt_series_i16/download.sh
bash datasets/zenodo_tem_tilt_series_i16/inspect.sh
bash datasets/zenodo_tem_tilt_series_i16/build.sh
bash datasets/zenodo_tem_tilt_series_i16/verify.sh
```

Each emitted sample is one source-identical little-endian signed-int16 detector
plane. MRC and FEI headers are retained only as provenance and geometry
metadata, not as training bytes.
