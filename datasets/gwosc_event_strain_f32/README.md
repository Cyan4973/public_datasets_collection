# GWOSC Event Strain F32

Accepted recipe for GWOSC gravitational-wave detector strain text releases.

This is a new shape for the collection: calibrated interferometer strain time
series around compact-binary events. It is not speech/audio, seismic ground
motion, finance ticks, imagery, mesh data, or model tensors.

Scope:

- source: Gravitational Wave Open Science Center public event strain releases
- default seed: GW150914, H1 and L1, 32 seconds at 4096 Hz
- natural sample boundary: one detector-event strain segment per source text gzip
- primary array: one little-endian `float32` detector strain stream per segment
- missing policy: reject malformed, non-finite, multi-column, tiny, or constant-prefix files
- output cap: primary samples must remain under 1 GB

The default seed is intentionally conservative and exact. To extend the recipe
with more GWOSC event-detector text strain files, provide a whitespace-separated
URL list:

```text
# event detector url
GW151226 H1 https://.../H-...txt.gz
GW151226 L1 https://.../L-...txt.gz
```

Then run:

```bash
GWOSC_URLS_FILE=/path/to/gwosc_urls.txt bash datasets/gwosc_event_strain_f32/download.sh
bash datasets/gwosc_event_strain_f32/build.sh
bash datasets/gwosc_event_strain_f32/verify.sh
```

For the default seed:

```bash
bash datasets/gwosc_event_strain_f32/download.sh
bash datasets/gwosc_event_strain_f32/build.sh
bash datasets/gwosc_event_strain_f32/verify.sh
```

The download stage writes `download_plan.tsv`, `download_inventory.tsv`,
`download_inventory.json`, and `download_failures.tsv` under
`.data/downloads/gwosc_event_strain_f32/`. The build/verify stages write
material statistics under `.data/filtered/gwosc_event_strain_f32/` and the
machine-readable sample index under `.data/index/gwosc_event_strain_f32/`.
