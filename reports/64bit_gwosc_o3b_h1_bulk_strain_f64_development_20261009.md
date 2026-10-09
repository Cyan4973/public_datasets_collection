# GWOSC O3b LIGO Hanford bulk strain float64 development

## Outcome

Accepted `gwosc_o3b_h1_bulk_strain_f64`. It holds calibrated LIGO Hanford (H1) gravitational-wave strain h(t) from the official GWOSC O3b bulk archive, emitted as native float64.

This is the first 64-bit detector-strain family, locally or in the downstream mirror. The existing `gwosc_event_strain_f32` recipe is different:

- It parses two 32-s GW150914 text event segments into float32.
- Its source product, source file, epoch and width all differ from this recipe.

The downstream `gwosc_strain_f32` is 32-bit. Novelty is therefore new content in a known modality (`new_content_same_modality`), not a new modality.

## Source and rights

- Source: GWOSC bulk archive `https://gwosc.org/archive/data/O3b_4KHZ_R1/`, release O3b_4KHZ_R1.
- Channel and frame type: channel `H1:DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01`, frame type `H1_HOFT_CLEAN_SUB60HZ_C01`.
- Run: O3b, GPS 1256655618-1269363618, data release DOI 10.7935/pr1e-j706.
- Files: 7 pinned HDF5 files totalling 906,496,481 bytes. Each has an exact size, a sha256 observed on first download, and GWOSC's published min/max/mean/stdev recorded in `files.tsv`. GWOSC publishes no file checksums.
- License: CC BY 4.0. https://gwosc.org/acknowledgement/ states "Data from this web site are licensed under a Creative Commons Attribution 4.0 International License", and every page footer says "Data released under a CC BY 4.0 License".
- Attribution: cite ApJS 267, 29 (2023) and include the GWOSC acknowledgment. Both are carried in the manifest.

## Shape and conversion

Each natural record is one complete 4096-s GWOSC archive file. A sample is that file's `/strain/Strain` dataset: 16,777,216 float64 values at 4096 Hz.

`scripts/gwosc_h5.py` is a pure-stdlib HDF5 reader derived from the accepted SXS reader. It handles superblock v0, v1 object headers and v1 chunk B-trees, and adds:

- the `[deflate, fletcher32]` filter pipeline;
- variable-length global-heap strings.

Decoding works chunk by chunk. For each of the 2048 chunks of 8192 values:

1. Verify the chunk's Fletcher-32.
2. Inflate it to exactly 65,536 B.
3. Append it in element order.

There is no rescaling, narrowing or reordering.

Selection is set at author time by `discover.sh`:

- Split the O3b span into 7 equal bins.
- In each bin, take the 4096-aligned slot nearest the bin centre that lies wholly inside one H1_DATA segment.
- Keep the slot only if GWOSC reports dutycycle 100 and nans_fraction 0 for it.

L1, V1 and the 16 kHz release are excluded so the family stays one detector, one calibration and one sample rate.

## Accepted output

- Primary samples: 7 (GPS starts 1257562112, 1259376640, 1261191168, 1263005696, 1264824320, 1266638848, 1268449280; 2019-11-12 to 2020-03-17)
- Primary values: 117,440,512
- Primary bytes: 939,524,096
- Sample size: 16,777,216 values / 134,217,728 B each
- Downloaded bytes: 906,496,481
- Value range: -1.913e-18 to 1.571e-18; per-file stdev 4.70e-20 to 1.68e-19
- Measured breadth: OK. The nearest family is rqcd SU(3) gauge links at feature distance 0.0389 with compression loss 0.0757, so it is not compression-equivalent.

## Judge checks

- **Gate:** `gate.py` PASS, no warnings.
- **verify.sh:** the judge re-ran it and got `verify_ok samples=7 bytes=939524096`. This covers a byte-exact re-decode of every source, the index fields and the manifest totals.
- **Decode correctness:** decoded per-file mean and stdev match GWOSC's independently published values to ~1e-13 relative; min/max are identical.
- **Element order:** stdlib boundary test. Mean |diff| at chunk boundaries equals the interior value (e.g. 0.0175 vs 0.0177 sd), whereas a one-chunk misorder gives about 1.1 sd.
- **Width honesty:**
  - 0 of 1,048,576 values are float32-exact.
  - Mantissa trailing-zero counts follow a geometric distribution, so the full 52-bit precision is used.
  - All values checked are distinct, with no fill.
- **Content:** PSDs from stdlib FFTs show low-frequency-dominated colored noise in six files (lag-1 autocorrelation 0.989-0.9998). Two files show natural detector non-stationarity within the same quantity and unit:
  - The Nov-2019 file is dominated by a growing ~1010 Hz violin-mode line (70% of power).
  - The Feb-2020 file has a broadband rise in its last 512 s.
- **Selection:** the files sit at bin fractions 1/14, 3/14, …, 13/14 of the run. Each is 4096-aligned and inside its pinned H1_DATA segment.
- **Rights:** the judge fetched the acknowledgement page and confirmed the CC BY 4.0 grant for site data. No credentials, no personal data.
- **Novelty:** `novelty.py` checks by URL, terms and type/instrument/archive find no 64-bit GW strain. The same-host match, gwosc_event_strain_f32, uses a different source file.
- **Volume:** 7 samples is the maximum of whole 134 MB records under the 1 GB cap, consistent with accepted large-record families (csiro_parkes_uwl, figshare_rmd17, zenodo_gia, nasa_pds_mola). The extraction ratio is about 1.04.
