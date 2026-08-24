# Lower South San Francisco Bay ADCP Byte Fields

This staged recipe reuses the three CC BY 4.0 RDI PD0 recordings owned and
pinned by `datasets/zenodo_adcp_pd0_i16`, but extracts three source-native byte
blocks that the accepted velocity recipe deliberately leaves unused:

- correlation magnitude (`0x0200`);
- echo intensity (`0x0300`); and
- percent good (`0x0400`).

Each field becomes one complete recording-level tensor with shape
`[measurement_ensemble, depth_cell, beam]`. With 70,474 ensembles, 51 cells,
and four beams, each family contains 14,376,696 values; the three families
total 43,130,088 uint8 values and bytes across nine natural samples.

This adds measurement and quality-map behavior rather than duplicating the
existing signed-int16 earth-coordinate velocity values. The shared downloader
validates the accepted source cache and invokes its owner only when absent.

Run:

```bash
bash datasets/zenodo_adcp_pd0_backscatter_quality_u8/download.sh
bash datasets/zenodo_adcp_pd0_backscatter_quality_u8/build.sh
bash datasets/zenodo_adcp_pd0_backscatter_quality_u8/verify.sh
```
