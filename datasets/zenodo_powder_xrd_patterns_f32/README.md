# Zenodo Powder-XRD Patterns Float32 — Discovery

This candidate searches Zenodo for experimental one-dimensional powder X-ray
diffraction scans under explicit CC0 or CC BY licenses. It targets measured
intensity curves, not rendered plots, papers, simulated reference patterns,
single-crystal coordinate files, or two-dimensional detector images.

Run from the repository root:

```bash
bash datasets/zenodo_powder_xrd_patterns_f32/discover.sh
```

The discovery is bounded. It fetches Zenodo metadata, ZIP central directories,
and at most small text members or prefixes needed to establish a plausible
numeric table. It does not download complete large archives.

Results are written under `.data/discovery/zenodo_powder_xrd_patterns_f32/`,
with the durable log at
`.data/logs/zenodo_powder_xrd_patterns_f32/discover.latest.log`.

A follow-up source must provide several complete experimental scans with at
least 1,000 intensity values per natural sample. The angular coordinate is
alignment metadata; only the measured intensity array is intended as primary
little-endian float32 material.

Broad discovery identified Zenodo record `4955141`, *Data from: Pressure-induced
symmetry changes in body-centred cubic zeolites*, as the strongest source. It
is CC0 and contains pressure-series `.xy` scans for empty and filled Na-X and
RHO zeolites. Run the exact-record preflight with:

```bash
bash datasets/zenodo_powder_xrd_patterns_f32/preflight.sh
```

The preflight retrieves record metadata and ZIP ranges for every eligible `.xy`
member, but does not download the complete archive. It rejects unrelated text
tables, validates strict two-column scan geometry, and measures unique float32
intensity payloads. The source contains one exact duplicate pair
(`zFAUf_p18.xy` and `zFAUf_p19.xy`); the lexicographically first scan is kept.

The accepted workflow is:

```bash
bash datasets/zenodo_powder_xrd_patterns_f32/download.sh
bash datasets/zenodo_powder_xrd_patterns_f32/build.sh
bash datasets/zenodo_powder_xrd_patterns_f32/verify.sh
```

It emits 147 complete intensity scans containing 647,009 little-endian float32
values and 2,588,036 primary bytes. Natural sample lengths range from 4,396 to
4,405 values, with a median of 4,403.
