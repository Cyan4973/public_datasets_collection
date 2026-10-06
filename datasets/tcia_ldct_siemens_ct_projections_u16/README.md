# TCIA LDCT-and-Projection-data: Siemens full-dose helical CT projection views (uint16)

Measured clinical helical CT data in the projection domain. Each sample is one
complete projection view: a single gantry angle and table position, covering
all 736 detector columns (channels) by 64 detector rows of a Siemens SOMATOM
Definition Flash scanner. The values are the stored 16-bit codes of the
DICOM-CT-PD format (Chen et al., Med. Phys. 2015). The vendor has already
corrected and log-converted the signal, so each code is a quantized X-ray
attenuation line integral (`code × RescaleSlope + RescaleIntercept`), not a
raw photon count.

## Source and license

- Collection: The Cancer Imaging Archive, *Low Dose CT Image and Projection
  Data* (LDCT-and-Projection-data), Version 7,
  DOI [10.7937/9npb-2637](https://doi.org/10.7937/9npb-2637).
- License: CC BY 4.0. The collection page lists the "Images of the Chest" and
  "Images of the Liver" downloads as CC BY 4.0 and says: *"Changed license for
  Chest and Liver patients from NIH Controlled Data Access (TCIA Restricted)
  to CC 4.0."* Every pinned NBIA series row carries
  `LicenseURI = https://creativecommons.org/licenses/by/4.0/`, and
  `download.sh` re-checks this on every run. The head (`N*`) subjects are
  still NIH-controlled. They are not listed by the public API and are not
  used.
- Required citation: McCollough, C., Chen, B., Holmes III, D., Duan, X., Yu,
  Z., Yu, L., Leng, S., Fletcher, J. (2020). Low Dose CT Image and Projection
  Data (LDCT-and-Projection-data) (Version 7) [dataset]. The Cancer Imaging
  Archive. https://doi.org/10.7937/9npb-2637
- Access: anonymous NBIA v1 REST endpoints (`getSeries`,
  `getSOPInstanceUIDs`, `getSingleImage`). No credentials are used.

## Scope and selection

- Series: all 100 public series with `Manufacturer = SIEMENS` and
  `SeriesDescription = "Full dose projections"`. That is 50 chest (`C###`,
  `CHEST`) and 50 liver/abdomen (`L###`, `ABDOMEN`) subjects, one series
  each, 2,958,812 instances in total. They are pinned in `series_pins.tsv`
  with series/study UIDs, instance counts and byte sizes. `download.sh`
  fails if the live listing drifts. `scripts/make_series_pins.py` documents
  how the pins were derived from one `getSeries` listing.
- Excluded: `Low dose projections` (the low dose is simulated by noise
  insertion), every GE series (different detector, 62–119 KB per instance),
  reconstructed image series, and the NIH-controlled head subjects.
- Views: 20 per series, 2,000 in total. For each series the full SOP
  Instance UID listing is sorted lexicographically, and ranks
  `floor((2i+1)·n/40)` for `i = 0..19` are taken. The UIDs are opaque hashes
  unrelated to acquisition order, so this is a deterministic pseudo-random
  draw of views spread over the whole helical scan. Samples are named
  `<PatientID>_i<InstanceNumber>.bin`. The `InstanceNumber` and the per-view
  focal-centre angle and z position are recorded in the index.

The views are subsampled because one series holds 11k–92k views (1.1–9.1 GB).
The whole collection would exceed the 1 GB cap by two orders of magnitude.
Each view is still a complete natural record. Nothing is tiled or
concatenated.

## Format and conversion

- Source object: DICOM Raw Data Storage (SOP class
  `1.2.840.10008.5.1.4.1.1.66`), Implicit VR Little Endian, preceded by an
  Explicit VR group-0002 meta header. Mayo private groups 7029–7041
  (`CtProjectionData-MayoClinc-v1`) carry the geometry. A pure-stdlib walker
  descends undefined-length sequences and items, including the empty
  `(0040,0555)` sequence, to their `FFFE` delimiters.
- Checks on every instance: Rows=736, Columns=64 (matching DICOM-CT-PD
  `NumberofDetectorColumns=736` and `NumberofDetectorRows=64`),
  BitsAllocated=BitsStored=16, HighBit=15, PixelRepresentation=0, one
  MONOCHROME2 sample, `HELICAL`/`FANBEAM`/`CYLINDRICAL`, and all seven
  preprocessing flags `(7039,1003..1009)` = `YES` (beam-hardening, gain,
  dark-field, flat-field, bad-pixel and scatter correction, plus LogFlag).
  Pixel Data must be the final element and exactly 94,208 bytes. The decoded
  min/max must equal the `(0028,0106/0107)` Smallest/Largest Image Pixel
  Value tags.
- Output: the Pixel Data bytes unchanged. Each sample is little-endian
  uint16 of shape `[736, 64]` (detector column major, 64 detector-row values
  per column): 47,104 values or 94,208 bytes per sample. Index min/max come
  from the stored codes.
- Auxiliary only (index rows, not samples): RescaleSlope/RescaleIntercept
  (constant within each series; build fails otherwise), kVp, tube current,
  flying-focal-spot mode, source angular steps per rotation, focal-centre
  angle and z position, source SHA-256.

## Expected output

| quantity | value |
| --- | --- |
| samples | 2,000 (1,000 chest + 1,000 abdomen) |
| values | 94,208,000 uint16 |
| bytes | 188,416,000 |
| download | 435.8 MB realized: 0.55 MB series listing, 235.9 MB SOP UID listings, 198.3 MB DICOM (2,000 objects of 99,136–99,148 bytes) |

The SOP UID listings make up more than half of the download. NBIA serves
them as uncompressed JSON (about 80 bytes per UID), and the public API has
no lighter way to address individual views. They are cached, and
`verify.sh` uses them to re-derive the selection.

## Homogeneity notes

All 100 series come from one scanner model, use one detector geometry and
one DICOM-CT-PD encoding: corrected, log-converted line integrals quantized
to uint16, all with FFSZ flying focal spot. Realized acquisition groups,
from `filtered/<id>/ingest_stats.json`:

| group | series | kVp | angular steps / rotation | rescale slope |
| --- | --- | --- | --- | --- |
| chest (`C###`) | 50 | 120 | 1,152 | 1.31e-4 – 2.01e-4 |
| abdomen (`L###`) | 14 | 120 | 2,304 | 1.39e-4 – 1.97e-4 |
| abdomen (`L###`) | 36 | 100 | 2,304 | 1.12e-4 – 1.78e-4 |

Rescale intercepts range from -0.268 to -0.134, and tube current from 38 to
796 mA. The slope varies within every group. It appears to be chosen per
series so that the series' line-integral range fills the 16-bit code range.
The stored codes therefore look alike across the groups:

| group | per-view mean code (median) | distinct values per view (median) | max line integral per series (median) |
| --- | --- | --- | --- |
| 100 kVp abdomen | ~15.5k | ~18.5k | 8.3 |
| 120 kVp abdomen | ~19.6k | ~20.2k | 9.0 |
| 120 kVp chest | ~14.3k | ~17.2k | 8.4 |

Angular steps per rotation affect only the spacing between views, not the
contents of a single 736×64 view. The 100 kVp abdomen scans have a softer
spectrum, so their physical attenuation differs somewhat. Their encoding,
unit (dimensionless line integral) and code range are the same.

Realized range: codes 45..65535. A single view (`L203_i001583`) has 64 of
its 47,104 codes at the 65535 ceiling (encoder saturation). They are kept
unchanged as source values. Per-view distinct values range from 3,003 (a
scan-start/end chest view) to about 30k, with a median of 18,040. Within
each scan, the selected views span 72–100% of the InstanceNumber range
(median 92%).

## Run

```bash
bash staging/tcia_ldct_siemens_ct_projections_u16/download.sh
bash staging/tcia_ldct_siemens_ct_projections_u16/build.sh
bash staging/tcia_ldct_siemens_ct_projections_u16/verify.sh
```

`DATA_DIR` (default `.data`) selects the data root, and `DELAY_SECONDS`
(default 0.2) sets the pause between API requests. Re-runs reuse validated
listings and instances. Logs are written to
`$DATA_DIR/logs/tcia_ldct_siemens_ct_projections_u16/`.
