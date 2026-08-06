# Neuropixels Opto Kilosort Templates Float32

This recipe extracts 14 native little-endian float32 Kilosort 4 spike-template
tensors from seven exact CC BY 4.0 mouse Neuropixels Opto session archives.

Run:

```bash
bash datasets/zenodo_npx_opto_templates_f32/download.sh
bash datasets/zenodo_npx_opto_templates_f32/inspect.sh
bash datasets/zenodo_npx_opto_templates_f32/build.sh
bash datasets/zenodo_npx_opto_templates_f32/verify.sh
```

The downloader reads ZIP/ZIP64 central directories and range-extracts only the
14 `templates.npy` members: about 13.93 MB transferred and 140.42 MB of numeric
payload retained. It does not download the seven parent archives, whose
combined size is about 34.6 GB.

Each output sample is one complete session tensor in source C order with axes
`spike_template × 61 time samples × probe channel`. Channel and template counts
vary naturally by session.
