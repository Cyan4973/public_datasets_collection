# TCIA LDCT-and-Projection-data Siemens full-dose CT projection views uint16 development

## Outcome

Accepted `tcia_ldct_siemens_ct_projections_u16`: measured clinical helical-CT data in the projection domain.

- Each sample is one complete DICOM-CT-PD projection view from a Siemens SOMATOM Definition Flash: one gantry angle and table position, 736 detector channels x 64 detector rows.
- Values are stored as native unsigned 16-bit codes of vendor-corrected, log-converted X-ray attenuation line integrals.

This is a new quantity for the corpus. The only CT projection material so far is `zenodo_lodopab_ct_sinograms_f32`: simulated parallel-beam float32 sinograms derived from LIDC images. The other projection families are electron-microscope tilt series (`zenodo_tem_tilt_series_i16`) and neutron radiography (`zenodo_imat_neutron_projections_f32`), both different modalities. No local, registry, ledger or downstream row covers LDCT-and-Projection-data.

## Source and rights

- Source: The Cancer Imaging Archive, *Low Dose CT Image and Projection Data* (LDCT-and-Projection-data), Version 7, DOI 10.7937/9npb-2637.
- Access: anonymous NBIA v1 REST endpoints `getSeries`, `getSOPInstanceUIDs` and `getSingleImage`, called by curl only, with no credentials.
- License: CC BY 4.0.
  - The collection page's Version 7 table lists "Images of the Chest" (99 subjects) and "Images of the Liver" (100 subjects) as CC BY 4.0.
  - The version history states: "Changed license for Chest and Liver patients from NIH Controlled Data Access (TCIA Restricted) to CC 4.0."
  - All 698 rows of the live `getSeries` listing carry LicenseURI `https://creativecommons.org/licenses/by/4.0/`, including the 100 pinned rows.
  - Head (`N*`) subjects remain NIH-controlled. They are not listed by the public API and are not used.
- Required citation: McCollough et al. (2020), DOI 10.7937/9npb-2637. Publications should acknowledge grants EB017095 and EB017185.
- Safety: the source DICOMs are de-identified (IdentityRemoved=YES, DICOMANON). Only pixel codes are emitted. The index carries technical metadata and TCIA pseudonymous IDs, matching accepted TCIA peers.

## Shape and conversion

- Scope: all 100 public series with Manufacturer `SIEMENS` and SeriesDescription `Full dose projections`, i.e. 50 chest (`C###`) and 50 abdomen (`L###`) subjects with 2,958,812 views in total. All are pinned with UIDs, counts and sizes.
- Excluded: low-dose series (noise-simulated), GE series, reconstructed images and head subjects.
- Selection: 20 views per series, at ranks `floor((2i+1)n/40)` of the lexicographically sorted SOP UIDs. The UIDs are opaque hashes, so this is a deterministic pseudo-random draw. Selected views span 72–99% of each scan (median 92%).
- Natural record: one DICOM Raw Data Storage instance, which is one projection view. Nothing is tiled or concatenated.
- Decode: a pure-stdlib Implicit VR LE walker that descends undefined-length sequences. Each instance must satisfy:
  - Rows=736, Columns=64, 16/16/15, unsigned, MONOCHROME2;
  - Mayo `CtProjectionData-MayoClinc-v1` private creators;
  - HELICAL/FANBEAM/CYLINDRICAL geometry, with all seven preprocessing flags set to YES;
  - Pixel Data as the final 94,208-byte element, with decoded min/max equal to the Smallest/Largest Image Pixel Value tags.
- Output: Pixel Data is written unchanged as LE uint16 `[736, 64]`, with the 64 detector-row values of each channel contiguous.
- Auxiliary metadata (index only): slope, intercept, kVp, mA, FFS mode, angular steps, focal-centre angle and z position.
- Acquisition groups, one scanner and FFSZ throughout:
  - 50 chest series at 120 kVp, 1,152 angular steps per rotation;
  - 14 abdomen series at 120 kVp, 2,304 steps;
  - 36 abdomen series at 100 kVp, 2,304 steps.
- The per-series rescale slope (1.12e-4 to 2.01e-4) and intercept (-0.268 to -0.134) normalize each series' line-integral range to the 16-bit code range. Stored-code distributions match across the groups.

## Accepted output

- Series: 100 (50 chest, 50 abdomen), 20 views each
- Primary samples: 2,000
- Primary values: 94,208,000 uint16
- Primary bytes: 188,416,000
- Sample size: 47,104 values (94,208 bytes), for every sample, so the median is the same
- Code range: 45..65535. One view (`L203_i001583`) has 64 codes at the 65535 ceiling.
- Distinct values per view: minimum 3,003, median 18,040, maximum 24,783
- Download: 435,780,524 bytes:
  - 0.55 MB series listing
  - 235.9 MB SOP UID listings
  - 198.3 MB DICOM (2,000 objects of 99,136–99,148 bytes)

## Judge checks

- `python3 tools/autocollect/gate.py staging/tcia_ldct_siemens_ct_projections_u16`: PASS, no warnings.
- Ran `verify.sh` myself: `verify=ok samples=2000 bytes=188416000 series=100 range=45..65535 min_distinct_per_view=3003`.
- Read every recipe file. build.sh uses only local downloads plus the pins file. download.sh is curl-only and anonymous. The download log shows 2,000/2,000 instances fetched with no retries.
- Bytes, using stdlib `array('H')` on 15 samples plus scans of all 2,000:
  - Layout is confirmed: the contiguous axis is smoother than the 64-stride axis.
  - Converted to line integrals, profiles show air (about 0) at the edge channels and 3–9 in the body centre.
  - All 2,000 sample hashes are unique. The closest same-series pairs (1–3 instances apart) share about 0.2% of their values, with a mean absolute difference of about 300 codes.
- Homogeneity: 4096-bin code histograms and per-view mean and distinct-value medians match across the three kVp and body-part groups.
- Source quirk: 185 views in the first or last ~10% of a scan contain edge-contiguous blocks of identical detector rows, up to 56 of 63 adjacent pairs. This is adaptive z-collimation, with shielded rows filled by the vendor export. It is source content, not a recipe artifact.
- Rights: opened the TCIA collection page and confirmed CC BY 4.0 for Chest and Liver plus the Version 7 relicensing note. Confirmed the LicenseURI on all 100 pinned rows of the local listing.
- Novelty: ran `novelty.py` on the collection URL and the getSeries URL with LDCT, DICOM-CT-PD, helical, sinogram, projection and nbia-api terms. Nothing else covers this collection or measured CT projection data.
- Documentation nit: the README says per-view distinct values reach "about 30k". The realized maximum is 24,783 (the minimum of 3,003 and median of 18,040 are correct).
