# hutubs_measured_hrir_f64

Measured binaural head-related impulse responses (HRIRs) from the HUTUBS HRTF
database (Audio Communication Group, TU Berlin, with Huawei and Sennheiser).
Each sample is one subject's SOFA `Data.IR` variable: 440 loudspeaker
directions x 2 ears x 256 taps at 44.1 kHz, stored by the producer as IEEE
float64. Samples are emitted unchanged as little-endian float64 in C order.

- Source: `https://sofacoustics.org/data/database/hutubs/ppN_HRIRs_measured.sofa`
  (N = 1..96), the SOFA database mirror of the DepositOnce deposit
  (DOI 10.14279/depositonce-8487).
- License: CC BY 4.0. Three sources state it: the DepositOnce item's
  `dc.rights.uri`, the `License` global attribute of every SOFA file, and
  Documentation.pdf. `download.sh` checks the first two.
- Scope: all 96 subjects, i.e. the whole measured population. 96 samples x
  225,280 values = 21,626,880 float64 values (173,015,040 bytes). Download is
  about 161 MB: 159,182,969 bytes of SOFA, plus the 1.7 MB documentation PDF
  and the license page.

## Material and homogeneity

All 96 files come from one measurement program: the same anechoic rig,
the same 440-point grid (`SourcePosition` must be byte-identical across files,
and build enforces this), 44.1 kHz, 256 taps, and one processing chain.
The 96 `*_HRIRs_measured.sofa` files are the only ones collected. The
`*_HRIRs_simulated.sofa` files (BEM simulations on a 1730-point grid) come
from a different generation process and are excluded.

Subject notes (Documentation.pdf, "Database" section):

- Subjects 1 and 96 are two measurements of the FABIAN head-and-torso
  simulator, a dummy head.
- Subjects 22 and 88 are two measurements of one human subject.

All four are kept, because each is a separate acoustic measurement. They are
flagged in the index field `subject_note`. Build also rejects byte-identical
`Data.IR` arrays.

Value facts (realized over all 96 subjects unless noted):

- Values range from -3.357 to 2.688.
- All 96 files share one `SourcePosition` grid, and `Data.Delay` is [0, 0]
  everywhere.
- Taps 0 and 255 are exactly zero in every row (window edges), and no other
  tap ever is: 1,760 zeros per sample.
- 223,522 of 225,280 bit patterns are distinct in every subject: all nonzero
  values, plus +0.0 and -0.0.
- Only the zeros are exactly representable in float32 (0.78% of values), so
  this is genuine float64, not widened float32.

## Conversion

The decoder is a pure-stdlib HDF5 reader, `scripts/h5lite.py`, copied from the
accepted cmip6/geoschem recipes. It verifies every lookup3 metadata checksum.

1. Walk the root group's dense link and attribute storage.
2. Require the pinned global attributes: `DatabaseName=HUTUBS`, the CC BY 4.0
   `License`, `SimpleFreeFieldHRIR`, `FIR`, and `ListenerShortName=ppN`.
3. Require `Data.IR` to be IEEE f64 LE with shape (440,2,256), stored as one
   chunk with a shuffle(8)+deflate pipeline.
4. Inflate the chunk, byte-unshuffle it, and write the 1,802,240 bytes to
   `samples/hutubs_measured_hrir_f64/measured_hrir_f64/pp<NNN>.bin`.

Missing-value policy (enforced in download validation, build and verify):

- Fatal: NaN or infinity; any |x| >= 1000 (the netCDF fill 9.97e36); an
  all-zero or constant (direction, ear) row, which would mean an unmeasured
  direction; fewer than 100,000 distinct values in a sample.
- Nothing is imputed or changed.

## Files

- `files.tsv`: the 96 pinned files (size, Last-Modified, sha256).
  - sha256 is pinned for all 96 files: pp1 and pp2 from probes, the other 94
    from the first full download (2026-10-09, cross-checked against the
    `SHA256SUMS` that download.sh writes).
- `discover.sh`: how `files.tsv` was resolved (listing plus HEAD requests).
- `download.sh`: license page, documentation PDF, and the 96 SOFA files
  (resumable curl, size/sha256/semantic validation).
- `build.sh` / `verify.sh`: decode, and independently re-derive. Verify locates
  the chunk through the creation-order index, then inflates and unshuffles it
  with separate code.
- `scripts/selftest.py`: a synthetic SOFA-like HDF5 file with the real
  layout. It covers 15 build rejection cases (big-endian/float32 `Data.IR`,
  fletcher32, missing shuffle, NaN, fill, zero row, `_FillValue`, wrong
  License/DatabaseName/ListenerShortName/sampling rate, grid mismatch,
  duplicate subject, sha256 pin) and 3 verify tamper cases.

## Novelty

- No HRTF/HRIR, SOFA or sofacoustics material exists in the local recipes,
  the registry or the downstream corpus (`novelty.py`).
- The nearest local families are room impulse responses: `openslr_rirs_noises_pcm16`
  (16-bit) and `aalto_arni_room_impulse_response_f32` (32-bit). Those are long,
  reverberant responses; these are short anechoic ear responses.
- At 64 bit, the most similar-looking material is probably
  `nmrxiv_p90_bruker_1h_fid_f64`, because both are damped oscillations. Whether
  they are close is for the zlsim gate to measure.
