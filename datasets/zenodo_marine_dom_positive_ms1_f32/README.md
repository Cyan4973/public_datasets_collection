# Marine DOM Positive-Ion MS1 Spectra (float32)

Accepted successor to the rejected float64 profile-spectrum attempt. The source is
the same CC BY 4.0 Zenodo study, but this recipe accurately preserves its native
representation: positive-ion centroid MS1 m/z and intensity arrays as float32.

The fixed scope is the two pooled late-fraction positive runs
`2D_Frac_10-12a.mzML` and `2D_Frac_10-12b.mzML`. MS level and polarity are
instrument acquisition semantics, not size-based filtering. Every qualifying
MS1 spectrum is emitted as its own natural sample, including shorter scans.

```bash
bash staging/zenodo_marine_dom_positive_ms1_f32/download.sh
bash staging/zenodo_marine_dom_positive_ms1_f32/build.sh
bash staging/zenodo_marine_dom_positive_ms1_f32/verify.sh
```

## Realized validation

The two checksum-verified source files contain 706 and 695 positive-ion MS1
spectra. Build and independent verification accepted 1,401 spectra, yielding
2,802 natural samples, 6,232,014 float32 values, and 24,928,056 primary bytes.
Median natural sample length is 2,368 values (range 133–4,250).
