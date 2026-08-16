# NOAA OISST Weekly SST Int16 Evaluation Suite — 2026-08-15

## Outcome

Registered `noaa_oisst_weekly_sst_i16_eval` as evaluation-only material. It
contains 1,727 complete weekly `180×360` global sea-surface-temperature grids,
111,909,600 native packed signed-int16 codes, and 223,819,200 decoded bytes.

This family is explicitly excluded from training and from the accepted recipe
audit. All downloaded, decoded, indexed, and logged material is isolated under
`.data/evaluation/noaa_oisst_weekly_sst_i16_eval/`.

## Rights status

Rights are recorded as unclear. The exact NCEI OISST V2 metadata requires the
dataset citation and says to consult a separate CDR Use Agreement, but does not
expose that agreement's text. “Freely available online” establishes access,
not a permissive training or redistribution license.

Accordingly, the recipe declares:

- `intended_use = "evaluation_only"`;
- `training_eligible = false`;
- `redistribution_authorized = false`; and
- `rights.status = "unclear"`.

Evaluation placement is not a rights grant. The source should remain local and
be used only where legally appropriate, with the NCEI/NOAA citation preserved.

## Source and representation

The pinned 223,865,152-byte CDF1 source has SHA-256
`07cb78dcda836d1322897141fbdd79be1bd20190eeb10ffe6e9596588d2160f8`.
Its `sst(time,lat,lon)` variable is native `NC_SHORT`, with 1,727 records,
180 latitudes, 360 longitudes, `scale_factor≈0.01`, `add_offset=0`, and declared
missing code 32767.

The decoder preserves stored codes rather than unpacking physical floats. It
byte-swaps each complete big-endian XDR record into canonical little-endian
int16. No cells are removed, reordered, normalized, scaled, imputed, or joined
across weeks.

## Coverage and validation

The series spans 1989-12-31 through 2023-01-29 at exact seven-day intervals.
Stored codes range from -180 to 3616, with 3,572 distinct values, 112,961 zeros,
and no occurrences of the declared 32767 missing code. Every grid is
nonconstant and all 1,727 decoded SHA-256 values are unique.

Build and fresh-source verification passed on 2026-08-15. The aggregate
little-endian output SHA-256 is
`3f581e112a4dc720c625af18983a1beb135484318dae99fb8cafddd5847b3064`.
Verification reparses the strict classic-NetCDF layout and compares every
evaluation output byte-for-byte with a fresh source record conversion.

Model weights, codec logic, and hyperparameters must be frozen before using
this suite as a holdout. Repeated tuning against it makes it development data,
not unseen evaluation material.
