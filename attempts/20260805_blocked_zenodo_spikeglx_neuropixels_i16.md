# Blocked: Zenodo SpikeGLX Neuropixels Int16

- Date: 2026-08-05
- Candidate: `zenodo_spikeglx_neuropixels_i16`
- Intended domain: non-human high-density extracellular neural recordings
- Intended representation: native little-endian interleaved signed-int16 probe samples
- Intended natural sample: complete or bounded time-by-electrode matrices

## Discovery performed

A license-first bounded search queried Zenodo for SpikeGLX, Neuropixels,
`ap.bin`, and `imec` records. It required CC0 or CC BY licensing, explicit
SpikeGLX/Neuropixels semantics, and clearly non-human context while rejecting
human, patient, clinical, and ambiguous-species records.

The final search examined 154 unique records:

- 128 declared an allowed license;
- 36 had explicit SpikeGLX/Neuropixels semantics; and
- 27 were clearly non-human.

Their complete Zenodo file inventories were inspected for modern AP/LF pairs,
legacy `imec.bin` pairs, compressed `.cbin`, NWB, and archives. ZIP central
directories were read remotely with bounded tail/range requests; no complete
archive was acquired.

## Result

No directly decodable native-int16 source qualified:

- zero direct `.ap.bin`/`.meta`, `.lf.bin`/`.meta`, or legacy
  `imec.bin`/`.meta` pairs were present;
- zero direct `.ap.cbin` or `.lf.cbin` files were present;
- 38 direct NWB files were exposed across three records; and
- 22 ZIP archives were successfully inspected, but none contained a raw
  SpikeGLX `.bin`/`.meta` pair.

The inspected ZIP objects total about 15.9 GB compressed and 30.5 GB declared
uncompressed. Their candidate contents are processed NPY/ALF/model outputs,
code, or other derived products rather than documented source-order int16
electrode matrices. The remaining archive types include TAR/7z/RAR or similarly
large processed bundles.

NWB is HDF5-based. This environment has neither `h5py` nor `h5dump`, and adding
an HDF5/NWB stack or attempting a dependency-heavy source build is
disproportionate for a speculative width hunt. No complete recordings were
downloaded and no samples were built.

This attempt is blocked rather than permanently rejected because a future
record may expose an exact direct SpikeGLX pair. Retry only with either:

- a permissively licensed direct `.bin`/`.meta` pair of manageable size; or
- an exact NWB source whose native int16 dataset and a simple already-available
  decoder are established in advance.

Do not repeat the same broad Zenodo/archive search without such a lead.

Ephemeral evidence:

- `.data/logs/zenodo_spikeglx_neuropixels_i16/discover.latest.log`
- `.data/discovery/zenodo_spikeglx_neuropixels_i16/summary.json`
- `.data/discovery/zenodo_spikeglx_neuropixels_i16/record_inventory.tsv`
- `.data/discovery/zenodo_spikeglx_neuropixels_i16/archive_inventory.tsv`
- `.data/discovery/zenodo_spikeglx_neuropixels_i16/qualified.tsv`
- `.data/discovery/zenodo_spikeglx_neuropixels_i16/query_failures.tsv`
