# TRACE 171 Å full-frame EUV images int16 development

## Outcome

Accepted `nasa_heliocloud_trace_171_euv_frames_i16` after one repair cycle.

The family holds whole 1024 x 1024 images of the solar corona taken by NASA's
TRACE telescope in the 171 Å (Fe IX/X) passband. They come from the SDAC TRACE
holdings in the NASA GSFC HelioCloud bucket. It is the first solar EUV imager
at 16 bits. The only other coronal EUV family is `nasa_sdo_aia_synoptic_i32`:
ten SDO/AIA images at 32 bits, from a different instrument with different
processing.

The first cycle was sent back for repair. Of its 86 kept frames, 68 came from
lossy onboard-JPEG frame programs, showing undershoot ringing around particle
spikes, and the lattice was wrongly described as unit gain. The repair:
- selects frames by an `FRM_NAM` allowlist of near-lossless programs;
- confirms the allowlist with a per-frame ringing test;
- widens discovery;
- documents the calibration-gain drift honestly.

## Source and rights

- Source: `https://gov-nasa-hdrl-data1.s3.amazonaws.com/sdac/trace/1998/`. This
  is the anonymous, not requester-pays NASA GSFC HelioCloud bucket.
- Pinned pool: 95 objects in `sources.tsv`, each with key, size 2,105,280
  bytes, MD5 = single-part ETag, Last-Modified and header facts.
- Pool size: 200,001,600 bytes. The inventory SHA-256 is
  `05fc1e62bee34aa4a5484975f41101b17eab5bdff53318efb26142cb5250129a`.
- Rights: the TRACE data policy letter
  (`https://sdowww.lmsal.com/TRACE/Data/DataArchive/dapolicy.htm`) says "All
  TRACE data will be equally available to everyone on the World Wide Web". The
  NASA SMD Science Information Policy treats SMD mission data as a public
  trust to be made publicly available. This is the same open-data basis, not a
  named license, as the accepted `nasa_heliocloud_iris_l1_fuv_frames_i16`
  recipe from the same bucket.
- `download.sh` re-fetches both pages and logs the phrase checks.
- Citation: Handy et al. 1999, Solar Physics 187, 229. Do not attribute
  outputs to NASA or use NASA insignia.

## Shape and conversion

Each natural record is one TRACE FITS image file: one exposure. The file has
two 2880-byte header blocks, BITPIX 16, no BZERO/BSCALE/BLANK, and a
1024 x 1024 big-endian int16 primary array. The conversion byteswaps the array
to little-endian and writes it whole, one sample per file, with no scaling,
cropping or tiling.

The values are the archived `trace_prep` product, not level-0 DN: dark
pedestal and current subtracted (`tr_dark_sub 2.10`), divided by a corrected
flat field (`tr_flat_sub 1.60`), then rounded. Negative values down to −90 are
genuine dark-subtracted read noise.

The header regime requires:
- 171 Å, amplifier A, unsummed, SOU_AREA 0, full-CCD extract, PERCENTD 100;
- exposure ≥ 1 s and IMG_MAX ≥ 300;
- the canonical HISTORY sequence;
- an `FRM_NAM` program that is near-lossless: the name contains `lossless`,
  ends in `Q0`, or is `cjs.caldc171`. `ras.jpeg171.aecm4` is admitted
  conditionally.

The data regime requires:
- spike-cell ringing D > −15 DN;
- no empty near-zero histogram bin (gain drift g ≈ 1.015–1.09 in the window);
- the 8x8 cell-edge ratio within 0.80–1.06 (secondary check);
- not degenerate: dominant value and zeros ≤ 15%, ≥ 256 distinct values, no
  constant rows or columns.

The window ends on 1998-10-31 because the gain later grows enough to leave
periodic empty bins.

## Accepted output

- Discovery: 9,459 headers in the cache (8,234 according to the recipe), 222
  header-regime passes. 95 frames were pinned on 80 days, at least 3 h apart
  and at most 2 per day.
- Primary samples: 72 frames on 65 days, from 1998-04-24 to 1998-10-23.
- Per month: Apr 7, May 13, Jun 10, Jul 14, Aug 17, Sep 8, Oct 3.
- Rejected, by first reason: 9 for an empty near-zero bin, 12 degenerate, 2
  ringing-untestable.
- By program: `cjs.caldc171` 48, `com.losslessdefaecfull_171` 9,
  `cjs.stdfull171Q0` 8, `com.losslesslastaecfull_171` 6,
  `cjs.stdaecfull171Q0` 1.
- Primary values: 75,497,472 (1,048,576 per sample).
- Primary bytes: 150,994,944.
- Value range: −90 to 5,110 DN. Exposures 2.896–77.94 s.
- Ringing D: −11 to −5 DN. Lattice worst-bin ratio ≥ 0.516, over 38–372
  tested bins.
- Aggregate SHA-256 of the samples, concatenated in sorted path order:
  `ba459f73ce2877313755a4305bf4246436cb6ef76cfd797cf03e97ed29bbec74`.
- zlsim: verdict OK. Nearest family `bbbc039_microscopy_u16` at distance
  0.1154, loss −0.55. Own compression ratio 2.42.

Caveats, all disclosed in the recipe:
- Two thirds of the frames are disk-centre calibration or synoptic pointings.
- The scope is six months of 1998, near solar minimum.
- A mild gain perturbation thins a few near-zero bins.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Reproducibility:** the judge's own `verify.sh` run passed. It re-derived
  the kept set from all 95 pinned frames with independent code and
  byte-compared every sample.
- **Bytes:** decoded all 72 samples with `struct`.
  - Per-frame medians are 9–40 DN; the dominant value covers at most 7.8%.
  - The longest identical-value run in a row is 11 pixels, so there are no
    fill blocks. Sample SHA-256s are unique.
  - Coarse maps show TRACE's octagonal illuminated field with vignetted
    corners near 0 DN, quiet-sun network, limb and active regions.
- **Near-lossless check, independent of the recipe's statistic:** the
  fraction of 8x8 DCT energy at u+v ≥ 8 in pure-noise corner cells (white
  noise = 0.444):
  - all 72 kept frames: 0.359–0.406;
  - Q0 reference frame (`cjs.stdaecfull171Q0`, 2007): 0.380;
  - lossy references (`cjs.stdaecfull171` 1999/2001/2003,
    `cjs.aecoffset4.full171` 2000): 0.182–0.195.
- **Ringing D, judge's own code:** lossy references −20.5 to −58; Q0 reference
  −10; kept frames −6 to −11.
- **Allowlist scope:** across the 9,459 cached 1998 headers, the allowlist
  matches only the five intended programs (372 headers). The lossy
  `cjs.stdaecfull171`, `ras.aecfb171*`, `cjs.stdfull171`, `cck.*` and
  aecoffset programs are all excluded.
- **Novelty:** `novelty.py` (URL, terms, breadth keys) finds no TRACE recipe,
  registry row, ledger entry or downstream family.
- **Small documentation errors, not affecting the bytes:**
  - The manifest filtering text says 56–653 tested lattice bins; the index
    shows 38–372.
  - `semantic_meaning` says the files were written to SDAC in 2007. The IDL
    headers say 2008 for 93 pinned files and 2013 for 2 (19981021_000717,
    rejected; 19981023_000717, kept). Both carry the same canonical HISTORY
    versions.
