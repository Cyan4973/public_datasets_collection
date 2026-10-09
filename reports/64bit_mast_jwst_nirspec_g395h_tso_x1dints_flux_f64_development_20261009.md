# JWST NIRSpec G395H TSO x1dints FLUX float64 development

## Outcome

Accepted `mast_jwst_nirspec_g395h_tso_x1dints_flux_f64`. It contains per-integration extracted
1-D spectra from JWST NIRSpec bright-object time series (BOTS). Each sample is the complete
`FLUX` column of the `EXTRACT1D` table of one public Level-2 `*-seg001_nrs1_x1dints.fits`
product: one row per integration and ~1,272 wavelength bins per row (2.86–3.72 µm), in native
float64 Jy.

This is the first 64-bit spectral-flux family in the local corpus. The `spectrum_1d` type
exists only at 32 bits (DESI DR1 coadd flux, ICRAF soil MIR, marine DOM MS1, powder XRD), and
the only other JWST recipe is `mast_jwst_nircam_sw_uncal_ramps_u16` (raw u16 imaging ramps).
Novelty kind: new content in a known modality, at a new width and from a new instrument. The
zlsim breadth verdict is OK: the nearest family is `ourairports_latitude` at feature distance
0.0872.

## Source and rights

- Discovery: MAST `Mast.Caom.Filtered` / `Mast.Caom.Products`
  (`https://mast.stsci.edu/api/v0/invoke`) with JWST, `timeseries`, `NIRSPEC/SLIT`,
  `F290LP;G395H` and calib_level 3. This returned 140 observations: 125 PUBLIC (122 SUB2048)
  and 15 EXCLUSIVE_ACCESS (excluded).
- Data: `https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/<file>`,
  anonymous HTTPS range reads. ETag, served size, CAL_VER/CRDS_CTX/SDP_VER and the EXTRACT1D
  layout are pinned per file in `sources.tsv`.
- License: MAST Data Use Policy (<https://archive.stsci.edu/publishing/data-use>, fetched
  2026-10-09): "Most data hosted at MAST are in the public domain ... and therefore do not have
  restrictions on use." The only exceptions are exclusive-access data (public "without
  restriction" after expiry), HLSPs (CC BY 4.0) and DSS/GSC (copyright). These are JWST
  mission pipeline products with `dataRights = PUBLIC`. This is the same basis as the accepted
  NIRCam ramps recipe.

## Shape and conversion

- Regime, enforced from FITS cards at discover, download, build and verify:
  - `TELESCOP=JWST`, `INSTRUME=NIRSPEC`, `DATAMODL=TSOMultiSpecModel`, `EXP_TYPE=NRS_BRIGHTOBJ`
  - `FXD_SLIT=S1600A1`, `FILTER=F290LP`, `GRATING=G395H`, `DETECTOR=NRS1`, `SUBARRAY=SUB2048`
  - `EXSEGNUM=1`, `INTSTART=1`, `NAXIS2 = INTEND-INTSTART+1`
  - FLUX is `nD` in `Jy`; WAVELENGTH is `nD` in `um`
- Selection: one product per normalized target (70 targets; newest CAL_VER first, then lowest
  file name). The four largest products were then dropped to cap FLUX at 500 MB, leaving 66
  products from 45 programs.
- Download: header pieces (57,600-byte ranges) up to EXTRACT1D, then HTTP multi-range requests
  of ≤150 rows that read only the 8n FLUX bytes of each row. Each part is matched by exact
  Content-Range, ETag and total size. `--max-filesize` forbids whole-file fallback.
- Conversion: the FLUX row offset is computed from the preceding TFORMs (observed 4 + 8n), rows
  are concatenated in table order, and the result is byte-swapped from big-endian to
  little-endian float64. Nothing is rounded, rescaled or masked. Sample shape is
  `[NAXIS2, n]`, row-major.
- Missing values: NaN is the pipeline's native fill for extraction-edge bins (bins 0–26 and the
  last 5 of each row) and is kept bit-for-bit. Every row must be ≥90% finite, have ≥2 distinct
  values and contain no infinities.
- Known native artifact: one bad detector column gives one extreme bin per row (bin 230–233,
  tracking n). Its values are about −5.5e3 to −6.2e3 Jy (near-constant) in CAL_VER 2.0.1
  products and fluctuate ±1e4–1.5e6 Jy in 3.0.0 products. It is not flagged in DQ, makes up
  0.08% of values, and is kept unmasked and documented.

## Accepted output

- Samples: 66, one per target, from 45 programs, observed 2022-05-30 to 2026-07-30
- Integrations: 49,094; bins per row: 1,271–1,274
- Primary values: 62,455,583
- Primary bytes: 499,644,664
- Rows per sample: 8–1,462; values per sample: 10,168–1,861,126 (median 886,584; gate median
  884,040)
- NaN values: 1,579,373 (2.53%)
- Pipeline versions: 42 products at CAL_VER 3.0.0 / jwst_1584.pmap, 24 at 2.0.1 /
  jwst_1535.pmap
- Transfer: 506,781,092 bytes in total; all 66 products matched their pinned ETag (0
  reprocessed)

## Judge checks

- `gate.py`: PASS with no warnings. I ran `verify.sh` myself and it succeeded (66 ok;
  programs=45, targets=66, nan_fraction=0.0253).
- Independent upstream check: I range-fetched one full 178,000-byte EXTRACT1D row (row 3 of
  jw03375001001) from MAST. Its FLUX bytes decoded as `>f8` equal sample row 3 exactly. The
  WAVELENGTH column of the same row is a monotonic 2.8618–3.7205 µm grid. DQ at the extreme bin
  equals that of its neighbours.
- Byte statistics over up to 60 rows from each of the 66 samples:
  - 0.0% of finite values are float32-exact, and the mantissas are fully used (no widening)
  - per-sample median |flux| ranges from 7.7e-5 Jy (2MASS dwarfs) to 1.22 Jy
  - every row has exactly one >1000×-median bin, at the documented column
  - integration-to-integration relative change per bin is ~3.5e-3 (median) and ~9e-3 (p90):
    genuine photon noise, not rounded near-duplicates like the TSIS SIM precedent
- Build is local-only: curl appears only in download.sh and discover.sh. No credentials
  appear in any script, and samples contain no personal data.
- Rights: I read the fetched policy HTML. It contains the public-domain sentence, and its
  restricted lists (exclusive access, HLSP CC BY, DSS/GSC) do not cover these products.
- Novelty: `novelty.py` URL, term, type and vocabulary checks found no 64-bit spectral family,
  no downstream match, and only TESS (same endpoint) and NIRCam u16 (same mission) as related
  recipes.
